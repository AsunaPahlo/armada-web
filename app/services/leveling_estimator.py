"""
Submarine leveling time estimator service.

Estimates time to reach target level using a phased model that accounts for:
- Build swaps (SSSS 1-25, SSUS 25-90+)
- Increasing EXP/voyage as deeper sectors unlock
- Discovery RNG impact (three estimate tiers)
- Real-world inefficiency factors
- Sector-based slot unlocks (J, O, T discoveries)

Uses Lumina database data for:
- EXP required per level (SubmarineRank)
- EXP per sector and survey duration (SubmarineExploration)
"""
from dataclasses import dataclass
from typing import Optional


class LevelingEstimator:
    """
    Estimates submarine leveling time using a phased model.

    The model accounts for:
    - Different EXP rates at different level ranges (from Lumina sector data)
    - Build changes (SSSS early, SSUS later)
    - Discovery RNG impact (decreases at higher levels)
    - Real-world inefficiency (delayed sends, repairs, etc.)
    - Sector discovery timing for slot unlocks
    """

    # Phase definitions: (level_start, level_end, map_id, rank_min, rank_max, discovery_rng_factor)
    # map_id: 1=Deep-sea Site, 2=Sea of Ash, 3=Sea of Jade
    # EXP and voyage times are loaded from Lumina SubmarineExploration data
    # Discovery RNG only significantly affects DSS (map 1) - later maps are farming
    PHASE_DEFINITIONS = [
        (1, 25, 1, 1, 25, 0.40),      # Deep-sea Site shallow - discovery heavy
        (25, 50, 1, 20, 50, 0.20),    # Deep-sea Site deep - still some discovery
        (50, 75, 2, 50, 70, 0.02),    # Sea of Ash - mostly farming, minimal RNG
        (75, 90, 3, 70, 90, 0.01),    # Sea of Jade - farming routes
        (90, 125, 4, 90, 105, 0.00),  # Sirensong Sea - pure farming
    ]

    # Fallback phase data if Lumina data unavailable
    # (level_start, level_end, avg_exp_per_voyage, avg_voyage_hours, discovery_rng_factor)
    FALLBACK_PHASES = [
        (1, 25, 200_000, 20, 0.40),     # Conservative early estimate
        (25, 50, 800_000, 50, 0.20),    # Mid-game
        (50, 75, 1_500_000, 60, 0.02),  # Late-mid - farming
        (75, 90, 2_500_000, 80, 0.01),  # Late game - farming
        (90, 125, 4_000_000, 90, 0.00), # Post-90 - pure farming
    ]

    # Discovery rate assumptions for three estimate tiers (DSS unlock chance)
    DISCOVERY_RATES = {
        'optimistic': 0.50,   # Good surveillance, lucky RNG
        'expected': 0.25,     # Average discovery rate
        'pessimistic': 0.10,  # Unlucky or low surveillance builds
    }

    # Real-world inefficiency multiplier (delayed sends, repairs, suboptimal choices)
    INEFFICIENCY_MULTIPLIER = 1.18

    # Slot unlock sectors and their prerequisite chains
    # Based on unlock_tree.py - B is a starting sector (already unlocked)
    # Path shows sectors that need to be DISCOVERED (not already unlocked)
    SLOT_UNLOCK_SECTORS = {
        2: {'sector': 'J', 'sector_id': 10, 'path': ['E', 'J']},           # B→E→J, but B is start
        3: {'sector': 'O', 'sector_id': 15, 'path': ['N', 'O']},           # J→N→O
        4: {'sector': 'T', 'sector_id': 20, 'path': ['S', 'T']},           # O→S→T
    }

    # Average voyages per sector discovery (inverse of discovery rate)
    # 50% rate = 2 voyages, 25% rate = 4 voyages, 10% rate = 10 voyages
    VOYAGES_PER_DISCOVERY = {
        'optimistic': 2.0,    # 50% discovery rate
        'expected': 4.0,      # 25% discovery rate
        'pessimistic': 10.0,  # 10% discovery rate
    }

    # Average voyage hours during early unlock phase (shallow sectors)
    EARLY_VOYAGE_HOURS = 14

    def __init__(self):
        """Initialize estimator and load data from database."""
        self.ranks = {}
        self.phases = []  # Will be populated from Lumina data
        self._loaded = False

    def _ensure_loaded(self):
        """Lazy load rank and sector data on first use."""
        if self._loaded:
            return
        self._load_data()
        self._loaded = True

    def _load_data(self):
        """Load rank EXP requirements and sector data from Lumina database."""
        try:
            from flask import has_app_context
            if not has_app_context():
                self._use_fallback_data()
                return

            from app.models.lumina import SubmarineRank, SubmarineExploration

            # Load rank EXP requirements
            for rank in SubmarineRank.query.all():
                self.ranks[rank.id] = rank.exp_to_next

            if not self.ranks:
                self._use_fallback_data()
                return

            # Calculate phase data from Lumina sector information
            self.phases = []
            for level_start, level_end, map_id, rank_min, rank_max, rng_factor in self.PHASE_DEFINITIONS:
                # Get sectors for this phase's map and rank range
                sectors = SubmarineExploration.query.filter(
                    SubmarineExploration.map_id == map_id,
                    SubmarineExploration.rank_req >= rank_min,
                    SubmarineExploration.rank_req <= rank_max,
                    SubmarineExploration.exp_reward > 0
                ).all()

                if sectors:
                    # Calculate average EXP and time for a 5-point voyage
                    avg_sector_exp = sum(s.exp_reward for s in sectors) / len(sectors)
                    avg_sector_time = sum(s.survey_duration_min for s in sectors) / len(sectors)

                    # 5-point voyage with travel overhead (~30% extra for travel between sectors)
                    voyage_exp = avg_sector_exp * 5
                    voyage_hours = (avg_sector_time * 5 * 1.3) / 60  # Convert to hours with travel

                    # Early game penalty: can't do full 5-point routes, limited parts
                    # Reduces effective EXP/hour in early phases
                    if level_start < 25:
                        voyage_exp *= 0.6  # Only ~3 points average, suboptimal sectors
                        voyage_hours *= 0.8  # Shorter voyages

                    self.phases.append((level_start, level_end, voyage_exp, voyage_hours, rng_factor))
                else:
                    # Use fallback for this phase
                    for fb in self.FALLBACK_PHASES:
                        if fb[0] == level_start:
                            self.phases.append(fb)
                            break

            if not self.phases:
                self._use_fallback_data()

        except Exception as e:
            print(f"[LevelingEstimator] Error loading data: {e}")
            self._use_fallback_data()

    def _use_fallback_data(self):
        """Use approximate EXP values if database unavailable."""
        # Approximate EXP requirements based on FFXIV submarine data
        # These values are conservative estimates - real DB values preferred
        for level in range(1, 126):
            if level <= 15:
                self.ranks[level] = 60_000 + (level * 8_000)
            elif level <= 30:
                self.ranks[level] = 120_000 + (level * 10_000)
            elif level <= 50:
                self.ranks[level] = 200_000 + (level * 12_000)
            elif level <= 75:
                self.ranks[level] = 350_000 + (level * 15_000)
            else:
                self.ranks[level] = 500_000 + (level * 18_000)

        # Use fallback phase data
        self.phases = list(self.FALLBACK_PHASES)

    def get_exp_in_range(self, start_level: int, end_level: int) -> int:
        """
        Get total EXP needed to level from start_level to end_level.

        Args:
            start_level: Current level
            end_level: Target level

        Returns:
            Total EXP required
        """
        self._ensure_loaded()
        if start_level >= end_level:
            return 0
        return sum(self.ranks.get(i, 0) for i in range(start_level, end_level))

    def get_hours_to_level(self, from_level: int, to_level: int) -> float:
        """
        Calculate base hours to level using phased model (no RNG adjustment).

        Uses Lumina sector data for EXP/voyage and voyage duration.

        Args:
            from_level: Current submarine level
            to_level: Target level

        Returns:
            Estimated hours (base, before RNG/inefficiency)
        """
        self._ensure_loaded()
        if from_level >= to_level:
            return 0.0

        total_hours = 0.0

        for phase_start, phase_end, exp_rate, voyage_hours, _ in self.phases:
            # Skip phases entirely before our current level
            if from_level >= phase_end:
                continue
            # Stop if we've passed our target
            if to_level <= phase_start:
                break

            # Calculate effective level range within this phase
            eff_start = max(from_level, phase_start)
            eff_end = min(to_level, phase_end)

            if eff_start >= eff_end:
                continue

            # Calculate EXP needed in this phase
            phase_exp = self.get_exp_in_range(eff_start, eff_end)

            # Calculate voyages needed (EXP / EXP per voyage)
            phase_voyages = phase_exp / exp_rate if exp_rate > 0 else 0

            # Calculate hours (voyages * hours per voyage)
            total_hours += phase_voyages * voyage_hours

        return total_hours

    def apply_rng_factor(self, hours: float, level: int, discovery_rate: float) -> float:
        """
        Apply discovery RNG factor based on current level and discovery rate.

        Lower discovery rates mean more failed unlock attempts, increasing time.
        The impact decreases at higher levels where discovery RNG matters less.

        Args:
            hours: Base hours estimate
            level: Current submarine level
            discovery_rate: Discovery rate (0.10 - 0.50)

        Returns:
            Adjusted hours
        """
        self._ensure_loaded()
        # Find applicable phase for RNG factor
        rng_factor = 0.0  # Default for high levels (no RNG impact)
        for phase_start, phase_end, _, _, factor in self.phases:
            if phase_start <= level < phase_end:
                rng_factor = factor
                break

        # Apply RNG adjustment: worse discovery = more time
        # Use linear formula capped at reasonable multiplier
        # Formula: hours * (1 + factor * (1 - rate))
        # This gives modest increases even for low discovery rates
        if discovery_rate > 0 and discovery_rate < 1.0 and rng_factor > 0:
            adjustment = 1 + rng_factor * (1 - discovery_rate)
            return hours * adjustment

        return hours

    def estimate_sub_leveling(
        self,
        submarine,
        target_level: int = 90,
        fc_id: str = "",
        fc_name: str = ""
    ) -> dict:
        """
        Estimate leveling time for a single submarine.

        Args:
            submarine: SubmarineInfo object or dict with level, name, etc.
            target_level: Target level to reach
            fc_id: FC identifier
            fc_name: FC name for display

        Returns:
            Dict with estimate details
        """
        # Handle both object and dict inputs
        if hasattr(submarine, 'level'):
            current_level = submarine.level
            sub_name = submarine.name
            exp_progress = getattr(submarine, 'exp_progress', 0)
            build = getattr(submarine, 'build', '')
            unlock_plan_guid = getattr(submarine, 'unlock_plan_guid', '')
            voyage_status = getattr(submarine, 'status', 'unknown')
            hours_remaining = getattr(submarine, 'hours_remaining', 0)
            route_name = getattr(submarine, 'route_name', '')
            return_time = getattr(submarine, 'return_time', None)
        else:
            current_level = submarine.get('level', 1)
            sub_name = submarine.get('name', 'Unknown')
            exp_progress = submarine.get('exp_progress', 0)
            build = submarine.get('build', '')
            unlock_plan_guid = submarine.get('unlock_plan_guid', '')
            voyage_status = submarine.get('status', 'unknown')
            hours_remaining = submarine.get('hours_remaining', 0)
            route_name = submarine.get('route_name', '')
            return_time = submarine.get('return_time', None)

        # Already at or above target
        if current_level >= target_level:
            return {
                'submarine_name': sub_name,
                'fc_id': fc_id,
                'fc_name': fc_name,
                'current_level': current_level,
                'target_level': target_level,
                'already_at_target': True,
                'estimates': {
                    'optimistic': {'hours': 0, 'days': 0},
                    'expected': {'hours': 0, 'days': 0},
                    'pessimistic': {'hours': 0, 'days': 0},
                },
                'on_unlock_plan': bool(unlock_plan_guid),
                'unlock_plan_name': '',
                'exp_progress': exp_progress,
                'build': build,
                'voyage_status': voyage_status,
                'hours_remaining': round(hours_remaining, 2) if hours_remaining else 0,
                'route': route_name,
                'return_time': return_time.isoformat() if return_time else None,
            }

        # Calculate base hours
        base_hours = self.get_hours_to_level(current_level, target_level)

        # Calculate estimates for each tier
        estimates = {}
        for tier, rate in self.DISCOVERY_RATES.items():
            adjusted_hours = self.apply_rng_factor(base_hours, current_level, rate)
            adjusted_hours *= self.INEFFICIENCY_MULTIPLIER
            estimates[tier] = {
                'hours': round(adjusted_hours, 1),
                'days': round(adjusted_hours / 24, 1)
            }

        return {
            'submarine_name': sub_name,
            'fc_id': fc_id,
            'fc_name': fc_name,
            'current_level': current_level,
            'target_level': target_level,
            'already_at_target': False,
            'estimates': estimates,
            'on_unlock_plan': bool(unlock_plan_guid),
            'unlock_plan_name': '',
            'exp_progress': exp_progress,
            'build': build,
            'voyage_status': voyage_status,
            'hours_remaining': round(hours_remaining, 2) if hours_remaining else 0,
            'route': route_name,
            'return_time': return_time.isoformat() if return_time else None,
        }

    def _get_hours_for_sub_with_rng(self, from_level: int, to_level: int, discovery_rate: float) -> float:
        """Get hours to level with RNG and inefficiency applied."""
        base_hours = self.get_hours_to_level(from_level, to_level)
        adjusted_hours = self.apply_rng_factor(base_hours, from_level, discovery_rate)
        return adjusted_hours * self.INEFFICIENCY_MULTIPLIER

    def _get_slot_unlock_hours(self, slot_num: int, tier: str, unlocked_sectors: set = None) -> float:
        """
        Calculate hours until a slot unlocks based on sector discovery.

        Args:
            slot_num: Slot number (2, 3, or 4)
            tier: Discovery tier ('optimistic', 'expected', 'pessimistic')
            unlocked_sectors: Set of already unlocked sector letters

        Returns:
            Hours until slot unlocks (0 if already unlocked)
        """
        if slot_num not in self.SLOT_UNLOCK_SECTORS:
            return 0

        if unlocked_sectors is None:
            unlocked_sectors = set()

        slot_info = self.SLOT_UNLOCK_SECTORS[slot_num]
        voyages_per_discovery = self.VOYAGES_PER_DISCOVERY[tier]

        # Count sectors still needed to discover
        # For slot 2: need B, E, J from scratch
        # For slot 3: need N, O (assumes J already discovered for slot 2)
        # For slot 4: need S, T (assumes O already discovered for slot 3)

        if slot_num == 2:
            # Full path from start
            sectors_needed = [s for s in slot_info['path'] if s not in unlocked_sectors]
        elif slot_num == 3:
            # Assumes slot 2 (J) is done or will be done
            # Check if J is unlocked
            if 'J' in unlocked_sectors:
                sectors_needed = [s for s in slot_info['path'] if s not in unlocked_sectors]
            else:
                # Need to do slot 2 path first, then slot 3 path
                slot2_sectors = [s for s in self.SLOT_UNLOCK_SECTORS[2]['path'] if s not in unlocked_sectors]
                sectors_needed = slot2_sectors + [s for s in slot_info['path'] if s not in unlocked_sectors]
        elif slot_num == 4:
            # Assumes slots 2 and 3 (J, O) are done or will be done
            if 'O' in unlocked_sectors:
                sectors_needed = [s for s in slot_info['path'] if s not in unlocked_sectors]
            elif 'J' in unlocked_sectors:
                # Need slot 3 path, then slot 4 path
                slot3_sectors = [s for s in self.SLOT_UNLOCK_SECTORS[3]['path'] if s not in unlocked_sectors]
                sectors_needed = slot3_sectors + [s for s in slot_info['path'] if s not in unlocked_sectors]
            else:
                # Need all paths
                slot2_sectors = [s for s in self.SLOT_UNLOCK_SECTORS[2]['path'] if s not in unlocked_sectors]
                slot3_sectors = [s for s in self.SLOT_UNLOCK_SECTORS[3]['path'] if s not in unlocked_sectors]
                sectors_needed = slot2_sectors + slot3_sectors + [s for s in slot_info['path'] if s not in unlocked_sectors]
        else:
            sectors_needed = []

        if not sectors_needed:
            return 0

        # Calculate voyages needed
        total_voyages = len(sectors_needed) * voyages_per_discovery

        # Convert to hours
        return total_voyages * self.EARLY_VOYAGE_HOURS * self.INEFFICIENCY_MULTIPLIER

    def estimate_fc_leveling(
        self,
        fc_subs: list,
        target_level: int,
        fc_id: str,
        fc_name: str,
        world: str = ""
    ) -> dict:
        """
        Estimate leveling time for all subs in an FC.

        For FCs with fewer than 4 subs, accounts for slot unlock timing:
        - Slot 2 unlocks at rank 20
        - Slot 3 unlocks at rank 30
        - Slot 4 unlocks at rank 40

        FC is "done" when the LAST sub (including future unlocked ones) reaches target.

        Args:
            fc_subs: List of SubmarineInfo objects for this FC
            target_level: Target level
            fc_id: FC identifier
            fc_name: FC name
            world: FC's world

        Returns:
            Dict with FC-level estimate and per-sub breakdown
        """
        if not fc_subs:
            return {
                'fc_id': fc_id,
                'fc_name': fc_name,
                'world': world,
                'subs_at_target': 0,
                'subs_below_target': 0,
                'total_subs': 0,
                'max_subs': 4,
                'pending_unlocks': 4,
                'slowest_sub': None,
                'estimates': {
                    'optimistic': {'hours': 0, 'days': 0},
                    'expected': {'hours': 0, 'days': 0},
                    'pessimistic': {'hours': 0, 'days': 0},
                },
                'submarines': [],
            }

        current_sub_count = len(fc_subs)

        # Get estimates for existing submarines
        sub_estimates = []
        for sub in fc_subs:
            est = self.estimate_sub_leveling(sub, target_level, fc_id, fc_name)
            sub_estimates.append(est)

        # Find the lead sub (highest level)
        lead_sub = max(fc_subs, key=lambda s: s.level if hasattr(s, 'level') else s.get('level', 0))
        lead_level = lead_sub.level if hasattr(lead_sub, 'level') else lead_sub.get('level', 0)

        # Track completion times per tier for all subs (existing + future)
        all_completion_hours = {
            'optimistic': [],
            'expected': [],
            'pessimistic': [],
        }

        # Add existing sub completion times
        for est in sub_estimates:
            if not est['already_at_target']:
                for tier in all_completion_hours:
                    all_completion_hours[tier].append(est['estimates'][tier]['hours'])

        # Calculate future sub unlocks if FC has fewer than 4 subs
        # Uses sector-based unlock timing (discover J for slot 2, O for slot 3, T for slot 4)
        pending_unlocks = 0
        future_subs = []

        # Track cumulative unlock time (each slot builds on previous)
        cumulative_unlock_hours = {'optimistic': 0, 'expected': 0, 'pessimistic': 0}

        for slot_num in [2, 3, 4]:
            if current_sub_count >= slot_num:
                # Slot already unlocked (we have this many subs)
                continue

            pending_unlocks += 1
            slot_info = self.SLOT_UNLOCK_SECTORS.get(slot_num, {})
            unlock_sector = slot_info.get('sector', '?')

            # Calculate when this slot unlocks and when the new sub would reach target
            for tier, rate in self.DISCOVERY_RATES.items():
                # Hours to discover the unlock sector (cumulative from previous slots)
                hours_until_unlock = self._get_slot_unlock_hours(slot_num, tier)

                # Hours for new sub to go from level 1 to target
                hours_new_sub_to_target = self._get_hours_for_sub_with_rng(1, target_level, rate)

                # Total hours = unlock time + new sub leveling time
                total_hours = hours_until_unlock + hours_new_sub_to_target
                all_completion_hours[tier].append(total_hours)

            # Add placeholder for future sub in the list
            future_sub_est = {
                'submarine_name': f'[Slot {slot_num} - Discover Sector {unlock_sector}]',
                'fc_id': fc_id,
                'fc_name': fc_name,
                'current_level': 0,
                'target_level': target_level,
                'already_at_target': False,
                'is_future_sub': True,
                'unlock_sector': unlock_sector,
                'estimates': {},
                'on_unlock_plan': False,
                'unlock_plan_name': '',
                'exp_progress': 0,
                'build': '',
            }

            for tier, rate in self.DISCOVERY_RATES.items():
                hours_until_unlock = self._get_slot_unlock_hours(slot_num, tier)
                hours_new_sub = self._get_hours_for_sub_with_rng(1, target_level, rate)
                total = hours_until_unlock + hours_new_sub
                future_sub_est['estimates'][tier] = {
                    'hours': round(total, 1),
                    'days': round(total / 24, 1)
                }

            future_subs.append(future_sub_est)

        # Add future subs to the list
        sub_estimates.extend(future_subs)

        # Count subs at target vs below (only existing subs)
        subs_at_target = sum(1 for s in sub_estimates if s['already_at_target'])
        subs_below_target = sum(1 for s in sub_estimates if not s['already_at_target'] and not s.get('is_future_sub'))

        # FC completion time is the MAX of all sub completion times
        fc_estimates = {}
        slowest_sub = None
        max_expected_hours = 0

        for tier in self.DISCOVERY_RATES:
            if all_completion_hours[tier]:
                max_hours = max(all_completion_hours[tier])
                fc_estimates[tier] = {
                    'hours': round(max_hours, 1),
                    'days': round(max_hours / 24, 1)
                }
                if tier == 'expected' and max_hours > 0:
                    max_expected_hours = max_hours
            else:
                fc_estimates[tier] = {'hours': 0, 'days': 0}

        # Find which sub is the bottleneck
        if max_expected_hours > 0:
            for est in sub_estimates:
                if not est['already_at_target']:
                    if abs(est['estimates']['expected']['hours'] - max_expected_hours) < 1:
                        slowest_sub = est['submarine_name']
                        break

        return {
            'fc_id': fc_id,
            'fc_name': fc_name,
            'world': world,
            'subs_at_target': subs_at_target,
            'subs_below_target': subs_below_target,
            'total_subs': current_sub_count,
            'max_subs': 4,
            'pending_unlocks': pending_unlocks,
            'slowest_sub': slowest_sub,
            'estimates': fc_estimates,
            'submarines': sub_estimates,
        }


# Singleton instance
leveling_estimator = LevelingEstimator()
