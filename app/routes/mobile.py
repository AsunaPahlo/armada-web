"""
Mobile PWA routes for Armada.
Provides a native app-like experience for mobile devices.
"""
from flask import Blueprint, render_template, jsonify, redirect, url_for
from flask_login import login_required, current_user

from app import db
from app.services import get_fleet_manager

mobile_bp = Blueprint('mobile', __name__, url_prefix='/m')


@mobile_bp.route('/')
@login_required
def index():
    """Mobile dashboard - main fleet overview."""
    return render_template('mobile/dashboard.html')


@mobile_bp.route('/submarines')
@login_required
def submarines():
    """Mobile submarine list - all submarines."""
    return render_template('mobile/submarines.html')


@mobile_bp.route('/stats')
@login_required
def stats():
    """Mobile statistics view."""
    return render_template('mobile/stats.html')


@mobile_bp.route('/settings')
@login_required
def settings():
    """Mobile settings view."""
    return render_template('mobile/settings.html')


@mobile_bp.route('/offline')
def offline():
    """Offline fallback page."""
    return render_template('mobile/offline.html')


# ============================================================================
# Mobile API Endpoints
# ============================================================================

@mobile_bp.route('/api/fleet')
@login_required
def api_fleet():
    """Get fleet data optimized for mobile."""
    fleet = get_fleet_manager()
    fleet_data = fleet.get_dashboard_data()

    # Get data from the dashboard format
    summary = fleet_data.get('summary', {})
    fc_summaries = fleet_data.get('fc_summaries', [])

    # Transform data for mobile consumption
    fcs = []
    soon_subs = 0

    for fc in fc_summaries:
        fc_subs = []

        for sub in fc.get('submarines', []):
            hours = sub.get('hours_remaining', 999)

            if 0 < hours <= 0.5:
                soon_subs += 1

            fc_subs.append({
                'name': sub.get('name', 'Unknown'),
                'level': sub.get('level', 0),
                'route': sub.get('route', ''),
                'route_name': sub.get('route', ''),
                'hours_remaining': hours,
                'status': sub.get('status', 'unknown'),
                'build': sub.get('build', ''),
            })

        fcs.append({
            'fc_id': fc.get('fc_id', ''),
            'name': fc.get('fc_name', 'Unknown FC'),
            'tag': '',  # Not in fc_summaries
            'world': fc.get('world', ''),
            'submarines': fc_subs,
            'ready_subs': fc.get('ready_subs', 0),
            'soonest_return': fc.get('soonest_return'),
            'ceruleum': fc.get('ceruleum', 0),
            'repair_kits': fc.get('repair_kits', 0),
        })

    return jsonify({
        'total_fcs': summary.get('fc_count', len(fcs)),
        'total_submarines': summary.get('total_subs', 0),
        'ready_submarines': summary.get('ready_subs', 0),
        'soon_submarines': soon_subs,
        'fcs': fcs,
    })


@mobile_bp.route('/api/submarines')
@login_required
def api_submarines():
    """Get all submarines for mobile list view."""
    fleet = get_fleet_manager()
    fleet_data = fleet.get_dashboard_data()

    # Use the pre-sorted submarines list from dashboard data
    all_subs = fleet_data.get('submarines', [])

    submarines = []
    for sub in all_subs:
        submarines.append({
            'name': sub.get('name', 'Unknown'),
            'fc_id': str(sub.get('fc_id', '')),
            'fc_name': sub.get('fc_name', 'Unknown FC'),
            'fc_tag': '',
            'level': sub.get('level', 0),
            'route': sub.get('route', ''),
            'route_name': sub.get('route', ''),
            'hours_remaining': sub.get('hours_remaining', 999),
            'status': sub.get('status', 'unknown'),
            'build': sub.get('build', ''),
        })

    return jsonify({
        'submarines': submarines,
        'total': len(submarines),
    })


@mobile_bp.route('/api/stats')
@login_required
def api_stats():
    """Get stats data for mobile - uses profit tracker for net profit calculations."""
    try:
        days = 30

        # Get profit data (includes material costs)
        from app.services.profit_tracker import profit_tracker
        profit_data = profit_tracker.get_profit_summary(days=days)
        profit_summary = profit_data.get('summary', {})

        # Get hidden FC IDs
        try:
            from app.models.fc_config import get_hidden_fc_ids
            hidden_fc_ids = get_hidden_fc_ids()
        except Exception:
            hidden_fc_ids = set()

        # Get voyage stats using same functions as desktop stats page
        from datetime import datetime, timedelta
        from sqlalchemy import func
        from app.routes.stats import get_voyage_chart_data
        from app.services.stats_tracker import StatsTracker
        from app.models.voyage_loot import VoyageLoot

        # Get total voyages (same as desktop stats page header)
        tracker = StatsTracker()
        voyage_summary = tracker.calculate_summary_stats(days=days)
        total_voyages = voyage_summary['total_voyages']

        # Get total items from loot records
        now = datetime.utcnow()
        cutoff = now - timedelta(days=days)
        items_query = db.session.query(func.sum(VoyageLoot.total_items)).filter(
            VoyageLoot.captured_at >= cutoff
        )
        if hidden_fc_ids:
            items_query = items_query.filter(~VoyageLoot.fc_id.in_(hidden_fc_ids))
        total_items = items_query.scalar() or 0

        # Get top routes (same function as desktop stats page charts)
        chart_data = get_voyage_chart_data(days=days)
        top_routes = chart_data['by_route'][:5]

        # Get fleet data for level distribution and supply info
        fleet = get_fleet_manager()
        fleet_data = fleet.get_dashboard_data()
        summary = fleet_data.get('summary', {})
        fc_summaries = fleet_data.get('fc_summaries', [])

        # Level distribution
        level_dist = {'1-25': 0, '26-50': 0, '51-75': 0, '76-100': 0, '100+': 0}
        for fc in fc_summaries:
            for sub in fc.get('submarines', []):
                level = sub.get('level', 0)
                if level <= 25:
                    level_dist['1-25'] += 1
                elif level <= 50:
                    level_dist['26-50'] += 1
                elif level <= 75:
                    level_dist['51-75'] += 1
                elif level <= 100:
                    level_dist['76-100'] += 1
                else:
                    level_dist['100+'] += 1

        # Supply overview
        supply_urgent = [
            {
                'name': fc.get('fc_name', 'Unknown'),
                'days': fc.get('days_until_restock'),
                'ceruleum': fc.get('ceruleum', 0),
                'kits': fc.get('repair_kits', 0),
            }
            for fc in fc_summaries
            if fc.get('days_until_restock') is not None
        ]
        supply_urgent.sort(key=lambda x: x['days'] if x['days'] is not None else 999)
        supply_urgent = supply_urgent[:5]

        return jsonify({
            'summary': {
                'total_fcs': summary.get('fc_count', 0),
                'total_subs': summary.get('total_subs', 0),
                'total_voyages': total_voyages,
                'returned_voyages': total_voyages,  # Same as total for consistency
                'net_profit': profit_summary.get('total_net_profit', 0),
                'total_items': int(total_items),
                'avg_daily_profit': profit_summary.get('avg_daily_income', 0),
            },
            'top_routes': top_routes,
            'level_distribution': level_dist,
            'supply_urgent': supply_urgent,
            'days': days,
        })

    except Exception as e:
        print(f"[Mobile Stats] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
