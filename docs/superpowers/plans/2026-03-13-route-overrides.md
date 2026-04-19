# Route Overrides Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a settings section that lets users mark additional routes as "farming" (beyond what's in RouteStats), with optional gil/sub/day values, and surface unrecognized fleet routes as suggestions.

**Architecture:** Store overrides in a dedicated `route_overrides` SQLAlchemy table. Add a new settings partial + sidebar nav item + API endpoints in the existing settings blueprint. Hook overrides into `fleet_manager.py` (leveling detection) and `route_stats_service.py` (gil lookup).

**Tech Stack:** Flask, Jinja2, SQLAlchemy, Bootstrap 5, vanilla JS

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `app/models/route_override.py` | RouteOverride model + helper functions |
| Create | `app/templates/settings/partials/route_overrides.html` | Settings UI partial |
| Modify | `app/routes/settings.py` | Add partial route + API endpoints |
| Modify | `app/templates/settings/index.html:16-17` | Add sidebar nav item |
| Modify | `app/__init__.py:98` | Register model import for table creation |
| Modify | `app/services/fleet_manager.py:506-508` | Union overrides into `known_routes` |
| Modify | `app/services/route_stats_service.py:252-254` | Fallback to override gil values |

---

## Chunk 1: Backend

### Task 1: Create RouteOverride Model

**Files:**
- Create: `app/models/route_override.py`
- Modify: `app/__init__.py:98`

- [ ] **Step 1: Create the model file**

Create `app/models/route_override.py`:

```python
"""
Route override model for user-defined farming routes.
"""
from datetime import datetime
from app import db


class RouteOverride(db.Model):
    """User-defined route overrides that mark routes as farming."""
    __tablename__ = 'route_overrides'

    id = db.Column(db.Integer, primary_key=True)
    route_name = db.Column(db.String(20), nullable=False, unique=True, index=True)
    gil_per_day = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<RouteOverride {self.route_name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'route_name': self.route_name,
            'gil_per_day': self.gil_per_day,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


def get_all_route_overrides():
    """Get all route overrides as a list of RouteOverride objects."""
    return RouteOverride.query.order_by(RouteOverride.route_name).all()


def get_override_route_names():
    """Get set of all override route names for quick lookup."""
    return set(r.route_name for r in RouteOverride.query.all())


def get_override_gil(route_name):
    """
    Get gil/day for a route override.

    Args:
        route_name: Route name to look up

    Returns:
        gil_per_day value or None if not found/not set
    """
    override = RouteOverride.query.filter_by(route_name=route_name).first()
    if override and override.gil_per_day is not None:
        return override.gil_per_day
    return None
```

- [ ] **Step 2: Register the model import in `app/__init__.py`**

In `app/__init__.py`, add after line 98 (`from app.models import gil_config  # noqa: F401`):

```python
        from app.models import route_override  # noqa: F401
```

- [ ] **Step 3: Commit**

```bash
git add app/models/route_override.py app/__init__.py
git commit -m "feat: add RouteOverride model"
```

---

### Task 2: Add Route Overrides API Endpoints

**Files:**
- Modify: `app/routes/settings.py`

- [ ] **Step 1: Add the partial route for route-overrides**

Add after the `partial_alerts` route (after line 190) in `app/routes/settings.py`:

```python
@settings_bp.route('/partial/route-overrides')
@login_required
def partial_route_overrides():
    """Route overrides partial."""
    from app.models.route_override import get_all_route_overrides
    from app.models.lumina import RouteStats
    from app.services import get_fleet_manager

    overrides = get_all_route_overrides()

    # Get known routes from RouteStats + existing overrides
    known_routes = set(r.route_name for r in RouteStats.query.all())
    override_names = set(o.route_name for o in overrides)

    # Get unrecognized routes from live fleet data
    unrecognized = set()
    try:
        fleet = get_fleet_manager()
        accounts = fleet.get_data()
        for account in accounts:
            for char in account.characters:
                for sub in char.submarines:
                    if sub.route_name and sub.route_name not in known_routes and sub.route_name not in override_names:
                        unrecognized.add(sub.route_name)
    except Exception:
        pass

    return render_template(
        'settings/partials/route_overrides.html',
        overrides=overrides,
        unrecognized=sorted(unrecognized),
    )
```

- [ ] **Step 2: Add the API endpoints for add/remove**

Add after the `update_general_settings` route (after line 249) in `app/routes/settings.py`:

```python
@settings_bp.route('/api/route-overrides', methods=['POST'])
@login_required
@writable_required
def add_route_override():
    """Add a route override."""
    import re
    from app.models.route_override import RouteOverride
    from app.models.lumina import RouteStats

    data = request.get_json() or {}
    route = str(data.get('route', '')).strip().upper()

    if not route or not re.match(r'^[A-Z]{1,10}$', route):
        return jsonify({'success': False, 'message': 'Invalid route name. Use 1-10 uppercase letters.'}), 400

    gil_per_day = data.get('gil_per_day')
    if gil_per_day is not None and gil_per_day != '':
        try:
            gil_per_day = int(gil_per_day)
            if gil_per_day < 0:
                return jsonify({'success': False, 'message': 'Gil/day must be positive.'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Gil/day must be a number.'}), 400
    else:
        gil_per_day = None

    # Check if already in RouteStats
    if RouteStats.query.filter_by(route_name=route).first():
        return jsonify({'success': False, 'message': f'Route {route} already exists in the database.'}), 400

    # Check for duplicate override
    if RouteOverride.query.filter_by(route_name=route).first():
        return jsonify({'success': False, 'message': f'Route {route} is already overridden.'}), 400

    override = RouteOverride(route_name=route, gil_per_day=gil_per_day)
    db.session.add(override)
    db.session.commit()

    return jsonify({'success': True})


@settings_bp.route('/api/route-overrides/<route_name>', methods=['DELETE'])
@login_required
@writable_required
def remove_route_override(route_name):
    """Remove a route override."""
    from app.models.route_override import RouteOverride

    route_upper = route_name.strip().upper()
    override = RouteOverride.query.filter_by(route_name=route_upper).first()

    if not override:
        return jsonify({'success': False, 'message': 'Override not found.'}), 404

    db.session.delete(override)
    db.session.commit()

    return jsonify({'success': True})
```

- [ ] **Step 3: Commit**

```bash
git add app/routes/settings.py
git commit -m "feat: add route overrides API endpoints"
```

---

### Task 3: Hook Overrides into Fleet Manager and Route Stats

**Files:**
- Modify: `app/services/fleet_manager.py:506-508`
- Modify: `app/services/route_stats_service.py:252-254`

- [ ] **Step 1: Update fleet_manager.py to include overrides in known_routes**

At `app/services/fleet_manager.py`, replace lines 506-508:

```python
        # Get known production routes from database
        from app.models.lumina import RouteStats
        known_routes = set(r.route_name for r in RouteStats.query.all())
```

With:

```python
        # Get known production routes from database + user overrides
        from app.models.lumina import RouteStats
        from app.models.route_override import get_override_route_names
        known_routes = set(r.route_name for r in RouteStats.query.all())
        known_routes |= get_override_route_names()
```

- [ ] **Step 2: Update route_stats_service.py to fall back to override gil values**

At `app/services/route_stats_service.py`, replace lines 252-254:

```python
    routes = RouteStats.query.filter_by(route_name=route_name).all()
    if not routes:
        return None
```

With:

```python
    routes = RouteStats.query.filter_by(route_name=route_name).all()
    if not routes:
        # Check user-defined route overrides
        from app.models.route_override import get_override_gil
        return get_override_gil(route_name)
```

- [ ] **Step 3: Commit**

```bash
git add app/services/fleet_manager.py app/services/route_stats_service.py
git commit -m "feat: integrate route overrides into leveling detection and gil lookup"
```

---

## Chunk 2: Frontend

### Task 4: Add Sidebar Nav Item

**Files:**
- Modify: `app/templates/settings/index.html:14-18`

- [ ] **Step 1: Add route-overrides nav item between Tags and Exclusions**

In `app/templates/settings/index.html`, after line 15 (the Tags nav item), add:

```html
            <a href="#" class="settings-nav-item" data-section="route-overrides">
                <i class="bi bi-signpost-split"></i> Route Overrides
            </a>
```

- [ ] **Step 2: Commit**

```bash
git add app/templates/settings/index.html
git commit -m "feat: add route overrides sidebar nav item"
```

---

### Task 5: Create Route Overrides Partial Template

**Files:**
- Create: `app/templates/settings/partials/route_overrides.html`

- [ ] **Step 1: Create the partial template**

Create `app/templates/settings/partials/route_overrides.html`:

```html
<div class="settings-section-header">
    <h2><i class="bi bi-signpost-split"></i> Route Overrides</h2>
</div>

{% if current_user.is_readonly %}
<div class="alert alert-info mb-4">
    <i class="bi bi-info-circle"></i> You have read-only access. Contact an admin to modify route overrides.
</div>
{% endif %}

<div class="row">
    <!-- About Section -->
    <div class="col-lg-3 mb-4">
        <div class="settings-card">
            <div class="settings-card-title">
                <i class="bi bi-info-circle"></i> About Route Overrides
            </div>
            <p class="text-muted mb-3">
                Routes in the database are automatically classified as <strong>farming</strong>.
                Use overrides to mark additional routes as farming so submarines on those routes
                are not counted as leveling.
            </p>
            <p class="text-muted mb-0">
                Optionally set an estimated <strong>Gil/Sub/Day</strong> value for each override.
                This will be used in dashboard gil calculations. Leave blank if unknown.
            </p>
        </div>

        {% if unrecognized %}
        <div class="settings-card mt-3">
            <div class="settings-card-title">
                <i class="bi bi-lightbulb"></i> Unrecognized Routes
            </div>
            <p class="text-muted small mb-3">
                These routes are currently used by your fleet but not recognized as farming routes.
                Click to add as an override.
            </p>
            <div class="d-flex flex-wrap gap-2">
                {% for route in unrecognized %}
                <button type="button"
                        class="btn btn-outline-warning btn-sm suggestion-btn"
                        data-route="{{ route }}"
                        {% if current_user.is_readonly %}disabled{% endif %}>
                    <i class="bi bi-plus-circle"></i> {{ route }}
                </button>
                {% endfor %}
            </div>
        </div>
        {% endif %}
    </div>

    <!-- Overrides Management -->
    <div class="col-lg-9">
        <!-- Add Override Form -->
        {% if not current_user.is_readonly %}
        <div class="settings-card">
            <div class="settings-card-title">
                <i class="bi bi-plus-lg"></i> Add Override
            </div>
            <form id="add-override-form" class="d-flex gap-3 align-items-end">
                <div class="settings-form-group mb-0" style="flex: 1; max-width: 200px;">
                    <label for="override-route">Route Name</label>
                    <input type="text" class="form-control" id="override-route"
                           placeholder="e.g. ABCD" maxlength="10"
                           style="text-transform: uppercase;">
                </div>
                <div class="settings-form-group mb-0" style="flex: 1; max-width: 200px;">
                    <label for="override-gil">Gil/Sub/Day <span class="text-muted">(optional)</span></label>
                    <input type="number" class="form-control" id="override-gil"
                           placeholder="e.g. 15000" min="0">
                </div>
                <div>
                    <button type="submit" class="btn btn-primary">
                        <i class="bi bi-plus-lg"></i> Add
                    </button>
                </div>
            </form>
            <div id="override-error" class="text-danger small mt-2" style="display: none;"></div>
        </div>
        {% endif %}

        <!-- Current Overrides Table -->
        <div class="settings-card" style="padding: 0;">
            <div class="d-flex justify-content-between align-items-center p-3" style="border-bottom: 1px solid var(--ffxiv-border);">
                <div class="settings-card-title mb-0">
                    <i class="bi bi-list-check"></i> Current Overrides
                    <span class="badge bg-secondary ms-2">{{ overrides|length }}</span>
                </div>
            </div>
            {% if overrides %}
            <div class="table-responsive">
                <table class="table table-dark table-hover mb-0">
                    <thead>
                        <tr>
                            <th>Route</th>
                            <th>Gil/Sub/Day</th>
                            {% if not current_user.is_readonly %}
                            <th class="text-center" style="width: 80px;">Remove</th>
                            {% endif %}
                        </tr>
                    </thead>
                    <tbody>
                        {% for o in overrides %}
                        <tr>
                            <td><strong>{{ o.route_name }}</strong></td>
                            <td>
                                {% if o.gil_per_day is not none %}
                                    {{ "{:,}".format(o.gil_per_day) }}
                                {% else %}
                                    <span class="text-muted">—</span>
                                {% endif %}
                            </td>
                            {% if not current_user.is_readonly %}
                            <td class="text-center">
                                <button type="button" class="btn btn-link text-danger p-0 remove-override-btn"
                                        data-route="{{ o.route_name }}" title="Remove override">
                                    <i class="bi bi-x-circle fs-5"></i>
                                </button>
                            </td>
                            {% endif %}
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="p-4 text-center text-muted">
                <i class="bi bi-inbox fs-3 d-block mb-2"></i>
                No route overrides configured.
            </div>
            {% endif %}
        </div>
    </div>
</div>

<script>
(function() {
    const form = document.getElementById('add-override-form');
    const errorEl = document.getElementById('override-error');

    async function addOverride(route, gilPerDay) {
        if (errorEl) {
            errorEl.style.display = 'none';
            errorEl.textContent = '';
        }

        try {
            const resp = await fetch('/settings/api/route-overrides', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({
                    route: route,
                    gil_per_day: gilPerDay || null
                })
            });
            const data = await resp.json();

            if (data.success) {
                window.reloadSettingsSection('route-overrides');
            } else {
                if (errorEl) {
                    errorEl.textContent = data.message || 'Failed to add override.';
                    errorEl.style.display = 'block';
                }
            }
        } catch (err) {
            console.error('Error adding override:', err);
            if (errorEl) {
                errorEl.textContent = 'Network error adding override.';
                errorEl.style.display = 'block';
            }
        }
    }

    if (form) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            const route = document.getElementById('override-route').value.trim().toUpperCase();
            const gil = document.getElementById('override-gil').value.trim();
            if (!route) return;
            addOverride(route, gil);
        });
    }

    document.querySelectorAll('.remove-override-btn').forEach(btn => {
        btn.addEventListener('click', async function() {
            const route = this.dataset.route;

            try {
                const resp = await fetch(`/settings/api/route-overrides/${encodeURIComponent(route)}`, {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                });
                const data = await resp.json();

                if (data.success) {
                    window.reloadSettingsSection('route-overrides');
                } else {
                    alert(data.message || 'Failed to remove override.');
                }
            } catch (err) {
                console.error('Error removing override:', err);
                alert('Error removing override.');
            }
        });
    });

    document.querySelectorAll('.suggestion-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const route = this.dataset.route;
            addOverride(route, null);
        });
    });
})();
</script>
```

- [ ] **Step 2: Commit**

```bash
git add app/templates/settings/partials/route_overrides.html
git commit -m "feat: add route overrides settings UI"
```

---

### Task 6: Manual Smoke Test

- [ ] **Step 1: Verify the feature end-to-end**

1. Run `python run.py`
2. Go to Settings page — verify "Route Overrides" appears in sidebar between Tags and Exclusions
3. Click it — verify the partial loads with the add form and empty overrides list
4. If fleet has unrecognized routes, verify suggestion chips appear
5. Add an override with a route name and gil/day — verify it appears in the table
6. Add an override without gil/day — verify it shows "—" for gil
7. Remove an override — verify it disappears
8. Check dashboard — verify overridden routes show as farming (not leveling) and gil values display correctly
9. Try adding a route that already exists in RouteStats — verify error message
10. Try adding a duplicate override — verify error message

- [ ] **Step 2: Commit any fixes if needed**
