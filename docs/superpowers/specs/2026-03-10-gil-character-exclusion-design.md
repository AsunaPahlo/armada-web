# Gil Character Exclusion

Exclude specific characters from gil page totals and chart while still showing them in the table.

## Problem

User runs submarines for friends on some characters. Those characters' gil inflates the total and chart, misrepresenting personal wealth.

## Design

### Model: `GilConfig` (`app/models/gil_config.py`)

New table `gil_configs` following the `FCConfig` pattern:

| Column | Type | Description |
|--------|------|-------------|
| id | Integer PK | Auto-increment |
| cid | String, unique, indexed | Character ID from GilRecord |
| excluded_from_gil | Boolean, default False | Whether to exclude from totals/chart |
| updated_at | DateTime | Last modified timestamp |

Helpers:
- `get_gil_excluded_cids() -> set` — returns set of CID strings where `excluded_from_gil=True`
- `update_gil_config(cid, **kwargs)` — upsert pattern matching `update_fc_config`
- `_migrate_gil_config_columns()` — runtime column migration

### Route: `gil_config_bp` (`app/routes/gil_config.py`)

Blueprint registered at `/settings/gil-config`.

- `POST /toggle` — accepts `{cid, setting, value}`, validates setting against allowed list, calls `update_gil_config`

### Settings Integration

**Sidebar entry** in `settings/index.html`: "Gil Exclusions" with `data-section="gil-config"`.

**Partial route** in `settings.py`: `/partial/gil-config` — queries latest GilRecord per CID to build character list, merges with GilConfig state, renders partial.

**Partial template** (`settings/partials/gil_config.html`):
- Table listing all characters (name, world, client) with eye/eye-slash toggle button
- Search input for filtering
- Info card explaining what exclusion does
- Same IIFE JS pattern as fc_config partial

### Gil API Changes (`app/routes/gil.py`)

**`/api/data` endpoint modifications:**
- Import `get_gil_excluded_cids()`
- Add `cid` and `excluded` fields to each character object in response
- Filter excluded CIDs from `prev_values` forward-fill (removes from chart totals)
- Filter excluded CIDs from `total_gil` and `chart_char_counts` summaries
- Keep excluded characters in the `characters` array

### Gil Page Changes (`app/templates/gil.html`)

**Table rendering:**
- Excluded rows: dimmed (opacity 0.5), `bi-eye-slash` icon before character name
- Non-excluded rows: render as before
- Summary cards (`total-gil`, `char-count`) computed from non-excluded characters only

### Registration (`app/__init__.py`)

- Import and register `gil_config_bp` at `/settings/gil-config`
- Import `gil_config` model
- Call `_migrate_gil_config_columns()` on startup
