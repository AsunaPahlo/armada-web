"""
Route override model for user-defined farming routes.
"""
from datetime import datetime
from app import db


class RouteOverride(db.Model):
    """User-defined route overrides that mark routes as farming."""
    __tablename__ = 'route_overrides'

    id = db.Column(db.Integer, primary_key=True)
    route_name = db.Column(db.String(20), nullable=False, unique=True, index=True)
    gil_per_day = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<RouteOverride {self.route_name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'route_name': self.route_name,
            'gil_per_day': self.gil_per_day,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


def get_all_route_overrides():
    """Get all route overrides as a list of RouteOverride objects."""
    return RouteOverride.query.order_by(RouteOverride.route_name).all()


def get_override_route_names():
    """Get set of all override route names for quick lookup."""
    return set(r.route_name for r in RouteOverride.query.all())


def get_override_gil(route_name):
    """
    Get gil/day for a route override.

    Args:
        route_name: Route name to look up

    Returns:
        gil_per_day value or None if not found/not set
    """
    override = RouteOverride.query.filter_by(route_name=route_name).first()
    if override and override.gil_per_day is not None:
        return override.gil_per_day
    return None
