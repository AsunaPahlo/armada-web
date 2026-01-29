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
        self._last_update: datetime = None
        self._update_callbacks: list[Callable] = []
        self._update_thread: threading.Thread = None
        self._running = False
        self._lock = threading.Lock()

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
        """Save plugin data to file for persistence."""
        try:
            # Ensure data directory exists
            PLUGIN_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Build save data with metadata
            save_data = {}
            for plugin_id, accounts_data in self._plugin_data_raw.items():
                metadata = self._plugin_metadata.get(plugin_id, {})
                save_data[plugin_id] = {
                    'accounts': accounts_data,
                    'timestamp': metadata.get('timestamp'),
                    'received_at': metadata.get('received_at')
                }

            with open(PLUGIN_DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2)
        except Exception as e:
            logger.warning(f"Error saving plugin data: {e}")

    def add_account(self, nickname: str, config_path: str):
        """Add an account to monitor."""
        self.parser.add_account(nickname, config_path)

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

    def set_plugin_data(self, plugin_id: str, accounts_data: list[dict], timestamp: str = None, received_at: str = None):
        """
        Store fleet data received from a plugin.

        Args:
            plugin_id: Unique identifier for the plugin
            accounts_data: List of account data dicts from the plugin
            timestamp: Timestamp from the plugin data
            received_at: When the server received the data
        """
        with self._lock:
            # Get old state before merging for activity tracking
            old_data = self._plugin_data_raw.get(plugin_id, [])
            is_first_update = not old_data

            # Merge unlock_sectors data - preserve existing data when new data is empty
            # The plugin can only read unlock data for the currently logged-in character's FC,
            # so we need to preserve unlock data for other characters/FCs
            accounts_data = self._merge_unlock_data(plugin_id, accounts_data)

            # Track activity changes (compare old vs new state)
            try:
                from app.services.activity_tracker import activity_tracker
                activity_tracker.detect_and_log_changes(
                    old_data=old_data,
                    new_data=accounts_data,
                    is_first_update=is_first_update
                )
            except Exception as e:
                logger.info(f"Activity tracking error: {e}")

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

                # Persist to file
                self._save_plugin_data()

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
            else:
                self._plugin_data.clear()
                self._plugin_data_raw.clear()
                self._plugin_metadata.clear()

            # Persist the change
            self._save_plugin_data()

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
        current_time = time.time()  # UTC timestamp
        # sub.return_time is a naive datetime representing UTC (from utcfromtimestamp)
        # Use calendar.timegm to correctly interpret it as UTC, not local time
        return_timestamp = calendar.timegm(sub.return_time.timetuple())
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

        Returns:
            Dictionary with dashboard summary and details
        """
        accounts = self.get_data(force_refresh=True)

        # Record stats snapshot (for voyage tracking)
        try:
            from app.services.stats_tracker import stats_tracker
            stats_tracker.record_snapshot(accounts)
        except Exception as e:
            logger.info(f"Stats recording error: {e}")

        # Get known production routes from database
        from app.models.lumina import RouteStats
        known_routes = set(r.route_name for r in RouteStats.query.all())

        # Get FC visibility configuration (hidden FCs are excluded from views and stats)
        try:
            from app.models.fc_config import get_hidden_fc_ids, get_all_fc_configs
            hidden_fc_ids = get_hidden_fc_ids()
            fc_configs = get_all_fc_configs()
            if hidden_fc_ids:
                logger.info(f"Hidden FC IDs: {hidden_fc_ids}")
        except Exception as e:
            # fc_configs table may not exist yet on first run
            logger.info(f"FC config load error (may be first run): {e}")
            hidden_fc_ids = set()
            fc_configs = {}

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
                        'unlocked_slots': 0,
                        'needs_dive_credits': False,
                        'dive_credits_needed': 0
                    }

                # Aggregate supplies
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
                    total_ceruleum_per_day += tanks_per_day
                    total_kits_per_day += kits_per_day

                    # Track routes for this FC
                    if sub.route_name:
                        fc_summaries[fc_id_str]['routes'].add(sub.route_name)

                    # Track soonest return (both hours and absolute timestamp)
                    current_soonest = fc_summaries[fc_id_str]['soonest_return']
                    if current_soonest is None or current_hours < current_soonest:
                        fc_summaries[fc_id_str]['soonest_return'] = current_hours
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

        # Sort submarines by return time
        all_submarines.sort(key=lambda x: x['hours_remaining'])

        # Calculate global supply forecast as minimum across all FCs
        # (supplies are per-FC, not shared, so we take the soonest restock needed)
        min_days_until_restock = 999.0
        limiting_fc = None
        limiting_resource = 'none'

        for fc_id, fc in fc_summaries.items():
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

        # Add notes to each FC
        try:
            from app.models.fc_config import get_all_fc_notes
            fc_notes_map = get_all_fc_notes()
            for fc in fc_summaries.values():
                fc_id = str(fc.get('fc_id', ''))
                fc['notes'] = fc_notes_map.get(fc_id, '')
        except Exception:
            # fc_config table may not have notes column yet
            for fc in fc_summaries.values():
                fc['notes'] = ''

        return {
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
            'submarines': all_submarines
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
