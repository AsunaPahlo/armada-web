# FC Credits Tracking Feature Design

## Problem

FC credits accumulate in each Free Company's coffers and are spent on FC buffs and crafting. The plugin already reports current FC credit balances per FC (via `fc_points` from `FCPointsHook`) and per supplier character (via `fc_credits`), but the web app only displays the current value — there's no history, no earnings rate, and no chart showing how credits accumulate over time.

Users want to answer: *how many credits did I earn this week / this month / all-time, and what does the balance look like over time across my FCs?*

## Solution

Record one snapshot per FC per day of the current credit balance, then render a dedicated `/credits` page with:

- Four stat cards: week earned, month earned, all-time earned, current total balance
- A single aggregated line chart of total balance per day across all included FCs
- A per-FC toggle list so FCs can be excluded from the chart and stat cards

"Earned" is calculated as the sum of positive deltas between consecutive snapshots, so spending doesn't reduce the earnings figures.

The plugin is already sending the data — this is pure web-side work.

## Data Model

New model: `app/models/fc_credits_snapshot.py`

```python
class FCCreditsSnapshot(db.Model):
    __tablename__ = 'fc_credits_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    fc_id = db.Column(db.String(64), nullable=False, index=True)
    snapshot_date = db.Column(db.Date, nullable=False, index=True)
    credits = db.Column(db.BigInteger, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('fc_id', 'snapshot_date', name='uq_fc_credits_fc_date'),
    )
```

One row per FC per day. Latest value seen during the day wins (upsert on `(fc_id, snapshot_date)`).

Size estimate: ~10 FCs × 365 days ≈ 3,650 rows/year. Kept forever — no pruning.

Add one column to the existing `FcConfig` model:

```python
excluded_from_credits = db.Column(db.Boolean, nullable=False, default=False)
```

Use the existing auto-migration pattern in `create_app()` to add the column if missing.

## Data Ingestion

Hook into `on_fleet_data()` in `app/routes/websocket.py` after the existing `FleetManager.update_from_plugin(...)` call succeeds. Iterate parsed fleet data and call `FCCreditsTracker.record_snapshot(fc_id, credits)` for each FC with a valid credits value.

**Value selection rule per FC per ingestion:**

1. If the FC dict has `fc_points > 0` for this `fc_id`, use it (authoritative — live packet intercept).
2. Else, if any supplier reports `fc_credits > 0` for this `fc_id`, use the max across suppliers for that FC.
3. Else, skip — do not write `0`, as that likely means a character without FC access, not an actual zero balance.

Wrap the entire snapshot loop in try/except so a snapshot failure never breaks fleet data ingestion.

## Service Layer

New file: `app/services/fc_credits_tracker.py`

```python
class FCCreditsTracker:
    @staticmethod
    def record_snapshot(fc_id: str, credits: int) -> None:
        """Upsert today's snapshot for an FC. snapshot_date = server local today()."""

    @staticmethod
    def get_report(days: int, exclude_fc_ids: set[str]) -> dict:
        """Build full credits report for the /credits page.

        days=0 means full history. Other values limit the chart window and the
        week/month cards; all_time_earned always uses full history regardless.
        """
```

**`get_report` return shape:**

```python
{
    "series": [
        {"date": "2026-03-20", "balance": 123456},
        {"date": "2026-03-21", "balance": 124500},
        ...
    ],
    "cards": {
        "week_earned":     int,
        "month_earned":    int,
        "all_time_earned": int,
        "current_balance": int,
    },
    "included_fcs": [
        {"fc_id": "...", "fc_name": "...", "world": "...",
         "current_balance": int, "excluded": False}
    ],
    "excluded_fcs": [
        {"fc_id": "...", "fc_name": "...", "world": "...",
         "current_balance": int, "excluded": True}
    ],
}
```

**Positive-delta sum algorithm:**

For each FC, sort snapshots by date ascending. `earned = sum(max(0, s[i].credits - s[i-1].credits) for i in 1..n)`. Compute per-FC, then sum across included FCs for the stat cards.

**Aggregation for the chart `series`:**

Group snapshots by date. For each date, sum the latest balance of every included FC that has a snapshot on or before that date. Result: one `{date, balance}` object per day in the selected window. If an FC has no snapshot for a given date, use its most recent prior snapshot (carry-forward) so the aggregate line stays continuous.

**FC name resolution:** Look up names from the `fc_summaries` dict returned by `FleetManager.get_dashboard_data()` (each entry has `fc_name`, `world`). Fall back to the `fc_id` string when the FC is no longer in plugin data.

**Cards respect windows:** `week_earned` = last 7 days, `month_earned` = last 30 days, `all_time_earned` = full history. `current_balance` = sum of the latest balance across included FCs.

## Routes

New blueprint: `app/routes/credits.py`, registered in `app/__init__.py` with `url_prefix="/credits"`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/credits` | Render `credits.html` skeleton |
| `GET` | `/credits/data?days=N` | AJAX JSON — calls `FCCreditsTracker.get_report(days, excluded)` |
| `POST` | `/credits/toggle` | JSON body `{fc_id, excluded}` — upsert `FcConfig.excluded_from_credits` |

**`/credits/data` query param:**

- `days` (int, default 30). Allowed values: 7, 14, 30, 90, 365, 0 (where 0 = all time).
- Reads `excluded_from_credits=True` rows from `FcConfig` to build the `exclude_fc_ids` set.

**`/credits/toggle` behavior:**

- Upserts the `FcConfig` row for the given `fc_id`, creating one if missing.
- Returns `{"status": "ok"}` on success, HTTP 400 on bad payload.

**Auth decorators:**

- `GET` routes: `@login_required`
- `POST /credits/toggle`: `@login_required` + `@writable_required`

## UI

**Template:** `app/templates/credits.html`, extends `base.html`. Matches the look of `/stats` and `/gil`.

**Layout (top to bottom):**

1. **Page header** — title "FC Credits" + day selector buttons (7 / 14 / 30 / 90 / 365 / All). Active button highlighted. Clicking a button triggers `loadData(N)`; no URL change.
2. **Stat cards row** — four Bootstrap cards in a single row: This Week Earned, This Month Earned, All-Time Earned, Current Balance.
3. **Line chart** — Chart.js, single aggregated series. X-axis = date, Y-axis = total balance across included FCs. Legend hidden (only one line).
4. **FC toggle list** — below the chart. Each FC row shows: name, world, current balance, and a Bootstrap toggle switch. Toggling calls `POST /credits/toggle` then re-fetches `/credits/data`.
5. **Empty state** — when no snapshots exist, show: *"No FC credits data yet — it'll populate as your plugin sends data."* Hide chart and stat cards in this state.

**JS module:** `app/static/js/credits.js`

- `loadData(days)` — fetch `/credits/data?days=N`, update cards, rebuild chart, rebuild toggle list
- `toggleFC(fc_id, excluded)` — POST toggle, then `loadData(currentDays)`
- Day selector buttons call `loadData(N)` and update `data-active-days`
- On page load: `loadData(30)`

**Navigation:** add a "Credits" link to the main nav in `base.html` next to "Gil".

**Chart library:** Chart.js, already loaded by `/stats` — reuse the same import.

## Testing

- **Unit tests** for `FCCreditsTracker`:
  - `record_snapshot` creates a new row on first call
  - `record_snapshot` updates credits and `updated_at` on same-day second call (upsert)
  - `get_report` positive-delta algorithm ignores decreases (spending doesn't reduce earnings)
  - `get_report` aggregates correctly with multiple FCs
  - `get_report` with `exclude_fc_ids` filters both chart series and stat cards
  - `get_report` carry-forward fills gaps when one FC has no snapshot on a given date
- **Route tests** for `/credits/*`:
  - `GET /credits/data` returns the expected shape
  - `POST /credits/toggle` upserts `FcConfig`
  - Readonly user is blocked from `POST /credits/toggle`
- **Manual verification** with real plugin data:
  - After one fleet_data payload, a row appears in `fc_credits_snapshots` for each FC with credits
  - Toggling an FC off removes it from the chart and stat cards
  - Day selector re-fetches without a page reload

## Constraints

- Plugin already sends the data — no plugin changes required.
- Snapshots fire on every plugin fleet_data payload, but upserts on `(fc_id, date)` so effective write rate is at most one row per FC per day.
- Server local time is used for `snapshot_date` to match `DailyStats` convention.
- No backfill — history starts when this feature ships.
