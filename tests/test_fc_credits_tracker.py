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
