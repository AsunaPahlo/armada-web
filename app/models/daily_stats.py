"""
Daily aggregated statistics for fast stats queries.
Updated incrementally when new voyage/loot data arrives.
"""
from datetime import datetime, date
from app import db


class DailyStats(db.Model):
    """Pre-aggregated daily statistics."""

    __tablename__ = 'daily_stats'

    id = db.Column(db.Integer, primary_key=True)

    # The date this record covers
    stats_date = db.Column(db.Date, nullable=False, index=True)

    # Optional FC-level breakdown (NULL = fleet-wide totals)
    fc_id = db.Column(db.String(50), nullable=True, index=True)

    # Voyage stats
    total_voyages = db.Column(db.Integer, default=0)
    returned_voyages = db.Column(db.Integer, default=0)

    # Loot stats
    total_gil = db.Column(db.BigInteger, default=0)
    total_items = db.Column(db.Integer, default=0)

    # Route tracking (JSON: {"route_name": count, ...})
    route_counts = db.Column(db.Text, nullable=True)

    # When this record was last updated
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('stats_date', 'fc_id', name='unique_daily_stats'),
    )

    @classmethod
    def get_or_create(cls, stats_date: date, fc_id: str = None):
        """Get existing record or create new one for the given date/fc."""
        record = cls.query.filter_by(stats_date=stats_date, fc_id=fc_id).first()
        if not record:
            record = cls(stats_date=stats_date, fc_id=fc_id)
            db.session.add(record)
        return record

    @classmethod
    def increment_voyage(cls, stats_date: date, fc_id: str, route_name: str = None, returned: bool = False):
        """Increment voyage count for a date. Called when new voyage is recorded."""
        import json

        # Update FC-specific stats
        record = cls.get_or_create(stats_date, fc_id)
        record.total_voyages += 1
        if returned:
            record.returned_voyages += 1

        if route_name:
            routes = json.loads(record.route_counts) if record.route_counts else {}
            routes[route_name] = routes.get(route_name, 0) + 1
            record.route_counts = json.dumps(routes)

        # Also update fleet-wide totals (fc_id=NULL)
        fleet_record = cls.get_or_create(stats_date, None)
        fleet_record.total_voyages += 1
        if returned:
            fleet_record.returned_voyages += 1

        if route_name:
            fleet_routes = json.loads(fleet_record.route_counts) if fleet_record.route_counts else {}
            fleet_routes[route_name] = fleet_routes.get(route_name, 0) + 1
            fleet_record.route_counts = json.dumps(fleet_routes)

        db.session.commit()

    @classmethod
    def increment_loot(cls, stats_date: date, fc_id: str, gil_value: int, item_count: int):
        """Increment loot totals for a date. Called when new loot is recorded."""
        # Update FC-specific stats
        record = cls.get_or_create(stats_date, fc_id)
        record.total_gil += gil_value
        record.total_items += item_count

        # Also update fleet-wide totals
        fleet_record = cls.get_or_create(stats_date, None)
        fleet_record.total_gil += gil_value
        fleet_record.total_items += item_count

        db.session.commit()

    @classmethod
    def get_summary(cls, days: int = 30, fc_id: str = None, exclude_fc_ids: set = None):
        """Get aggregated stats for the last N days.

        Args:
            days: Number of days to look back
            fc_id: Optional specific FC to get stats for
            exclude_fc_ids: Optional set of FC IDs to exclude (for hidden FCs)
        """
        import json
        from datetime import timedelta
        from sqlalchemy import func, and_

        cutoff = date.today() - timedelta(days=days)

        # Build query filters
        filters = [cls.stats_date >= cutoff]

        if fc_id:
            # Specific FC
            filters.append(cls.fc_id == fc_id)
        elif exclude_fc_ids:
            # Fleet-wide but exclude hidden FCs - sum individual FC records
            filters.append(cls.fc_id.isnot(None))
            filters.append(~cls.fc_id.in_(exclude_fc_ids))
        else:
            # Fleet-wide totals (fc_id=NULL records)
            filters.append(cls.fc_id.is_(None))

        # Aggregate query - also count distinct days with data
        result = db.session.query(
            func.sum(cls.total_voyages),
            func.sum(cls.returned_voyages),
            func.sum(cls.total_gil),
            func.sum(cls.total_items),
            func.count(func.distinct(cls.stats_date))
        ).filter(and_(*filters)).first()

        total_voyages = int(result[0] or 0)
        returned_voyages = int(result[1] or 0)
        total_gil = int(result[2] or 0)
        total_items = int(result[3] or 0)
        actual_days = int(result[4] or 0)

        # Get route counts - need to aggregate JSON
        if fc_id:
            route_filters = [cls.stats_date >= cutoff, cls.fc_id == fc_id]
        elif exclude_fc_ids:
            route_filters = [cls.stats_date >= cutoff, cls.fc_id.isnot(None), ~cls.fc_id.in_(exclude_fc_ids)]
        else:
            route_filters = [cls.stats_date >= cutoff, cls.fc_id.is_(None)]

        records = cls.query.filter(and_(*route_filters)).all()

        combined_routes = {}
        for rec in records:
            if rec.route_counts:
                routes = json.loads(rec.route_counts)
                for route, count in routes.items():
                    combined_routes[route] = combined_routes.get(route, 0) + count

        # Sort by count descending, take top 5
        top_routes = sorted(combined_routes.items(), key=lambda x: x[1], reverse=True)[:5]
        top_routes = [{'route': r[0], 'count': r[1]} for r in top_routes]

        # Calculate daily average: use actual days with data, but cap at requested window
        days_for_avg = min(actual_days, days) if actual_days > 0 else 0
        daily_avg = int(total_gil / days_for_avg) if days_for_avg > 0 else 0

        return {
            'total_voyages': total_voyages,
            'returned_voyages': returned_voyages,
            'total_gil': total_gil,
            'total_items': total_items,
            'daily_profit': daily_avg,
            'actual_days': actual_days,
            'top_routes': top_routes,
        }

    @classmethod
    def rebuild_from_raw_data(cls):
        """
        Rebuild all daily stats from raw voyage/loot tables.
        Use this for initial population or if calculation logic changes.
        """
        import json
        from collections import defaultdict
        from datetime import datetime
        from sqlalchemy import func
        from app.models.voyage import Voyage
        from app.models.voyage_loot import VoyageLoot

        def parse_date(d):
            """Convert string or date to date object."""
            if d is None:
                return None
            if isinstance(d, date):
                return d
            if isinstance(d, str):
                return datetime.strptime(d, '%Y-%m-%d').date()
            return d

        print("[DailyStats] Starting rebuild from raw data...")

        # Clear existing data
        cls.query.delete()
        db.session.commit()

        # Aggregate voyages by date and fc_id
        print("[DailyStats] Aggregating voyages...")
        voyage_data = db.session.query(
            func.date(Voyage.return_time).label('stats_date'),
            Voyage.fc_id,
            Voyage.route_name,
            func.count(Voyage.id).label('count')
        ).filter(
            Voyage.return_time.isnot(None)
        ).group_by(
            func.date(Voyage.return_time),
            Voyage.fc_id,
            Voyage.route_name
        ).all()

        # Build stats dict: {(date, fc_id): {voyages, routes}}
        stats = defaultdict(lambda: {'voyages': 0, 'routes': defaultdict(int)})
        fleet_stats = defaultdict(lambda: {'voyages': 0, 'routes': defaultdict(int)})

        for row in voyage_data:
            stats_date = parse_date(row.stats_date)
            key = (stats_date, row.fc_id)
            stats[key]['voyages'] += row.count
            if row.route_name:
                stats[key]['routes'][row.route_name] += row.count

            # Fleet totals
            fleet_key = (stats_date, None)
            fleet_stats[fleet_key]['voyages'] += row.count
            if row.route_name:
                fleet_stats[fleet_key]['routes'][row.route_name] += row.count

        # Aggregate loot by date and fc_id
        print("[DailyStats] Aggregating loot...")
        loot_data = db.session.query(
            func.date(VoyageLoot.captured_at).label('stats_date'),
            VoyageLoot.fc_id,
            func.sum(VoyageLoot.total_gil_value).label('gil'),
            func.sum(VoyageLoot.total_items).label('items')
        ).group_by(
            func.date(VoyageLoot.captured_at),
            VoyageLoot.fc_id
        ).all()

        for row in loot_data:
            stats_date = parse_date(row.stats_date)
            key = (stats_date, row.fc_id)
            stats[key]['gil'] = int(row.gil or 0)
            stats[key]['items'] = int(row.items or 0)

            # Fleet totals
            fleet_key = (stats_date, None)
            fleet_stats[fleet_key]['gil'] = fleet_stats[fleet_key].get('gil', 0) + int(row.gil or 0)
            fleet_stats[fleet_key]['items'] = fleet_stats[fleet_key].get('items', 0) + int(row.items or 0)

        # Create records
        print("[DailyStats] Creating summary records...")
        count = 0

        try:
            # FC-specific records
            for (stats_date, fc_id), data in stats.items():
                if stats_date is None:
                    continue
                record = cls(
                    stats_date=stats_date,
                    fc_id=fc_id,
                    total_voyages=data['voyages'],
                    returned_voyages=data['voyages'],  # All are returned if we're counting by return_time
                    total_gil=data.get('gil', 0),
                    total_items=data.get('items', 0),
                    route_counts=json.dumps(dict(data['routes'])) if data['routes'] else None
                )
                db.session.add(record)
                count += 1

            # Fleet-wide records
            for (stats_date, _), data in fleet_stats.items():
                if stats_date is None:
                    continue
                record = cls(
                    stats_date=stats_date,
                    fc_id=None,
                    total_voyages=data['voyages'],
                    returned_voyages=data['voyages'],
                    total_gil=data.get('gil', 0),
                    total_items=data.get('items', 0),
                    route_counts=json.dumps(dict(data['routes'])) if data['routes'] else None
                )
                db.session.add(record)
                count += 1

            db.session.commit()
            print(f"[DailyStats] Rebuild complete. Created {count} records.")
            return count
        except Exception as e:
            db.session.rollback()
            print(f"[DailyStats] Error during rebuild: {e}")
            raise

    def __repr__(self):
        return f'<DailyStats {self.stats_date} fc={self.fc_id}>'
