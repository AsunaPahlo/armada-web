"""
Route Stats Service - Fetches gil/earnings data from community spreadsheet.

Source: Fightclub Submarine Spreadsheet
https://docs.google.com/spreadsheets/d/1aOhMH-XrWBIV93Veo3Wo0zz38z-tqk6QWO_4xzu5ZMg/

Note: Only gil-related data is used from this sheet.
Fuel/repair calculations use Lumina data for accuracy.
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
    """Parse hours from string."""
    try:
        return int(value.strip().strip('"'))
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

    def update_route_stats(self, force: bool = False) -> int:
        """
        Update route stats from Google Sheet.

        Returns:
            Number of routes updated
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

                # Parse values - use Gil/Sub/Day (per submarine, not per FC)
                gil_per_sub_day = parse_gil_value(row.get('Gil/Sub/Day', '0'))
                avg_exp = parse_exp(row.get('Avg EXP', '0'))
                fc_points = parse_gil_value(row.get('FC Points', '0'))

                # Skip rows with no meaningful data
                if gil_per_sub_day == 0:
                    continue

                # Upsert route stats - keep the LOWEST gil/sub/day for each route
                # (conservative estimate, same route can have higher gil at higher levels)
                route = RouteStats.query.filter_by(route_name=route_name).first()
                if not route:
                    route = RouteStats(route_name=route_name)
                    db.session.add(route)
                    route.gil_per_sub_day = gil_per_sub_day
                    route.avg_exp = avg_exp
                    route.fc_points = fc_points
                elif gil_per_sub_day < route.gil_per_sub_day:
                    # Only update if this entry has lower gil (conservative)
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
        logger.info(f"[RouteStats] Updated {count} routes from spreadsheet")
        return count

    def ensure_data_loaded(self) -> bool:
        """Ensure route stats are loaded on startup."""
        route_count = RouteStats.query.count()
        if route_count == 0:
            logger.info("[RouteStats] No data found, performing initial load...")
            self.update_route_stats(force=True)
            return True
        return False

    def get_gil_per_day(self, route_name: str) -> Optional[int]:
        """
        Get gil per day for a route name.

        Args:
            route_name: Route name like 'OJ', 'JORZ', etc.

        Returns:
            Gil per submarine per day, or None if not found
        """
        route = RouteStats.query.filter_by(route_name=route_name).first()
        return route.gil_per_sub_day if route else None


# Singleton instance
route_stats_service = RouteStatsService()


def get_route_gil_per_day(route_name: str) -> int:
    """
    Get gil per day for a route, with fallback to hardcoded values.

    Args:
        route_name: Route name like 'OJ', 'JORZ', etc.

    Returns:
        Gil per submarine per day
    """
    # Try database first
    route = RouteStats.query.filter_by(route_name=route_name).first()
    if route and route.gil_per_sub_day > 0:
        return route.gil_per_sub_day

    # No route data available
    return 0


def get_route_stats(route_name: str) -> Optional[dict]:
    """
    Get full route stats.

    Returns dict with gil_per_sub_day, avg_exp, fc_points.
    """
    route = RouteStats.query.filter_by(route_name=route_name).first()
    if not route:
        return None

    return {
        'route_name': route.route_name,
        'gil_per_sub_day': route.gil_per_sub_day,
        'avg_exp': route.avg_exp,
        'fc_points': route.fc_points
    }
