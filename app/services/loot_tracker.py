"""
Loot Tracker service

Records and queries voyage loot data for gil-per-voyage tracking.
"""
import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models.voyage import Voyage
from app.models.voyage_loot import VoyageLoot, VoyageLootItem
from app.utils.logging import get_logger

logger = get_logger('LootTracker')


class LootTracker:
    """
    Tracks and records submarine voyage loot.
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern to preserve state between calls."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize loot tracker."""
        if self._initialized:
            return
        self._initialized = True

    def record_loot(self, plugin_id: str, loot_data: dict) -> dict:
        """
        Record voyage loot from plugin.

        Args:
            plugin_id: Plugin identifier
            loot_data: Loot payload from plugin

        Returns:
            dict with success status and message
        """
        try:
            character_name = loot_data.get('character_name', '')
            fc_id = loot_data.get('fc_id', '')
            fc_tag = loot_data.get('fc_tag', '')
            submarine_name = loot_data.get('submarine_name', '')
            sectors = loot_data.get('sectors', [])
            items = loot_data.get('items', [])
            total_gil_value = loot_data.get('total_gil_value', 0)
            captured_at_str = loot_data.get('captured_at', '')

            # Parse captured_at timestamp
            try:
                captured_at = datetime.fromisoformat(captured_at_str.replace('Z', '+00:00'))
                # Convert to naive datetime (remove timezone)
                if captured_at.tzinfo is not None:
                    captured_at = captured_at.replace(tzinfo=None)
            except (ValueError, AttributeError):
                captured_at = datetime.utcnow()

            # Check for duplicate submission
            existing = VoyageLoot.query.filter_by(
                fc_id=fc_id,
                submarine_name=submarine_name,
                captured_at=captured_at
            ).first()

            if existing:
                return {
                    'success': True,
                    'message': 'Loot already recorded',
                    'duplicate': True
                }

            # Create loot record
            loot = VoyageLoot(
                account_name=plugin_id,
                character_name=character_name,
                fc_id=fc_id,
                fc_tag=fc_tag,
                submarine_name=submarine_name,
                route_sectors=json.dumps(sectors) if sectors else None,
                total_items=len(items),
                total_gil_value=total_gil_value,
                captured_at=captured_at
            )

            # Try to find matching voyage record
            voyage = self._find_matching_voyage(fc_id, submarine_name, captured_at)
            if voyage:
                loot.voyage_id = voyage.id
                loot.route_name = voyage.route_name

                # Calculate and set voyage duration if not already set
                if sectors and not voyage.duration_hours:
                    self._calculate_voyage_duration(voyage, sectors, fc_id, submarine_name)

            # Calculate route_name from sectors if not set from voyage
            if not loot.route_name and sectors:
                from app.services.submarine_data import get_route_name_from_points
                loot.route_name = get_route_name_from_points(sectors)

            db.session.add(loot)
            db.session.flush()  # Get loot.id

            # Add item records
            for item_data in items:
                item = VoyageLootItem(
                    voyage_loot_id=loot.id,
                    sector_id=item_data.get('sector_id', 0),
                    item_id_primary=item_data.get('item_id_primary', 0),
                    item_name_primary=item_data.get('item_name_primary', ''),
                    count_primary=item_data.get('count_primary', 0),
                    hq_primary=item_data.get('hq_primary', False),
                    vendor_price_primary=item_data.get('vendor_price_primary', 0),
                    item_id_additional=item_data.get('item_id_additional', 0),
                    item_name_additional=item_data.get('item_name_additional', ''),
                    count_additional=item_data.get('count_additional', 0),
                    hq_additional=item_data.get('hq_additional', False),
                    vendor_price_additional=item_data.get('vendor_price_additional', 0)
                )
                db.session.add(item)

            db.session.commit()

            # Update daily stats incrementally
            try:
                from app.models.daily_stats import DailyStats
                DailyStats.increment_loot(
                    stats_date=captured_at.date(),
                    fc_id=fc_id,
                    gil_value=total_gil_value,
                    item_count=len(items)
                )
            except Exception as e:
                logger.warning(f" Failed to update daily stats: {e}")

            logger.info(f"Recorded loot for {submarine_name}: {len(items)} items, {total_gil_value:,} gil")

            return {
                'success': True,
                'message': f'Recorded {len(items)} items worth {total_gil_value:,} gil',
                'loot_id': loot.id,
                'voyage_linked': voyage is not None
            }

        except Exception as e:
            db.session.rollback()
            logger.warning(f"Error recording loot: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _find_matching_voyage(self, fc_id: str, submarine_name: str,
                               captured_at: datetime, window_minutes: int = 5) -> Optional[Voyage]:
        """
        Find a voyage record that matches the loot capture time.

        Looks for voyages where recorded_at is within the specified window
        of the loot capture time. We use recorded_at because when loot is
        collected, the voyage record gets updated with the new voyage data
        at approximately the same time.

        Args:
            fc_id: FC identifier
            submarine_name: Submarine name
            captured_at: When loot was captured
            window_minutes: Time window to match (±minutes)

        Returns:
            Matching Voyage or None
        """
        try:
            window = timedelta(minutes=window_minutes)
            start_time = captured_at - window
            end_time = captured_at + window

            logger.info(f"Looking for voyage: fc_id={fc_id}, sub={submarine_name}")
            logger.info(f"Window: {start_time} to {end_time}")

            # First check what voyages exist for this submarine
            all_voyages = Voyage.query.filter(
                Voyage.fc_id == fc_id,
                Voyage.submarine_name == submarine_name
            ).all()
            logger.info(f"Found {len(all_voyages)} voyages for this sub/FC")
            for v in all_voyages:
                logger.info(f"  ID {v.id}: recorded_at={v.recorded_at}, in_window={start_time <= v.recorded_at <= end_time}")

            # Simple query without complex ordering
            voyage = Voyage.query.filter(
                Voyage.fc_id == fc_id,
                Voyage.submarine_name == submarine_name,
                Voyage.recorded_at >= start_time,
                Voyage.recorded_at <= end_time
            ).order_by(Voyage.recorded_at.desc()).first()

            if voyage:
                logger.info(f"Matched voyage ID {voyage.id}")
            else:
                logger.info(f"No matching voyage found")

            return voyage

        except Exception as e:
            logger.warning(f"Error finding matching voyage: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _calculate_voyage_duration(self, voyage: Voyage, sectors: list[int],
                                    fc_id: str, submarine_name: str) -> None:
        """
        Calculate and set voyage duration based on route and submarine stats.

        Uses the voyage's submarine_build string if available, which is the most
        accurate since it was recorded when the voyage was sent. Falls back to
        fleet manager lookup only if build string is not available.

        Args:
            voyage: The voyage record to update
            sectors: List of sector IDs from the voyage
            fc_id: FC identifier to find the submarine
            submarine_name: Submarine name to find
        """
        try:
            from app.services.voyage_duration_calculator import calculate_voyage_duration_from_build

            duration = None

            # Prefer using the voyage's recorded build string
            if voyage.submarine_build:
                duration = calculate_voyage_duration_from_build(
                    route_points=sectors,
                    build=voyage.submarine_build,
                    level=voyage.submarine_level or 1
                )

            if duration:
                voyage.duration_hours = duration
                # Also store route_points on voyage if not set
                if not voyage.route_points:
                    voyage.route_points = json.dumps(sectors)
                logger.info(f"Set voyage duration: {duration:.2f} hours for {submarine_name}")
            else:
                logger.info(f"Could not calculate duration for {submarine_name} (build: {voyage.submarine_build})")

        except Exception as e:
            logger.warning(f"Error calculating voyage duration: {e}")
            import traceback
            traceback.print_exc()

    def get_loot_history(self, days: int = 30, fc_id: str = None,
                         submarine_name: str = None, page: int = 1,
                         per_page: int = 50, sort_by: str = 'captured_at',
                         sort_dir: str = 'desc') -> dict:
        """
        Get paginated loot history.

        Args:
            days: Number of days to look back (0 = all)
            fc_id: Filter by FC (optional)
            submarine_name: Filter by submarine (optional)
            page: Page number (1-indexed)
            per_page: Results per page (default 50, max 100)
            sort_by: Column to sort by
            sort_dir: Sort direction ('asc' or 'desc')

        Returns:
            Dict with 'items', 'total', 'page', 'per_page', 'pages'
        """
        # Clamp per_page to reasonable limits
        per_page = min(max(per_page, 10), 100)
        page = max(page, 1)

        # Get hidden FC IDs to exclude
        try:
            from app.models.fc_config import get_hidden_fc_ids
            hidden_fc_ids = get_hidden_fc_ids()
        except Exception:
            hidden_fc_ids = set()

        query = VoyageLoot.query

        # Apply time filter (days=0 means no filter)
        if days > 0:
            cutoff = datetime.utcnow() - timedelta(days=days)
            query = query.filter(VoyageLoot.captured_at >= cutoff)

        # Exclude hidden FCs
        if hidden_fc_ids:
            query = query.filter(~VoyageLoot.fc_id.in_(hidden_fc_ids))

        if fc_id:
            query = query.filter(VoyageLoot.fc_id == fc_id)
        if submarine_name:
            query = query.filter(VoyageLoot.submarine_name == submarine_name)

        # Get total count before pagination
        total = query.count()

        # Map sort_by to actual columns
        sort_columns = {
            'captured_at': VoyageLoot.captured_at,
            'submarine': VoyageLoot.submarine_name,
            'route': VoyageLoot.route_name,
            'items': VoyageLoot.total_items,
            'gil': VoyageLoot.total_gil_value,
        }

        sort_column = sort_columns.get(sort_by, VoyageLoot.captured_at)
        if sort_dir == 'asc':
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

        # Apply pagination
        offset = (page - 1) * per_page
        loot_records = query.offset(offset).limit(per_page).all()

        items = [{
            'id': l.id,
            'account': l.account_name,
            'character': l.character_name,
            'fc_id': l.fc_id,
            'fc_tag': l.fc_tag,
            'submarine': l.submarine_name,
            'route_name': l.route_name,
            'total_items': l.total_items,
            'total_gil_value': l.total_gil_value,
            'captured_at': l.captured_at.isoformat() + 'Z',
            'voyage_linked': l.voyage_id is not None
        } for l in loot_records]

        return {
            'items': items,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page  # Ceiling division
        }

    def get_loot_details(self, loot_id: int) -> Optional[dict]:
        """
        Get detailed loot record with all items.

        Args:
            loot_id: Loot record ID

        Returns:
            Loot record with items or None
        """
        loot = VoyageLoot.query.get(loot_id)
        if not loot:
            return None

        items = [{
            'sector_id': item.sector_id,
            'item_id_primary': item.item_id_primary,
            'item_name_primary': item.item_name_primary,
            'count_primary': item.count_primary,
            'hq_primary': item.hq_primary,
            'vendor_price_primary': item.vendor_price_primary,
            'value_primary': item.primary_value,
            'item_id_additional': item.item_id_additional,
            'item_name_additional': item.item_name_additional,
            'count_additional': item.count_additional,
            'hq_additional': item.hq_additional,
            'vendor_price_additional': item.vendor_price_additional,
            'value_additional': item.additional_value,
            'total_value': item.total_value
        } for item in loot.items]

        return {
            'id': loot.id,
            'account': loot.account_name,
            'character': loot.character_name,
            'fc_id': loot.fc_id,
            'fc_tag': loot.fc_tag,
            'submarine': loot.submarine_name,
            'route_name': loot.route_name,
            'route_sectors': json.loads(loot.route_sectors) if loot.route_sectors else [],
            'total_items': loot.total_items,
            'total_gil_value': loot.total_gil_value,
            'captured_at': loot.captured_at.isoformat() + 'Z',
            'recorded_at': loot.recorded_at.isoformat() + 'Z',
            'voyage_linked': loot.voyage_id is not None,
            'items': items
        }

    def get_loot_summary(self, days: int = 30) -> dict:
        """
        Get aggregated loot statistics.

        Args:
            days: Number of days to include (0 = all)

        Returns:
            Summary statistics dictionary
        """
        from sqlalchemy import func, and_

        # Get hidden FC IDs to exclude
        try:
            from app.models.fc_config import get_hidden_fc_ids
            hidden_fc_ids = get_hidden_fc_ids()
        except Exception:
            hidden_fc_ids = set()

        # Build filter conditions
        filters = []
        if days > 0:
            cutoff = datetime.utcnow() - timedelta(days=days)
            filters.append(VoyageLoot.captured_at >= cutoff)
        if hidden_fc_ids:
            filters.append(~VoyageLoot.fc_id.in_(hidden_fc_ids))

        # Total counts
        count_query = VoyageLoot.query
        if filters:
            count_query = count_query.filter(and_(*filters))
        total_loot = count_query.count()

        gil_query = db.session.query(func.sum(VoyageLoot.total_gil_value))
        if filters:
            gil_query = gil_query.filter(and_(*filters))
        total_gil = gil_query.scalar() or 0

        # Average gil per voyage
        avg_gil = total_gil / total_loot if total_loot > 0 else 0

        # Average gil per day (will be calculated after daily_totals query)
        avg_gil_per_day = 0

        # Top submarines by gil (total)
        sub_query = db.session.query(
            VoyageLoot.submarine_name,
            VoyageLoot.fc_id,
            func.count(VoyageLoot.id).label('voyage_count'),
            func.sum(VoyageLoot.total_gil_value).label('total_gil')
        )
        if filters:
            sub_query = sub_query.filter(and_(*filters))
        top_submarines = sub_query.group_by(
            VoyageLoot.submarine_name,
            VoyageLoot.fc_id
        ).order_by(
            func.sum(VoyageLoot.total_gil_value).desc()
        ).limit(10).all()

        # Top submarines by gil normalized to 24 hours
        # Only include voyages with duration data
        sub_norm_query = db.session.query(
            VoyageLoot.submarine_name,
            VoyageLoot.fc_id,
            func.count(VoyageLoot.id).label('voyage_count'),
            func.sum(VoyageLoot.total_gil_value).label('total_gil'),
            func.sum(VoyageLoot.total_gil_value * 24.0 / Voyage.duration_hours).label('total_gil_normalized')
        ).join(
            Voyage, VoyageLoot.voyage_id == Voyage.id
        ).filter(
            Voyage.duration_hours.isnot(None),
            Voyage.duration_hours > 0
        )
        if filters:
            sub_norm_query = sub_norm_query.filter(and_(*filters))
        top_submarines_normalized = sub_norm_query.group_by(
            VoyageLoot.submarine_name,
            VoyageLoot.fc_id
        ).order_by(
            func.sum(VoyageLoot.total_gil_value * 24.0 / Voyage.duration_hours).desc()
        ).limit(10).all()

        # Top routes by average gil per 24 hours (normalized by voyage duration)
        # Only include voyages with duration data
        # Default to known routes only (routes in route_stats table)
        from app.models.lumina import RouteStats
        known_routes = db.session.query(RouteStats.route_name).all()
        known_route_names = {r.route_name for r in known_routes}

        route_filters = [VoyageLoot.route_name.isnot(None)] + filters
        if known_route_names:
            route_filters.append(VoyageLoot.route_name.in_(known_route_names))

        route_query = db.session.query(
            VoyageLoot.route_name,
            func.count(VoyageLoot.id).label('voyage_count'),
            func.avg(VoyageLoot.total_gil_value).label('avg_gil'),
            func.sum(VoyageLoot.total_gil_value).label('total_gil'),
            func.avg(Voyage.duration_hours).label('avg_duration_hours'),
            (func.avg(VoyageLoot.total_gil_value) * 24.0 / func.avg(Voyage.duration_hours)).label('avg_gil_per_24h')
        ).join(
            Voyage, VoyageLoot.voyage_id == Voyage.id
        ).filter(
            and_(*route_filters),
            Voyage.duration_hours.isnot(None),
            Voyage.duration_hours > 0
        )
        top_routes = route_query.group_by(
            VoyageLoot.route_name
        ).order_by(
            (func.avg(VoyageLoot.total_gil_value) * 24.0 / func.avg(Voyage.duration_hours)).desc()
        ).limit(10).all()

        # Daily totals for chart
        daily_query = db.session.query(
            func.date(VoyageLoot.captured_at).label('date'),
            func.count(VoyageLoot.id).label('voyages'),
            func.sum(VoyageLoot.total_gil_value).label('total_gil')
        )
        if filters:
            daily_query = daily_query.filter(and_(*filters))
        daily_totals = daily_query.group_by(
            func.date(VoyageLoot.captured_at)
        ).order_by(
            func.date(VoyageLoot.captured_at)
        ).all()

        # Calculate average gil per day
        if daily_totals:
            num_days = len(daily_totals)
            avg_gil_per_day = total_gil / num_days if num_days > 0 else 0
        else:
            avg_gil_per_day = 0

        # Helper to snap duration to nearest standard (24, 36, 48)
        def snap_duration(hours):
            if hours is None:
                return 24
            valid = [24, 36, 48]
            return min(valid, key=lambda d: abs(d - hours))

        return {
            'period_days': days if days > 0 else 'all',
            'total_voyages': total_loot,
            'total_gil': total_gil,
            'avg_gil_per_voyage': round(avg_gil, 0),
            'avg_gil_per_day': round(avg_gil_per_day, 0),
            'top_submarines': [
                {
                    'submarine': s.submarine_name,
                    'fc_id': s.fc_id,
                    'voyage_count': s.voyage_count,
                    'total_gil': s.total_gil
                }
                for s in top_submarines
            ],
            'top_submarines_normalized': [
                {
                    'submarine': s.submarine_name,
                    'fc_id': s.fc_id,
                    'voyage_count': s.voyage_count,
                    'total_gil': s.total_gil,
                    'total_gil_normalized': round(s.total_gil_normalized, 0) if s.total_gil_normalized else 0
                }
                for s in top_submarines_normalized
            ],
            'top_routes': [
                {
                    'route': r.route_name,
                    'voyage_count': r.voyage_count,
                    'avg_gil': round(r.avg_gil, 0) if r.avg_gil else 0,
                    'duration_hours': snap_duration(r.avg_duration_hours),
                    'avg_gil_per_24h': round(r.avg_gil_per_24h, 0) if r.avg_gil_per_24h else 0,
                    'total_gil': r.total_gil or 0
                }
                for r in top_routes
            ],
            'daily_totals': [
                {
                    'date': str(d.date),
                    'voyages': d.voyages,
                    'total_gil': d.total_gil
                }
                for d in daily_totals
            ]
        }

    def get_top_routes(self, days: int = 30, known_only: bool = True) -> list:
        """
        Get top routes by average gil per 24 hours.

        Args:
            days: Number of days to include (0 = all)
            known_only: If True, only include routes from route_stats table

        Returns:
            List of route statistics
        """
        from sqlalchemy import func, and_
        from app.models.voyage import Voyage
        from app.models.lumina import RouteStats

        # Get hidden FC IDs to exclude
        try:
            from app.models.fc_config import get_hidden_fc_ids
            hidden_fc_ids = get_hidden_fc_ids()
        except Exception:
            hidden_fc_ids = set()

        # Build filter conditions
        filters = [VoyageLoot.route_name.isnot(None)]
        if days > 0:
            cutoff = datetime.utcnow() - timedelta(days=days)
            filters.append(VoyageLoot.captured_at >= cutoff)
        if hidden_fc_ids:
            filters.append(~VoyageLoot.fc_id.in_(hidden_fc_ids))

        # If known_only, get the list of known route names
        if known_only:
            known_routes = db.session.query(RouteStats.route_name).all()
            known_route_names = {r.route_name for r in known_routes}
            if known_route_names:
                filters.append(VoyageLoot.route_name.in_(known_route_names))

        # Query for top routes
        route_query = db.session.query(
            VoyageLoot.route_name,
            func.count(VoyageLoot.id).label('voyage_count'),
            func.avg(VoyageLoot.total_gil_value).label('avg_gil'),
            func.sum(VoyageLoot.total_gil_value).label('total_gil'),
            func.avg(Voyage.duration_hours).label('avg_duration_hours'),
            (func.avg(VoyageLoot.total_gil_value) * 24.0 / func.avg(Voyage.duration_hours)).label('avg_gil_per_24h')
        ).join(
            Voyage, VoyageLoot.voyage_id == Voyage.id
        ).filter(
            and_(*filters),
            Voyage.duration_hours.isnot(None),
            Voyage.duration_hours > 0
        )

        top_routes = route_query.group_by(
            VoyageLoot.route_name
        ).order_by(
            (func.avg(VoyageLoot.total_gil_value) * 24.0 / func.avg(Voyage.duration_hours)).desc()
        ).limit(10).all()

        # Helper to snap duration to nearest standard (24, 36, 48)
        def snap_duration(hours):
            if hours is None:
                return 24
            valid = [24, 36, 48]
            return min(valid, key=lambda d: abs(d - hours))

        return [
            {
                'route': r.route_name,
                'voyage_count': r.voyage_count,
                'avg_gil': round(r.avg_gil, 0) if r.avg_gil else 0,
                'duration_hours': snap_duration(r.avg_duration_hours),
                'avg_gil_per_24h': round(r.avg_gil_per_24h, 0) if r.avg_gil_per_24h else 0,
                'total_gil': r.total_gil or 0
            }
            for r in top_routes
        ]


# Singleton instance for use across the application
loot_tracker = LootTracker()
