"""
Dashboard routes
"""
from flask import Blueprint, render_template
from flask_login import login_required

from app.services import get_fleet_manager

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    """Main dashboard view."""
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()
    return render_template('dashboard.html', data=data)


@dashboard_bp.route('/submarines')
@login_required
def submarines():
    """All submarines list view."""
    from app.models.tag import get_all_fc_tags_map
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()
    fc_tags = get_all_fc_tags_map()
    return render_template('submarines.html', submarines=data['submarines'], summary=data['summary'], fc_tags=fc_tags)


@dashboard_bp.route('/status')
@login_required
def status():
    """Plugin and system status view."""
    from flask import current_app
    from app.routes.websocket import get_plugin_status
    plugins = get_plugin_status(current_app._get_current_object())
    fleet = get_fleet_manager()
    file_accounts = fleet.parser.get_file_accounts_info()
    return render_template('status.html', plugins=plugins, file_accounts=file_accounts)
