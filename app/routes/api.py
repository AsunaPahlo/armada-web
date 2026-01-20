"""
REST API routes
"""
from flask import Blueprint, jsonify, current_app
from flask_login import login_required

from app.services import get_fleet_manager
from app.services.stats_tracker import StatsTracker
from app.decorators import writable_required

api_bp = Blueprint('api', __name__)

_stats_tracker: StatsTracker = None


def get_stats_tracker() -> StatsTracker:
    """Get or create the stats tracker instance."""
    global _stats_tracker
    if _stats_tracker is None:
        _stats_tracker = StatsTracker()
    return _stats_tracker


@api_bp.route('/dashboard')
@login_required
def dashboard_data():
    """Get current dashboard data as JSON."""
    fleet = get_fleet_manager()
    return jsonify(fleet.get_dashboard_data())


@api_bp.route('/submarines')
@login_required
def submarines_list():
    """Get all submarines as JSON."""
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()
    return jsonify(data['submarines'])


@api_bp.route('/fc/<int:fc_id>')
@login_required
def fc_data(fc_id: int):
    """Get FC data as JSON."""
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()

    for fc in data['fc_summaries']:
        if fc['fc_id'] == fc_id:
            return jsonify(fc)

    return jsonify({'error': 'FC not found'}), 404


@api_bp.route('/stats/voyages')
@login_required
def voyage_history():
    """Get voyage history."""
    tracker = get_stats_tracker()
    voyages = tracker.get_voyage_history(days=30)
    return jsonify(voyages)


@api_bp.route('/stats/daily')
@login_required
def daily_stats():
    """Get daily statistics."""
    tracker = get_stats_tracker()
    stats = tracker.get_daily_stats(days=30)
    return jsonify(stats)


@api_bp.route('/stats/summary')
@login_required
def summary_stats():
    """Get summary statistics."""
    tracker = get_stats_tracker()
    summary = tracker.calculate_summary_stats(days=30)
    return jsonify(summary)


@api_bp.route('/health')
def health():
    """Health check endpoint (no auth required)."""
    return jsonify({'status': 'ok'})


@api_bp.route('/plugins')
@login_required
def plugin_status():
    """Get status of connected plugins."""
    from app.routes.websocket import get_plugin_status
    return jsonify(get_plugin_status(current_app._get_current_object()))


@api_bp.route('/plugins/<plugin_id>', methods=['DELETE'])
@login_required
@writable_required
def clear_plugin(plugin_id: str):
    """Clear cached data for a specific plugin."""
    from app.routes.websocket import clear_plugin_data as clear_ws_plugin_data

    try:
        fleet = get_fleet_manager()
        fleet.clear_plugin_data(plugin_id)
        clear_ws_plugin_data(plugin_id)
        return jsonify({'success': True, 'message': f'Cleared data for {plugin_id}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
