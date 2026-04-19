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
