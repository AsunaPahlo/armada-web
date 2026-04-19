# FC Credits Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/credits` page that shows FC credit balance history (aggregate line chart), earnings stats (week/month/all-time), and per-FC include/exclude toggles, with daily snapshots written whenever the plugin sends fleet data.

**Architecture:** New SQLAlchemy model `FCCreditsSnapshot` (one row per FC per day). A `FCCreditsTracker` service upserts snapshots during websocket ingestion and produces a report dict for the page. A new `credits_bp` blueprint serves the HTML skeleton plus an AJAX JSON endpoint and a toggle POST. Front-end is a Chart.js line chart + Bootstrap stat cards + a toggle list, all driven by one JS module.

**Tech Stack:** Flask 3.1.2, Flask-SQLAlchemy (SQLite), Flask-Login, Chart.js (CDN), Bootstrap 5, gevent (background snapshot write inside existing websocket greenlet), pytest for unit tests.

Spec: `docs/superpowers/specs/2026-04-19-fc-credits-tracking-design.md`

---

## File Structure

**New files:**
- `app/models/fc_credits_snapshot.py` — `FCCreditsSnapshot` model
- `app/services/fc_credits_tracker.py` — `FCCreditsTracker` service + pure-function helpers
- `app/routes/credits.py` — `credits_bp` blueprint with `GET /`, `GET /data`, `POST /toggle`
- `app/templates/credits.html` — page skeleton
- `app/static/js/credits.js` — chart + cards + toggle logic
- `tests/test_fc_credits_tracker.py` — unit tests for tracker

**Modified files:**
- `app/models/fc_config.py` — add `excluded_from_credits` column + migration entry + `get_credits_excluded_fc_ids()` helper
- `app/__init__.py` — import new model, register blueprint
- `app/routes/websocket.py` — hook snapshot ingestion into `_process_fleet_data_background`
- `app/templates/base.html` — add "Credits" nav link
- `tests/conftest.py` — add Flask app + in-memory DB fixtures

---

## Task 1: Test Infrastructure

Add pytest fixtures for a Flask app with an in-memory SQLite DB so later tasks can write DB-backed tests.

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Replace conftest.py with app/db fixtures**

```python
"""Pytest configuration — provides Flask app + in-memory DB fixtures."""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-production')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')


@pytest.fixture
def app():
    """Create a Flask app bound to an in-memory SQLite DB, clean per test."""
    from app import create_app, db as _db

    flask_app = create_app()
    flask_app.config['TESTING'] = True
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    flask_app.config['WTF_CSRF_ENABLED'] = False

    with flask_app.app_context():
        _db.drop_all()
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    """Yield the SQLAlchemy db instance bound to the test app."""
    from app import db as _db
    return _db


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
```

- [ ] **Step 2: Run existing tests to confirm nothing broke**

Run: `pytest tests/ -v`
Expected: All existing tests (test_executor, test_lexer, test_parser) still pass. The new fixtures are unused by them but shouldn't break imports.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add Flask app and in-memory DB fixtures for tracker tests"
```

---

## Task 2: FCCreditsSnapshot Model + FCConfig Column

Create the snapshot model and add the `excluded_from_credits` column to the existing `FCConfig` model (with auto-migration).

**Files:**
- Create: `app/models/fc_credits_snapshot.py`
- Modify: `app/models/fc_config.py`
- Modify: `app/__init__.py:99-103` (import block)
- Test: `tests/test_fc_credits_tracker.py`

- [ ] **Step 1: Write failing test for model existence and unique constraint**

Create `tests/test_fc_credits_tracker.py`:

```python
"""Tests for FC credits tracking model + tracker service."""
from datetime import date, datetime, timedelta
import pytest


def test_snapshot_model_upsert_unique_per_fc_per_day(app, db):
    """Two rows for same fc_id+date must violate the unique constraint."""
    from app.models.fc_credits_snapshot import FCCreditsSnapshot

    s1 = FCCreditsSnapshot(
        fc_id="12345", snapshot_date=date(2026, 4, 19),
        credits=1000, updated_at=datetime.utcnow()
    )
    db.session.add(s1)
    db.session.commit()

    s2 = FCCreditsSnapshot(
        fc_id="12345", snapshot_date=date(2026, 4, 19),
        credits=2000, updated_at=datetime.utcnow()
    )
    db.session.add(s2)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_fc_config_excluded_from_credits_column(app, db):
    """FCConfig should expose excluded_from_credits flag defaulting to False."""
    from app.models.fc_config import FCConfig

    cfg = FCConfig(fc_id="99999")
    db.session.add(cfg)
    db.session.commit()

    loaded = FCConfig.query.filter_by(fc_id="99999").first()
    assert loaded.excluded_from_credits is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fc_credits_tracker.py -v`
Expected: FAIL — `ImportError: No module named 'app.models.fc_credits_snapshot'` and `AttributeError: ... 'excluded_from_credits'`.

- [ ] **Step 3: Create the model**

Write `app/models/fc_credits_snapshot.py`:

```python
"""Per-FC daily snapshot of FC credits balance."""
from datetime import datetime
from app import db


class FCCreditsSnapshot(db.Model):
    """One row per FC per day. Latest value seen during the day wins."""
    __tablename__ = 'fc_credits_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    fc_id = db.Column(db.String(64), nullable=False, index=True)
    snapshot_date = db.Column(db.Date, nullable=False, index=True)
    credits = db.Column(db.BigInteger, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('fc_id', 'snapshot_date', name='uq_fc_credits_fc_date'),
    )

    def __repr__(self):
        return f'<FCCreditsSnapshot fc={self.fc_id} date={self.snapshot_date} credits={self.credits}>'
```

- [ ] **Step 4: Add column + migration to FCConfig**

In `app/models/fc_config.py`, add `excluded_from_credits` column after `exclude_from_supply` (around line 15):

```python
    exclude_from_supply = db.Column(db.Boolean, default=False)  # Exclude from restock calculations
    excluded_from_credits = db.Column(db.Boolean, default=False)  # Exclude from /credits page
```

Update `to_dict()` to include it (after the `exclude_from_supply` entry):

```python
            'exclude_from_supply': self.exclude_from_supply,
            'excluded_from_credits': self.excluded_from_credits,
```

Add a migration entry in `_migrate_fc_config_columns()` to the `migrations` list:

```python
    migrations = [
        ('exclude_from_supply', 'BOOLEAN DEFAULT 0'),
        ('target_sub_level', 'INTEGER DEFAULT NULL'),
        ('excluded_from_credits', 'BOOLEAN DEFAULT 0'),
    ]
```

Add a new helper function at the bottom of the file (after `get_supply_excluded_fc_ids`):

```python
def get_credits_excluded_fc_ids() -> set:
    """Get set of FC IDs that are excluded from the /credits page."""
    _migrate_fc_config_columns()
    excluded = FCConfig.query.filter_by(excluded_from_credits=True).all()
    return {c.fc_id for c in excluded}
```

- [ ] **Step 5: Import the new model in create_app**

In `app/__init__.py`, inside the `with app.app_context():` block (after `from app.models import saved_report`), add:

```python
        from app.models import fc_credits_snapshot  # noqa: F401
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_fc_credits_tracker.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Commit**

```bash
git add app/models/fc_credits_snapshot.py app/models/fc_config.py app/__init__.py tests/test_fc_credits_tracker.py
git commit -m "feat: add FCCreditsSnapshot model and FCConfig.excluded_from_credits column"
```

---

## Task 3: Pure-Function Algorithm Helpers

Extract the positive-delta-sum and carry-forward-aggregate algorithms as pure functions. They're the most failure-prone logic, so isolate and test them without DB.

**Files:**
- Create: `app/services/fc_credits_tracker.py` (partial — helpers only)
- Test: `tests/test_fc_credits_tracker.py` (append)

- [ ] **Step 1: Write failing tests for helpers**

Append to `tests/test_fc_credits_tracker.py`:

```python
from datetime import date


def test_positive_delta_sum_ignores_decreases():
    """Positive-delta sum: spending (negative delta) must not subtract from earnings."""
    from app.services.fc_credits_tracker import positive_delta_sum

    snapshots = [
        (date(2026, 4, 10), 1000),
        (date(2026, 4, 11), 1500),  # +500 earned
        (date(2026, 4, 12), 1200),  # -300 spent (ignored)
        (date(2026, 4, 13), 1800),  # +600 earned
    ]
    assert positive_delta_sum(snapshots) == 1100


def test_positive_delta_sum_empty_or_single_point():
    """A single snapshot or empty list returns 0."""
    from app.services.fc_credits_tracker import positive_delta_sum

    assert positive_delta_sum([]) == 0
    assert positive_delta_sum([(date(2026, 4, 10), 500)]) == 0


def test_aggregate_daily_balance_carry_forward():
    """Aggregate across FCs, carrying last known value forward when an FC has no snapshot on a day."""
    from app.services.fc_credits_tracker import aggregate_daily_balance

    per_fc = {
        "fc_a": [(date(2026, 4, 10), 1000), (date(2026, 4, 12), 1500)],
        "fc_b": [(date(2026, 4, 11), 500)],
    }
    result = aggregate_daily_balance(per_fc, date(2026, 4, 10), date(2026, 4, 13))
    # 2026-04-10: fc_a=1000, fc_b=0 (no snapshot yet)  => 1000
    # 2026-04-11: fc_a=1000 (carry), fc_b=500         => 1500
    # 2026-04-12: fc_a=1500, fc_b=500 (carry)         => 2000
    # 2026-04-13: fc_a=1500 (carry), fc_b=500 (carry) => 2000
    assert result == [
        (date(2026, 4, 10), 1000),
        (date(2026, 4, 11), 1500),
        (date(2026, 4, 12), 2000),
        (date(2026, 4, 13), 2000),
    ]


def test_aggregate_daily_balance_no_snapshots():
    """Empty input returns empty list."""
    from app.services.fc_credits_tracker import aggregate_daily_balance

    assert aggregate_daily_balance({}, date(2026, 4, 10), date(2026, 4, 13)) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fc_credits_tracker.py -v`
Expected: FAIL — `ImportError: No module named 'app.services.fc_credits_tracker'` on the new tests.

- [ ] **Step 3: Implement the helpers**

Create `app/services/fc_credits_tracker.py`:

```python
"""FC Credits tracker service: snapshot upsert + report generation."""
from datetime import date, timedelta


def positive_delta_sum(snapshots: list) -> int:
    """Sum of positive deltas between consecutive snapshots.

    Args:
        snapshots: list of (date, credits) tuples, sorted ascending by date.

    Returns:
        Sum of increases (spending decreases are ignored).
    """
    if len(snapshots) < 2:
        return 0
    total = 0
    for i in range(1, len(snapshots)):
        delta = snapshots[i][1] - snapshots[i - 1][1]
        if delta > 0:
            total += delta
    return total


def aggregate_daily_balance(per_fc: dict, start: date, end: date) -> list:
    """Produce one (date, total_balance) tuple per day between start and end inclusive.

    For each day, sum the last-known balance of every FC that has a snapshot on or before that day.
    FCs with no snapshot yet contribute 0.

    Args:
        per_fc: dict mapping fc_id -> list of (date, credits) tuples, sorted ascending.
        start: first date in the output range.
        end: last date in the output range.

    Returns:
        List of (date, total_balance) tuples, one per day in [start, end].
    """
    if not per_fc:
        return []

    # Index snapshots by fc_id for carry-forward lookup
    result = []
    # For each FC, track the index of the "next" snapshot to consider
    indices = {fc_id: 0 for fc_id in per_fc}
    # Last known balance per FC (carry-forward)
    last_known = {fc_id: 0 for fc_id in per_fc}

    current = start
    while current <= end:
        # Advance each FC's pointer while the next snapshot's date <= current
        for fc_id, snaps in per_fc.items():
            idx = indices[fc_id]
            while idx < len(snaps) and snaps[idx][0] <= current:
                last_known[fc_id] = snaps[idx][1]
                idx += 1
            indices[fc_id] = idx
        total = sum(last_known.values())
        result.append((current, total))
        current += timedelta(days=1)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fc_credits_tracker.py -v`
Expected: PASS (all 6 tests now).

- [ ] **Step 5: Commit**

```bash
git add app/services/fc_credits_tracker.py tests/test_fc_credits_tracker.py
git commit -m "feat: add positive_delta_sum and aggregate_daily_balance helpers"
```

---

## Task 4: FCCreditsTracker Class — record_snapshot + get_report

Wire the helpers into a class with DB I/O: upsert snapshots and build the full report dict.

**Files:**
- Modify: `app/services/fc_credits_tracker.py`
- Test: `tests/test_fc_credits_tracker.py` (append)

- [ ] **Step 1: Write failing tests for record_snapshot + get_report**

Append to `tests/test_fc_credits_tracker.py`:

```python
def test_record_snapshot_inserts_new(app, db):
    """First call for (fc_id, today) inserts a new row."""
    from app.services.fc_credits_tracker import FCCreditsTracker
    from app.models.fc_credits_snapshot import FCCreditsSnapshot

    FCCreditsTracker.record_snapshot("fc_1", 5000)
    row = FCCreditsSnapshot.query.filter_by(fc_id="fc_1").first()
    assert row is not None
    assert row.credits == 5000
    assert row.snapshot_date == date.today()


def test_record_snapshot_upserts_same_day(app, db):
    """Second call same day updates the existing row; no duplicate."""
    from app.services.fc_credits_tracker import FCCreditsTracker
    from app.models.fc_credits_snapshot import FCCreditsSnapshot

    FCCreditsTracker.record_snapshot("fc_1", 5000)
    FCCreditsTracker.record_snapshot("fc_1", 7500)
    rows = FCCreditsSnapshot.query.filter_by(fc_id="fc_1").all()
    assert len(rows) == 1
    assert rows[0].credits == 7500


def test_get_report_basic_shape(app, db, monkeypatch):
    """get_report returns the expected dict keys and respects exclusions."""
    from app.services.fc_credits_tracker import FCCreditsTracker
    from app.models.fc_credits_snapshot import FCCreditsSnapshot
    from datetime import datetime

    today = date.today()
    # Two FCs, multiple days
    for fc_id, creds_by_day in [
        ("fc_a", [(today - timedelta(days=2), 1000),
                  (today - timedelta(days=1), 1500),
                  (today, 2000)]),
        ("fc_b", [(today - timedelta(days=2), 500),
                  (today, 800)]),
    ]:
        for d, c in creds_by_day:
            db.session.add(FCCreditsSnapshot(
                fc_id=fc_id, snapshot_date=d, credits=c,
                updated_at=datetime.utcnow()
            ))
    db.session.commit()

    # Stub fc_summaries lookup so FC names resolve
    def fake_fc_info(fc_id):
        return {"fc_a": ("FC Alpha", "Gilgamesh"),
                "fc_b": ("FC Beta", "Gilgamesh")}.get(fc_id, (fc_id, ""))
    monkeypatch.setattr(
        "app.services.fc_credits_tracker._fc_info_lookup",
        fake_fc_info
    )

    # With no exclusions
    report = FCCreditsTracker.get_report(days=7, exclude_fc_ids=set())
    assert set(report.keys()) == {"series", "cards", "included_fcs", "excluded_fcs"}
    assert report["cards"]["current_balance"] == 2800  # 2000 + 800
    assert report["cards"]["all_time_earned"] == 1000 + 500 + 300  # fc_a:(0->1000->1500->2000 = 1000+500+500), but only deltas: 500+500 = 1000; fc_b: 300
    # Recompute expected: fc_a deltas = (1500-1000) + (2000-1500) = 1000
    #                     fc_b deltas = (800-500) = 300
    # total = 1300
    assert report["cards"]["all_time_earned"] == 1300
    assert len(report["included_fcs"]) == 2
    assert len(report["excluded_fcs"]) == 0

    # With fc_b excluded
    report = FCCreditsTracker.get_report(days=7, exclude_fc_ids={"fc_b"})
    assert report["cards"]["current_balance"] == 2000
    assert report["cards"]["all_time_earned"] == 1000
    assert len(report["included_fcs"]) == 1
    assert len(report["excluded_fcs"]) == 1
    assert report["excluded_fcs"][0]["fc_id"] == "fc_b"


def test_get_report_empty(app, db, monkeypatch):
    """With no snapshots, report returns zeros and empty lists."""
    from app.services.fc_credits_tracker import FCCreditsTracker

    monkeypatch.setattr(
        "app.services.fc_credits_tracker._fc_info_lookup",
        lambda fc_id: (fc_id, "")
    )
    report = FCCreditsTracker.get_report(days=30, exclude_fc_ids=set())
    assert report["series"] == []
    assert report["cards"] == {
        "week_earned": 0, "month_earned": 0,
        "all_time_earned": 0, "current_balance": 0
    }
    assert report["included_fcs"] == []
    assert report["excluded_fcs"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fc_credits_tracker.py -v`
Expected: FAIL — `AttributeError: module 'app.services.fc_credits_tracker' has no attribute 'FCCreditsTracker'`.

- [ ] **Step 3: Implement FCCreditsTracker**

Append to `app/services/fc_credits_tracker.py`:

```python
from datetime import datetime


def _fc_info_lookup(fc_id: str) -> tuple:
    """Return (fc_name, world) for an fc_id by looking it up in the live FleetManager.

    Falls back to (fc_id, "") if the FC is not currently in plugin data. Wrapped in a
    function so tests can monkeypatch it without pulling in the FleetManager singleton.
    """
    try:
        from app.services import get_fleet_manager
        fleet = get_fleet_manager()
        data = fleet.get_dashboard_data() or {}
        summaries = data.get('fc_summaries', [])
        # fc_summaries may be a list of dicts or a dict keyed by fc_id depending on caller
        if isinstance(summaries, dict):
            summaries = list(summaries.values())
        for fc in summaries:
            if str(fc.get('fc_id')) == str(fc_id):
                return (fc.get('fc_name', fc_id), fc.get('world', ''))
    except Exception:
        pass
    return (fc_id, "")


class FCCreditsTracker:
    """Service for FC credits snapshots and report generation."""

    @staticmethod
    def record_snapshot(fc_id: str, credits: int) -> None:
        """Upsert today's snapshot for an FC. Latest value wins within a day."""
        from app import db
        from app.models.fc_credits_snapshot import FCCreditsSnapshot

        today = date.today()
        row = FCCreditsSnapshot.query.filter_by(
            fc_id=str(fc_id), snapshot_date=today
        ).first()
        if row:
            row.credits = int(credits)
            row.updated_at = datetime.utcnow()
        else:
            row = FCCreditsSnapshot(
                fc_id=str(fc_id),
                snapshot_date=today,
                credits=int(credits),
                updated_at=datetime.utcnow()
            )
            db.session.add(row)
        db.session.commit()

    @staticmethod
    def get_report(days: int, exclude_fc_ids: set) -> dict:
        """Build the full credits report for the /credits page.

        Args:
            days: number of days for chart window and week/month cards.
                  0 means all history for the chart.
            exclude_fc_ids: set of fc_id strings to exclude from chart + stat cards.

        Returns:
            dict with keys: series, cards, included_fcs, excluded_fcs.
        """
        from app.models.fc_credits_snapshot import FCCreditsSnapshot

        exclude_fc_ids = {str(x) for x in exclude_fc_ids}
        all_rows = FCCreditsSnapshot.query.order_by(
            FCCreditsSnapshot.fc_id, FCCreditsSnapshot.snapshot_date
        ).all()

        # Group by fc_id
        per_fc_all = {}
        for r in all_rows:
            per_fc_all.setdefault(r.fc_id, []).append((r.snapshot_date, r.credits))

        if not per_fc_all:
            return {
                "series": [],
                "cards": {"week_earned": 0, "month_earned": 0,
                          "all_time_earned": 0, "current_balance": 0},
                "included_fcs": [],
                "excluded_fcs": [],
            }

        today = date.today()
        included_fc_ids = [fid for fid in per_fc_all if fid not in exclude_fc_ids]
        excluded_fc_ids_present = [fid for fid in per_fc_all if fid in exclude_fc_ids]

        # Chart series: aggregate over included FCs
        per_fc_included = {fid: per_fc_all[fid] for fid in included_fc_ids}
        if days > 0:
            # Chart window: last N days up to today
            start = today - timedelta(days=days - 1)
        else:
            # All time: from the earliest snapshot date across included FCs
            earliest = min(
                (snaps[0][0] for snaps in per_fc_included.values() if snaps),
                default=today
            )
            start = earliest
        agg = aggregate_daily_balance(per_fc_included, start, today)
        series = [{"date": d.isoformat(), "balance": b} for d, b in agg]

        # Cards (only over included FCs)
        def window_delta_sum(window_days: int) -> int:
            if window_days <= 0:
                # All-time
                return sum(positive_delta_sum(per_fc_included[fid]) for fid in included_fc_ids)
            cutoff = today - timedelta(days=window_days - 1)
            total = 0
            for fid in included_fc_ids:
                snaps = per_fc_included[fid]
                # Include the last snapshot strictly before the cutoff as the "anchor"
                # so the first day's delta reflects earnings relative to the entering balance.
                anchor = None
                in_window = []
                for d, c in snaps:
                    if d < cutoff:
                        anchor = (d, c)
                    else:
                        in_window.append((d, c))
                windowed = ([anchor] if anchor else []) + in_window
                total += positive_delta_sum(windowed)
            return total

        week_earned = window_delta_sum(7)
        month_earned = window_delta_sum(30)
        all_time_earned = sum(positive_delta_sum(per_fc_all[fid]) for fid in included_fc_ids)
        current_balance = sum(
            per_fc_included[fid][-1][1] for fid in included_fc_ids if per_fc_included[fid]
        )

        # FC lists for the toggle UI
        def fc_entry(fc_id, excluded: bool) -> dict:
            name, world = _fc_info_lookup(fc_id)
            snaps = per_fc_all.get(fc_id, [])
            current = snaps[-1][1] if snaps else 0
            return {
                "fc_id": fc_id,
                "fc_name": name,
                "world": world,
                "current_balance": current,
                "excluded": excluded,
            }

        included_fcs = [fc_entry(fid, False) for fid in included_fc_ids]
        excluded_fcs = [fc_entry(fid, True) for fid in excluded_fc_ids_present]

        return {
            "series": series,
            "cards": {
                "week_earned": week_earned,
                "month_earned": month_earned,
                "all_time_earned": all_time_earned,
                "current_balance": current_balance,
            },
            "included_fcs": included_fcs,
            "excluded_fcs": excluded_fcs,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fc_credits_tracker.py -v`
Expected: PASS (all 10 tests now).

- [ ] **Step 5: Commit**

```bash
git add app/services/fc_credits_tracker.py tests/test_fc_credits_tracker.py
git commit -m "feat: add FCCreditsTracker with record_snapshot and get_report"
```

---

## Task 5: Websocket Ingestion Hook

Record a snapshot for every FC in the payload during fleet_data processing. Mirror the `_process_gil_records` pattern.

**Files:**
- Modify: `app/routes/websocket.py`
- Test: `tests/test_fc_credits_tracker.py` (append)

- [ ] **Step 1: Write failing test for the ingestion helper**

Append to `tests/test_fc_credits_tracker.py`:

```python
def test_process_fc_credits_snapshots_from_fc_points(app, db):
    """Ingestion helper reads fc_points from parsed fleet data and writes snapshots."""
    from app.routes.websocket import _process_fc_credits_snapshots
    from app.models.fc_credits_snapshot import FCCreditsSnapshot

    # Fleet data shape: accounts is a list; we look for FC data under the 'fcs' key
    # Plugin payload (lowercase keys) has fcs: { "<fc_id>": { ..., "fc_points": N } }
    accounts = [
        {
            "fcs": {
                "111": {"name": "FC One", "fc_points": 12000},
                "222": {"name": "FC Two", "fc_points": 3400},
            }
        }
    ]
    suppliers = []

    _process_fc_credits_snapshots(accounts, suppliers)

    rows = FCCreditsSnapshot.query.order_by(FCCreditsSnapshot.fc_id).all()
    assert len(rows) == 2
    assert rows[0].fc_id == "111"
    assert rows[0].credits == 12000
    assert rows[1].fc_id == "222"
    assert rows[1].credits == 3400


def test_process_fc_credits_snapshots_supplier_fallback(app, db):
    """If no fc_points in fcs, fall back to supplier fc_credits (max per fc)."""
    from app.routes.websocket import _process_fc_credits_snapshots
    from app.models.fc_credits_snapshot import FCCreditsSnapshot

    accounts = []
    suppliers = [
        {"fc_id": "333", "fc_credits": 500},
        {"fc_id": "333", "fc_credits": 800},  # max wins
        {"fc_id": "444", "fc_credits": 0},     # zero is skipped
    ]

    _process_fc_credits_snapshots(accounts, suppliers)

    rows = FCCreditsSnapshot.query.order_by(FCCreditsSnapshot.fc_id).all()
    assert len(rows) == 1
    assert rows[0].fc_id == "333"
    assert rows[0].credits == 800


def test_process_fc_credits_snapshots_skips_zero_fc_points(app, db):
    """fc_points == 0 should not write a snapshot (likely missing FC access)."""
    from app.routes.websocket import _process_fc_credits_snapshots
    from app.models.fc_credits_snapshot import FCCreditsSnapshot

    accounts = [{"fcs": {"555": {"name": "FC Five", "fc_points": 0}}}]
    _process_fc_credits_snapshots(accounts, [])

    assert FCCreditsSnapshot.query.count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fc_credits_tracker.py -v`
Expected: FAIL — `ImportError: cannot import name '_process_fc_credits_snapshots'`.

- [ ] **Step 3: Add the ingestion helper to websocket.py**

In `app/routes/websocket.py`, after the `_process_gil_records` function (near line 100), add:

```python
def _process_fc_credits_snapshots(accounts, suppliers):
    """Write one FC credits snapshot per FC present in the payload.

    Preference: fc_points inside accounts[*].fcs[fc_id]. Fallback: max fc_credits
    across supplier entries for the same fc_id. Zero values are skipped so a character
    without FC access doesn't overwrite a real balance with 0.
    """
    from app.services.fc_credits_tracker import FCCreditsTracker

    per_fc = {}  # fc_id -> credits (best guess)

    # Pass 1: authoritative fc_points from account FC dicts
    if isinstance(accounts, list):
        for acct in accounts:
            if not isinstance(acct, dict):
                continue
            fcs = acct.get('fcs') or acct.get('FCData') or {}
            if not isinstance(fcs, dict):
                continue
            for fc_id, fc_info in fcs.items():
                if not isinstance(fc_info, dict):
                    continue
                points = fc_info.get('fc_points', fc_info.get('FCPoints', 0))
                try:
                    points = int(points or 0)
                except (TypeError, ValueError):
                    points = 0
                if points > 0:
                    per_fc[str(fc_id)] = points

    # Pass 2: supplier fallback (max per fc_id) — only if no fc_points entry yet
    if isinstance(suppliers, list):
        supplier_maxes = {}
        for s in suppliers:
            if not isinstance(s, dict):
                continue
            fc_id = s.get('fc_id')
            if not fc_id:
                continue
            try:
                creds = int(s.get('fc_credits', 0) or 0)
            except (TypeError, ValueError):
                creds = 0
            if creds <= 0:
                continue
            fc_id = str(fc_id)
            if creds > supplier_maxes.get(fc_id, 0):
                supplier_maxes[fc_id] = creds
        for fc_id, creds in supplier_maxes.items():
            per_fc.setdefault(fc_id, creds)

    for fc_id, credits in per_fc.items():
        try:
            FCCreditsTracker.record_snapshot(fc_id, credits)
        except Exception as e:
            plugin_logger.warning(f"Failed to record FC credits snapshot for {fc_id}: {e}")
```

- [ ] **Step 4: Call the helper from `_process_fleet_data_background`**

In `app/routes/websocket.py`, inside `_process_fleet_data_background` (around line 343), **after** the `_process_gil_records` block, add:

```python
            # Record FC credits snapshots (per FC per day)
            try:
                _process_fc_credits_snapshots(accounts, suppliers)
            except Exception as e:
                plugin_logger.warning(f"Error processing FC credits snapshots: {e}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_fc_credits_tracker.py -v`
Expected: PASS (all 13 tests now).

- [ ] **Step 6: Commit**

```bash
git add app/routes/websocket.py tests/test_fc_credits_tracker.py
git commit -m "feat: record FC credits snapshots on every fleet_data ingestion"
```

---

## Task 6: Flask Blueprint — /credits Routes

Create the blueprint with three endpoints, register it in the factory, and add route tests.

**Files:**
- Create: `app/routes/credits.py`
- Modify: `app/__init__.py` (import + register blueprint)
- Test: `tests/test_fc_credits_tracker.py` (append)

- [ ] **Step 1: Write failing tests for routes**

Append to `tests/test_fc_credits_tracker.py`:

```python
from flask_login import login_user


def _login_test_user(client, app):
    """Seed + log in a test user so @login_required routes are accessible."""
    from app.models.user import User
    from app import db as _db

    with app.app_context():
        if not User.query.filter_by(username="tester").first():
            u = User(username="tester", role="admin")
            u.set_password("testpass")
            _db.session.add(u)
            _db.session.commit()
    return client.post("/auth/login", data={
        "username": "tester", "password": "testpass"
    }, follow_redirects=True)


def test_credits_index_renders(client, app):
    """GET /credits returns 200 with the page skeleton."""
    _login_test_user(client, app)
    resp = client.get("/credits/")
    assert resp.status_code == 200
    assert b"FC Credits" in resp.data


def test_credits_data_returns_json(client, app, db):
    """GET /credits/data returns report JSON with expected keys."""
    _login_test_user(client, app)
    resp = client.get("/credits/data?days=30")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"series", "cards", "included_fcs", "excluded_fcs"}


def test_credits_data_days_param_bounds(client, app, db):
    """Invalid days values should be coerced to a safe default."""
    _login_test_user(client, app)
    resp = client.get("/credits/data?days=abc")
    assert resp.status_code == 200
    resp = client.get("/credits/data?days=-1")
    assert resp.status_code == 200


def test_credits_toggle_upserts_fc_config(client, app, db):
    """POST /credits/toggle flips excluded_from_credits for a given fc_id."""
    from app.models.fc_config import FCConfig
    _login_test_user(client, app)

    resp = client.post("/credits/toggle", json={"fc_id": "fc_x", "excluded": True})
    assert resp.status_code == 200
    cfg = FCConfig.query.filter_by(fc_id="fc_x").first()
    assert cfg is not None
    assert cfg.excluded_from_credits is True

    resp = client.post("/credits/toggle", json={"fc_id": "fc_x", "excluded": False})
    assert resp.status_code == 200
    cfg = FCConfig.query.filter_by(fc_id="fc_x").first()
    assert cfg.excluded_from_credits is False


def test_credits_toggle_bad_payload(client, app):
    """Missing fc_id returns 400."""
    _login_test_user(client, app)
    resp = client.post("/credits/toggle", json={"excluded": True})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fc_credits_tracker.py -v`
Expected: FAIL — `404 Not Found` for `/credits/` because the blueprint isn't registered.

- [ ] **Step 3: Create the blueprint**

Create `app/routes/credits.py`:

```python
"""FC Credits tracking page routes."""
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required

from app import db
from app.decorators import writable_required
from app.models.fc_config import FCConfig, get_credits_excluded_fc_ids
from app.services.fc_credits_tracker import FCCreditsTracker

credits_bp = Blueprint('credits', __name__)

ALLOWED_DAYS = {0, 7, 14, 30, 90, 365}


@credits_bp.route('/')
@login_required
def index():
    """Render the FC credits page skeleton."""
    return render_template('credits.html')


@credits_bp.route('/data')
@login_required
def data():
    """Return the FC credits report as JSON for the chart + cards."""
    try:
        days = int(request.args.get('days', 30))
    except (TypeError, ValueError):
        days = 30
    if days not in ALLOWED_DAYS:
        days = 30

    excluded = get_credits_excluded_fc_ids()
    report = FCCreditsTracker.get_report(days=days, exclude_fc_ids=excluded)
    return jsonify(report)


@credits_bp.route('/toggle', methods=['POST'])
@login_required
@writable_required
def toggle():
    """Toggle excluded_from_credits for a given fc_id.

    Body: {"fc_id": "...", "excluded": true|false}
    """
    payload = request.get_json(silent=True) or {}
    fc_id = payload.get('fc_id')
    excluded = payload.get('excluded')
    if not fc_id or not isinstance(excluded, bool):
        return jsonify({"error": "fc_id (string) and excluded (bool) required"}), 400

    fc_id = str(fc_id)
    cfg = FCConfig.query.filter_by(fc_id=fc_id).first()
    if not cfg:
        cfg = FCConfig(fc_id=fc_id)
        db.session.add(cfg)
    cfg.excluded_from_credits = excluded
    db.session.commit()
    return jsonify({"status": "ok"})
```

- [ ] **Step 4: Register the blueprint in the factory**

In `app/__init__.py`, add the import (near line 70, next to `reports_bp`):

```python
    from app.routes.credits import credits_bp
```

And register it (near line 88, next to the other blueprint registrations):

```python
    app.register_blueprint(credits_bp, url_prefix='/credits')
```

- [ ] **Step 5: Create a minimal template placeholder so `/credits/` returns 200**

Create `app/templates/credits.html` with just enough content to pass the route test (full template comes in Task 7):

```html
{% extends "base.html" %}
{% block title %}FC Credits{% endblock %}
{% block content %}
<h1>FC Credits</h1>
<div id="credits-root"></div>
{% endblock %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_fc_credits_tracker.py -v`
Expected: PASS (all 18 tests now).

- [ ] **Step 7: Commit**

```bash
git add app/routes/credits.py app/__init__.py app/templates/credits.html tests/test_fc_credits_tracker.py
git commit -m "feat: add /credits blueprint with index, data, and toggle routes"
```

---

## Task 7: Template + JS (Stat Cards, Chart, Toggle List)

Build the full UI with Chart.js, Bootstrap cards, a day selector, and a per-FC toggle list.

**Files:**
- Modify: `app/templates/credits.html` (full replacement)
- Create: `app/static/js/credits.js`

- [ ] **Step 1: Replace the credits.html skeleton with the full template**

Overwrite `app/templates/credits.html`:

```html
{% extends "base.html" %}
{% block title %}FC Credits{% endblock %}
{% block content %}
<div class="container-fluid py-4">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <h1 class="h3 mb-0"><i class="bi bi-coin"></i> FC Credits</h1>
    <div class="btn-group" role="group" aria-label="Day range selector" id="credits-day-selector">
      <button type="button" class="btn btn-outline-primary" data-days="7">7d</button>
      <button type="button" class="btn btn-outline-primary" data-days="14">14d</button>
      <button type="button" class="btn btn-outline-primary active" data-days="30">30d</button>
      <button type="button" class="btn btn-outline-primary" data-days="90">90d</button>
      <button type="button" class="btn btn-outline-primary" data-days="365">1y</button>
      <button type="button" class="btn btn-outline-primary" data-days="0">All</button>
    </div>
  </div>

  <div id="credits-empty" class="alert alert-info d-none" role="alert">
    No FC credits data yet &mdash; it'll populate as your plugin sends data.
  </div>

  <div id="credits-content">
    <div class="row g-3 mb-4">
      <div class="col-6 col-lg-3">
        <div class="card h-100"><div class="card-body">
          <div class="text-muted small">This Week Earned</div>
          <div class="h4 mb-0" id="card-week-earned">&mdash;</div>
        </div></div>
      </div>
      <div class="col-6 col-lg-3">
        <div class="card h-100"><div class="card-body">
          <div class="text-muted small">This Month Earned</div>
          <div class="h4 mb-0" id="card-month-earned">&mdash;</div>
        </div></div>
      </div>
      <div class="col-6 col-lg-3">
        <div class="card h-100"><div class="card-body">
          <div class="text-muted small">All-Time Earned</div>
          <div class="h4 mb-0" id="card-alltime-earned">&mdash;</div>
        </div></div>
      </div>
      <div class="col-6 col-lg-3">
        <div class="card h-100"><div class="card-body">
          <div class="text-muted small">Current Balance</div>
          <div class="h4 mb-0" id="card-current-balance">&mdash;</div>
        </div></div>
      </div>
    </div>

    <div class="card mb-4"><div class="card-body">
      <canvas id="credits-chart" height="100"></canvas>
    </div></div>

    <div class="card">
      <div class="card-header">FCs</div>
      <ul class="list-group list-group-flush" id="credits-fc-list"></ul>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="{{ url_for('static', filename='js/credits.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Create the JS module**

Create `app/static/js/credits.js`:

```javascript
(function () {
  'use strict';

  let chart = null;
  let currentDays = 30;

  function fmt(n) {
    if (n == null) return '—';
    return Number(n).toLocaleString();
  }

  function setDayActive(days) {
    document.querySelectorAll('#credits-day-selector button').forEach(b => {
      b.classList.toggle('active', String(b.dataset.days) === String(days));
    });
  }

  function renderCards(cards) {
    document.getElementById('card-week-earned').textContent = fmt(cards.week_earned);
    document.getElementById('card-month-earned').textContent = fmt(cards.month_earned);
    document.getElementById('card-alltime-earned').textContent = fmt(cards.all_time_earned);
    document.getElementById('card-current-balance').textContent = fmt(cards.current_balance);
  }

  function renderChart(series) {
    const canvas = document.getElementById('credits-chart');
    const labels = series.map(p => p.date);
    const data = series.map(p => p.balance);

    if (chart) {
      chart.data.labels = labels;
      chart.data.datasets[0].data = data;
      chart.update();
      return;
    }
    chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: 'Total FC Credits',
          data: data,
          borderColor: '#667eea',
          backgroundColor: 'rgba(102, 126, 234, 0.15)',
          fill: true,
          tension: 0.2,
          pointRadius: 2,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: false, ticks: { callback: v => Number(v).toLocaleString() } } }
      }
    });
  }

  function renderFcList(included, excluded) {
    const ul = document.getElementById('credits-fc-list');
    ul.innerHTML = '';
    const all = included.concat(excluded);
    if (all.length === 0) {
      ul.innerHTML = '<li class="list-group-item text-muted">No FCs yet</li>';
      return;
    }
    all.sort((a, b) => (b.current_balance || 0) - (a.current_balance || 0));
    for (const fc of all) {
      const li = document.createElement('li');
      li.className = 'list-group-item d-flex align-items-center justify-content-between';
      const label = document.createElement('div');
      label.innerHTML = `<strong>${fc.fc_name || fc.fc_id}</strong>`
        + `<span class="text-muted ms-2">${fc.world || ''}</span>`
        + `<span class="badge bg-secondary ms-2">${fmt(fc.current_balance)}</span>`;
      const switchWrap = document.createElement('div');
      switchWrap.className = 'form-check form-switch';
      const input = document.createElement('input');
      input.className = 'form-check-input';
      input.type = 'checkbox';
      input.role = 'switch';
      input.checked = !fc.excluded;  // checked == included
      input.addEventListener('change', () => toggleFc(fc.fc_id, !input.checked));
      switchWrap.appendChild(input);
      li.appendChild(label);
      li.appendChild(switchWrap);
      ul.appendChild(li);
    }
  }

  function showEmpty(isEmpty) {
    document.getElementById('credits-empty').classList.toggle('d-none', !isEmpty);
    document.getElementById('credits-content').classList.toggle('d-none', isEmpty);
  }

  async function loadData(days) {
    currentDays = days;
    setDayActive(days);
    const resp = await fetch(`/credits/data?days=${days}`);
    if (!resp.ok) {
      console.error('Failed to load credits data', resp.status);
      return;
    }
    const body = await resp.json();
    const isEmpty = body.included_fcs.length === 0 && body.excluded_fcs.length === 0;
    showEmpty(isEmpty);
    if (isEmpty) return;
    renderCards(body.cards);
    renderChart(body.series);
    renderFcList(body.included_fcs, body.excluded_fcs);
  }

  async function toggleFc(fcId, excluded) {
    const resp = await fetch('/credits/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fc_id: fcId, excluded: excluded })
    });
    if (!resp.ok) {
      console.error('Toggle failed', resp.status);
      return;
    }
    await loadData(currentDays);
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('#credits-day-selector button').forEach(btn => {
      btn.addEventListener('click', () => {
        const d = parseInt(btn.dataset.days, 10);
        loadData(Number.isFinite(d) ? d : 30);
      });
    });
    loadData(30);
  });
})();
```

- [ ] **Step 3: Run the existing route tests to confirm the template still renders**

Run: `pytest tests/test_fc_credits_tracker.py::test_credits_index_renders -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add app/templates/credits.html app/static/js/credits.js
git commit -m "feat: add credits page template and JS (chart, cards, toggle list)"
```

---

## Task 8: Nav Link + Manual Verification

Add the nav link and confirm the feature end-to-end with a running server.

**Files:**
- Modify: `app/templates/base.html` (add nav item next to "Gil")

- [ ] **Step 1: Find the nav item for Gil in base.html**

Run: `grep -n "gil.index\|/gil" app/templates/base.html`
Note the line number where the "Gil" nav link lives.

- [ ] **Step 2: Add a "Credits" nav item immediately after the Gil nav item**

Open `app/templates/base.html`. Find the `<li class="nav-item">` block containing `url_for('gil.index')` (it renders the "Gil" link). Immediately after its closing `</li>`, insert:

```html
        <li class="nav-item">
          <a class="nav-link {% if request.endpoint and request.endpoint.startswith('credits.') %}active{% endif %}"
             href="{{ url_for('credits.index') }}">
            <i class="bi bi-coin"></i> Credits
          </a>
        </li>
```

If the existing nav uses different classes or a different active-link convention, match it — the block above assumes the same pattern as the Gil link. Check the adjacent Gil `<li>` and mirror its exact class and icon markup.

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass (existing report-engine tests + 18 new credits tests).

- [ ] **Step 4: Start the dev server and manually verify**

Run: `python run.py`

Open `http://localhost:5000/credits` in a browser (log in first). Verify:

1. Page loads with the "FC Credits" heading and day selector (30d active).
2. If no snapshots exist yet, the empty-state alert shows and nothing else.
3. Visit the server with the plugin running — after one fleet_data payload, refresh `/credits`.
4. Stat cards populate, chart shows a line, FC toggle list shows each FC with its current balance and a switch.
5. Click a switch to exclude an FC — list refreshes, that FC moves to "off" state, chart and cards update.
6. Click day selector buttons — chart + cards re-fetch without page reload (watch network tab).
7. Click the "Credits" nav link from other pages — it's highlighted on the credits page.

- [ ] **Step 5: Commit the nav change**

```bash
git add app/templates/base.html
git commit -m "feat: add Credits link to main navigation"
```

- [ ] **Step 6: Final commit summary**

Run: `git log --oneline -8`
Expected: a clean chain of commits, one per task:
- test: add Flask app and in-memory DB fixtures for tracker tests
- feat: add FCCreditsSnapshot model and FCConfig.excluded_from_credits column
- feat: add positive_delta_sum and aggregate_daily_balance helpers
- feat: add FCCreditsTracker with record_snapshot and get_report
- feat: record FC credits snapshots on every fleet_data ingestion
- feat: add /credits blueprint with index, data, and toggle routes
- feat: add credits page template and JS (chart, cards, toggle list)
- feat: add Credits link to main navigation

---

## Self-Review Notes

- **Spec coverage:**
  - Data model (`FCCreditsSnapshot`, `FCConfig.excluded_from_credits`) → Task 2 ✓
  - Ingestion (fc_points + supplier fallback, skip 0, try/except) → Task 5 ✓
  - `record_snapshot` upsert + `get_report` shape → Task 4 ✓
  - Positive-delta algorithm + carry-forward aggregation → Task 3 ✓
  - Three routes with auth decorators → Task 6 ✓
  - UI layout (cards, chart, toggle list, empty state, day selector) → Task 7 ✓
  - AJAX (no URL param for chart refresh) → Task 7 ✓
  - Nav link → Task 8 ✓
  - Tests for tracker + routes → Tasks 3–6 ✓
  - Manual verification → Task 8 ✓

- **Known constraints acknowledged by the plan:**
  - `FCConfig` class name is `FCConfig` (not `FcConfig`); plan uses the real name.
  - The migration column `excluded_from_credits` is added via the existing `_migrate_fc_config_columns` pattern.
  - FC name resolution uses `_fc_info_lookup` with a safe fallback to `fc_id` so the page still works when the FleetManager cache is cold.
