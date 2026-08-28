"""
Fleet Manager service

Coordinates config parsing, data aggregation, and real-time updates.
"""
import calendar
import copy
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlalchemy.exc import SQLAlchemyError

from app.services.config_parser import ConfigParser, AccountData
from app.utils.logging import get_logger

logger = get_logger('FleetManager')

# Default path for persisted plugin data
PLUGIN_DATA_FILE = Path(__file__).parent.parent.parent / 'data' / 'plugin_data.json'


def compute_gil_per_day_by_tag(fc_summaries: list) -> list:
    """Aggregate gil/day per FC tag, plus an 'Untagged' bucket.

    An FC's gil/day is counted in full in every tag it carries, so buckets can
    overlap for multi-tag FCs. FCs with no tags accumulate into a single
    'Untagged' bucket.

    Returns a list of bucket dicts (tag_id, tag_name, color, gil_per_day,
    fc_count) sorted by gil/day descending (tie-break by name). The 'Untagged'
    bucket, when present, is appended last; it is omitted entirely when every FC
    is tagged.
    """
    tag_buckets: dict = {}  # tag_id -> bucket dict
    untagged_gpd = 0.0
    untagged_count = 0

    for fc in fc_summaries:
        gpd = fc.get('gil_per_day', 0) or 0
        tags = fc.get('tags') or []
        if tags:
            for tag in tags:
                tid = tag.get('id')
                bucket = tag_buckets.get(tid)
                if bucket is None:
                    bucket = {
                        'tag_id': tid,
                        'tag_name': tag.get('name', ''),
                        'color': tag.get('color', 'secondary'),
                        'gil_per_day': 0.0,
                        'fc_count': 0,
                    }
                    tag_buckets[tid] = bucket
                bucket['gil_per_day'] += gpd
                bucket['fc_count'] += 1
        else:
            untagged_gpd += gpd
            untagged_count += 1

    result = sorted(
        tag_buckets.values(),
        key=lambda b: (-b['gil_per_day'], b['tag_name']),
    )
    for bucket in result:
        bucket['gil_per_day'] = int(bucket['gil_per_day'])

    if untagged_count > 0:
        result.append({
            'tag_id': None,
            'tag_name': 'Untagged',
            'color': 'secondary',
            'gil_per_day': int(untagged_gpd),
            'fc_count': untagged_count,
        })

    return result


class FleetManager:
    """
    Manages submarine fleet data across all accounts.
    Provides real-time updates and data aggregation.
    """

    def __init__(self, accounts_config_path: str | Path = None):
        """
        Initialize fleet manager.

        Args:
            accounts_config_path: Path to accounts.json configuration
        """
        self.parser = ConfigParser(accounts_config_path)
        self._cached_data: list[AccountData] = []
        self._plugin_data: dict[str, list[AccountData]] = {}  # plugin_id -> list of AccountData
        self._plugin_data_raw: dict[str, list[dict]] = {}  # Raw data for persistence
        self._plugin_metadata: dict[str, dict] = {}  # plugin_id -> {timestamp, received_at}
        self._carried_forward_subs: dict[str, set] = {}  # plugin_id -> set of (cid, sub_name) carried forward once
        self._supplier_data: dict[str, list[dict]] = {}  # plugin_id -> list of supplier dicts
        self._last_update: datetime = None
        self._update_callbacks: list[Callable] = []
        self._update_thread: threading.Thread = None
        self._running = False
        self._lock = threading.Lock()
        self._rebuild_lock = threading.Lock()  # Serializes _rebuild_dashboard calls
        self._cached_dashboard: dict | None = None  # Pre-computed dashboard result
        self._save_timer: threading.Timer | None = None  # Debounced file persistence

        # Load persisted plugin data on startup
        self._load_plugin_data()

    def _load_plugin_data(self):
        """Load persisted plugin data from file."""
        try:
            if PLUGIN_DATA_FILE.exists():
                with open(PLUGIN_DATA_FILE, 'r', encoding='utf-8') as f:
                    saved_data = json.load(f)

                for plugin_id, plugin_entry in saved_data.items():
                    # Skip internal keys
                    if plugin_id.startswith('_'):
                        continue

                    # Support both old format (list) and new format (dict with metadata)
                    if isinstance(plugin_entry, list):
                        accounts_data = plugin_entry
                        metadata = {}
                    else:
                        accounts_data = plugin_entry.get('accounts', [])
                        metadata = {
                            'timestamp': plugin_entry.get('timestamp'),
                            'received_at': plugin_entry.get('received_at')
                        }

                    self._plugin_data_raw[plugin_id] = accounts_data
                    self._plugin_metadata[plugin_id] = metadata

                    # Load supplier data
                    if isinstance(plugin_entry, dict):
                        suppliers = plugin_entry.get('suppliers', [])
                        if suppliers:
                            self._supplier_data[plugin_id] = suppliers

                    # Parse the raw data into AccountData objects
                    parsed_accounts = []
                    for account_data in accounts_data:
                        try:
                            parsed = self.parser.parse_plugin_data(account_data)
                            if parsed.characters:
                                parsed_accounts.append(parsed)
                        except Exception as e:
                            logger.warning(f"Error parsing saved plugin data: {e}")

                    if parsed_accounts:
                        self._plugin_data[plugin_id] = parsed_accounts

                    # Initialize activity tracker with existing FCs to prevent spurious activity entries
                    try:
                        from app.services.activity_tracker import activity_tracker
                        activity_tracker.initialize_from_existing_data(accounts_data)
                    except Exception as e:
                        logger.warning(f"Error initializing activity tracker: {e}")

                    if metadata.get('received_at'):
                        logger.info(f"Loaded plugin data for {plugin_id} (last data: {metadata.get('received_at')})")

        except Exception as e:
            logger.warning(f"Error loading plugin data file: {e}")

    def _save_plugin_data(self):
        """Schedule a debounced save of plugin data to file.

        If multiple updates arrive within 5 seconds, only the last one writes to disk.
        The actual I/O happens in a background thread, outside the lock.
        """
        # Cancel any pending save
        if self._save_timer is not None:
            self._save_timer.cancel()

        # Snapshot the data to save (under the lock, which the caller already holds)
        save_data = {}
        for plugin_id, accounts_data in self._plugin_data_raw.items():
            metadata = self._plugin_metadata.get(plugin_id, {})
            save_data[plugin_id] = {
                'accounts': accounts_data,
                'timestamp': metadata.get('timestamp'),
                'received_at': metadata.get('received_at'),
                'suppliers': self._supplier_data.get(plugin_id, [])
            }

        def _do_save():
            try:
                PLUGIN_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(PLUGIN_DATA_FILE, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, indent=2)
            except Exception as e:
                logger.warning(f"Error saving plugin data: {e}")

        self._save_timer = threading.Timer(5.0, _do_save)
        self._save_timer.daemon = True
        self._save_timer.start()

    def add_account(self, nickname: str, config_path: str):
        """Add an account to monitor."""
        self.parser.add_account(nickname, config_path)

    def _resolve_missing_fc_ids(self, plugin_id: str, new_accounts_data: list[dict]) -> list[dict]:
        """
        Resolve fc_id=0 using last known fc_id from previous plugin data.

        The plugin can only read FC data for the currently logged-in character.
        Other characters may have fc_id=0. We look up their last known fc_id
        from previous data using their character ID (cid).

        Args:
            plugin_id: Plugin identifier
            new_accounts_data: New account data from plugin (already deepcopied)

        Returns:
            Account data with fc_id=0 resolved where possible
        """
        existing_data = self._plugin_data_raw.get(plugin_id, [])
        if not existing_data:
            return new_accounts_data

        # Build lookup of cid -> last known fc_id from previous data
        # Normalize cid to string to avoid int/str type mismatches
        known_fc_ids = {}
        for account in existing_data:
            for char in account.get('characters', []):
                cid = str(char.get('cid', ''))
                fc_id = char.get('fc_id')
                if cid and fc_id and fc_id != 0 and str(fc_id) != '0':
                    known_fc_ids[cid] = fc_id

        if not known_fc_ids:
            return new_accounts_data

        # Patch fc_id=0 with last known fc_id
        for account in new_accounts_data:
            for char in account.get('characters', []):
                cid = str(char.get('cid', ''))
                fc_id = char.get('fc_id')
                if (not fc_id or fc_id == 0 or str(fc_id) == '0') and cid in known_fc_ids:
                    old_fc_id = known_fc_ids[cid]
                    logger.debug(f"Resolved fc_id=0 for {char.get('name', '?')} (cid={cid}) -> {old_fc_id}")
                    char['fc_id'] = old_fc_id

        return new_accounts_data

    def _preserve_missing_submarines(self, plugin_id: str, new_accounts_data: list[dict]) -> list[dict]:
        """
        Carry forward submarines that disappeared from the latest update for one grace period.

        If a submarine was present in the previous data but missing in the new data,
        inject it back for one update cycle so it stays visible on the dashboard.
        If it's still missing on the next update, let it actually disappear.

        Args:
            plugin_id: Plugin identifier
            new_accounts_data: New account data (already deepcopied by _merge_unlock_data)

        Returns:
            Account data with temporarily missing submarines preserved
        """
        existing_data = self._plugin_data_raw.get(plugin_id, [])
        if not existing_data:
            return new_accounts_data

        # Build lookup of (cid, sub_name) -> sub_data from old data
        old_subs = {}  # (cid, sub_name) -> sub dict
        for account in existing_data:
            for char in account.get('characters', []):
                cid = str(char.get('cid', ''))
                if not cid:
                    continue
                for sub in char.get('submarines', []):
                    sub_name = sub.get('name', '')
                    if sub_name:
                        old_subs[(cid, sub_name)] = sub

        # Build lookup of (cid, sub_name) from new data
        new_subs = set()
        for account in new_accounts_data:
            for char in account.get('characters', []):
                cid = str(char.get('cid', ''))
                if not cid:
                    continue
                for sub in char.get('submarines', []):
                    sub_name = sub.get('name', '')
                    if sub_name:
                        new_subs.add((cid, sub_name))

        # Find subs that disappeared
        missing = set(old_subs.keys()) - new_subs
        if not missing:
            # All subs accounted for - clear any carried forward tracking
            self._carried_forward_subs.pop(plugin_id, None)
            return new_accounts_data

        previously_carried = self._carried_forward_subs.get(plugin_id, set())
        carry_now = set()

        # Build a map of cid -> char dict in new data for injection
        new_chars_by_cid = {}
        for account in new_accounts_data:
            for char in account.get('characters', []):
                cid = str(char.get('cid', ''))
                if cid:
                    new_chars_by_cid[cid] = char

        for key in missing:
            cid, sub_name = key
            if key in previously_carried:
                # Already carried forward once - let it go
                logger.info(f"Submarine {sub_name} (cid={cid}) missing for 2+ updates, removing from dashboard")
                continue

            # First time missing - carry forward
            carry_now.add(key)
            char_dict = new_chars_by_cid.get(cid)
            if char_dict is not None:
                char_dict.setdefault('submarines', []).append(copy.deepcopy(old_subs[key]))
                logger.debug(f"Preserving temporarily missing submarine {sub_name} (cid={cid})")

        # Update tracking
        if carry_now:
            self._carried_forward_subs[plugin_id] = carry_now
        else:
            self._carried_forward_subs.pop(plugin_id, None)

        return new_accounts_data

    def _merge_unlock_data(self, plugin_id: str, new_accounts_data: list[dict]) -> list[dict]:
        """
        Merge unlock_sectors data, preserving existing data when new data is empty.

        The game plugin can only read unlock data for the currently logged-in character's FC.
        Other characters in the data will have empty unlock_sectors. We need to preserve
        their existing unlock data rather than overwriting with empty lists.

        Args:
            plugin_id: Plugin identifier
            new_accounts_data: New account data from plugin

        Returns:
            Merged account data with preserved unlock_sectors
        """
        # Get existing raw data for this plugin
        existing_data = self._plugin_data_raw.get(plugin_id, [])
        if not existing_data:
            return new_accounts_data

        # Build lookup of existing unlock_sectors by character ID
        existing_unlocks = {}
        for account in existing_data:
            for char in account.get('characters', []):
                cid = char.get('cid')
                unlocks = char.get('unlocked_sectors', [])
                if cid and unlocks:
                    existing_unlocks[cid] = unlocks

        # Merge: preserve existing unlock data when new data is empty
        merged_data = copy.deepcopy(new_accounts_data)

        for account in merged_data:
            for char in account.get('characters', []):
                cid = char.get('cid')
                new_unlocks = char.get('unlocked_sectors', [])

                # If new data is empty but we have existing data, preserve it
                if not new_unlocks and cid in existing_unlocks:
                    char['unlocked_sectors'] = existing_unlocks[cid]

        return merged_data

    def set_plugin_data(self, plugin_id: str, accounts_data: list[dict], timestamp: str = None, received_at: str = None, suppliers: list[dict] = None):
        """
        Store fleet data received from a plugin.

        Args:
            plugin_id: Unique identifier for the plugin
            accounts_data: List of account data dicts from the plugin
            timestamp: Timestamp from the plugin data
            received_at: When the server received the data
            suppliers: List of supplier character dicts from the plugin
        """
        with self._lock:
            # Get old state before merging for activity tracking
            old_data = self._plugin_data_raw.get(plugin_id, [])
            is_first_update = not old_data

            # Merge unlock_sectors data - preserve existing data when new data is empty
            # The plugin can only read unlock data for the currently logged-in character's FC,
            # so we need to preserve unlock data for other characters/FCs
            accounts_data = self._merge_unlock_data(plugin_id, accounts_data)

            # Resolve fc_id=0 from last known data if it occurs
            # Characters should normally always have a valid fc_id, but in rare cases
            # the plugin may return 0 - fall back to the last known fc_id for that character
            accounts_data = self._resolve_missing_fc_ids(plugin_id, accounts_data)

            # Track activity changes (compare old vs new state)
            # This must run BEFORE _preserve_missing_submarines so it sees the real diff
            try:
                from app.services.activity_tracker import activity_tracker
                activity_tracker.detect_and_log_changes(
                    old_data=old_data,
                    new_data=accounts_data,
                    is_first_update=is_first_update
                )
            except Exception as e:
                logger.info(f"Activity tracking error: {e}")

            # Carry forward submarines that temporarily disappeared for one update cycle
            # so they remain visible on the dashboard during brief data blips
            accounts_data = self._preserve_missing_submarines(plugin_id, accounts_data)

            # Parse each account from the plugin
            parsed_accounts = []
            for account_data in accounts_data:
                try:
                    parsed = self.parser.parse_plugin_data(account_data)
                    if parsed.characters:  # Only add if there's actual data
                        parsed_accounts.append(parsed)
                except Exception as e:
                    logger.warning(f"Error parsing plugin data: {e}")

            if parsed_accounts:
                self._plugin_data[plugin_id] = parsed_accounts
                self._plugin_data_raw[plugin_id] = accounts_data  # Store raw for persistence
                self._plugin_metadata[plugin_id] = {
                    'timestamp': timestamp,
                    'received_at': received_at or (datetime.utcnow().isoformat() + 'Z')
                }
                self._last_update = datetime.now()
            elif plugin_id not in self._plugin_data_raw:
                # Ensure plugin has an entry in raw data even if no fleet data parsed
                # (e.g. supplier-only accounts with no submarines). This is needed so
                # _save_plugin_data includes this plugin's supplier data in the file.
                self._plugin_data_raw[plugin_id] = accounts_data
                self._plugin_metadata[plugin_id] = {
                    'timestamp': timestamp,
                    'received_at': received_at or (datetime.utcnow().isoformat() + 'Z')
                }

            # Store supplier data if provided
            if suppliers is not None:
                self._supplier_data[plugin_id] = suppliers

            # Persist to file (covers both fleet data and supplier updates)
            self._save_plugin_data()

        # Rebuild dashboard cache outside the lock (uses its own get_data lock)
        try:
            self._rebuild_dashboard()
        except Exception as e:
            logger.warning(f"Error rebuilding dashboard after plugin data: {e}")

    def clear_plugin_data(self, plugin_id: str = None):
        """
        Clear plugin data.

        Args:
            plugin_id: Specific plugin to clear, or None for all
        """
        with self._lock:
            if plugin_id:
                self._plugin_data.pop(plugin_id, None)
                self._plugin_data_raw.pop(plugin_id, None)
                self._plugin_metadata.pop(plugin_id, None)
                self._supplier_data.pop(plugin_id, None)
                self._carried_forward_subs.pop(plugin_id, None)
            else:
                self._plugin_data.clear()
                self._plugin_data_raw.clear()
                self._plugin_metadata.clear()
                self._supplier_data.clear()
                self._carried_forward_subs.clear()

            # Persist the change
            self._save_plugin_data()

        # Rebuild dashboard after clearing data
        try:
            self._rebuild_dashboard()
        except Exception as e:
            logger.warning(f"Error rebuilding dashboard after clear: {e}")

    def get_plugin_metadata(self, plugin_id: str = None) -> dict:
        """
        Get plugin metadata (timestamps).

        Args:
            plugin_id: Specific plugin, or None for all

        Returns:
            Metadata dict or dict of all plugin metadata
        """
        with self._lock:
            if plugin_id:
                return self._plugin_metadata.get(plugin_id, {})
            return dict(self._plugin_metadata)

    def refresh(self) -> list[AccountData]:
        """
        Refresh data from all account configs.

        Returns:
            List of updated AccountData
        """
        with self._lock:
            self._cached_data = self.parser.parse_all_accounts()
            self._last_update = datetime.now()
        return self._cached_data

    def get_data(self, force_refresh: bool = False) -> list[AccountData]:
        """
        Get fleet data, optionally forcing a refresh.
        Merges file-based data with plugin data.

        Args:
            force_refresh: If True, re-parse all configs

        Returns:
            List of AccountData
        """
        with self._lock:
            # Get file-based data
            if force_refresh or not self._cached_data:
                self._cached_data = self.parser.parse_all_accounts()
                self._last_update = datetime.now()

            # Merge with plugin data
            all_accounts = list(self._cached_data)

            # Add plugin data (each plugin can have multiple accounts)
            for plugin_id, plugin_accounts in self._plugin_data.items():
                all_accounts.extend(plugin_accounts)

            return all_accounts

    def _recalculate_sub_status(self, sub) -> tuple[str, float]:
        """
        Recalculate submarine status and hours_remaining based on current time.

        Returns:
            Tuple of (status, hours_remaining)
        """
        # sub.return_time is a naive datetime representing UTC (from utcfromtimestamp)
        # Use calendar.timegm to correctly interpret it as UTC, not local time
        return_timestamp = calendar.timegm(sub.return_time.timetuple())

        # Idle submarines (never dispatched or returned and not re-sent) have epoch-0 return time
        if return_timestamp <= 0:
            return 'ready', 0.0

        current_time = time.time()  # UTC timestamp
        hours_remaining = (return_timestamp - current_time) / 3600

        if hours_remaining <= 0:
            status = 'ready'
        elif hours_remaining <= 0.5:
            status = 'returning_soon'
        else:
            status = 'voyaging'

        return status, hours_remaining

    def get_dashboard_data(self) -> dict:
        """
        Get aggregated data formatted for dashboard display.
        Returns the pre-computed cached dashboard. If no cache exists yet,
        triggers a rebuild (e.g. on first call after startup).

        Returns:
            Dictionary with dashboard summary and details
        """
        if self._cached_dashboard is None:
            self._rebuild_dashboard()
        return self._cached_dashboard

    def get_character_region_counts(self) -> dict:
        """Per-account character counts by region and world (live snapshot).

        Counts every character currently in fleet data, grouped by account
        (plugin nickname). Not affected by stats-page filters. Accounts with no
        characters are omitted.
        """
        from app.services.submarine_data import get_world_region

        totals: dict[str, int] = {}
        grand_total = 0
        accounts_out = []

        for account in self.get_data():
            region_totals: dict[str, int] = {}
            regions: dict[str, dict[str, int]] = {}
            acct_total = 0
            for char in account.characters:
                world = char.world or 'Unknown'
                region = get_world_region(world)
                region_totals[region] = region_totals.get(region, 0) + 1
                regions.setdefault(region, {})
                regions[region][world] = regions[region].get(world, 0) + 1
                totals[region] = totals.get(region, 0) + 1
                acct_total += 1
                grand_total += 1

            if acct_total == 0:
                continue

            sorted_regions = {
                r: dict(sorted(worlds.items(), key=lambda kv: (-kv[1], kv[0])))
                for r, worlds in regions.items()
            }
            accounts_out.append({
                'nickname': account.nickname,
                'total': acct_total,
                'region_totals': region_totals,
                'regions': sorted_regions,
            })

        accounts_out.sort(key=lambda a: a['nickname'])
        return {'totals': totals, 'grand_total': grand_total, 'accounts': accounts_out}

    def _rebuild_dashboard(self):
        """
        Rebuild the cached dashboard data from current fleet state.
        Called when plugin data changes or on first access.
        Serialized via _rebuild_lock to prevent concurrent rebuilds racing.
        """
        with self._rebuild_lock:
            self._rebuild_dashboard_inner()

    def _rebuild_dashboard_inner(self):
        """Inner rebuild logic, must be called while holding _rebuild_lock."""
        accounts = self.get_data()

        # Record stats snapshot only during rebuilds (not on every read)
        try:
            from app.services.stats_tracker import stats_tracker
            stats_tracker.record_snapshot(accounts)
        except Exception as e:
            logger.info(f"Stats recording error: {e}")

        # Get known production routes from cache + user overrides
        from app.services.game_data_cache import get_all_route_names
        from app.models.route_override import get_override_route_names
        known_routes = get_all_route_names()
        known_routes |= get_override_route_names()

        # Get FC visibility configuration (hidden FCs are excluded from views and stats)
        # Single query, derive hidden/excluded/notes in Python
        try:
            from app.models.fc_config import FCConfig
            from app.models.fc_config import _migrate_fc_config_columns
            _migrate_fc_config_columns()
            all_fc_configs = FCConfig.query.all()
            hidden_fc_ids = {c.fc_id for c in all_fc_configs if not c.visible}
            supply_excluded_fc_ids = {c.fc_id for c in all_fc_configs if c.exclude_from_supply}
            fc_notes_map = {c.fc_id: c.notes for c in all_fc_configs if c.notes}
            if hidden_fc_ids:
                logger.info(f"Hidden FC IDs: {hidden_fc_ids}")
            if supply_excluded_fc_ids:
                logger.info(f"Supply-excluded FC IDs: {supply_excluded_fc_ids}")
        except Exception as e:
            # fc_configs table may not exist yet on first run
            logger.info(f"FC config load error (may be first run): {e}")
            hidden_fc_ids = set()
            supply_excluded_fc_ids = set()
            fc_notes_map = {}

        # Get FC housing data
        try:
            from app.models.fc_housing import get_all_fc_housing
            fc_housing = get_all_fc_housing()
        except Exception as e:
            logger.info(f"FC housing load error (may be first run): {e}")
            fc_housing = {}

        # Aggregate totals
        total_subs = 0
        ready_subs = 0
        leveling_subs = 0
        total_gil_per_day = 0.0
        total_ceruleum_per_day = 0.0
        total_kits_per_day = 0.0
        total_ceruleum = 0
        total_repair_kits = 0
        all_submarines = []
        fc_summaries = {}

        for account in accounts:
            for char in account.characters:
                fc_id = char.fc_id

                # Skip characters with no FC (fc_id = 0 means FC data couldn't be read or not in FC)
                if not fc_id or fc_id == 0:
                    continue

                fc_info = account.fc_data.get(fc_id)
                fc_name = fc_info.name if fc_info and fc_info.name else f"FC-{fc_id}"

                # Initialize FC summary if needed
                # Convert fc_id to string to avoid JavaScript precision issues with large integers
                fc_id_str = str(fc_id) if fc_id else 'unknown'

                # Skip hidden FCs entirely (hidden FCs are excluded from views and stats)
                if fc_id_str in hidden_fc_ids:
                    continue

                if fc_id_str not in fc_summaries:
                    # Get region from character's world
                    from app.services.submarine_data import get_world_region
                    region = get_world_region(char.world)

                    # Get house address from FC housing if available
                    try:
                        housing = fc_housing.get(fc_id_str)
                        house_address = housing.address if housing else None
                    except Exception as e:
                        logger.warning(f"Error getting house address for FC {fc_id_str}: {e}")
                        house_address = None

                    fc_summaries[fc_id_str] = {
                        'fc_id': fc_id_str,
                        'fc_name': fc_name,
                        'fc_gil': fc_info.gil if fc_info else 0,
                        'fc_points': fc_info.fc_points if fc_info else 0,
                        'region': region,
                        'world': char.world,
                        'house_address': house_address,
                        'accounts': set(),
                        'characters': [],
                        'submarines': [],
                        'routes': set(),  # Track unique routes
                        'total_subs': 0,
                        'ready_subs': 0,
                        'leveling_subs': 0,
                        'ceruleum': 0,
                        'repair_kits': 0,
                        'gil_per_day': 0.0,
                        'ceruleum_per_day': 0.0,
                        'kits_per_day': 0.0,
                        'soonest_return': None,
                        'soonest_return_time': None,
                        'days_until_restock': None,
                        'dive_credits': 0,
                        'inventory_parts': {},  # item_id -> count, aggregated across characters
                        'unlocked_slots': 0,
                        'needs_dive_credits': False,
                        'dive_credits_needed': 0,
                        'exclude_from_supply': fc_id_str in supply_excluded_fc_ids,
                        'workshop_disabled': False
                    }

                # Aggregate supplies (skip FCs excluded from supply calculations)
                if fc_id_str not in supply_excluded_fc_ids:
                    total_ceruleum += char.ceruleum
                    total_repair_kits += char.repair_kits

                fc_summaries[fc_id_str]['accounts'].add(account.nickname)
                fc_summaries[fc_id_str]['characters'].append({
                    'name': char.name,
                    'world': char.world,
                    'account': account.nickname
                })
                fc_summaries[fc_id_str]['ceruleum'] += char.ceruleum
                fc_summaries[fc_id_str]['repair_kits'] += char.repair_kits
                fc_summaries[fc_id_str]['dive_credits'] += getattr(char, 'dive_credits', 0)
                # Flag FCs whose contributing character has subs but workshop automation is off
                if getattr(char, 'total_subs', 0) > 0 and not getattr(char, 'workshop_enabled', True):
                    fc_summaries[fc_id_str]['workshop_disabled'] = True
                # Aggregate inventory parts across characters in this FC
                for item_id, count in getattr(char, 'inventory_parts', {}).items():
                    fc_summaries[fc_id_str]['inventory_parts'][item_id] = \
                        fc_summaries[fc_id_str]['inventory_parts'].get(item_id, 0) + count
                # Track max unlocked slots (all chars in same FC share slots)
                fc_summaries[fc_id_str]['unlocked_slots'] = max(
                    fc_summaries[fc_id_str]['unlocked_slots'],
                    getattr(char, 'num_sub_slots', 0)
                )

                for sub in char.submarines:
                    # Recalculate status based on current time (not when data was parsed)
                    current_status, current_hours = self._recalculate_sub_status(sub)

                    # Update FC-level stats
                    fc_summaries[fc_id_str]['total_subs'] += 1
                    fc_summaries[fc_id_str]['gil_per_day'] += sub.gil_per_day

                    if current_status == 'ready':
                        fc_summaries[fc_id_str]['ready_subs'] += 1

                    # Count leveling subs (route not in known production routes)
                    if not sub.route_name or sub.route_name not in known_routes:
                        fc_summaries[fc_id_str]['leveling_subs'] += 1

                    # Use Lumina-calculated consumption rates from submarine
                    tanks_per_day = sub.tanks_per_day
                    kits_per_day = sub.kits_per_day
                    fc_summaries[fc_id_str]['ceruleum_per_day'] += tanks_per_day
                    fc_summaries[fc_id_str]['kits_per_day'] += kits_per_day

                    # Update global totals
                    total_subs += 1
                    if current_status == 'ready':
                        ready_subs += 1
                    if not sub.route_name or sub.route_name not in known_routes:
                        leveling_subs += 1
                    total_gil_per_day += sub.gil_per_day
                    # Skip supply totals for FCs excluded from supply calculations
                    if fc_id_str not in supply_excluded_fc_ids:
                        total_ceruleum_per_day += tanks_per_day
                        total_kits_per_day += kits_per_day

                    # Track routes for this FC
                    if sub.route_name:
                        fc_summaries[fc_id_str]['routes'].add(sub.route_name)

                    # Track soonest return (both hours and absolute timestamp)
                    # Ready subs count as 0 so FCs with ready subs sort to the top
                    current_soonest = fc_summaries[fc_id_str]['soonest_return']
                    effective_hours = 0 if current_status == 'ready' else current_hours
                    if current_soonest is None or effective_hours < current_soonest:
                        fc_summaries[fc_id_str]['soonest_return'] = effective_hours
                        if current_status == 'ready':
                            fc_summaries[fc_id_str]['soonest_return_time'] = None
                        else:
                            fc_summaries[fc_id_str]['soonest_return_time'] = sub.return_time.isoformat() + 'Z'

                    sub_data = {
                        'account': account.nickname,
                        'character': char.name,
                        'world': char.world,
                        'fc_id': fc_id,
                        'fc_name': fc_name,
                        'name': sub.name,
                        'status': current_status,
                        'hours_remaining': round(current_hours, 2),
                        'return_time': sub.return_time.isoformat() + 'Z',
                        'return_time_display': sub.return_time.strftime('%H:%M:%S'),
                        'level': sub.level,
                        'build': sub.build,
                        'parts': sub.parts,
                        'route': sub.route_name,
                        'exp_progress': round(sub.exp_progress, 1),
                        'gil_per_day': sub.gil_per_day,
                        'enabled': sub.enabled
                    }

                    all_submarines.append(sub_data)
                    fc_summaries[fc_id_str]['submarines'].append(sub_data)

        # Convert sets to lists and calculate FC-level supply forecasts
        for fc_id in fc_summaries:
            fc = fc_summaries[fc_id]
            fc['accounts'] = list(fc['accounts'])

            # Default soonest_return for FCs with no submarines
            # so Jinja2 sort doesn't fail comparing None with float
            if fc['soonest_return'] is None:
                fc['soonest_return'] = 0

            # Flag FCs with potential duplicate submarines
            # - More than 4 subs is impossible (definite duplicates)
            # - Multiple characters in same FC could report the same subs
            fc['has_duplicate_subs'] = fc['total_subs'] > 4 or len(fc['characters']) > 1

            # If all subs have the same route, set unified_route
            routes = fc['routes']
            if len(routes) == 1:
                fc['unified_route'] = list(routes)[0]
            else:
                fc['unified_route'] = None
            fc['routes'] = list(routes)  # Convert set to list for JSON

            # If all subs belong to one character, set unified_character
            unique_chars = set(c['name'] for c in fc['characters'])
            if len(unique_chars) == 1:
                fc['unified_character'] = list(unique_chars)[0]
            else:
                fc['unified_character'] = None

            # Calculate days until restock for this FC
            if fc['ceruleum_per_day'] > 0 and fc['kits_per_day'] > 0:
                days_from_ceruleum = fc['ceruleum'] / fc['ceruleum_per_day']
                days_from_kits = fc['repair_kits'] / fc['kits_per_day']
                fc['days_until_restock'] = round(min(days_from_ceruleum, days_from_kits), 1)
                fc['limiting_resource'] = 'ceruleum' if days_from_ceruleum < days_from_kits else 'kits'
            else:
                fc['days_until_restock'] = None
                fc['limiting_resource'] = None

            # Round consumption rates for display
            fc['ceruleum_per_day'] = round(fc['ceruleum_per_day'], 1)
            fc['kits_per_day'] = round(fc['kits_per_day'], 2)

            # Determine FC mode (farming vs leveling)
            if fc['total_subs'] == 0:
                fc['mode'] = 'empty'
            elif fc['leveling_subs'] == 0:
                fc['mode'] = 'farming'
            elif fc['leveling_subs'] == fc['total_subs']:
                fc['mode'] = 'leveling'
            else:
                fc['mode'] = 'mixed'

            # Calculate if FC needs more dive credits for next slot
            # Slot costs: 1, 3, 5, 7 for slots 1-4
            slot_costs = [1, 3, 5, 7]
            unlocked = fc['unlocked_slots']
            credits = fc['dive_credits']
            if unlocked < 4:
                # Calculate credits needed for next slot
                next_slot_cost = slot_costs[unlocked] if unlocked < 4 else 0
                fc['needs_dive_credits'] = credits < next_slot_cost
                fc['dive_credits_needed'] = max(0, next_slot_cost - credits)
            else:
                fc['needs_dive_credits'] = False
                fc['dive_credits_needed'] = 0

            # Calculate unbuilt submarines (slots unlocked but no sub built)
            fc['unbuilt_subs'] = max(0, fc['unlocked_slots'] - fc['total_subs'])

        # Sort submarines by return time
        all_submarines.sort(key=lambda x: x['hours_remaining'])

        # Calculate global supply forecast as minimum across all FCs
        # (supplies are per-FC, not shared, so we take the soonest restock needed)
        min_days_until_restock = 999.0
        limiting_fc = None
        limiting_resource = 'none'

        for fc_id, fc in fc_summaries.items():
            # Skip FCs excluded from supply calculations
            if fc_id in supply_excluded_fc_ids:
                continue
            if fc['days_until_restock'] is not None and fc['days_until_restock'] < min_days_until_restock:
                min_days_until_restock = fc['days_until_restock']
                limiting_fc = fc['fc_name']
                limiting_resource = fc['limiting_resource']

        days_until_restock = min_days_until_restock

        # Count FCs by region
        region_counts = {'NA': 0, 'EU': 0, 'JP': 0, 'OCE': 0, 'Unknown': 0}
        for fc in fc_summaries.values():
            region = fc.get('region', 'Unknown')
            if region in region_counts:
                region_counts[region] += 1
            else:
                region_counts['Unknown'] += 1

        # Add tags to each FC
        try:
            from app.models.tag import get_all_fc_tags_map
            fc_tags_map = get_all_fc_tags_map()
            for fc in fc_summaries.values():
                fc_id = str(fc.get('fc_id', ''))
                fc['tags'] = fc_tags_map.get(fc_id, [])
        except Exception:
            # Tags table may not exist yet on first run
            for fc in fc_summaries.values():
                fc['tags'] = []

        # Add notes to each FC (using fc_notes_map from consolidated query above)
        for fc in fc_summaries.values():
            fc_id = str(fc.get('fc_id', ''))
            fc['notes'] = fc_notes_map.get(fc_id, '')

        # Build the new dashboard dict, then swap it in under the lock
        # to avoid races with update_time_fields() and get_dashboard_data()
        new_dashboard = {
            'summary': {
                'total_subs': total_subs,
                'ready_subs': ready_subs,
                'voyaging_subs': total_subs - ready_subs,
                'farming_subs': total_subs - leveling_subs,
                'leveling_subs': leveling_subs,
                'total_gil_per_day': int(total_gil_per_day),
                'fc_count': len(fc_summaries),
                'account_count': len(accounts),
                'region_counts': region_counts,
                'last_updated': self._last_update.isoformat() if self._last_update else None
            },
            'supply_forecast': {
                'total_ceruleum': total_ceruleum,
                'total_repair_kits': total_repair_kits,
                'ceruleum_per_day': round(total_ceruleum_per_day, 1),
                'kits_per_day': round(total_kits_per_day, 2),
                'days_until_restock': round(days_until_restock, 1),
                'limiting_resource': limiting_resource,
                'limiting_fc': limiting_fc
            },
            'fc_summaries': list(fc_summaries.values()),
            'gil_per_day_by_tag': compute_gil_per_day_by_tag(list(fc_summaries.values())),
            'submarines': all_submarines
        }
        with self._lock:
            self._cached_dashboard = new_dashboard

    def update_time_fields(self):
        """
        Lightweight update of time-sensitive fields on the cached dashboard.
        Called by the 30-second background loop instead of a full rebuild.
        Only updates: status, hours_remaining, soonest_return, ready_subs counts.
        Holds _lock to prevent concurrent mutation with _rebuild_dashboard().
        """
        with self._lock:
            self._update_time_fields_locked()

    def _update_time_fields_locked(self):
        """Inner time-field update, must be called while holding self._lock."""
        if self._cached_dashboard is None:
            return

        total_ready = 0
        total_subs = 0

        # Reset FC-level time fields before recalculating
        fc_map = {}
        for fc in self._cached_dashboard['fc_summaries']:
            fc_id = fc['fc_id']
            fc['soonest_return'] = None
            fc['soonest_return_time'] = None
            fc['ready_subs'] = 0
            fc_map[fc_id] = fc

        for sub in self._cached_dashboard['submarines']:
            total_subs += 1

            # Recalculate from return_time string
            try:
                return_time_str = sub.get('return_time', '')
                if return_time_str:
                    return_dt = datetime.fromisoformat(return_time_str.rstrip('Z'))
                    return_ts = calendar.timegm(return_dt.timetuple())

                    if return_ts <= 0:
                        sub['status'] = 'ready'
                        sub['hours_remaining'] = 0.0
                    else:
                        hours_remaining = (return_ts - time.time()) / 3600
                        sub['hours_remaining'] = round(hours_remaining, 2)
                        if hours_remaining <= 0:
                            sub['status'] = 'ready'
                        elif hours_remaining <= 0.5:
                            sub['status'] = 'returning_soon'
                        else:
                            sub['status'] = 'voyaging'
            except Exception:
                pass

            if sub.get('status') == 'ready':
                total_ready += 1

            # Update FC-level soonest return
            fc_id = str(sub.get('fc_id', ''))
            fc = fc_map.get(fc_id)
            if fc:
                if sub['status'] == 'ready':
                    fc['ready_subs'] += 1
                    effective_hours = 0
                else:
                    effective_hours = sub.get('hours_remaining', 999)

                current_soonest = fc['soonest_return']
                if current_soonest is None or effective_hours < current_soonest:
                    fc['soonest_return'] = effective_hours
                    if sub['status'] == 'ready':
                        fc['soonest_return_time'] = None
                    else:
                        fc['soonest_return_time'] = sub.get('return_time')

        # Default soonest_return for FCs with no updates
        for fc in self._cached_dashboard['fc_summaries']:
            if fc['soonest_return'] is None:
                fc['soonest_return'] = 0

        # Update summary counts
        self._cached_dashboard['summary']['ready_subs'] = total_ready
        self._cached_dashboard['summary']['voyaging_subs'] = total_subs - total_ready

    def get_supplier_summary(self, ceruleum_per_day: float = None, kits_per_day: float = None) -> dict:
        """
        Get aggregated supplier character data.

        Args:
            ceruleum_per_day: Override consumption rate (e.g. from filtered FC data).
                              If None, uses global rate from dashboard data.
            kits_per_day: Override consumption rate. If None, uses global rate.

        Returns dict with:
            - suppliers: list of individual supplier entries
            - total_ceruleum: total across all suppliers (personal + retainer + deduplicated FC chest)
            - total_repair_kits: total across all suppliers
            - ceruleum_days: days of supply based on consumption
            - repair_days: days of supply based on consumption
        """
        all_suppliers = []
        total_ceruleum = 0
        total_repair_kits = 0
        total_fc_credits = 0

        # Track FC-level data already counted to avoid double-counting when
        # multiple suppliers share the same FC
        seen_fc_ids = set()

        for plugin_id, suppliers in self._supplier_data.items():
            for s in suppliers:
                # Personal + retainer amounts (FC chest already excluded by plugin)
                ceruleum = s.get('ceruleum', 0)
                repair_kits = s.get('repair_kits', 0)
                fc_credits = 0

                # FC-level data: only count once per FC to avoid double-counting
                # when multiple suppliers share the same FC
                fc_id = s.get('fc_id', '0')
                if fc_id and fc_id != '0' and fc_id not in seen_fc_ids:
                    seen_fc_ids.add(fc_id)
                    ceruleum += s.get('fc_ceruleum', 0)
                    repair_kits += s.get('fc_repair_kits', 0)
                    fc_credits = s.get('fc_credits', 0)

                total_ceruleum += ceruleum
                total_repair_kits += repair_kits
                total_fc_credits += fc_credits
                all_suppliers.append({
                    'name': s.get('name', 'Unknown'),
                    'world': s.get('world', ''),
                    'ceruleum': ceruleum,
                    'repair_kits': repair_kits,
                    'fc_credits': fc_credits,
                    'last_updated': s.get('last_updated', '')
                })

        # Use provided rates or fall back to global dashboard rates
        if ceruleum_per_day is None or kits_per_day is None:
            dashboard = self.get_dashboard_data()
            forecast = dashboard.get('supply_forecast', {})
            if ceruleum_per_day is None:
                ceruleum_per_day = forecast.get('ceruleum_per_day', 0)
            if kits_per_day is None:
                kits_per_day = forecast.get('kits_per_day', 0)

        ceruleum_days = total_ceruleum / ceruleum_per_day if ceruleum_per_day > 0 else None
        repair_days = total_repair_kits / kits_per_day if kits_per_day > 0 else None

        return {
            'suppliers': all_suppliers,
            'total_ceruleum': total_ceruleum,
            'total_repair_kits': total_repair_kits,
            'total_fc_credits': total_fc_credits,
            'ceruleum_days': round(ceruleum_days, 1) if ceruleum_days is not None else None,
            'repair_days': round(repair_days, 1) if repair_days is not None else None
        }

    def start_background_updates(self, interval: int = 30, callback: Callable = None):
        """
        Start background thread for periodic data updates.

        Args:
            interval: Seconds between updates
            callback: Function to call with updated data
        """
        if callback:
            self._update_callbacks.append(callback)

        if self._running:
            return

        self._running = True

        def update_loop():
            while self._running:
                data = self.get_dashboard_data()
                for cb in self._update_callbacks:
                    try:
                        cb(data)
                    except Exception as e:
                        logger.info(f"Callback error: {e}")
                time.sleep(interval)

        self._update_thread = threading.Thread(target=update_loop, daemon=True)
        self._update_thread.start()

    def stop_background_updates(self):
        """Stop background update thread."""
        self._running = False
        if self._update_thread:
            self._update_thread.join(timeout=5)
