"""
Route Stats Service - Fetches gil/earnings data from community spreadsheet.

Source: Fightclub Submarine Spreadsheet
https://docs.google.com/spreadsheets/d/1aOhMH-XrWBIV93Veo3Wo0zz38z-tqk6QWO_4xzu5ZMg/

Note: Only gil-related data is used from this sheet.
Fuel/repair calculations use Lumina data for accuracy.

Routes can have multiple duration variants (e.g., JORZ at 36h and 48h).
The correct variant is selected by matching the submarine's calculated voyage duration.
"""
import csv
import io
import logging
import re
from datetime import datetime, timedelta
from typing import Optional
import requests

from app import db
from app.models.lumina import DataVersion, RouteStats
from app.services.voyage_duration_calculator import snap_duration_to_bucket

logger = logging.getLogger(__name__)

# Google Sheets CSV export URL
SPREADSHEET_ID = "1aOhMH-XrWBIV93Veo3Wo0zz38z-tqk6QWO_4xzu5ZMg"
SHEET_GID = "1825335500"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&gid={SHEET_GID}"

# Update interval (6 hours)
UPDATE_INTERVAL_HOURS = 6


def parse_gil_value(value: str) -> int:
    """Parse gil value from string like '118,854' or '475.4k'."""
    if not value:
        return 0

    # Remove quotes and whitespace
    value = value.strip().strip('"').strip()

    # Handle 'k' suffix (thousands)
    if value.lower().endswith('k'):
        try:
            return int(float(value[:-1]) * 1000)
        except ValueError:
            pass

    # Handle 'm' suffix (millions)
    if value.lower().endswith('m'):
        try:
            return int(float(value[:-1]) * 1000000)
        except ValueError:
            pass

    # Remove commas and try to parse
    try:
        return int(value.replace(',', ''))
    except ValueError:
        return 0


def parse_hours(value: str) -> int:
    """Parse hours from string, snapping to nearest standard voyage bucket."""
    try:
        raw = float(value.strip().strip('"'))
        return int(snap_duration_to_bucket(raw))
    except (ValueError, AttributeError):
        return 24  # Default


def parse_exp(value: str) -> int:
    """Parse experience value from string like '678.0k' or '1.01m'."""
    return parse_gil_value(value)  # Same format


class RouteStatsService:
    """Service for fetching route earnings data from community spreadsheet."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Armada-SubmarineDashboard/1.0'
        })

    def needs_update(self) -> bool:
        """Check if route stats need to be updated."""
        version = DataVersion.query.filter_by(table_name='route_stats').first()
        if not version:
            return True

        time_since_update = datetime.utcnow() - version.last_updated
        return time_since_update > timedelta(hours=UPDATE_INTERVAL_HOURS)

    def fetch_spreadsheet(self) -> Optional[str]:
        """Fetch CSV data from Google Sheets."""
        try:
            response = self.session.get(SHEET_URL, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"[RouteStats] Failed to fetch spreadsheet: {e}")
            return None

    def _migrate_route_stats_table(self):
        """Migrate route_stats table to support duration_hours column."""
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)

        if 'route_stats' not in inspector.get_table_names():
            return  # Table doesn't exist yet, will be created with new schema

        existing_columns = {col['name'] for col in inspector.get_columns('route_stats')}

        if 'duration_hours' not in existing_columns:
            # Drop and recreate - this is cached data that gets re-fetched
            logger.info("[RouteStats] Migrating table to add duration_hours column...")
            db.session.execute(text('DROP TABLE IF EXISTS route_stats'))
            db.session.commit()
            # Recreate with new schema
            RouteStats.__table__.create(db.engine, checkfirst=True)
            # Clear version so data gets re-fetched
            version = DataVersion.query.filter_by(table_name='route_stats').first()
            if version:
                db.session.delete(version)
                db.session.commit()
            logger.info("[RouteStats] Migration complete, table will be repopulated")

    def update_route_stats(self, force: bool = False) -> int:
        """
        Update route stats from Google Sheet.
        Stores all duration variants for each route.

        Returns:
            Number of route entries updated
        """
        table_name = 'route_stats'

        if not force and not self.needs_update():
            logger.debug(f"[RouteStats] Skipping update (not due)")
            return 0

        content = self.fetch_spreadsheet()
        if not content:
            return 0

        # Parse CSV
        reader = csv.DictReader(io.StringIO(content))
        count = 0

        for row in reader:
            try:
                # Get route name from 'Route' column
                route_name = row.get('Route', '').strip().strip('"')

                # Stop at first blank row (end of first table)
                # The spreadsheet has multiple tables separated by blank rows
                if not route_name:
                    break

                # Skip header-like rows
                if route_name.lower() == 'route':
                    continue

                # Parse values
                gil_per_sub_day = parse_gil_value(row.get('Gil/Sub/Day', '0'))
                avg_exp = parse_exp(row.get('Avg EXP', '0'))
                fc_points = parse_gil_value(row.get('FC Points', '0'))
                duration_hours = parse_hours(row.get('Hours', '24'))

                # Skip rows with no meaningful data
                if gil_per_sub_day == 0:
                    continue

                # Upsert by (route_name, duration_hours) - each variant is its own row
                route = RouteStats.query.filter_by(
                    route_name=route_name,
                    duration_hours=duration_hours
                ).first()

                if not route:
                    route = RouteStats(
                        route_name=route_name,
                        duration_hours=duration_hours
                    )
                    db.session.add(route)

                route.gil_per_sub_day = gil_per_sub_day
                route.avg_exp = avg_exp
                route.fc_points = fc_points

                count += 1

            except Exception as e:
                logger.warning(f"[RouteStats] Error parsing row: {e}")
                continue

        # Update version tracking
        version = DataVersion.query.filter_by(table_name=table_name).first()
        if not version:
            version = DataVersion(table_name=table_name)
            db.session.add(version)

        version.last_updated = datetime.utcnow()
        version.row_count = count

        db.session.commit()
        logger.info(f"[RouteStats] Updated {count} route entries from spreadsheet")
        return count

    def ensure_data_loaded(self) -> bool:
        """Ensure route stats are loaded on startup."""
        self._migrate_route_stats_table()
        route_count = RouteStats.query.count()
        if route_count == 0:
            logger.info("[RouteStats] No data found, performing initial load...")
            self.update_route_stats(force=True)
            return True
        return False

    def get_gil_per_day(self, route_name: str, duration_hours: Optional[int] = None) -> Optional[int]:
        """
        Get gil per day for a route name, optionally matching by duration.

        Args:
            route_name: Route name like 'OJ', 'JORZ', etc.
            duration_hours: Voyage duration in hours (24, 36, 48, etc.)
                           If provided, finds the closest matching duration variant.

        Returns:
            Gil per submarine per day, or None if not found
        """
        return _lookup_route_gil(route_name, duration_hours)


# Singleton instance
route_stats_service = RouteStatsService()


def _lookup_route_gil(route_name: str, duration_hours: Optional[int] = None) -> Optional[int]:
    """
    Look up gil/day for a route, matching by duration when available.

    Priority:
    1. Exact duration match
    2. Closest duration match
    3. Any match for this route (highest gil/day if no duration info)
    """
    routes = RouteStats.query.filter_by(route_name=route_name).all()
    if not routes:
        # Check user-defined route overrides
        from app.models.route_override import get_override_gil
        return get_override_gil(route_name)

    # Single variant - return it directly
    if len(routes) == 1:
        return routes[0].gil_per_sub_day

    # Multiple variants - try to match by duration
    if duration_hours is not None:
        # Snap to bucket for consistency
        snapped = int(snap_duration_to_bucket(float(duration_hours)))

        # Try exact match first
        for r in routes:
            if r.duration_hours == snapped:
                return r.gil_per_sub_day

        # Find closest duration
        closest = min(routes, key=lambda r: abs(r.duration_hours - snapped))
        return closest.gil_per_sub_day

    # No duration info - return highest gil/day (most common/optimistic)
    best = max(routes, key=lambda r: r.gil_per_sub_day)
    return best.gil_per_sub_day


def get_route_gil_per_day(route_name: str, duration_hours: Optional[int] = None) -> int:
    """
    Get gil per day for a route, with duration matching.

    Args:
        route_name: Route name like 'OJ', 'JORZ', etc.
        duration_hours: Optional voyage duration for selecting the right variant.

    Returns:
        Gil per submarine per day, or 0 if not found
    """
    result = _lookup_route_gil(route_name, duration_hours)
    return result if result and result > 0 else 0


def get_route_stats(route_name: str, duration_hours: Optional[int] = None) -> Optional[dict]:
    """
    Get full route stats, optionally matching by duration.

    Returns dict with route_name, duration_hours, gil_per_sub_day, avg_exp, fc_points.
    """
    routes = RouteStats.query.filter_by(route_name=route_name).all()
    if not routes:
        return None

    # Pick best match
    route = routes[0]
    if len(routes) > 1 and duration_hours is not None:
        snapped = int(snap_duration_to_bucket(float(duration_hours)))
        # Exact match or closest
        route = min(routes, key=lambda r: abs(r.duration_hours - snapped))

    return {
        'route_name': route.route_name,
        'duration_hours': route.duration_hours,
        'gil_per_sub_day': route.gil_per_sub_day,
        'avg_exp': route.avg_exp,
        'fc_points': route.fc_points
    }
