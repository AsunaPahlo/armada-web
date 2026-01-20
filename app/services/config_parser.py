"""
AutoRetainer DefaultConfig.json parser

Parses submarine data from AutoRetainer plugin configuration files.
"""
import base64
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field

from app.services.submarine_data import (
    SUB_PARTS_LOOKUP, CLASS_SHORTCUTS,
    item_id_to_row_id, get_route_name_from_points
)


@dataclass
class SubmarineInfo:
    """Submarine data extracted from config."""
    name: str
    return_time: datetime
    hours_remaining: float
    status: str  # 'ready', 'returning_soon', 'voyaging'
    level: int = 0
    current_exp: int = 0
    next_level_exp: int = 0
    exp_progress: float = 0.0
    build: str = ""  # e.g., "S+S+U+C+"
    parts: list = field(default_factory=list)  # List of part names
    part_ids: list = field(default_factory=list)  # List of part item IDs (21792+)
    part_row_ids: list = field(default_factory=list)  # List of part row IDs (1-40) for duration calc
    route_plan_guid: str = ""
    route_name: str = ""
    route_points: list = field(default_factory=list)  # List of sector IDs
    enabled: bool = True
    gil_per_day: float = 0.0
    tanks_per_day: float = 0.0
    kits_per_day: float = 0.0


@dataclass
class CharacterInfo:
    """Character data with submarines."""
    cid: int
    name: str
    world: str
    fc_id: int
    gil: int
    ceruleum: int
    repair_kits: int
    num_sub_slots: int
    submarines: list = field(default_factory=list)
    enabled_subs: list = field(default_factory=list)
    sent_voyages_by_day: dict = field(default_factory=dict)
    unlocked_sectors: list = field(default_factory=list)

    @property
    def ready_subs(self) -> int:
        """Count of submarines that have returned."""
        return sum(1 for sub in self.submarines if sub.status == 'ready')

    @property
    def total_subs(self) -> int:
        """Total submarine count."""
        return len(self.submarines)

    @property
    def soonest_return(self) -> float | None:
        """Hours until soonest submarine returns (can be negative if ready)."""
        if not self.submarines:
            return None
        return min(sub.hours_remaining for sub in self.submarines)


@dataclass
class FCInfo:
    """Free Company data."""
    fc_id: int
    name: str
    gil: int
    fc_points: int
    holder_chara: int


@dataclass
class AccountData:
    """Complete account data from one AutoRetainer config."""
    nickname: str
    config_path: str
    characters: list = field(default_factory=list)
    fc_data: dict = field(default_factory=dict)  # FC ID -> FCInfo
    route_plans: dict = field(default_factory=dict)  # GUID -> name
    last_updated: datetime = None

    @property
    def total_subs(self) -> int:
        """Total submarines across all characters."""
        return sum(char.total_subs for char in self.characters)

    @property
    def ready_subs(self) -> int:
        """Ready submarines across all characters."""
        return sum(char.ready_subs for char in self.characters)

    @property
    def soonest_return(self) -> float | None:
        """Soonest submarine return across all characters."""
        returns = [char.soonest_return for char in self.characters if char.soonest_return is not None]
        return min(returns) if returns else None


class ConfigParser:
    """Parser for AutoRetainer DefaultConfig.json files."""

    def __init__(self, accounts_config_path: str | Path = None):
        """
        Initialize parser.

        Args:
            accounts_config_path: Path to accounts.json configuration file
        """
        self.accounts_config_path = Path(accounts_config_path) if accounts_config_path else None
        self.accounts: list[dict] = []
        self._load_accounts_config()

    def _load_accounts_config(self):
        """Load accounts configuration from JSON file."""
        if self.accounts_config_path and self.accounts_config_path.exists():
            try:
                with open(self.accounts_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.accounts = config.get('accounts', [])
            except Exception as e:
                print(f"[ConfigParser] Error loading accounts config: {e}")

    def add_account(self, nickname: str, config_path: str):
        """Add an account configuration."""
        self.accounts.append({
            'nickname': nickname,
            'config_path': config_path
        })

    def _get_build_string(self, sub_data: dict) -> str:
        """Convert part IDs to build string like 'S+S+U+C+'."""
        parts = []
        for key in ['Part1', 'Part2', 'Part3', 'Part4']:
            part_id = sub_data.get(key, 0)
            if part_id != 0:
                full_name = SUB_PARTS_LOOKUP.get(part_id, f"Unknown({part_id})")
                # Get short code
                for prefix, code in CLASS_SHORTCUTS.items():
                    if full_name.startswith(prefix):
                        parts.append(code)
                        break
                else:
                    parts.append('?')
        return ''.join(parts)

    def _get_part_names(self, sub_data: dict) -> list[str]:
        """Get list of full part names."""
        parts = []
        for key in ['Part1', 'Part2', 'Part3', 'Part4']:
            part_id = sub_data.get(key, 0)
            if part_id != 0:
                parts.append(SUB_PARTS_LOOKUP.get(part_id, f"Unknown({part_id})"))
        return parts

    def _get_part_ids(self, sub_data: dict) -> list[int]:
        """Get list of part IDs."""
        part_ids = []
        for key in ['Part1', 'Part2', 'Part3', 'Part4']:
            part_id = sub_data.get(key, 0)
            if part_id != 0:
                part_ids.append(part_id)
        return part_ids

    def _calculate_status(self, hours_remaining: float) -> str:
        """Determine submarine status based on hours remaining."""
        if hours_remaining <= 0:
            return 'ready'
        elif hours_remaining <= 0.5:  # 30 minutes
            return 'returning_soon'
        else:
            return 'voyaging'

    def _get_route_gil_per_day(self, route_name: str, build: str) -> float:
        """
        Get gil per day for a route, using database first then fallback.

        Args:
            route_name: Route name like 'OJ', 'JORZ', etc.
            build: Build string for fallback lookup

        Returns:
            Gil per submarine per day
        """
        # Try database first
        try:
            from flask import current_app
            if current_app:
                from app.models.lumina import RouteStats
                route = RouteStats.query.filter_by(route_name=route_name).first()
                if route and route.gil_per_sub_day > 0:
                    return float(route.gil_per_sub_day)
        except Exception:
            pass

        # No route data available
        return 0.0

    def _calculate_consumption(
        self,
        part_ids: list[int],
        route_points: list[int],
        sub_level: int
    ) -> tuple[float, float]:
        """
        Calculate consumption rates based on actual parts and route.

        Uses Lumina data for accurate calculations:
        - Fuel: sum of CeruleumTankReq for all sectors
        - Repair: based on damage formula and part repair materials

        Returns:
            Tuple of (tanks_per_day, kits_per_day)
        """
        # Default fallback values
        default_tanks = 9.0
        default_kits = 1.33

        if not part_ids or not route_points:
            return default_tanks, default_kits

        try:
            from flask import current_app
            if not current_app:
                return default_tanks, default_kits

            from app.models.lumina import SubmarinePart, SubmarineExploration

            # Calculate fuel cost (sum of ceruleum for all sectors)
            total_ceruleum = 0
            sector_ranks = []
            for sector_id in route_points:
                sector = SubmarineExploration.query.get(sector_id)
                if sector:
                    total_ceruleum += sector.ceruleum_tank_req
                    sector_ranks.append(sector.rank_req)

            if not sector_ranks:
                return default_tanks, default_kits

            # Calculate damage per voyage
            # Formula: (335 + Sector.RankReq - Part.Rank) * 7 per sector
            BASE_DAMAGE = 335
            DAMAGE_MULT = 7
            MAX_DURABILITY = 30000

            max_part_damage = 0
            total_repair_materials = 0

            for item_id in part_ids:
                # Convert AutoRetainer Item ID to Lumina row ID
                row_id = item_id_to_row_id(item_id)
                if not row_id:
                    continue

                part = SubmarinePart.query.get(row_id)
                if not part:
                    continue

                total_repair_materials += part.repair_materials

                # Calculate damage for this part across all sectors
                part_damage = 0
                for sector_rank in sector_ranks:
                    part_damage += (BASE_DAMAGE + sector_rank - part.rank) * DAMAGE_MULT

                max_part_damage = max(max_part_damage, part_damage)

            if max_part_damage <= 0:
                return default_tanks, default_kits

            # Calculate voyages until repair needed
            voyages_until_repair = MAX_DURABILITY / max_part_damage

            # Calculate voyage duration from actual sector survey times
            total_survey_minutes = 0
            for sector_id in route_points:
                sector = SubmarineExploration.query.get(sector_id)
                if sector:
                    total_survey_minutes += sector.survey_duration_min

            # Add ~20% for travel time between sectors
            total_voyage_minutes = total_survey_minutes * 1.2
            estimated_voyage_hours = total_voyage_minutes / 60.0

            # Minimum 12 hours, maximum 48 hours for sanity
            estimated_voyage_hours = max(12.0, min(48.0, estimated_voyage_hours))

            voyages_per_day = 24.0 / estimated_voyage_hours

            # Calculate daily rates
            tanks_per_day = total_ceruleum * voyages_per_day
            kits_per_voyage = total_repair_materials / voyages_until_repair if voyages_until_repair > 0 else 0
            kits_per_day = kits_per_voyage * voyages_per_day

            return round(tanks_per_day, 1), round(kits_per_day, 2)

        except Exception as e:
            # Fall back to defaults on any error
            return default_tanks, default_kits

    def parse_config(self, config_path: str, nickname: str = "Unknown") -> AccountData:
        """
        Parse a single AutoRetainer config file.

        Args:
            config_path: Path to DefaultConfig.json
            nickname: Account nickname for identification

        Returns:
            AccountData with all parsed information
        """
        account = AccountData(
            nickname=nickname,
            config_path=config_path,
            last_updated=datetime.now()
        )

        if not os.path.isfile(config_path):
            return account

        try:
            with open(config_path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
        except Exception as e:
            print(f"[ConfigParser] Error reading {config_path}: {e}")
            return account

        current_time = datetime.now().timestamp()

        # Parse route plans with full data (name + sector points)
        for plan in data.get('SubmarinePointPlans', []):
            guid = plan.get('GUID', '')
            name = plan.get('Name', '')
            points = plan.get('Points', [])  # List of sector IDs
            if guid:
                account.route_plans[guid] = {
                    'name': name,
                    'points': points
                }

        # Parse FC data
        fc_data_raw = data.get('FCData', {})
        if isinstance(fc_data_raw, dict):
            for fc_id_str, fc_info in fc_data_raw.items():
                try:
                    fc_id = int(fc_id_str)
                    account.fc_data[fc_id] = FCInfo(
                        fc_id=fc_id,
                        name=fc_info.get('Name', ''),
                        gil=fc_info.get('Gil', 0),
                        fc_points=fc_info.get('FCPoints', 0),
                        holder_chara=fc_info.get('HolderChara', 0)
                    )
                except (ValueError, TypeError):
                    pass

        # Parse characters from OfflineData
        offline_data = data.get('OfflineData', [])
        for char_data in offline_data:
            if not isinstance(char_data, dict) or 'CID' not in char_data:
                continue

            character = CharacterInfo(
                cid=char_data.get('CID', 0),
                name=char_data.get('Name', 'Unknown'),
                world=char_data.get('World', 'Unknown'),
                fc_id=char_data.get('FCID', 0),
                gil=char_data.get('Gil', 0),
                ceruleum=char_data.get('Ceruleum', 0),
                repair_kits=char_data.get('RepairKits', 0),
                num_sub_slots=char_data.get('NumSubSlots', 0),
                enabled_subs=char_data.get('EnabledSubs', []),
                sent_voyages_by_day=char_data.get('SentVoyagesByDay', {})
            )

            # Parse submarines
            offline_sub_data = char_data.get('OfflineSubmarineData', [])
            additional_sub_data = char_data.get('AdditionalSubmarineData', {})

            for sub_dict in offline_sub_data:
                sub_name = sub_dict.get('Name', '')
                return_timestamp = sub_dict.get('ReturnTime', 0)

                if return_timestamp <= 0:
                    continue

                # Calculate time remaining
                hours_remaining = (return_timestamp - current_time) / 3600
                return_dt = datetime.utcfromtimestamp(return_timestamp)

                # Get additional data if available
                add_data = additional_sub_data.get(sub_name, {})
                build = self._get_build_string(add_data) if add_data else ""

                # Calculate exp progress
                current_exp = add_data.get('CurrentExp', 0)
                next_level_exp = add_data.get('NextLevelExp', 1)
                exp_progress = (current_exp / next_level_exp * 100) if next_level_exp > 0 else 0

                # Get current route points from base64-encoded Points field
                current_route_points = []
                points_b64 = add_data.get('Points', '')
                if points_b64:
                    try:
                        decoded = base64.b64decode(points_b64)
                        current_route_points = [b for b in decoded if b > 0]
                    except Exception:
                        pass

                # Get route info from plan GUID as fallback
                route_guid = add_data.get('SelectedPointPlan', '')
                route_plan = account.route_plans.get(route_guid, {})
                plan_points = route_plan.get('points', []) if isinstance(route_plan, dict) else []
                plan_name = route_plan.get('name', '') if isinstance(route_plan, dict) else ''

                # Use current route points if available, otherwise fall back to plan points
                route_points = current_route_points if current_route_points else plan_points

                # Ensure route_points are integers (may come as strings from JSON)
                route_points = [int(p) for p in route_points if p is not None]

                # Generate route name from actual sector points using Lumina data
                # Fall back to plan name if points are empty
                route_name = ""
                if route_points:
                    route_name = get_route_name_from_points(route_points)
                if not route_name and plan_name:
                    route_name = plan_name

                # Get part IDs for consumption calculation
                part_ids = self._get_part_ids(add_data)
                sub_level = add_data.get('Level', 0)

                # Calculate consumption based on actual parts and route
                tanks_per_day, kits_per_day = self._calculate_consumption(
                    part_ids, route_points, sub_level
                )

                # Get gil earnings from route stats database (falls back to hardcoded)
                gil_per_day = self._get_route_gil_per_day(route_name, build)

                submarine = SubmarineInfo(
                    name=sub_name,
                    return_time=return_dt,
                    hours_remaining=hours_remaining,
                    status=self._calculate_status(hours_remaining),
                    level=sub_level,
                    current_exp=current_exp,
                    next_level_exp=next_level_exp,
                    exp_progress=exp_progress,
                    build=build,
                    parts=self._get_part_names(add_data),
                    part_ids=part_ids,
                    route_plan_guid=route_guid,
                    route_name=route_name,
                    route_points=route_points,
                    enabled=sub_name in character.enabled_subs,
                    gil_per_day=gil_per_day,
                    tanks_per_day=tanks_per_day,
                    kits_per_day=kits_per_day
                )

                character.submarines.append(submarine)

            # Only add characters with submarines
            if character.submarines:
                account.characters.append(character)

        return account

    def parse_all_accounts(self) -> list[AccountData]:
        """
        Parse all configured and enabled accounts.

        Returns:
            List of AccountData for each enabled account
        """
        results = []
        for acc in self.accounts:
            # Skip disabled accounts (enabled defaults to True if not specified)
            if not acc.get('enabled', True):
                continue
            nickname = acc.get('nickname', 'Unknown')
            config_path = acc.get('config_path', '')
            if config_path:
                account_data = self.parse_config(config_path, nickname)
                results.append(account_data)
        return results

    def get_file_accounts_info(self) -> list[dict]:
        """
        Get information about enabled file-based accounts for status display.

        Returns:
            List of account info dicts with nickname, config_path, and exists status
        """
        import os
        results = []
        for acc in self.accounts:
            if not acc.get('enabled', True):
                continue
            config_path = acc.get('config_path', '')
            results.append({
                'nickname': acc.get('nickname', 'Unknown'),
                'config_path': config_path,
                'exists': os.path.isfile(config_path) if config_path else False
            })
        return results

    def parse_plugin_data(self, plugin_data: dict) -> AccountData:
        """
        Parse fleet data received from plugin (already in dict format).

        Args:
            plugin_data: Dict with nickname, characters, fc_data, route_plans

        Returns:
            AccountData with all parsed information
        """
        nickname = plugin_data.get('nickname', 'Plugin')

        account = AccountData(
            nickname=nickname,
            config_path='plugin',
            last_updated=datetime.now()
        )

        current_time = datetime.now().timestamp()

        # Parse route plans
        route_plans_raw = plugin_data.get('route_plans', {})
        for guid, plan_data in route_plans_raw.items():
            if isinstance(plan_data, dict):
                account.route_plans[guid] = {
                    'name': plan_data.get('name', ''),
                    'points': plan_data.get('points', [])
                }
            else:
                account.route_plans[guid] = {'name': str(plan_data), 'points': []}

        # Parse FC data
        fc_data_raw = plugin_data.get('fc_data', {})
        for fc_id_str, fc_info in fc_data_raw.items():
            try:
                fc_id = int(fc_id_str)
                account.fc_data[fc_id] = FCInfo(
                    fc_id=fc_id,
                    name=fc_info.get('name', ''),
                    gil=fc_info.get('gil', 0),
                    fc_points=fc_info.get('fc_points', 0),
                    holder_chara=int(fc_info.get('holder_chara', 0))
                )

                # Store house address if present
                if fc_info.get('house_district') and fc_info.get('house_ward') and fc_info.get('house_plot'):
                    try:
                        from app.models.fc_housing import update_fc_housing
                        update_fc_housing(
                            fc_id=fc_id_str,
                            world=fc_info.get('house_world', ''),
                            district=fc_info.get('house_district', ''),
                            ward=int(fc_info.get('house_ward', 0)),
                            plot=int(fc_info.get('house_plot', 0))
                        )
                    except Exception as e:
                        print(f"[ConfigParser] Error storing FC house address: {e}")
            except (ValueError, TypeError):
                pass

        # Parse characters
        characters_raw = plugin_data.get('characters', [])
        for char_data in characters_raw:
            if not isinstance(char_data, dict):
                continue

            character = CharacterInfo(
                cid=int(char_data.get('cid', 0)),
                name=char_data.get('name', 'Unknown'),
                world=char_data.get('world', 'Unknown'),
                fc_id=int(char_data.get('fc_id', 0)),
                gil=char_data.get('gil', 0),
                ceruleum=char_data.get('ceruleum', 0),
                repair_kits=char_data.get('repair_kits', 0),
                num_sub_slots=char_data.get('num_sub_slots', 0),
                enabled_subs=char_data.get('enabled_subs', []),
                unlocked_sectors=char_data.get('unlocked_sectors', [])
            )

            # Parse submarines
            submarines_raw = char_data.get('submarines', [])
            for sub_data in submarines_raw:
                sub_name = sub_data.get('name', '')
                return_timestamp = sub_data.get('return_time', 0)

                if return_timestamp <= 0:
                    continue

                # Calculate time remaining
                hours_remaining = (return_timestamp - current_time) / 3600
                return_dt = datetime.utcfromtimestamp(return_timestamp)

                # Normalize keys to uppercase for helper methods (plugin sends lowercase)
                normalized_sub_data = {
                    'Part1': sub_data.get('part1', 0),
                    'Part2': sub_data.get('part2', 0),
                    'Part3': sub_data.get('part3', 0),
                    'Part4': sub_data.get('part4', 0),
                }

                # Build string from parts
                build = self._get_build_string(normalized_sub_data)
                parts = self._get_part_names(normalized_sub_data)
                part_ids = [
                    sub_data.get('part1', 0),
                    sub_data.get('part2', 0),
                    sub_data.get('part3', 0),
                    sub_data.get('part4', 0)
                ]
                part_ids = [p for p in part_ids if p != 0]

                # Get part row IDs (1-40) directly from plugin if available
                # These are more reliable for duration calculation than parsing build strings
                part_row_ids = sub_data.get('part_row_ids', [])
                if part_row_ids:
                    # Filter out zeros and ensure integers
                    part_row_ids = [int(p) for p in part_row_ids if p and int(p) > 0]

                # Calculate exp progress
                current_exp = sub_data.get('current_exp', 0)
                next_level_exp = sub_data.get('next_level_exp', 1)
                exp_progress = (current_exp / next_level_exp * 100) if next_level_exp > 0 else 0

                # Get route info - prefer current_route_points (actual voyage) over selected plan
                current_route_points = sub_data.get('current_route_points', [])
                route_guid = sub_data.get('selected_route', '')
                route_plan = account.route_plans.get(route_guid, {})
                plan_points = route_plan.get('points', []) if isinstance(route_plan, dict) else []
                plan_name = route_plan.get('name', '') if isinstance(route_plan, dict) else ''

                # Use current route points if available, otherwise fall back to plan points
                route_points = current_route_points if current_route_points else plan_points

                # Ensure route_points are integers (may come as strings from JSON)
                route_points = [int(p) for p in route_points if p is not None]

                # Generate route name from actual sector points using Lumina data
                # Fall back to plan name if points are empty
                route_name = ""
                if route_points:
                    route_name = get_route_name_from_points(route_points)
                if not route_name and plan_name:
                    route_name = plan_name

                # Calculate consumption
                sub_level = sub_data.get('level', 0)
                tanks_per_day, kits_per_day = self._calculate_consumption(
                    part_ids, route_points, sub_level
                )

                # Get gil earnings
                gil_per_day = self._get_route_gil_per_day(route_name, build)

                submarine = SubmarineInfo(
                    name=sub_name,
                    return_time=return_dt,
                    hours_remaining=hours_remaining,
                    status=self._calculate_status(hours_remaining),
                    level=sub_level,
                    current_exp=current_exp,
                    next_level_exp=next_level_exp,
                    exp_progress=exp_progress,
                    build=build,
                    parts=parts,
                    part_ids=part_ids,
                    part_row_ids=part_row_ids,
                    route_plan_guid=route_guid,
                    route_name=route_name,
                    route_points=route_points,
                    enabled=sub_name in character.enabled_subs,
                    gil_per_day=gil_per_day,
                    tanks_per_day=tanks_per_day,
                    kits_per_day=kits_per_day
                )

                character.submarines.append(submarine)

            # Only add characters with submarines
            if character.submarines:
                account.characters.append(character)

        return account

    def get_all_submarines_flat(self) -> list[dict]:
        """
        Get a flat list of all submarines across all accounts.
        Useful for dashboard display.

        Returns:
            List of submarine dictionaries with account/character context
        """
        submarines = []
        for account in self.parse_all_accounts():
            for char in account.characters:
                fc_info = account.fc_data.get(char.fc_id)
                fc_name = fc_info.name if fc_info else ""
                for sub in char.submarines:
                    submarines.append({
                        'account': account.nickname,
                        'character': char.name,
                        'world': char.world,
                        'fc_id': char.fc_id,
                        'fc_name': fc_name,
                        'submarine': sub.name,
                        'status': sub.status,
                        'hours_remaining': sub.hours_remaining,
                        'return_time': sub.return_time.isoformat() + 'Z',
                        'level': sub.level,
                        'build': sub.build,
                        'route': sub.route_name,
                        'exp_progress': sub.exp_progress,
                        'gil_per_day': sub.gil_per_day,
                        'ceruleum': char.ceruleum,
                        'repair_kits': char.repair_kits
                    })
        return submarines
