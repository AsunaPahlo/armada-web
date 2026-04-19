# Gil Character Exclusion Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow excluding specific characters from gil page totals/chart while still showing them (dimmed) in the table.

**Architecture:** New `GilConfig` model (mirrors `FCConfig` pattern) with a settings partial for toggling exclusions. Gil API filters excluded CIDs from chart/totals but keeps them in the character list with an `excluded` flag. Frontend dims excluded rows and shows eye-slash icon.

**Tech Stack:** Flask, SQLAlchemy, Jinja2, Chart.js, Bootstrap Icons

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `app/models/gil_config.py` | GilConfig model, helpers, migration |
| Create | `app/routes/gil_config.py` | Toggle endpoint blueprint |
| Create | `app/templates/settings/partials/gil_config.html` | Settings UI partial |
| Modify | `app/routes/settings.py:70` | Add partial route for gil-config |
| Modify | `app/__init__.py:62-99` | Register blueprint, import model, call migration |
| Modify | `app/templates/settings/index.html:17-18` | Add sidebar nav item |
| Modify | `app/routes/gil.py:39-170` | Filter excluded CIDs from chart/totals, add cid+excluded to response |
| Modify | `app/templates/gil.html:181-265` | Dim excluded rows, eye-slash icon, filter summary cards |

---

### Task 1: Create GilConfig Model

**Files:**
- Create: `app/models/gil_config.py`

- [ ] **Step 1: Create the model file**

```python
"""Per-character gil configuration settings."""
from datetime import datetime
from app import db


class GilConfig(db.Model):
    """Per-character gil exclusion settings."""
    __tablename__ = 'gil_configs'

    id = db.Column(db.Integer, primary_key=True)
    cid = db.Column(db.String(30), nullable=False, unique=True, index=True)
    excluded_from_gil = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<GilConfig {self.cid}>'

    def to_dict(self):
        return {
            'cid': self.cid,
            'excluded_from_gil': self.excluded_from_gil,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


def _migrate_gil_config_columns():
    """Add any missing columns to the gil_configs table (for existing databases)."""
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)

    if 'gil_configs' not in inspector.get_table_names():
        return

    existing_columns = {col['name'] for col in inspector.get_columns('gil_configs')}

    migrations = [
        # Future columns can be added here
    ]

    for col_name, col_def in migrations:
        if col_name not in existing_columns:
            try:
                db.session.execute(
                    text(f'ALTER TABLE gil_configs ADD COLUMN {col_name} {col_def}')
                )
                db.session.commit()
            except Exception:
                db.session.rollback()


def get_all_gil_configs() -> dict:
    """Get all gil configs as a dict mapping cid -> GilConfig."""
    configs = GilConfig.query.all()
    return {c.cid: c for c in configs}


def get_gil_excluded_cids() -> set:
    """Get set of CIDs excluded from gil totals/chart."""
    excluded = GilConfig.query.filter_by(excluded_from_gil=True).all()
    return {c.cid for c in excluded}


def update_gil_config(cid: str, **kwargs) -> GilConfig:
    """Update configuration for a character (upsert)."""
    cid = str(cid)
    config = GilConfig.query.filter_by(cid=cid).first()
    if not config:
        config = GilConfig(cid=cid)
        db.session.add(config)

    for key, value in kwargs.items():
        if hasattr(config, key) and value is not None:
            setattr(config, key, value)

    config.updated_at = datetime.utcnow()
    db.session.commit()
    return config
```

- [ ] **Step 2: Commit**

```bash
git add app/models/gil_config.py
git commit -m "feat: add GilConfig model for character gil exclusions"
```

---

### Task 2: Create Gil Config Route

**Files:**
- Create: `app/routes/gil_config.py`

- [ ] **Step 1: Create the route file**

```python
"""Gil configuration routes for managing per-character gil exclusions."""
from flask import Blueprint, jsonify, request
from flask_login import login_required

from app.models.gil_config import update_gil_config
from app.decorators import writable_required

gil_config_bp = Blueprint('gil_config', __name__)

ALLOWED_SETTINGS = {'excluded_from_gil'}


@gil_config_bp.route('/toggle', methods=['POST'])
@login_required
@writable_required
def toggle_setting():
    """Toggle a gil configuration setting for a character."""
    data = request.get_json() or request.form

    cid = str(data.get('cid', '')).strip()
    setting = data.get('setting', 'excluded_from_gil').strip()
    value = data.get('value')

    if not cid:
        return jsonify({'success': False, 'message': 'Character ID is required'}), 400

    if setting not in ALLOWED_SETTINGS:
        return jsonify({'success': False, 'message': f'Invalid setting: {setting}'}), 400

    if value is None:
        return jsonify({'success': False, 'message': 'Value is required'}), 400

    if isinstance(value, str):
        value = value.lower() in ('true', '1', 'yes')
    else:
        value = bool(value)

    config = update_gil_config(cid, **{setting: value})

    return jsonify({
        'success': True,
        'config': config.to_dict()
    })
```

- [ ] **Step 2: Commit**

```bash
git add app/routes/gil_config.py
git commit -m "feat: add gil config toggle route"
```

---

### Task 3: Register Blueprint and Model in App Factory

**Files:**
- Modify: `app/__init__.py:62-99`

- [ ] **Step 1: Add blueprint import after line 68 (after `gil_bp` import)**

Add this line after `from app.routes.gil import gil_bp`:
```python
from app.routes.gil_config import gil_config_bp
```

- [ ] **Step 2: Register blueprint after line 84 (after `gil_bp` registration)**

Add this line after `app.register_blueprint(gil_bp, url_prefix='/gil')`:
```python
app.register_blueprint(gil_config_bp, url_prefix='/settings/gil-config')
```

- [ ] **Step 3: Add model import after line 95 (after `gil_record` import)**

Add this line after `from app.models import gil_record  # noqa: F401`:
```python
from app.models import gil_config  # noqa: F401
```

- [ ] **Step 4: Add migration call after line 99 (after `fc_config._migrate_fc_config_columns()`)**

Add this line after `fc_config._migrate_fc_config_columns()`:
```python
gil_config._migrate_gil_config_columns()
```

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py
git commit -m "feat: register gil config blueprint and model"
```

---

### Task 4: Add Settings Partial Route

**Files:**
- Modify: `app/routes/settings.py:70-129`

- [ ] **Step 1: Add partial route after `partial_fc_config` (after line 129)**

Insert after the `partial_fc_config` function:

```python
@settings_bp.route('/partial/gil-config')
@login_required
def partial_gil_config():
    """Gil character exclusion partial."""
    from sqlalchemy import func
    from app.models.gil_record import GilRecord
    from app.models.gil_config import get_all_gil_configs

    gil_configs = get_all_gil_configs()

    # Get latest record per character
    latest = (
        db.session.query(
            GilRecord.cid,
            func.max(GilRecord.record_date).label('max_date')
        )
        .group_by(GilRecord.cid)
        .subquery()
    )

    records = (
        db.session.query(GilRecord)
        .join(latest, db.and_(
            GilRecord.cid == latest.c.cid,
            GilRecord.record_date == latest.c.max_date
        ))
        .order_by(GilRecord.character_name)
        .all()
    )

    characters = []
    for r in records:
        config = gil_configs.get(r.cid)
        characters.append({
            'cid': r.cid,
            'character_name': r.character_name,
            'world': r.world,
            'client_nickname': r.client_nickname,
            'total_gil': r.gil_player + r.gil_retainer,
            'excluded_from_gil': config.excluded_from_gil if config else False,
        })

    return render_template('settings/partials/gil_config.html', characters=characters)
```

- [ ] **Step 2: Commit**

```bash
git add app/routes/settings.py
git commit -m "feat: add gil config settings partial route"
```

---

### Task 5: Add Sidebar Nav Item

**Files:**
- Modify: `app/templates/settings/index.html:17-18`

- [ ] **Step 1: Add nav item after the existing "Exclusions" item (after line 19)**

Insert after the fc-config nav item (line 19, closing `</a>`):
```html
<a href="#" class="settings-nav-item" data-section="gil-config">
    <i class="bi bi-cash-coin"></i> Gil Exclusions
</a>
```

- [ ] **Step 2: Commit**

```bash
git add app/templates/settings/index.html
git commit -m "feat: add gil exclusions to settings sidebar"
```

---

### Task 6: Create Settings Partial Template

**Files:**
- Create: `app/templates/settings/partials/gil_config.html`

- [ ] **Step 1: Create the partial template**

```html
<div class="settings-section-header">
    <h2><i class="bi bi-cash-coin"></i> Gil Exclusions</h2>
</div>

{% if current_user.is_readonly %}
<div class="alert alert-info mb-4">
    <i class="bi bi-info-circle"></i> You have read-only access. Contact an admin to modify exclusions.
</div>
{% endif %}

<div class="row">
    <!-- About Section -->
    <div class="col-lg-3 mb-4">
        <div class="settings-card">
            <div class="settings-card-title">
                <i class="bi bi-info-circle"></i> About Gil Exclusions
            </div>
            <p class="text-muted mb-0">
                <i class="bi bi-eye-slash text-secondary"></i> <strong>Excluded</strong> -
                Excluded characters are removed from the gil chart, total gil, and character count.
                They still appear in the table (dimmed with an <i class="bi bi-eye-slash"></i> icon) so you can see their gil at a glance.
            </p>
        </div>
    </div>

    <!-- Character List Section -->
    <div class="col-lg-9">
        <div class="settings-card" style="padding: 0;">
            <div class="d-flex justify-content-between align-items-center p-3" style="border-bottom: 1px solid var(--ffxiv-border);">
                <div class="settings-card-title mb-0">
                    <i class="bi bi-people"></i> Characters
                </div>
                <div class="input-group" style="max-width: 200px;">
                    <span class="input-group-text"><i class="bi bi-search"></i></span>
                    <input type="text" class="form-control" id="gil-config-search" placeholder="Search...">
                </div>
            </div>
            <div class="table-responsive" style="max-height: 60vh; overflow-y: auto;">
                <table class="table table-dark table-hover mb-0" id="gil-config-table">
                    <thead class="sticky-top" style="background: var(--ffxiv-bg-card);">
                        <tr>
                            <th>Character</th>
                            <th>World</th>
                            <th>Client</th>
                            <th class="text-end">Total Gil</th>
                            <th class="text-center" style="width: 100px;">Included</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for char in characters %}
                        <tr data-cid="{{ char.cid }}" data-name="{{ char.character_name|lower }}" data-world="{{ char.world|lower }}" data-client="{{ char.client_nickname|lower }}">
                            <td><strong>{{ char.character_name }}</strong></td>
                            <td>{{ char.world }}</td>
                            <td>{{ char.client_nickname }}</td>
                            <td class="text-end">{{ "{:,}".format(char.total_gil) }}</td>
                            <td class="text-center">
                                <button type="button"
                                        class="btn btn-link p-0 gil-toggle-btn{% if current_user.is_readonly %} disabled{% endif %}"
                                        data-cid="{{ char.cid }}"
                                        data-setting="excluded_from_gil"
                                        data-value="{{ 'true' if char.excluded_from_gil else 'false' }}"
                                        title="Toggle gil exclusion"
                                        {% if current_user.is_readonly %}disabled{% endif %}>
                                    <i class="bi bi-eye{% if char.excluded_from_gil %}-slash{% endif %} fs-5 {% if not char.excluded_from_gil %}text-info{% else %}text-secondary opacity-50{% endif %}"></i>
                                </button>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>

<style>
.gil-toggle-btn {
    transition: transform 0.1s ease;
}
.gil-toggle-btn:hover:not(.disabled) {
    transform: scale(1.2);
}
.gil-toggle-btn.disabled {
    cursor: not-allowed;
}
#gil-config-table tbody tr.hidden {
    display: none;
}
</style>

<script>
(function() {
    document.querySelectorAll('.gil-toggle-btn').forEach(btn => {
        if (btn.classList.contains('disabled')) return;

        btn.addEventListener('click', async function() {
            const cid = this.dataset.cid;
            const setting = this.dataset.setting;
            const currentValue = this.dataset.value === 'true';
            const newValue = !currentValue;

            const icon = this.querySelector('i');
            const originalClasses = icon.className;

            // Optimistic UI update (inverted: eye = included, eye-slash = excluded)
            if (newValue) {
                icon.classList.remove('bi-eye', 'text-info');
                icon.classList.add('bi-eye-slash', 'text-secondary', 'opacity-50');
            } else {
                icon.classList.remove('bi-eye-slash', 'text-secondary', 'opacity-50');
                icon.classList.add('bi-eye', 'text-info');
            }
            this.dataset.value = newValue.toString();

            try {
                const resp = await fetch('/settings/gil-config/toggle', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({
                        cid: cid,
                        setting: setting,
                        value: newValue
                    })
                });

                const data = await resp.json();

                if (!data.success) {
                    icon.className = originalClasses;
                    this.dataset.value = currentValue.toString();
                    alert(data.message || 'Failed to update setting');
                }
            } catch (err) {
                icon.className = originalClasses;
                this.dataset.value = currentValue.toString();
                console.error('Error updating setting:', err);
                alert('Error updating setting');
            }
        });
    });

    document.getElementById('gil-config-search')?.addEventListener('input', function() {
        const query = this.value.toLowerCase().trim();
        const rows = document.querySelectorAll('#gil-config-table tbody tr');

        rows.forEach(row => {
            const name = row.dataset.name || '';
            const world = row.dataset.world || '';
            const client = row.dataset.client || '';
            if (query === '' || name.includes(query) || world.includes(query) || client.includes(query)) {
                row.classList.remove('hidden');
            } else {
                row.classList.add('hidden');
            }
        });
    });
})();
</script>
```

- [ ] **Step 2: Commit**

```bash
git add app/templates/settings/partials/gil_config.html
git commit -m "feat: add gil exclusion settings partial template"
```

---

### Task 7: Update Gil API to Filter Excluded Characters

**Files:**
- Modify: `app/routes/gil.py:1-175`

- [ ] **Step 1: Add import at top of file (after line 5)**

Add after `from app.models.gil_record import GilRecord`:
```python
from app.models.gil_config import get_gil_excluded_cids
```

- [ ] **Step 2: Get excluded CIDs at start of `api_data()` (after line 29, the `tz_delta` line)**

Add after `tz_delta = timedelta(minutes=-tz_offset)`:
```python
excluded_cids = get_gil_excluded_cids()
```

- [ ] **Step 3: Filter excluded CIDs from chart forward-fill**

In the forward-fill loop (around line 91-97), replace:
```python
for d in dates_in_order:
    scanned = date_char_map[d]
    prev_values.update(scanned)
    daily_total = sum(prev_values.values())
    chart_labels.append(str(d))
    chart_totals.append(daily_total)
    chart_char_counts.append(len(prev_values))
```

With:
```python
for d in dates_in_order:
    scanned = date_char_map[d]
    prev_values.update(scanned)
    included = {cid: total for cid, total in prev_values.items() if cid not in excluded_cids}
    daily_total = sum(included.values())
    chart_labels.append(str(d))
    chart_totals.append(daily_total)
    chart_char_counts.append(len(included))
```

- [ ] **Step 4: Also filter excluded CIDs from pre-cutoff seed values**

In the pre-cutoff seeding (around line 83-84), after:
```python
for row in pre_cutoff:
    prev_values[row.cid] = int(row.total)
```

No change needed here — the filtering happens in the forward-fill loop above.

- [ ] **Step 5: Add `cid` and `excluded` to character response, filter total_gil**

In the character building loop (around lines 150-169), replace:
```python
    characters = []
    total_gil = 0
    for record in current_snapshot:
        current_total = record.gil_player + record.gil_retainer
        total_gil += current_total

        prev = previous_by_cid.get(record.cid)
        delta = current_total - (prev.gil_player + prev.gil_retainer) if prev else 0

        characters.append({
            'character_name': record.character_name,
            'world': record.world,
            'gil_player': record.gil_player,
            'gil_retainer': record.gil_retainer,
            'total': current_total,
            'delta': delta,
            'record_date': str((record.timestamp + tz_delta).date()) if record.timestamp else str(record.record_date),
            'last_updated': record.timestamp.isoformat() if record.timestamp else record.record_date.isoformat(),
            'client_nickname': record.client_nickname,
        })
```

With:
```python
    characters = []
    total_gil = 0
    for record in current_snapshot:
        current_total = record.gil_player + record.gil_retainer
        is_excluded = record.cid in excluded_cids
        if not is_excluded:
            total_gil += current_total

        prev = previous_by_cid.get(record.cid)
        delta = current_total - (prev.gil_player + prev.gil_retainer) if prev else 0

        characters.append({
            'cid': record.cid,
            'character_name': record.character_name,
            'world': record.world,
            'gil_player': record.gil_player,
            'gil_retainer': record.gil_retainer,
            'total': current_total,
            'delta': delta,
            'excluded': is_excluded,
            'record_date': str((record.timestamp + tz_delta).date()) if record.timestamp else str(record.record_date),
            'last_updated': record.timestamp.isoformat() if record.timestamp else record.record_date.isoformat(),
            'client_nickname': record.client_nickname,
        })
```

- [ ] **Step 6: Commit**

```bash
git add app/routes/gil.py
git commit -m "feat: filter excluded characters from gil chart and totals"
```

---

### Task 8: Update Gil Page Frontend

**Files:**
- Modify: `app/templates/gil.html:181-316`

- [ ] **Step 1: Update `loadData` to compute non-excluded character count**

In the `loadData` function (around line 313-316), replace:
```javascript
document.getElementById('total-gil').textContent = formatNumber(data.total_gil);
document.getElementById('char-count').textContent = data.characters.length;
```

With:
```javascript
document.getElementById('total-gil').textContent = formatNumber(data.total_gil);
var includedCount = data.characters.filter(function(c) { return !c.excluded; }).length;
document.getElementById('char-count').textContent = includedCount;
```

- [ ] **Step 2: Update `renderTable` to dim excluded rows and show eye-slash icon**

In the `renderTable` function (around line 250-265), replace:
```javascript
        tbody.innerHTML = characters.map(function(c, i) {
            var deltaClass = c.delta > 0 ? 'text-success' : (c.delta < 0 ? 'text-danger' : 'text-muted');
            var deltaPrefix = c.delta > 0 ? '+' : '';
            var deltaText = c.delta !== 0 ? (deltaPrefix + formatNumber(c.delta)) : '--';
            return '<tr>' +
                '<td>' + (i + 1) + '</td>' +
                '<td><strong>' + c.character_name + '</strong></td>' +
```

With:
```javascript
        tbody.innerHTML = characters.map(function(c, i) {
            var deltaClass = c.delta > 0 ? 'text-success' : (c.delta < 0 ? 'text-danger' : 'text-muted');
            var deltaPrefix = c.delta > 0 ? '+' : '';
            var deltaText = c.delta !== 0 ? (deltaPrefix + formatNumber(c.delta)) : '--';
            var rowStyle = c.excluded ? ' style="opacity: 0.5;"' : '';
            var excludeIcon = c.excluded ? '<i class="bi bi-eye-slash text-secondary me-1" title="Excluded from totals"></i>' : '';
            return '<tr' + rowStyle + '>' +
                '<td>' + (i + 1) + '</td>' +
                '<td>' + excludeIcon + '<strong>' + c.character_name + '</strong></td>' +
```

- [ ] **Step 3: Commit**

```bash
git add app/templates/gil.html
git commit -m "feat: show excluded characters dimmed with eye-slash icon in gil table"
```

---

### Task 9: Verify and Test

- [ ] **Step 1: Start the dev server**

Run: `python run.py`

- [ ] **Step 2: Verify settings page**

Navigate to `/settings#gil-config` — confirm character list loads with toggle buttons.

- [ ] **Step 3: Toggle a character exclusion**

Click the eye icon for a character — confirm it toggles to eye-slash.

- [ ] **Step 4: Verify gil page**

Navigate to `/gil` — confirm:
- Excluded character appears dimmed with eye-slash icon in table
- Total Gil card does not include excluded character's gil
- Character count does not include excluded characters
- Chart does not include excluded character's gil in totals

- [ ] **Step 5: Final commit (if any fixes needed)**
