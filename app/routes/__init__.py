"""
Armada route blueprints
"""
from app.routes.dashboard import dashboard_bp
from app.routes.api import api_bp
from app.routes.auth import auth_bp
from app.routes.stats import stats_bp

__all__ = ['dashboard_bp', 'api_bp', 'auth_bp', 'stats_bp']
