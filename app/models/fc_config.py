"""
Per-FC configuration settings model.
"""
from datetime import datetime
from app import db


class FCConfig(db.Model):
    """Per-FC configuration settings."""
    __tablename__ = 'fc_configs'

    id = db.Column(db.Integer, primary_key=True)
    fc_id = db.Column(db.String(30), nullable=False, unique=True, index=True)
    visible = db.Column(db.Boolean, default=True)
    exclude_from_supply = db.Column(db.Boolean, default=False)  # Exclude from restock calculations
    notes = db.Column(db.Text, nullable=True)  # User notes for this FC
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<FCConfig {self.fc_id}>'

    def to_dict(self):
        return {
            'fc_id': self.fc_id,
            'visible': self.visible,
            'exclude_from_supply': self.exclude_from_supply,
            'notes': self.notes,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


def _migrate_fc_config_columns():
    """Add any missing columns to the fc_configs table (for existing databases)."""
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)

    if 'fc_configs' not in inspector.get_table_names():
        return  # Table doesn't exist yet, will be created

    existing_columns = {col['name'] for col in inspector.get_columns('fc_configs')}

    migrations = [
        ('exclude_from_supply', 'BOOLEAN DEFAULT 0'),
    ]

    for col_name, col_def in migrations:
        if col_name not in existing_columns:
            try:
                db.session.execute(
                    text(f'ALTER TABLE fc_configs ADD COLUMN {col_name} {col_def}')
                )
                db.session.commit()
            except Exception:
                db.session.rollback()


def get_all_fc_configs() -> dict:
    """
    Get all FC configurations as a dict.

    Returns:
        Dict mapping fc_id -> FCConfig object
    """
    _migrate_fc_config_columns()
    configs = FCConfig.query.all()
    return {c.fc_id: c for c in configs}


def get_all_fc_notes() -> dict:
    """
    Get all FC notes as a dict.

    Returns:
        Dict mapping fc_id -> notes string (or None if no notes)
    """
    configs = FCConfig.query.filter(FCConfig.notes.isnot(None)).all()
    return {c.fc_id: c.notes for c in configs}


def get_hidden_fc_ids() -> set:
    """
    Get set of FC IDs that are marked as hidden.
    Hidden FCs are excluded from all views and stats.

    Returns:
        Set of fc_id strings that have visible=False
    """
    hidden = FCConfig.query.filter_by(visible=False).all()
    return {c.fc_id for c in hidden}


def get_supply_excluded_fc_ids() -> set:
    """
    Get set of FC IDs that are excluded from supply/restock calculations.

    Returns:
        Set of fc_id strings that have exclude_from_supply=True
    """
    excluded = FCConfig.query.filter_by(exclude_from_supply=True).all()
    return {c.fc_id for c in excluded}


def update_fc_config(fc_id: str, **kwargs) -> FCConfig:
    """
    Update configuration for an FC.

    Args:
        fc_id: The FC identifier
        **kwargs: Configuration fields to update (visible, etc.)

    Returns:
        Updated FCConfig object
    """
    fc_id = str(fc_id)
    config = FCConfig.query.filter_by(fc_id=fc_id).first()
    if not config:
        config = FCConfig(fc_id=fc_id)
        db.session.add(config)

    # Update any provided fields
    for key, value in kwargs.items():
        if hasattr(config, key):
            # Allow None for notes (to clear), but not for other fields
            if value is not None or key == 'notes':
                setattr(config, key, value)

    config.updated_at = datetime.utcnow()
    db.session.commit()
    return config
