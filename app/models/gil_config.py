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
