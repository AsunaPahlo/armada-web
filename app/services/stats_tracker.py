"""
Stats Tracker service

Records and queries per-voyage statistics.
"""
from datetime import datetime, date, timedelta
from typing import Optional

from app import db
from app.models.voyage import Voyage, VoyageStats
from app.services.config_parser import AccountData, CharacterInfo, SubmarineInfo


class StatsTracker:
    """
    Tracks submarine voyages and calculates statistics.
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern to preserve state between calls."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize stats tracker."""
        if self._initialized:
            return
        self._initialized = True
        self._previous_states: dict = {}  # (cid, sub_name) -> last_return_time
        self._state_loaded = False  # Track if we've loaded state from DB

    def _load_previous_states(self):
        """Load previous submarine states from voyages table on startup."""
        if self._state_loaded:
            return

        try:
            # Load from voyages table instead of snapshots (simpler, faster)
            # Get the most recent voyage per submarine
            from sqlalchemy import text
            query = text("""
                SELECT character_cid, submarine_name, return_time
                FROM voyages v1
                WHERE return_time = (
                    SELECT MAX(return_time)
                    FROM voyages v2
                    WHERE v2.character_cid = v1.character_cid
                    AND v2.submarine_name = v1.submarine_name
                )
            """)

            result = db.session.execute(query)
            count = 0
            for row in result:
                # Store by cid+sub_name - we'll match on these in record_snapshot
                self._previous_states[(row.character_cid, row.submarine_name)] = row.return_time
                count += 1

            if count > 0:
                print(f"[StatsTracker] Loaded {count} submarine states from voyages")

            self._state_loaded = True
        except Exception as e:
            print(f"[StatsTracker] Error loading previous states: {e}")
            self._state_loaded = True  # Don't retry on error

    def record_snapshot(self, accounts: list[AccountData]):
        """
        Detect voyage completions by comparing submarine return times.

        Args:
            accounts: List of AccountData from parser
        """
        # Load previous states from DB on first call (handles server restart)
        self._load_previous_states()

        current_time = datetime.utcnow()
        voyages_recorded = 0

        for account in accounts:
            for char in account.characters:
                fc_info = account.fc_data.get(char.fc_id)
                fc_name = fc_info.name if fc_info else ""

                for sub in char.submarines:
                    # Key by cid (as string) + sub name for consistency
                    key = (str(char.cid), sub.name)

                    # Check if this submarine has a new voyage
                    prev_return = self._previous_states.get(key)

                    if prev_return is not None:
                        # If return time changed (new voyage started), the previous voyage was completed
                        if sub.return_time != prev_return:
                            try:
                                voyage = self._record_voyage(
                                    account=account,
                                    char=char,
                                    sub=sub,
                                    fc_name=fc_name,
                                    collected_time=current_time,
                                    prev_return_time=prev_return
                                )
                                db.session.commit()
                                voyages_recorded += 1

                                # Update daily stats incrementally
                                if voyage and prev_return:
                                    try:
                                        from app.models.daily_stats import DailyStats
                                        DailyStats.increment_voyage(
                                            stats_date=prev_return.date(),
                                            fc_id=str(char.fc_id) if char.fc_id else '',
                                            route_name=sub.route_name,
                                            returned=True
                                        )
                                    except Exception as e:
                                        print(f"[StatsTracker] Warning: Failed to update daily stats: {e}")
                            except Exception as e:
                                db.session.rollback()
                                print(f"[StatsTracker] Error recording voyage for {sub.name}: {e}")

                    # Update state cache
                    self._previous_states[key] = sub.return_time

        if voyages_recorded > 0:
            print(f"[StatsTracker] Recorded {voyages_recorded} new voyage(s)")

    def _record_voyage(self, account: AccountData, char: CharacterInfo,
                       sub: SubmarineInfo, fc_name: str, collected_time: datetime,
                       prev_return_time: datetime = None) -> Optional[Voyage]:
        """
        Record a COMPLETED voyage to the database.

        This is called when we detect a submarine has started a new voyage,
        which means the previous voyage must have been completed and collected.
        We record the PREVIOUS voyage (using prev_return_time), not the new one.

        Returns:
            The created Voyage object, or None if not created
        """
        cid_str = str(char.cid)
        fc_id_str = str(char.fc_id) if char.fc_id else None

        # Only record if we have a previous return time (completed voyage)
        if not prev_return_time:
            return None

        # Check if voyage already exists (avoid duplicate on server restart)
        existing = Voyage.query.filter_by(
            character_cid=cid_str,
            submarine_name=sub.name,
            return_time=prev_return_time
        ).first()

        if existing:
            return None  # Already recorded

        # Get route_points - prefer from submarine, fall back to deriving from route_name
        import json
        from app.services.submarine_data import get_points_from_route_name
        from app.services.voyage_duration_calculator import calculate_voyage_duration_from_build

        route_points = sub.route_points if sub.route_points else []
        if not route_points and sub.route_name:
            route_points = get_points_from_route_name(sub.route_name)

        # Calculate duration from route and build
        duration_hours = None
        if route_points and sub.build:
            duration_hours = calculate_voyage_duration_from_build(
                route_points=route_points,
                build=sub.build,
                level=sub.level or 1
            )

        # Record the completed voyage (the one that just returned)
        voyage = Voyage(
            account_name=account.nickname,
            character_name=char.name,
            character_cid=cid_str,
            fc_id=fc_id_str,
            fc_name=fc_name,
            world=char.world,
            submarine_name=sub.name,
            submarine_level=sub.level,
            submarine_build=sub.build,
            route_name=sub.route_name,
            route_points=json.dumps(route_points) if route_points else None,
            duration_hours=duration_hours,
            return_time=prev_return_time,
            was_collected=True,
            collected_at=collected_time
        )
        db.session.add(voyage)
        db.session.flush()  # Get voyage.id

        # Try to link any unlinked loot records that match this voyage
        self._link_unlinked_loot(voyage, collected_time)

        return voyage

    def _link_unlinked_loot(self, voyage: Voyage, collected_time: datetime,
                            window_minutes: int = 5):
        """
        Link unlinked loot records to this voyage.

        Called after a voyage is recorded to catch loot that arrived
        before the voyage was recorded in the database.

        Args:
            voyage: The newly recorded voyage
            collected_time: When the voyage was collected
            window_minutes: Time window to match (±minutes)
        """
        try:
            from app.models.voyage_loot import VoyageLoot

            window = timedelta(minutes=window_minutes)
            start_time = collected_time - window
            end_time = collected_time + window

            # Find unlinked loot for this submarine/FC within the time window
            unlinked_loot = VoyageLoot.query.filter(
                VoyageLoot.fc_id == voyage.fc_id,
                VoyageLoot.submarine_name == voyage.submarine_name,
                VoyageLoot.voyage_id.is_(None),
                VoyageLoot.captured_at >= start_time,
                VoyageLoot.captured_at <= end_time
            ).all()

            if unlinked_loot:
                for loot in unlinked_loot:
                    loot.voyage_id = voyage.id
                    if not loot.route_name and voyage.route_name:
                        loot.route_name = voyage.route_name
                    print(f"[StatsTracker] Linked loot ID {loot.id} to voyage ID {voyage.id}")

        except Exception as e:
            print(f"[StatsTracker] Error linking loot to voyage: {e}")

    def mark_voyage_collected(self, character_cid: int, submarine_name: str,
                               return_time: datetime) -> bool:
        """
        Mark a voyage as collected.

        Returns:
            True if voyage was found and marked
        """
        voyage = Voyage.query.filter_by(
            character_cid=character_cid,
            submarine_name=submarine_name,
            return_time=return_time
        ).first()

        if voyage and not voyage.was_collected:
            voyage.was_collected = True
            voyage.collected_at = datetime.utcnow()
            db.session.commit()
            return True
        return False

    def get_voyage_history(self, days: int = 30, account_name: str = None,
                           fc_id: int = None, page: int = 1, per_page: int = 50,
                           sort_by: str = 'return_time', sort_dir: str = 'desc') -> dict:
        """
        Get voyage history with pagination and sorting.

        Args:
            days: Number of days to look back
            account_name: Filter by account (optional)
            fc_id: Filter by FC (optional)
            page: Page number (1-indexed)
            per_page: Items per page
            sort_by: Column to sort by
            sort_dir: Sort direction ('asc' or 'desc')

        Returns:
            Dict with 'voyages', 'total', 'page', 'per_page', 'pages'
        """
        from app.models.voyage_loot import VoyageLoot

        # Get hidden FC IDs to exclude
        try:
            from app.models.fc_config import get_hidden_fc_ids
            hidden_fc_ids = get_hidden_fc_ids()
        except Exception:
            hidden_fc_ids = set()

        # Left outer join with VoyageLoot to get loot_id if linked
        query = db.session.query(Voyage, VoyageLoot.id.label('loot_id')).outerjoin(
            VoyageLoot, VoyageLoot.voyage_id == Voyage.id
        )

        # Exclude hidden FCs
        if hidden_fc_ids:
            query = query.filter(~Voyage.fc_id.in_(hidden_fc_ids))

        # Apply time filter (days=0 means no filter / all history)
        if days > 0:
            cutoff = datetime.utcnow() - timedelta(days=days)
            query = query.filter(Voyage.return_time >= cutoff)

        if account_name:
            query = query.filter(Voyage.account_name == account_name)
        if fc_id:
            query = query.filter(Voyage.fc_id == fc_id)

        # Map sort_by to actual columns
        sort_columns = {
            'submarine': Voyage.submarine_name,
            'character': Voyage.character_name,
            'world': Voyage.world,
            'fc_name': Voyage.fc_name,
            'build': Voyage.submarine_build,
            'route': Voyage.route_name,
            'level': Voyage.submarine_level,
            'return_time': Voyage.return_time,
        }

        sort_column = sort_columns.get(sort_by, Voyage.return_time)
        if sort_dir == 'asc':
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

        # Get total count
        total = query.count()

        # Apply pagination (per_page=0 means return all)
        if per_page > 0:
            offset = (page - 1) * per_page
            results = query.offset(offset).limit(per_page).all()
            pages = (total + per_page - 1) // per_page  # Ceiling division
        else:
            results = query.all()
            pages = 1

        voyages = [{
            'id': v.id,
            'account': v.account_name,
            'character': v.character_name,
            'fc_name': v.fc_name,
            'world': v.world,
            'submarine': v.submarine_name,
            'level': v.submarine_level,
            'build': v.submarine_build,
            'route': v.route_name,
            'return_time': v.return_time.isoformat() + 'Z',
            'was_collected': v.was_collected,
            'collected_at': (v.collected_at.isoformat() + 'Z') if v.collected_at else None,
            'loot_id': loot_id
        } for v, loot_id in results]

        return {
            'voyages': voyages,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': pages
        }

    def _mark_past_voyages_collected(self, character_cid: str, submarine_name: str,
                                        current_return_time: datetime):
        """
        Mark any uncollected voyages for this submarine as collected.

        If a submarine is currently out on a voyage, any previous voyages must have
        been collected (you can't send a sub without collecting first).
        Only marks voyages where return_time has actually passed.
        """
        now = datetime.utcnow()
        try:
            pending_voyages = Voyage.query.filter(
                Voyage.character_cid == character_cid,
                Voyage.submarine_name == submarine_name,
                Voyage.was_collected == False,
                Voyage.return_time < current_return_time,  # Before current voyage
                Voyage.return_time < now  # And actually returned (not in future)
            ).all()

            if pending_voyages:
                for voyage in pending_voyages:
                    voyage.was_collected = True
                    voyage.collected_at = voyage.return_time  # Assume collected at return time
                db.session.commit()
                print(f"[StatsTracker] Auto-marked {len(pending_voyages)} past voyage(s) as collected for {submarine_name}")
        except Exception as e:
            db.session.rollback()
            print(f"[StatsTracker] Error marking past voyages collected: {e}")

    def aggregate_daily_stats(self, target_date: date = None):
        """
        Aggregate voyage data into daily stats per FC.

        Args:
            target_date: Date to aggregate (defaults to yesterday)
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        # Get all voyages for the target date
        start_of_day = datetime.combine(target_date, datetime.min.time())
        end_of_day = datetime.combine(target_date, datetime.max.time())

        voyages = Voyage.query.filter(
            Voyage.return_time >= start_of_day,
            Voyage.return_time <= end_of_day
        ).all()

        if not voyages:
            return

        # Group by account + FC
        from collections import defaultdict
        fc_stats = defaultdict(lambda: {
            'voyages_sent': 0,
            'voyages_collected': 0,
            'submarines': set(),
            'estimated_gil': 0
        })

        for v in voyages:
            key = (v.account_name, v.fc_id)
            fc_stats[key]['voyages_sent'] += 1
            if v.was_collected:
                fc_stats[key]['voyages_collected'] += 1
            fc_stats[key]['submarines'].add(v.submarine_name)
            fc_stats[key]['fc_name'] = v.fc_name

            # Estimate gil from route
            if v.route_name:
                from app.services.route_stats_service import get_route_gil_per_day
                gil = get_route_gil_per_day(v.route_name)
                if gil > 0:
                    # Convert gil/day to gil/voyage (assume ~2 voyages/day)
                    fc_stats[key]['estimated_gil'] += gil // 2

        # Upsert stats for each FC
        for (account_name, fc_id), stats in fc_stats.items():
            existing = VoyageStats.query.filter_by(
                account_name=account_name,
                fc_id=fc_id,
                stat_date=target_date
            ).first()

            if existing:
                existing.voyages_sent = stats['voyages_sent']
                existing.voyages_collected = stats['voyages_collected']
                existing.submarines_active = len(stats['submarines'])
                existing.estimated_gil = stats['estimated_gil']
            else:
                new_stat = VoyageStats(
                    account_name=account_name,
                    fc_id=fc_id,
                    fc_name=stats.get('fc_name', ''),
                    stat_date=target_date,
                    voyages_sent=stats['voyages_sent'],
                    voyages_collected=stats['voyages_collected'],
                    submarines_active=len(stats['submarines']),
                    estimated_gil=stats['estimated_gil']
                )
                db.session.add(new_stat)

        try:
            db.session.commit()
            print(f"[StatsTracker] Aggregated daily stats for {target_date}: {len(fc_stats)} FCs")
        except Exception as e:
            db.session.rollback()
            print(f"[StatsTracker] Error aggregating daily stats: {e}")

    def get_daily_stats(self, days: int = 30, fc_id: int = None) -> list[dict]:
        """
        Get aggregated daily statistics.

        Args:
            days: Number of days to include (0 = all)
            fc_id: Filter by FC (optional)

        Returns:
            List of daily stat records
        """
        query = VoyageStats.query

        # Apply time filter (days=0 means no filter)
        if days > 0:
            cutoff = date.today() - timedelta(days=days)
            query = query.filter(VoyageStats.stat_date >= cutoff)

        if fc_id:
            query = query.filter(VoyageStats.fc_id == fc_id)

        stats = query.order_by(VoyageStats.stat_date.desc()).all()

        return [{
            'date': s.stat_date.isoformat(),
            'account': s.account_name,
            'fc_name': s.fc_name,
            'voyages_sent': s.voyages_sent,
            'voyages_collected': s.voyages_collected,
            'submarines_active': s.submarines_active,
            'estimated_gil': s.estimated_gil,
            'ceruleum_used': s.ceruleum_used,
            'repair_kits_used': s.repair_kits_used
        } for s in stats]

    def calculate_summary_stats(self, days: int = 30) -> dict:
        """
        Calculate summary statistics.

        Args:
            days: Number of days to include (0 = all)

        Returns:
            Summary statistics dictionary
        """
        now = datetime.utcnow()

        # Get hidden FC IDs to exclude
        try:
            from app.models.fc_config import get_hidden_fc_ids
            hidden_fc_ids = get_hidden_fc_ids()
        except Exception:
            hidden_fc_ids = set()

        # Build base query with hidden FC filter
        base_query = Voyage.query
        if hidden_fc_ids:
            base_query = base_query.filter(~Voyage.fc_id.in_(hidden_fc_ids))

        # Build base queries (days=0 means no time filter)
        if days > 0:
            cutoff = now - timedelta(days=days)
            total_voyages = base_query.filter(Voyage.return_time >= cutoff).count()
        else:
            total_voyages = base_query.count()

        # Calculate avg voyages per day (use actual days from first voyage if days=0)
        if days > 0:
            avg_per_day = round(total_voyages / days, 1)
        else:
            first_voyage = base_query.order_by(Voyage.return_time.asc()).first()
            if first_voyage:
                actual_days = (now - first_voyage.return_time).days or 1
                avg_per_day = round(total_voyages / actual_days, 1)
            else:
                avg_per_day = 0

        return {
            'period_days': days if days > 0 else 'all',
            'total_voyages': total_voyages,
            'avg_voyages_per_day': avg_per_day
        }

    def link_all_unlinked_loot(self, window_minutes: int = 5) -> int:
        """
        Link all unlinked loot records to matching voyages.

        Useful for fixing historical data or after restarts.

        Args:
            window_minutes: Time window to match (±minutes)

        Returns:
            Number of loot records linked
        """
        try:
            from app.models.voyage_loot import VoyageLoot

            # Get all unlinked loot
            unlinked = VoyageLoot.query.filter(
                VoyageLoot.voyage_id.is_(None)
            ).all()

            if not unlinked:
                return 0

            linked_count = 0
            window = timedelta(minutes=window_minutes)

            for loot in unlinked:
                start_time = loot.captured_at - window
                end_time = loot.captured_at + window

                # Find matching voyage by recorded_at or collected_at
                voyage = Voyage.query.filter(
                    Voyage.fc_id == loot.fc_id,
                    Voyage.submarine_name == loot.submarine_name,
                    db.or_(
                        db.and_(
                            Voyage.recorded_at >= start_time,
                            Voyage.recorded_at <= end_time
                        ),
                        db.and_(
                            Voyage.collected_at >= start_time,
                            Voyage.collected_at <= end_time
                        )
                    )
                ).first()

                if voyage:
                    loot.voyage_id = voyage.id
                    if not loot.route_name and voyage.route_name:
                        loot.route_name = voyage.route_name
                    linked_count += 1

            if linked_count > 0:
                db.session.commit()
                print(f"[StatsTracker] Linked {linked_count} existing loot records to voyages")

            return linked_count

        except Exception as e:
            db.session.rollback()
            print(f"[StatsTracker] Error linking unlinked loot: {e}")
            return 0


# Singleton instance for use across the application
stats_tracker = StatsTracker()
