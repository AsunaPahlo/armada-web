"""
Activity log for tracking changes to submarines, sectors, routes, and parts.
"""
from datetime import datetime
from app import db


class ActivityLog(db.Model):
    """Log of submarine/FC activity changes."""

    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    fc_id = db.Column(db.String(30), nullable=False, index=True)
    fc_name = db.Column(db.String(100), nullable=True)

    activity_type = db.Column(db.String(50), nullable=False, index=True)
    submarine_name = db.Column(db.String(100), nullable=True)
    character_name = db.Column(db.String(100), nullable=True)

    old_value = db.Column(db.String(500), nullable=True)
    new_value = db.Column(db.String(500), nullable=True)
    details = db.Column(db.Text, nullable=True)  # JSON for extra context

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.Index('idx_activity_fc_created', 'fc_id', 'created_at'),
        db.Index('idx_activity_type_created', 'activity_type', 'created_at'),
    )

    # Activity type constants
    TYPE_BUILD_CHANGE = 'build_change'
    TYPE_LEVEL_UP = 'level_up'
    TYPE_ROUTE_CHANGE = 'route_change'
    TYPE_SECTOR_UNLOCK = 'sector_unlock'
    TYPE_SUBMARINE_ADDED = 'submarine_added'
    TYPE_SUBMARINE_REMOVED = 'submarine_removed'

    @classmethod
    def log_activity(cls, fc_id: str, activity_type: str, fc_name: str = None,
                     submarine_name: str = None, character_name: str = None,
                     old_value: str = None, new_value: str = None, details: str = None):
        """
        Create a new activity log entry.

        Args:
            fc_id: FC identifier
            activity_type: Type of activity (use TYPE_* constants)
            fc_name: Optional FC name
            submarine_name: Optional submarine name
            character_name: Optional character name
            old_value: Previous value (for changes)
            new_value: New value (for changes)
            details: JSON string for extra context
        """
        log = cls(
            fc_id=str(fc_id),
            fc_name=fc_name,
            activity_type=activity_type,
            submarine_name=submarine_name,
            character_name=character_name,
            old_value=old_value,
            new_value=new_value,
            details=details
        )
        db.session.add(log)
        return log

    @classmethod
    def get_fc_activity(cls, fc_id: str, page: int = 1, per_page: int = 25,
                        activity_types: list = None):
        """
        Get paginated activity logs for an FC.

        Args:
            fc_id: FC identifier
            page: Page number (1-indexed)
            per_page: Items per page
            activity_types: Optional list of activity types to filter

        Returns:
            Pagination object with activity logs
        """
        query = cls.query.filter_by(fc_id=str(fc_id))

        if activity_types:
            query = query.filter(cls.activity_type.in_(activity_types))

        query = query.order_by(cls.created_at.desc())
        return query.paginate(page=page, per_page=per_page, error_out=False)

    @classmethod
    def get_recent_activity(cls, limit: int = 50, fc_ids: list = None,
                            activity_types: list = None):
        """
        Get recent activity across all or specified FCs.

        Args:
            limit: Maximum number of entries to return
            fc_ids: Optional list of FC IDs to filter
            activity_types: Optional list of activity types to filter

        Returns:
            List of ActivityLog entries
        """
        query = cls.query

        if fc_ids:
            query = query.filter(cls.fc_id.in_([str(fid) for fid in fc_ids]))

        if activity_types:
            query = query.filter(cls.activity_type.in_(activity_types))

        query = query.order_by(cls.created_at.desc()).limit(limit)
        return query.all()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'fc_id': self.fc_id,
            'fc_name': self.fc_name,
            'activity_type': self.activity_type,
            'submarine_name': self.submarine_name,
            'character_name': self.character_name,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'details': self.details,
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None
        }

    def __repr__(self):
        return f'<ActivityLog {self.id} {self.activity_type} fc={self.fc_id}>'
