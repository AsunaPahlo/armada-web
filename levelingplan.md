# FC Submarine Leveling Time Estimator

**Status:** Ready for implementation (revisit tomorrow)
**Decisions:**
- Use sector EXP rewards (`SubmarineExploration.exp_reward`) for EXP calculations
- Parse unlock plans from AutoRetainer to estimate leveling subs
**TODO:** Decide on display location (new page vs dashboard vs both)

## Overview
Estimate how long until all submarines in an FC reach the target level (default 90, customizable), based on:
- Current submarine level and EXP
- EXP gained per voyage (from sector rewards)
- Voyage duration
- For unlock plan subs: remaining sectors to unlock

## Implementation Phases

### Phase 1: Config Parser - Parse Unlock Plans
**File:** `app/services/config_parser.py`

Add parsing for `SubmarineUnlockPlans` array from AutoRetainer config:
```python
# In AccountData dataclass, add:
unlock_plans: dict = field(default_factory=dict)  # GUID -> UnlockPlan

# Parse from DefaultConfig.json:
for plan in data.get('SubmarineUnlockPlans', []):
    guid = plan.get('GUID', '')
    account.unlock_plans[guid] = {
        'name': plan.get('Name', ''),
        'excluded_routes': plan.get('ExcludedRoutes', []),  # Sector IDs to skip
        'unlock_subs': plan.get('UnlockSubs', False),
        'enforce_plan': plan.get('EnforcePlan', False)
    }
```

Also need to link submarine to its selected unlock plan:
```python
# In SubmarineInfo, add:
unlock_plan_guid: str = ""  # GUID of selected unlock plan (if any)

# Parse from AdditionalSubmarineData:
unlock_plan_guid = add_data.get('SelectedUnlockPlan', '')
```

### Phase 2: Add Target Level Setting
**File:** `app/models/app_settings.py`
```python
DEFAULTS = {
    ...
    'target_submarine_level': ('90', 'Target level for submarine leveling estimates'),
}
```

**File:** `app/templates/profit_settings.html`
- Add input field for target level (1-125)

### Phase 3: Create Leveling Estimator Service
**New File:** `app/services/leveling_estimator.py`

```python
class LevelingEstimator:
    PHASES = [
        (1, 25, 180_000, 15, 0.35),   # SSSS early unlock
        (25, 50, 500_000, 18, 0.25),  # SSUS mid unlock
        (50, 75, 900_000, 20, 0.15),  # SSUS late unlock
        (75, 90, 1_400_000, 22, 0.05),# SSUS farming
    ]

    DISCOVERY_RATES = {
        'optimistic': 1.0,
        'expected': 0.75,
        'pessimistic': 0.55,
    }

    INEFFICIENCY_MULTIPLIER = 1.18

    SLOT_UNLOCK_RANKS = {2: 20, 3: 30, 4: 40}

    def __init__(self):
        # Load rank EXP data from database
        self.ranks = {r.id: r.exp_to_next for r in SubmarineRank.query.all()}

    def get_exp_in_range(self, start_level: int, end_level: int) -> int:
        """Get total EXP needed between two levels."""
        return sum(self.ranks.get(i, 0) for i in range(start_level, end_level))

    def get_hours_to_level(self, from_level: int, to_level: int) -> float:
        """Calculate hours to level using phased model."""
        total_hours = 0
        for phase_start, phase_end, exp_rate, voyage_hours, _ in self.PHASES:
            if from_level >= phase_end:
                continue
            eff_start = max(from_level, phase_start)
            eff_end = min(to_level, phase_end)
            if eff_start >= eff_end:
                continue
            phase_exp = self.get_exp_in_range(eff_start, eff_end)
            phase_voyages = phase_exp / exp_rate
            total_hours += phase_voyages * voyage_hours
        return total_hours

    def apply_rng_factor(self, hours: float, level: int, discovery_rate: float) -> float:
        """Apply discovery RNG factor based on current level."""
        for phase_start, phase_end, _, _, factor in self.PHASES:
            if phase_start <= level < phase_end:
                return hours * (1 + factor * (1/discovery_rate - 1))
        return hours * 1.05

    def estimate_sub_leveling(self, submarine, target_level: int = 90) -> dict:
        """Estimate time for one submarine to reach target."""
        if submarine.level >= target_level:
            return {'already_at_target': True, 'days_remaining': 0}

        base_hours = self.get_hours_to_level(submarine.level, target_level)

        estimates = {}
        for est_name, rate in self.DISCOVERY_RATES.items():
            adjusted_hours = self.apply_rng_factor(base_hours, submarine.level, rate)
            adjusted_hours *= self.INEFFICIENCY_MULTIPLIER
            estimates[est_name] = {
                'hours': adjusted_hours,
                'days': round(adjusted_hours / 24, 1)
            }

        return {
            'submarine_name': submarine.name,
            'current_level': submarine.level,
            'target_level': target_level,
            'estimates': estimates
        }

    def estimate_fc_leveling(self, fc_subs: list, target_level: int = 90) -> dict:
        """Estimate time for all subs in FC to reach target (last sub to finish)."""
        sub_estimates = [self.estimate_sub_leveling(sub, target_level) for sub in fc_subs]

        # FC is done when the LAST (slowest) sub hits target
        slowest = max(sub_estimates, key=lambda x: x['estimates']['expected']['days'])

        return {
            'submarines': sub_estimates,
            'subs_at_target': sum(1 for s in sub_estimates if s.get('already_at_target')),
            'subs_below_target': sum(1 for s in sub_estimates if not s.get('already_at_target')),
            'slowest_sub': slowest['submarine_name'],
            'estimates': slowest['estimates']
        }
```

### Phase 4: Add Routes and Template
**File:** `app/routes/stats.py`
```python
@stats_bp.route('/leveling')
@login_required
def leveling():
    """Submarine leveling estimates page."""
    target_level = AppSettings.get_int('target_submarine_level', 90)
    return render_template('leveling.html', target_level=target_level)

@stats_bp.route('/leveling/data')
@login_required
def leveling_data():
    """JSON endpoint for leveling estimates."""
    target_level = request.args.get('target', 90, type=int)
    # Return per-FC leveling estimates
    return jsonify(leveling_estimator.get_all_fc_estimates(target_level))
```

**New File:** `app/templates/leveling.html`
- Target level selector
- Per-FC cards with:
  - Progress bar (X/Y subs at target level)
  - **Three estimate display**: Optimistic / Expected (highlighted) / Pessimistic days
  - Expandable per-submarine breakdown showing all three estimates
  - Highlight subs on unlock plans
  - Tooltip explaining discovery rate assumptions

## Key Files to Modify/Create
1. `app/services/config_parser.py` - Parse unlock plans, link to submarines
2. `app/models/app_settings.py` - Add target_level setting
3. `app/services/leveling_estimator.py` - **NEW** - Core estimation logic
4. `app/routes/stats.py` - Add routes
5. `app/templates/leveling.html` - **NEW** - Leveling dashboard page
6. `app/templates/profit_settings.html` - Add target level input

## Data Dependencies
- `SubmarineRank` table - `exp_to_next` per rank (from Lumina CSV)
- `SubmarineExploration` table - `exp_reward` per sector (from Lumina CSV)
- `UNLOCK_TREE` - sector prerequisites for unlock order
- AutoRetainer config - `SubmarineUnlockPlans` array

## Phased Estimation Model

Leveling uses a **phased model** that accounts for:
- Part swaps (SSSS 1-25, SSUS 25-90)
- Increasing EXP/voyage as deeper sectors unlock
- Variable voyage durations based on route length
- Discovery RNG impact decreasing at higher levels

### Leveling Phases

| Phase | Levels | Build | Avg EXP/Voyage | Avg Voyage Hours | Discovery RNG Factor |
|-------|--------|-------|----------------|------------------|---------------------|
| Early Unlock | 1-25 | SSSS | 180,000 | 15h | 0.35 |
| Mid Unlock | 25-50 | SSUS | 500,000 | 18h | 0.25 |
| Late Unlock | 50-75 | SSUS | 900,000 | 20h | 0.15 |
| Farming/Final | 75-90 | SSUS | 1,400,000 | 22h | 0.05 |

### Submarine Slot Unlocks

New FCs must unlock submarine slots by discovering specific sectors:

| Slot | Sector | Location | Rank Required |
|------|--------|----------|---------------|
| Slot 2 | Unidentified Derelict | J | 20 |
| Slot 3 | Wreckage of Discovery I | O | 30 |
| Slot 4 | Purgatory | T | 40 |

### Real-World Inefficiency Multiplier

Apply **18% inefficiency multiplier** to account for:
- Delayed voyage sends (player availability)
- Discovery RNG on unlock sectors themselves
- Repair/parts downtime
- Sub-optimal route choices during learning

### Discovery Rate Estimation (Three Estimates)

| Estimate | Discovery Rate | Use Case |
|----------|---------------|----------|
| **Optimistic** | 100% | Best case, every voyage unlocks its target |
| **Expected** | 75% | Realistic average for decent surveillance stats |
| **Pessimistic** | 55% | Unlucky scenario or low surveillance builds |

```python
DISCOVERY_RATES = {
    'optimistic': 1.0,
    'expected': 0.75,
    'pessimistic': 0.55,
}

PHASES = [
    # (level_start, level_end, avg_exp_per_voyage, avg_voyage_hours, discovery_rng_factor)
    (1, 25, 180_000, 15, 0.35),   # SSSS early unlock
    (25, 50, 500_000, 18, 0.25),  # SSUS mid unlock
    (50, 75, 900_000, 20, 0.15),  # SSUS late unlock
    (75, 90, 1_400_000, 22, 0.05),# SSUS farming
]

INEFFICIENCY_MULTIPLIER = 1.18

SLOT_UNLOCK_RANKS = {
    2: 20,  # Sector J
    3: 30,  # Sector O
    4: 40,  # Sector T
}
```

### FC Completion Timeline

For a **new FC** (all 4 subs from level 1 to 90):

| Estimate | FC Complete | Months |
|----------|-------------|--------|
| Optimistic | ~115 days | 3.8 |
| Expected | ~128 days | 4.3 |
| Pessimistic | ~148 days | 4.9 |

Timeline logic:
1. Sub 1 starts Day 0
2. Sub 1 hits rank 20, discovers J -> Slot 2 unlocks, Sub 2 starts (~Day 6)
3. Sub 1 hits rank 30, discovers O -> Slot 3 unlocks, Sub 3 starts (~Day 12)
4. Sub 1 hits rank 40, discovers T -> Slot 4 unlocks, Sub 4 starts (~Day 18)
5. FC complete when Sub 4 (the last sub) hits level 90

The UI should display all three estimates, with **Expected** as the primary/highlighted value.

## Unlock Plan Estimation Logic

For subs on unlock plans, estimate voyages by:
1. Get `excluded_routes` from unlock plan
2. Get `unlocked_sectors` from character
3. Find remaining sectors = (all sectors) - (excluded) - (unlocked)
4. Sort by unlock order using `UNLOCK_TREE` prerequisites
5. Group into voyages (4-5 sectors per voyage based on sub capacity)
6. Sum EXP from `SubmarineExploration.exp_reward` for each voyage
7. Calculate voyage duration using existing calculator
8. **Apply discovery rate multiplier for each estimate tier**

## Edge Cases
- Sub already at/above target level - mark complete
- Sub with no route set - show "Unknown" estimate
- Sub on unlock plan with all sectors done - treat as farming sub
- Missing SubmarineRank data - log warning, use average
- Sub level > 125 (max) - cap at 125
- **Farming subs (not on unlock plan)** - all three estimates will be identical since no discovery RNG applies; they just repeat the same route

## Verification
1. Verify SubmarineRank data exists: `SELECT COUNT(*) FROM submarine_ranks`
2. Verify SubmarineExploration has exp_reward: `SELECT id, exp_reward FROM submarine_explorations LIMIT 10`
3. Test EXP calculation: manually verify for a known submarine
4. Test unlock plan parsing: check that plans appear in account data
5. Test estimation accuracy: compare estimate vs actual for a recently leveled sub
