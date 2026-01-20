"""
Lumina Data Service - Downloads and manages FFXIV game data from GitHub
Source: https://github.com/xivapi/ffxiv-datamining
"""
import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Optional
import requests

from app import db
from app.models.lumina import (
    DataVersion, SubmarinePart, SubmarineExploration,
    SubmarineMap, SubmarineRank
)

logger = logging.getLogger(__name__)

# GitHub raw URLs for CSV files
GITHUB_BASE_URL = "https://raw.githubusercontent.com/xivapi/ffxiv-datamining/master/csv/en"
CSV_FILES = {
    'submarine_parts': f"{GITHUB_BASE_URL}/SubmarinePart.csv",
    'submarine_explorations': f"{GITHUB_BASE_URL}/SubmarineExploration.csv",
    'submarine_maps': f"{GITHUB_BASE_URL}/SubmarineMap.csv",
    'submarine_ranks': f"{GITHUB_BASE_URL}/SubmarineRank.csv",
}

# Update interval (24 hours - once per day)
UPDATE_INTERVAL_HOURS = 24


class LuminaDataService:
    """Service for downloading and managing Lumina game data."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Armada-SubmarineDashboard/1.0'
        })

    def needs_update(self, table_name: str) -> bool:
        """Check if a table needs to be updated based on last update time."""
        version = DataVersion.query.filter_by(table_name=table_name).first()
        if not version:
            return True

        time_since_update = datetime.utcnow() - version.last_updated
        return time_since_update > timedelta(hours=UPDATE_INTERVAL_HOURS)

    def fetch_csv(self, url: str, table_name: str) -> Optional[str]:
        """
        Fetch CSV from GitHub with conditional request using ETag.
        Returns CSV content if new/updated, None if unchanged.
        """
        version = DataVersion.query.filter_by(table_name=table_name).first()

        headers = {}
        if version and version.etag:
            headers['If-None-Match'] = version.etag

        try:
            response = self.session.get(url, headers=headers, timeout=30)

            if response.status_code == 304:
                # Not modified
                logger.info(f"[Lumina] {table_name}: No changes (304)")
                # Update last checked time
                if version:
                    version.last_updated = datetime.utcnow()
                    db.session.commit()
                return None

            response.raise_for_status()

            # Store new ETag
            new_etag = response.headers.get('ETag')
            if version:
                version.etag = new_etag
                version.last_updated = datetime.utcnow()
            else:
                version = DataVersion(
                    table_name=table_name,
                    etag=new_etag,
                    last_updated=datetime.utcnow()
                )
                db.session.add(version)

            db.session.commit()
            return response.text

        except requests.RequestException as e:
            logger.error(f"[Lumina] Failed to fetch {table_name}: {e}")
            return None

    def parse_csv(self, content: str) -> list[dict]:
        """Parse CSV content, skipping the first two rows (headers)."""
        lines = content.strip().split('\n')
        if len(lines) < 3:
            return []

        # Row 0: key names, Row 1: type info, Row 2+: data
        # We'll use row 0 as headers
        reader = csv.DictReader(io.StringIO('\n'.join([lines[0]] + lines[2:])))
        return list(reader)

    def update_submarine_parts(self, force: bool = False) -> int:
        """Update submarine parts table from CSV."""
        table_name = 'submarine_parts'

        if not force and not self.needs_update(table_name):
            logger.debug(f"[Lumina] {table_name}: Skipping (not due for update)")
            return 0

        content = self.fetch_csv(CSV_FILES[table_name], table_name)
        if content is None:
            return 0

        rows = self.parse_csv(content)
        count = 0

        for row in rows:
            try:
                row_id = int(row.get('#', 0))
                if row_id == 0:
                    continue

                part = SubmarinePart.query.get(row_id)
                if not part:
                    part = SubmarinePart(id=row_id)
                    db.session.add(part)

                part.slot = int(row.get('Slot', 0))
                part.rank = int(row.get('Rank', 1))
                part.class_type = int(row.get('Class', 0))
                part.components = int(row.get('Components', 0))
                part.repair_materials = int(row.get('RepairMaterials', 0))
                part.surveillance = int(row.get('Surveillance', 0))
                part.retrieval = int(row.get('Retrieval', 0))
                part.speed = int(row.get('Speed', 0))
                part.range = int(row.get('Range', 0))
                part.favor = int(row.get('Favor', 0))

                count += 1
            except (ValueError, KeyError) as e:
                logger.warning(f"[Lumina] Error parsing part row: {e}")
                continue

        # Update version info
        version = DataVersion.query.filter_by(table_name=table_name).first()
        if version:
            version.row_count = count

        db.session.commit()
        logger.info(f"[Lumina] Updated {count} submarine parts")
        return count

    def update_submarine_explorations(self, force: bool = False) -> int:
        """Update submarine exploration sectors from CSV."""
        table_name = 'submarine_explorations'

        if not force and not self.needs_update(table_name):
            return 0

        content = self.fetch_csv(CSV_FILES[table_name], table_name)
        if content is None:
            return 0

        rows = self.parse_csv(content)
        count = 0

        for row in rows:
            try:
                row_id = int(row.get('#', 0))
                if row_id == 0:
                    continue

                sector = SubmarineExploration.query.get(row_id)
                if not sector:
                    sector = SubmarineExploration(id=row_id)
                    db.session.add(sector)

                sector.destination = row.get('Destination', '')
                sector.location = row.get('Location', '')
                sector.map_id = int(row.get('Map', 0))
                sector.rank_req = int(row.get('RankReq', 1))
                sector.ceruleum_tank_req = int(row.get('CeruleumTankReq', 1))
                sector.stars = int(row.get('Stars', 1))
                sector.exp_reward = int(row.get('ExpReward', 0))
                sector.survey_duration_min = int(row.get('SurveyDurationmin', 0))
                sector.survey_distance = int(row.get('SurveyDistance', 0))
                sector.x = int(row.get('X', 0))
                sector.y = int(row.get('Y', 0))
                sector.z = int(row.get('Z', 0))
                sector.starting_point = row.get('StartingPoint', 'False').lower() == 'true'

                count += 1
            except (ValueError, KeyError) as e:
                logger.warning(f"[Lumina] Error parsing exploration row: {e}")
                continue

        version = DataVersion.query.filter_by(table_name=table_name).first()
        if version:
            version.row_count = count

        db.session.commit()
        logger.info(f"[Lumina] Updated {count} submarine exploration sectors")
        return count

    def update_submarine_maps(self, force: bool = False) -> int:
        """Update submarine maps from CSV."""
        table_name = 'submarine_maps'

        if not force and not self.needs_update(table_name):
            return 0

        content = self.fetch_csv(CSV_FILES[table_name], table_name)
        if content is None:
            return 0

        rows = self.parse_csv(content)
        count = 0

        for row in rows:
            try:
                row_id = int(row.get('#', 0))
                if row_id == 0:
                    continue

                map_entry = SubmarineMap.query.get(row_id)
                if not map_entry:
                    map_entry = SubmarineMap(id=row_id)
                    db.session.add(map_entry)

                map_entry.name = row.get('Name', f'Map {row_id}')
                count += 1
            except (ValueError, KeyError) as e:
                logger.warning(f"[Lumina] Error parsing map row: {e}")
                continue

        version = DataVersion.query.filter_by(table_name=table_name).first()
        if version:
            version.row_count = count

        db.session.commit()
        logger.info(f"[Lumina] Updated {count} submarine maps")
        return count

    def update_submarine_ranks(self, force: bool = False) -> int:
        """Update submarine ranks from CSV."""
        table_name = 'submarine_ranks'

        if not force and not self.needs_update(table_name):
            return 0

        content = self.fetch_csv(CSV_FILES[table_name], table_name)
        if content is None:
            return 0

        rows = self.parse_csv(content)
        count = 0

        for row in rows:
            try:
                row_id = int(row.get('#', 0))
                # Rank 0 is valid (starting rank data)

                rank_entry = SubmarineRank.query.get(row_id)
                if not rank_entry:
                    rank_entry = SubmarineRank(id=row_id)
                    db.session.add(rank_entry)

                rank_entry.exp_to_next = int(row.get('ExpToNext', 0))
                rank_entry.capacity = int(row.get('Capacity', 0))
                rank_entry.surveillance_bonus = int(row.get('SurveillanceBonus', 0))
                rank_entry.retrieval_bonus = int(row.get('RetrievalBonus', 0))
                rank_entry.speed_bonus = int(row.get('SpeedBonus', 0))
                rank_entry.range_bonus = int(row.get('RangeBonus', 0))
                rank_entry.favor_bonus = int(row.get('FavorBonus', 0))

                count += 1
            except (ValueError, KeyError) as e:
                logger.warning(f"[Lumina] Error parsing rank row: {e}")
                continue

        version = DataVersion.query.filter_by(table_name=table_name).first()
        if version:
            version.row_count = count

        db.session.commit()
        logger.info(f"[Lumina] Updated {count} submarine ranks")
        return count

    def update_all(self, force: bool = False) -> dict:
        """Update all Lumina data tables."""
        results = {
            'parts': self.update_submarine_parts(force),
            'explorations': self.update_submarine_explorations(force),
            'maps': self.update_submarine_maps(force),
            'ranks': self.update_submarine_ranks(force),
        }
        total = sum(results.values())
        if total > 0:
            logger.info(f"[Lumina] Total updated: {total} rows")
        return results

    def ensure_data_loaded(self) -> bool:
        """Ensure data is loaded on startup. Returns True if data was loaded."""
        # Check if we have any data
        parts_count = SubmarinePart.query.count()
        explorations_count = SubmarineExploration.query.count()

        if parts_count == 0 or explorations_count == 0:
            logger.info("[Lumina] No data found, performing initial load...")
            self.update_all(force=True)
            return True

        return False

    def get_data_status(self) -> dict:
        """Get status of all data tables."""
        versions = DataVersion.query.all()
        return {
            v.table_name: {
                'last_updated': v.last_updated.isoformat() if v.last_updated else None,
                'row_count': v.row_count,
                'needs_update': self.needs_update(v.table_name)
            }
            for v in versions
        }


# Singleton instance
lumina_service = LuminaDataService()


def get_part_by_id(part_id: int) -> Optional[SubmarinePart]:
    """Get submarine part by ID."""
    return SubmarinePart.query.get(part_id)


def get_exploration_by_id(sector_id: int) -> Optional[SubmarineExploration]:
    """Get exploration sector by ID."""
    return SubmarineExploration.query.get(sector_id)


def get_exploration_by_location(location: str, map_id: int = None) -> Optional[SubmarineExploration]:
    """Get exploration sector by location letter."""
    query = SubmarineExploration.query.filter_by(location=location)
    if map_id:
        query = query.filter_by(map_id=map_id)
    return query.first()


def get_rank_bonuses(rank: int) -> Optional[SubmarineRank]:
    """Get rank bonuses for a given rank level."""
    return SubmarineRank.query.get(rank)


def get_map_name(map_id: int) -> str:
    """Get map name by ID."""
    map_entry = SubmarineMap.query.get(map_id)
    return map_entry.name if map_entry else f"Unknown ({map_id})"
