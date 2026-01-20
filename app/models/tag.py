"""
FC Tag models for categorizing Free Companies.
"""
from datetime import datetime
from app import db


class FCTag(db.Model):
    """User-defined tag for categorizing FCs."""
    __tablename__ = 'fc_tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    color = db.Column(db.String(20), default='secondary')  # Bootstrap color name
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to assignments
    assignments = db.relationship('FCTagAssignment', backref='tag', lazy='dynamic',
                                  cascade='all, delete-orphan')

    def __repr__(self):
        return f'<FCTag {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color
        }


class FCTagAssignment(db.Model):
    """Many-to-many: assigns tags to FCs."""
    __tablename__ = 'fc_tag_assignments'

    id = db.Column(db.Integer, primary_key=True)
    fc_id = db.Column(db.String(30), nullable=False, index=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('fc_tags.id', ondelete='CASCADE'),
                       nullable=False, index=True)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('fc_id', 'tag_id', name='unique_fc_tag'),
    )

    def __repr__(self):
        return f'<FCTagAssignment fc={self.fc_id} tag={self.tag_id}>'


def get_all_tags():
    """Get all tags ordered by name."""
    return FCTag.query.order_by(FCTag.name).all()


def get_fc_tags(fc_id: str) -> list:
    """Get all tags assigned to a specific FC."""
    assignments = FCTagAssignment.query.filter_by(fc_id=str(fc_id)).all()
    return [a.tag.to_dict() for a in assignments if a.tag]


def get_all_fc_tags_map() -> dict:
    """Get a mapping of fc_id -> list of tag dicts for all FCs."""
    assignments = FCTagAssignment.query.all()
    fc_tags = {}
    for a in assignments:
        fc_id = a.fc_id
        if fc_id not in fc_tags:
            fc_tags[fc_id] = []
        if a.tag:
            fc_tags[fc_id].append(a.tag.to_dict())
    return fc_tags
