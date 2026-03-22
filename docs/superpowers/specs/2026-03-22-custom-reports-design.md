# Custom Reports & Query Engine — Design Spec

## Overview

A custom reporting page for Armada-web that lets users build queries against fleet data using a hybrid interface: a visual query builder for common cases and a text-based DSL for power users. Both modes stay synced — the query text is the canonical representation.

## Query Language (DSL)

### Grammar

```
FIND <entity> [WHERE <conditions>] [GROUP BY <field>] [ORDER BY <field> [ASC|DESC]] [LIMIT <n>]
```

### Entities

| Entity | Alias | Source | Description |
|--------|-------|--------|-------------|
| `fcs` | — | FleetManager (live) | Free Companies — gil, supplies, world, region, sub count, housing |
| `subs` | `submarines` | FleetManager (live) | Individual submarines — level, build, parts, route, status |
| `voyages` | — | SQLite (Voyage model) | Voyage history — dates, routes, duration, collection status |
| `loot` | — | SQLite (VoyageLoot) | Per-voyage loot records — aggregated value, item details via child `items` |
| `activity` | — | SQLite (ActivityLog) | Activity log — build changes, level ups, route changes, sector unlocks |

**Note:** The original `supplies` entity has been merged into `fcs`. Supply fields (ceruleum, repair_kits, dive_credits) are queryable directly on the `fcs` entity since they are properties of an FC, not a separate data source. The `submarines` alias is accepted by the lexer and normalized to `subs` during parsing.

### Conditions

Conditions use `AND` / `OR` with parentheses for grouping:

```
FIND fcs WHERE ALL subs.level > 111 AND NO subs.build CONTAINS "SSUC"
FIND subs WHERE level >= 100 AND (route = "CSUZ" OR route = "MOJ")
FIND voyages WHERE fc.name = "My FC" AND date > "2026-01-01" AND duration < 24
FIND loot WHERE ANY items.name = "Petalouda Scales" AND date BETWEEN "2026-01-01" AND "2026-03-01"
```

### Field References & Quantifiers

There are two kinds of dot-notation field references:

1. **Child entity references** (downward) — Querying a parent about its children. Uses quantifiers.
   - `FIND fcs WHERE ALL subs.level > 111` — checks each FC's submarines
   - Quantifiers (`ALL`, `ANY`, `NO`) only apply here

2. **Parent entity references** (upward) — Accessing a parent's field from a child context. No quantifier.
   - `FIND subs WHERE fc.world = "Gilgamesh"` — looks up the sub's FC's world
   - `FIND voyages WHERE fc.name = "My FC"` — looks up the voyage's FC name

3. **Direct fields** (no dot) — Filtering on the entity's own fields. No quantifier.
   - `FIND subs WHERE level >= 100`

The parser distinguishes these by checking whether the dot-prefix names a child entity or a parent entity relative to the queried entity. Quantifiers are only valid on child references; using a quantifier on a direct or parent field is a parse error.

**Valid child relationships (for quantifier use):**

| From Entity | Child Entity | Access Pattern |
|-------------|-------------|----------------|
| `fcs` | `subs` | `FIND fcs WHERE ALL subs.level > 100` |
| `loot` | `items` | `FIND loot WHERE ANY items.name = "Petalouda Scales"` |

**Valid parent references (for lookup, no quantifier):**

| From Entity | Parent | Access Pattern |
|-------------|--------|----------------|
| `subs` | `fc` | `FIND subs WHERE fc.world = "Gilgamesh"` |
| `voyages` | `fc` | `FIND voyages WHERE fc.name = "My FC"` |
| `loot` | `fc` | `FIND loot WHERE fc.name = "My FC"` |
| `activity` | `fc` | `FIND activity WHERE fc.name = "My FC"` |

**Quantifiers (child references only):**

| Quantifier | Meaning |
|------------|---------|
| `ALL` | Every child must match (default when omitted on child refs) |
| `ANY` | At least one child matches |
| `NO` | No child matches |

### Operators

| Category | Operators |
|----------|-----------|
| Comparison | `=`, `!=`, `>`, `<`, `>=`, `<=` |
| Text | `CONTAINS`, `NOT CONTAINS`, `STARTS WITH`, `ENDS WITH` |
| Set | `IN (val1, val2)`, `NOT IN (val1, val2)` |
| Range | `BETWEEN val1 AND val2` |
| Null | `IS EMPTY`, `IS NOT EMPTY` |

### Queryable Fields

Each field has a DSL name (user-facing) and maps to a concrete data source. Fields marked with `→` show the mapping to the underlying model column or FleetManager key.

**`fcs`** (source: FleetManager `get_dashboard_data()` → `fc_summaries`):

| DSL Field | Source | Type |
|-----------|--------|------|
| `name` | `fc_name` | string |
| `world` | `world` | string |
| `region` | `region` | string (NA, EU, JP, OCE) |
| `gil` | `fc_gil` | number |
| `ceruleum` | `ceruleum` | number |
| `repair_kits` | `repair_kits` | number |
| `dive_credits` | `dive_credits` | number |
| `total_subs` | `total_subs` | number |
| `ready_subs` | `ready_subs` | number |
| `leveling_subs` | `leveling_subs` | number |
| `gil_per_day` | `gil_per_day` | number |
| `house_size` | FCHousing join → `house_size` property | string (Small, Medium, Large) |
| `tags` | FCTagAssignment join → tag names | set (see Tags section) |

**`subs`** (source: FleetManager `get_dashboard_data()` → `all_submarines`):

| DSL Field | Source | Type |
|-----------|--------|------|
| `name` | `name` | string |
| `level` | `level` | number |
| `build` | `build` | string (e.g., "S+S+U+C+") |
| `parts` | `parts` (list of part names) | set |
| `route` | `route` | string |
| `status` | `status` | string (ready, voyaging, returning_soon) |
| `gil_per_day` | `gil_per_day` | number |
| `exp_progress` | `exp_progress` | number (0-100) |
| `fc.name` | parent lookup → FC name | string |
| `fc.world` | parent lookup → FC world | string |

**`voyages`** (source: SQLite `Voyage` model):

| DSL Field | Model Column | Type |
|-----------|-------------|------|
| `submarine` | `submarine_name` | string |
| `world` | `world` | string |
| `route` | `route_name` | string |
| `departure` | `departure_time` | datetime |
| `return_time` | `return_time` | datetime |
| `duration` | `duration_hours` | number |
| `level` | `submarine_level` | number |
| `build` | `submarine_build` | string |
| `collected` | `was_collected` | boolean |
| `fc.name` | `fc_name` column (denormalized) | string |
| `fc.world` | `world` column | string |

Note: `fc.name` and `fc.world` on `voyages` use denormalized columns that already exist on the Voyage model, so no cross-source join is needed. They use parent reference syntax for consistency with other entities.

**`loot`** (source: SQLite `VoyageLoot` model — one row per voyage):

| DSL Field | Model Column | Type |
|-----------|-------------|------|
| `submarine` | `submarine_name` | string |
| `route` | `route_name` | string |
| `value` | `total_gil_value` | number |
| `date` | `captured_at` | datetime |
| `fc.name` | Resolved by joining `VoyageLoot.fc_id` → `Voyage.fc_id` → `Voyage.fc_name` | string |

Note: `VoyageLoot` has no `fc_name` column — only `fc_id`. The executor resolves `fc.name` by joining to the Voyage table's denormalized `fc_name`. For `fc.world`, the same join path applies via `Voyage.world`.

Loot child entity `items` (source: `VoyageLootItem` — multiple per `VoyageLoot`):

| DSL Field | Model Column | Type |
|-----------|-------------|------|
| `items.name` | `item_name_primary` OR `item_name_additional` | string (matches either) |
| `items.sector` | `sector_id` | number |
| `items.value` | `total_value` property | number |

Note: `items` fields are **only available in WHERE conditions** (for filtering loot records). They do not appear as result columns. When filtering, `items.name` checks both `item_name_primary` and `item_name_additional` — a match on either satisfies the condition.

**`activity`** (source: SQLite `ActivityLog` model):

| DSL Field | Model Column | Type |
|-----------|-------------|------|
| `activity_type` | `activity_type` | string (build_change, level_up, route_change, sector_unlock, submarine_added, submarine_removed) |
| `submarine` | `submarine_name` | string |
| `old_value` | `old_value` | string |
| `new_value` | `new_value` | string |
| `date` | `created_at` | datetime |
| `fc.name` | `fc_name` column (denormalized) | string |

Note: Like voyages, `fc.name` on activity uses the denormalized `fc_name` column on ActivityLog.

### Tags Semantics

Tags are a set-valued field on `fcs`. Operator behavior:

- `tags CONTAINS "Mining"` — FC has a tag named "Mining"
- `tags NOT CONTAINS "Mining"` — FC does not have that tag
- `tags IS EMPTY` — FC has no tags
- `tags IS NOT EMPTY` — FC has at least one tag
- `tags IN ("Mining", "Leveling")` — FC has any of the listed tags

## Architecture

### Data Flow

```
Frontend (reports.html + reports.js)
  │
  │  Query text string (canonical format)
  │
  ▼
POST /reports/run
  │
  ▼
report_engine.py
  ├── Lexer:    query string → token stream
  ├── Parser:   token stream → AST
  └── Executor: AST → results
        ├── DB entities (voyages, loot, activity) → SQLAlchemy queries
        └── Live entities (fcs, subs) → FleetManager data + Python filtering
  │
  ▼
Result Formatter
  ├── Table JSON (rows + columns)
  ├── Summary JSON (counts, totals, averages, groups)
  └── CSV export (streamed download)
```

### Backend Components

**New service — `app/services/report_engine.py`:**

Three-stage pipeline:

1. **Lexer** — Tokenizes query string into typed tokens:
   - Token types: KEYWORD, IDENTIFIER, OPERATOR, VALUE, QUANTIFIER, LPAREN, RPAREN, COMMA
   - Keywords: FIND, WHERE, AND, OR, GROUP, BY, ORDER, ASC, DESC, LIMIT, BETWEEN, IN, NOT, IS, EMPTY, CONTAINS, STARTS, ENDS, WITH, ALL, ANY, NO

2. **Parser** — Converts token stream into AST:
   ```python
   {
       "entity": "fcs",
       "conditions": {
           "type": "AND",
           "children": [
               {
                   "quantifier": "ALL",
                   "field": "subs.level",
                   "operator": ">",
                   "value": 111
               },
               {
                   "quantifier": "NO",
                   "field": "subs.build",
                   "operator": "CONTAINS",
                   "value": "SSUC"
               }
           ]
       },
       "group_by": null,
       "order_by": null,
       "limit": null
   }
   ```

3. **Executor** — Walks the AST and produces results:
   - For DB-backed entities: builds SQLAlchemy queries with filters, joins, aggregations
   - For live entities: fetches FleetManager data and applies Python filtering
   - Quantifier logic for child relationships:
     - `ALL subs.level > 111` → check every submarine in the FC, all must satisfy
     - `ANY subs.route = "CSUZ"` → check if at least one submarine matches
     - `NO subs.build CONTAINS "SSUC"` → check that none match
   - Returns uniform result format regardless of source

**New route blueprint — `app/routes/reports.py`:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/reports` | GET | Render reports page |
| `/reports/run` | POST | Execute query, return JSON results |
| `/reports/schema` | GET | Return entities, fields, operators (drives visual builder) |
| `/reports/save` | POST | Save a named report |
| `/reports/saved` | GET | List user's saved reports |
| `/reports/saved/<id>` | PUT | Update a saved report (name, query, display config) |
| `/reports/saved/<id>` | DELETE | Delete a saved report |
| `/reports/export` | POST | Run query and return CSV file (POST due to query length) |

**New model — `app/models/saved_report.py`:**

```python
class SavedReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    query_text = db.Column(db.Text, nullable=False)
    display_config = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**`display_config` JSON schema:**
```json
{
    "view_mode": "table",
    "visible_columns": ["name", "world", "gil_per_day"]
}
```

Note: `display_config` stores UI-level display preferences only (which view mode and which columns to show). Sorting and grouping are part of the DSL query text (`ORDER BY`, `GROUP BY`) and are not duplicated here. The query text is always the canonical source for query behavior.

### Frontend Components

**`app/templates/reports.html`:**
- Top-down layout: query builder at top, results below
- Tabbed interface: "Visual" and "Query" tabs
- Saved reports dropdown + save button in header area
- Results area with Table/Summary toggle and CSV export button

**`app/static/js/reports.js`:**

Key responsibilities:
- **Visual builder** — Dynamic condition rows with:
  - Logical operator (AND/OR) dropdown
  - Quantifier (ALL/ANY/NO) dropdown — shown only for child entity fields
  - Field picker — grouped dropdown populated from `/reports/schema`
  - Operator dropdown — context-sensitive (numeric vs. text vs. set)
  - Value input — type-appropriate (text, number, dropdown for enums like status/region)
  - Add/remove condition controls
  - Entity picker at top that resets conditions when changed

- **Query text editor** — Textarea with lightweight syntax highlighting (keyword coloring via regex spans). Fully editable.

- **Sync logic:**
  - Visual → Text: On any builder change, regenerate query text
  - Text → Visual: On tab switch to Visual, parse text and rebuild form. Show error banner if parse fails.

- **Results rendering:**
  - Table view: sortable columns, row data from query response. Paginated at 100 rows per page with page controls (results capped at 1000 total).
  - Summary view: see Summary View section below
  - CSV export: triggers download via POST `/reports/export` (submits current query text as form data)

- **Saved reports:** Save/load/delete via API calls, stored per-user

## GROUP BY & Summary View

### GROUP BY Clause

`GROUP BY <field>` groups results by the specified field. When active, the response includes aggregate values computed automatically based on field types:

- **Numeric fields** → count, sum, average, min, max
- **String fields** → count, distinct count
- **Datetime fields** → count, min (earliest), max (latest)

Example: `FIND voyages WHERE duration > 20 GROUP BY route` returns one row per route with aggregate stats for duration, level, etc.

GROUP BY works for both DB-backed entities (translated to SQL GROUP BY) and live entities (Python `itertools.groupby`). Only direct fields of the queried entity can be used in GROUP BY — not child or parent references.

### Summary View

The Summary/Table toggle in the UI controls the response format:

- **Table mode** (default): Returns individual result rows, paginated at 100 per page.
- **Summary mode**: Returns aggregate statistics for the full result set:
  - Total matching record count
  - Per-numeric-field: sum, average, min, max
  - Per-string-field: distinct value count, top 10 most common values
  - If GROUP BY is active, these aggregates are computed per group

The summary is computed server-side by the Result Formatter, driven by a `view_mode` parameter on the `/reports/run` request (`"table"` or `"summary"`).

## Error Handling & Safety

### Parser Errors
- User-friendly messages with position info: *"Expected operator after 'subs.level' at position 24"*
- Unknown fields suggest close matches: *"Unknown field 'sub.lvl' — did you mean 'subs.level'?"*
- Visual builder shows warning banner when switching from Query tab with invalid text

### Execution Safety
- Result set capped at 1000 rows total (note shown if truncated). Table view paginates at 100 rows per page.
- Query timeout: 10 seconds max execution time
- Read-only by design — parser grammar has no write operations
- Rate limiting: 1 query per second per user, using in-memory tracking (dict of user_id → last_query_timestamp). Simple and sufficient for single-server deployment.

### Edge Cases
- Live entities with no connected plugin data: return empty results with helpful message
- CSV export runs query fresh (not cached)
- Saved reports referencing removed fields: show migration warning when loaded

## Navigation

- New top-level nav item "Reports" alongside Dashboard, Stats, Profits, etc.
- Self-contained filtering — does not inherit from the global tag/region filter system
- Requires login (same auth as other pages)
- Both admin and read-only users can access reports and run queries (read-only operation)
- Saved reports are user-scoped: users can only see, edit, and delete their own saved reports
- The PUT and DELETE endpoints for saved reports verify ownership before modifying

## Scope Boundaries

Explicitly **not** in scope for v1:
- Shared/public saved reports (reports are personal only)
- Chart/graph generation in results (table + summary only)
- Scheduled/automated report runs
- Market price data (only vendor prices available)
- AllaganTools deep inventory integration (only what FleetManager exposes)
