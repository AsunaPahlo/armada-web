"""
REST API v1 - External API endpoints for programmatic access.

All endpoints require API key authentication via Authorization header:
    Authorization: Bearer <api_key>

Designed for external clients like MagicMirror modules, mobile apps, etc.
"""
from flask import Blueprint, jsonify

from app.decorators import api_key_required
from app.services import get_fleet_manager
from app.services.profit_tracker import profit_tracker

api_v1_bp = Blueprint('api_v1', __name__)


@api_v1_bp.route('/dashboard')
@api_key_required
def dashboard():
    """Get full dashboard data including summary, supply forecast, and all submarines.

    Returns:
        JSON with keys: summary, supply_forecast, fc_summaries, submarines
    """
    fleet = get_fleet_manager()
    return jsonify(fleet.get_dashboard_data())


@api_v1_bp.route('/submarines')
@api_key_required
def submarines():
    """Get list of all submarines with their current status.

    Returns:
        JSON array of submarine objects with: name, status, hours_remaining,
        return_time, level, build, route, fc_name, etc.
    """
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()
    return jsonify(data.get('submarines', []))


@api_v1_bp.route('/submarines/ready')
@api_key_required
def submarines_ready():
    """Get only submarines that are ready (returned from voyage).

    Returns:
        JSON array of submarine objects with status='ready'
    """
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()
    ready = [s for s in data.get('submarines', []) if s.get('status') == 'ready']
    return jsonify(ready)


@api_v1_bp.route('/submarines/voyaging')
@api_key_required
def submarines_voyaging():
    """Get only submarines that are currently voyaging.

    Returns:
        JSON array of submarine objects with status='voyaging' or 'returning_soon'
    """
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()
    voyaging = [s for s in data.get('submarines', [])
                if s.get('status') in ('voyaging', 'returning_soon')]
    return jsonify(voyaging)


@api_v1_bp.route('/status')
@api_key_required
def status():
    """Get a quick summary status of the fleet.

    Returns:
        JSON with: total_subs, ready_subs, voyaging_subs, days_until_restock,
        total_gil_per_day, avg_daily_profit, last_updated
    """
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()

    summary = data.get('summary', {})
    supply = data.get('supply_forecast', {})

    # Get avg daily profit directly from profit_tracker to avoid circular dependency
    try:
        profit_data = profit_tracker.get_daily_profits(days=30)
        if profit_data:
            total_profit = sum(d['net_profit'] for d in profit_data)
            avg_daily_profit = int(total_profit / len(profit_data))
        else:
            avg_daily_profit = 0
    except Exception:
        avg_daily_profit = 0

    return jsonify({
        'total_subs': summary.get('total_subs', 0),
        'ready_subs': summary.get('ready_subs', 0),
        'voyaging_subs': summary.get('voyaging_subs', 0),
        'returning_soon_subs': len([s for s in data.get('submarines', [])
                                    if s.get('status') == 'returning_soon']),
        'total_gil_per_day': summary.get('total_gil_per_day', 0),
        'avg_daily_profit': avg_daily_profit,
        'days_until_restock': supply.get('days_until_restock'),
        'limiting_resource': supply.get('limiting_resource'),
        'fc_count': summary.get('fc_count', 0),
        'last_updated': summary.get('last_updated'),
    })


@api_v1_bp.route('/fc')
@api_key_required
def fc_list():
    """Get list of all FCs with their submarine summaries.

    Returns:
        JSON array of FC summary objects
    """
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()
    return jsonify(data.get('fc_summaries', []))


@api_v1_bp.route('/fc/<int:fc_id>')
@api_key_required
def fc_detail(fc_id: int):
    """Get detailed data for a specific FC.

    Args:
        fc_id: The FC ID

    Returns:
        JSON FC summary object or 404 if not found
    """
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()

    for fc in data.get('fc_summaries', []):
        if fc.get('fc_id') == fc_id:
            return jsonify(fc)

    return jsonify({'success': False, 'error': 'FC not found'}), 404


@api_v1_bp.route('/supply')
@api_key_required
def supply_forecast():
    """Get supply forecast data.

    Returns:
        JSON with: total_ceruleum, total_repair_kits, ceruleum_per_day,
        kits_per_day, days_until_restock, limiting_resource, limiting_fc
    """
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()
    return jsonify(data.get('supply_forecast', {}))
