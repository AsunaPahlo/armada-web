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
    notes = db.Column(db.Text, nullable=True)  # User notes for this FC
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<FCConfig {self.fc_id}>'

    def to_dict(self):
        return {
            'fc_id': self.fc_id,
            'visible': self.visible,
            'notes': self.notes,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


def get_all_fc_configs() -> dict:
    """
    Get all FC configurations as a dict.

    Returns:
        Dict mapping fc_id -> FCConfig object
    """
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
