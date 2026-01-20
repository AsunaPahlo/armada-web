"""
API Key model for plugin authentication.
"""
import secrets
from datetime import datetime

from app import db


class APIKey(db.Model):
    """System-wide API key for plugin authentication."""

    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    key = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(80), nullable=True)  # Username who created it
    last_used_at = db.Column(db.DateTime, nullable=True)

    @staticmethod
    def generate_key():
        """Generate a secure random API key."""
        return secrets.token_hex(32)

    @classmethod
    def create(cls, name, created_by=None):
        """Create a new API key with a generated key value."""
        api_key = cls(
            name=name,
            key=cls.generate_key(),
            created_by=created_by
        )
        return api_key

    @classmethod
    def validate_key(cls, key):
        """Validate an API key and return the APIKey object if valid."""
        if not key:
            return None
        api_key = cls.query.filter_by(key=key).first()
        if api_key:
            # Update last used timestamp
            api_key.last_used_at = datetime.utcnow()
            db.session.commit()
        return api_key

    def to_dict(self, include_key=False):
        """Convert to dictionary."""
        data = {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_by': self.created_by,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None
        }
        if include_key:
            data['key'] = self.key
        return data

    def __repr__(self):
        return f'<APIKey {self.name}>'
