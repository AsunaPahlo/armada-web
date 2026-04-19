"""Tests for FC credits tracking model + tracker service."""
from datetime import date, datetime, timedelta
import pytest
from sqlalchemy.exc import IntegrityError


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
    with pytest.raises(IntegrityError):
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


def test_positive_delta_sum_all_decreases_returns_zero():
    """A strictly decreasing series has no positive deltas, so earnings are 0."""
    from app.services.fc_credits_tracker import positive_delta_sum

    snapshots = [
        (date(2026, 4, 10), 1000),
        (date(2026, 4, 11), 500),
        (date(2026, 4, 12), 100),
    ]
    assert positive_delta_sum(snapshots) == 0


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


def test_aggregate_daily_balance_snapshots_before_window():
    """Snapshots dated before the window start must carry forward to the window's first day."""
    from app.services.fc_credits_tracker import aggregate_daily_balance

    per_fc = {"fc_a": [(date(2026, 4, 1), 100), (date(2026, 4, 5), 200)]}
    result = aggregate_daily_balance(per_fc, date(2026, 4, 10), date(2026, 4, 11))
    assert result == [
        (date(2026, 4, 10), 200),
        (date(2026, 4, 11), 200),
    ]


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
    # fc_a positive deltas: (1500-1000) + (2000-1500) = 1000
    # fc_b positive deltas: (800-500) = 300
    # all_time_earned = 1300
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


def test_get_report_window_includes_pre_cutoff_anchor(app, db, monkeypatch):
    """Earnings on day 1 of the window should reflect delta from the last pre-window snapshot."""
    from app.services.fc_credits_tracker import FCCreditsTracker
    from app.models.fc_credits_snapshot import FCCreditsSnapshot
    from datetime import datetime

    today = date.today()
    # Snapshot 10 days ago at 1000, then today at 1500.
    # week_earned (7-day window) should be 500 — the anchor at today-10
    # gets included so the delta from anchor to today fires.
    db.session.add(FCCreditsSnapshot(
        fc_id="fc_a", snapshot_date=today - timedelta(days=10),
        credits=1000, updated_at=datetime.utcnow()
    ))
    db.session.add(FCCreditsSnapshot(
        fc_id="fc_a", snapshot_date=today,
        credits=1500, updated_at=datetime.utcnow()
    ))
    db.session.commit()
    monkeypatch.setattr(
        "app.services.fc_credits_tracker._fc_info_lookup",
        lambda fid: (fid, "")
    )
    report = FCCreditsTracker.get_report(days=7, exclude_fc_ids=set())
    assert report["cards"]["week_earned"] == 500


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
