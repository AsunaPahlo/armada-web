"""
Activity Tracker service

Detects changes between old and new plugin data states and logs them
to the activity log table.
"""
import json
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models.activity_log import ActivityLog
from app.utils.logging import get_logger

logger = get_logger('ActivityTracker')


class ActivityTracker:
    """
    Tracks and logs submarine fleet activity changes.

    Compares old state vs new state when plugin data arrives and
    detects changes per submarine: level, build, route.
    Also detects new sector unlocks per character.
    """

    def __init__(self):
        self._initialized_fcs = set()  # Track FCs we've seen before

    def _build_state_map(self, accounts_data: list[dict]) -> dict:
        """
        Build a lookup map of submarine state from raw plugin data.

        Returns:
            Dict mapping (fc_id, sub_name) -> {level, build, route, character}
        """
        state = {}

        for account in accounts_data:
            for char in account.get('characters', []):
                fc_id = str(char.get('fc_id', ''))
                char_name = char.get('name', '')

                for sub in char.get('submarines', []):
                    sub_name = sub.get('name', '')
                    if not sub_name:
                        continue

                    key = (fc_id, sub_name)

                    # Build the build string from parts
                    build = self._get_build_string(sub)

                    # Get route name from current_route_points
                    route_points = sub.get('current_route_points', [])
                    route_name = self._get_route_name(route_points)

                    state[key] = {
                        'level': sub.get('level', 0),
                        'build': build,
                        'route': route_name,
                        'route_points': route_points,
                        'character': char_name
                    }

        return state

    def _get_build_string(self, sub_data: dict) -> str:
        """Convert part IDs to build string like 'S+S+U+C+'."""
        from app.services.submarine_data import SUB_PARTS_LOOKUP, CLASS_SHORTCUTS

        parts = []
        for key in ['part1', 'part2', 'part3', 'part4']:
            part_id = sub_data.get(key, 0)
            if part_id != 0:
                full_name = SUB_PARTS_LOOKUP.get(part_id, f"Unknown({part_id})")
                for prefix, code in CLASS_SHORTCUTS.items():
                    if full_name.startswith(prefix):
                        parts.append(code)
                        break
                else:
                    parts.append('?')
        return ''.join(parts)

    def _get_route_name(self, route_points: list) -> str:
        """Get route name from sector points."""
        if not route_points:
            return ''

        try:
            from app.services.submarine_data import get_route_name_from_points
            route_points = [int(p) for p in route_points if p is not None]
            return get_route_name_from_points(route_points) or ''
        except Exception:
            return ''

    def _get_fc_info(self, accounts_data: list[dict]) -> dict:
        """Extract FC info (fc_id -> fc_name) from accounts data."""
        fc_info = {}
        for account in accounts_data:
            for fc_id_str, fc_data in account.get('fc_data', {}).items():
                fc_info[fc_id_str] = fc_data.get('name', f'FC-{fc_id_str}')
        return fc_info

    def _get_unlocked_sectors(self, accounts_data: list[dict]) -> dict:
        """
        Build a map of fc_id -> set of unlocked sector IDs.

        Returns:
            Dict mapping fc_id -> set of sector IDs
        """
        fc_sectors = {}

        for account in accounts_data:
            for char in account.get('characters', []):
                fc_id = str(char.get('fc_id', ''))
                unlocked = set(char.get('unlocked_sectors', []))

                if fc_id not in fc_sectors:
                    fc_sectors[fc_id] = set()
                fc_sectors[fc_id].update(unlocked)

        return fc_sectors

    def _get_submarines_by_fc(self, accounts_data: list[dict]) -> dict:
        """
        Build a map of fc_id -> set of submarine names.

        Returns:
            Dict mapping fc_id -> set of submarine names
        """
        fc_subs = {}

        for account in accounts_data:
            for char in account.get('characters', []):
                fc_id = str(char.get('fc_id', ''))

                if fc_id not in fc_subs:
                    fc_subs[fc_id] = set()

                for sub in char.get('submarines', []):
                    sub_name = sub.get('name', '')
                    if sub_name:
                        fc_subs[fc_id].add(sub_name)

        return fc_subs

    def detect_and_log_changes(self, old_data: list[dict], new_data: list[dict],
                               is_first_update: bool = False) -> int:
        """
        Detect changes between old and new data and log them.

        Args:
            old_data: Previous raw plugin data
            new_data: New raw plugin data
            is_first_update: If True, this is the first data for this FC
                           (skip logging everything as "new")

        Returns:
            Number of activities logged
        """
        if not new_data:
            return 0

        # Skip logging on first update to avoid flooding with "added" events
        if is_first_update or not old_data:
            # Just track which FCs we've seen
            for account in new_data:
                for char in account.get('characters', []):
                    fc_id = str(char.get('fc_id', ''))
                    self._initialized_fcs.add(fc_id)
            return 0

        changes_logged = 0
        fc_info = self._get_fc_info(new_data)

        old_state = self._build_state_map(old_data)
        new_state = self._build_state_map(new_data)

        old_subs_by_fc = self._get_submarines_by_fc(old_data)
        new_subs_by_fc = self._get_submarines_by_fc(new_data)

        old_sectors = self._get_unlocked_sectors(old_data)
        new_sectors = self._get_unlocked_sectors(new_data)

        # Track changes per submarine
        for key, new_sub in new_state.items():
            fc_id, sub_name = key
            fc_name = fc_info.get(fc_id, f'FC-{fc_id}')
            old_sub = old_state.get(key)

            if not old_sub:
                # New submarine appeared
                # Only log if we've seen this FC before (not first update)
                if fc_id in self._initialized_fcs:
                    ActivityLog.log_activity(
                        fc_id=fc_id,
                        fc_name=fc_name,
                        activity_type=ActivityLog.TYPE_SUBMARINE_ADDED,
                        submarine_name=sub_name,
                        character_name=new_sub.get('character'),
                        new_value=new_sub.get('build'),
                        details=json.dumps({'level': new_sub.get('level', 1)})
                    )
                    changes_logged += 1
                continue

            # Check for level up
            if old_sub['level'] < new_sub['level']:
                ActivityLog.log_activity(
                    fc_id=fc_id,
                    fc_name=fc_name,
                    activity_type=ActivityLog.TYPE_LEVEL_UP,
                    submarine_name=sub_name,
                    character_name=new_sub.get('character'),
                    old_value=str(old_sub['level']),
                    new_value=str(new_sub['level'])
                )
                changes_logged += 1

            # Check for build change
            if old_sub['build'] and new_sub['build'] and old_sub['build'] != new_sub['build']:
                ActivityLog.log_activity(
                    fc_id=fc_id,
                    fc_name=fc_name,
                    activity_type=ActivityLog.TYPE_BUILD_CHANGE,
                    submarine_name=sub_name,
                    character_name=new_sub.get('character'),
                    old_value=old_sub['build'],
                    new_value=new_sub['build']
                )
                changes_logged += 1

            # Check for route change
            if old_sub['route'] and new_sub['route'] and old_sub['route'] != new_sub['route']:
                ActivityLog.log_activity(
                    fc_id=fc_id,
                    fc_name=fc_name,
                    activity_type=ActivityLog.TYPE_ROUTE_CHANGE,
                    submarine_name=sub_name,
                    character_name=new_sub.get('character'),
                    old_value=old_sub['route'],
                    new_value=new_sub['route']
                )
                changes_logged += 1

        # Check for removed submarines
        for key, old_sub in old_state.items():
            fc_id, sub_name = key
            if key not in new_state:
                # Submarine was removed
                # Only log if we've seen this FC before (not first update)
                if fc_id in self._initialized_fcs:
                    fc_name = fc_info.get(fc_id, f'FC-{fc_id}')
                    ActivityLog.log_activity(
                        fc_id=fc_id,
                        fc_name=fc_name,
                        activity_type=ActivityLog.TYPE_SUBMARINE_REMOVED,
                        submarine_name=sub_name,
                        character_name=old_sub.get('character'),
                        old_value=old_sub.get('build')
                    )
                    changes_logged += 1

        # Check for sector unlocks per FC
        for fc_id, new_fc_sectors in new_sectors.items():
            old_fc_sectors = old_sectors.get(fc_id, set())
            newly_unlocked = new_fc_sectors - old_fc_sectors

            # Only log if:
            # 1. There are newly unlocked sectors
            # 2. We've seen this FC before
            # 3. The old data actually had some sectors (empty means "unknown", not "none")
            #    This prevents logging all sectors as "new" on first real unlock data
            if newly_unlocked and fc_id in self._initialized_fcs and old_fc_sectors:
                fc_name = fc_info.get(fc_id, f'FC-{fc_id}')

                # Get sector names for display
                sector_names = self._get_sector_names(newly_unlocked)

                ActivityLog.log_activity(
                    fc_id=fc_id,
                    fc_name=fc_name,
                    activity_type=ActivityLog.TYPE_SECTOR_UNLOCK,
                    new_value=', '.join(sorted(sector_names)),
                    details=json.dumps({'sector_ids': sorted(list(newly_unlocked))})
                )
                changes_logged += 1

        # Update initialized FCs
        for fc_id in new_subs_by_fc.keys():
            self._initialized_fcs.add(fc_id)

        # Commit all changes
        if changes_logged > 0:
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.warning(f"Error committing changes: {e}")
                return 0

        return changes_logged

    def _get_sector_names(self, sector_ids: set) -> list[str]:
        """Get sector letter codes for a set of sector IDs."""
        try:
            from app.models.lumina import SubmarineExploration
            names = []
            for sector_id in sector_ids:
                sector = SubmarineExploration.query.get(sector_id)
                if sector:
                    names.append(sector.location or sector.destination or str(sector_id))
                else:
                    names.append(str(sector_id))
            return names
        except Exception:
            return [str(sid) for sid in sector_ids]

    def is_first_update_for_fc(self, fc_id: str) -> bool:
        """Check if this is the first update for an FC."""
        return str(fc_id) not in self._initialized_fcs

    def initialize_from_existing_data(self, accounts_data: list[dict]) -> None:
        """
        Initialize the tracker with existing FC IDs from loaded data.

        Call this on startup after loading persisted plugin data to prevent
        spurious "removed" or "added" activity entries.
        """
        for account in accounts_data:
            for char in account.get('characters', []):
                fc_id = str(char.get('fc_id', ''))
                if fc_id and fc_id != '0':
                    self._initialized_fcs.add(fc_id)


# Singleton instance
activity_tracker = ActivityTracker()
