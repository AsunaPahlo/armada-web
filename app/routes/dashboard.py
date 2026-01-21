"""
Dashboard routes
"""
from flask import Blueprint, render_template, request, jsonify
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

    # Get pagination params
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(max(per_page, 10), 100)

    all_subs = data['submarines']
    total = len(all_subs)
    pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Initial page of submarines (sorted by time ascending - soonest first)
    sorted_subs = sorted(all_subs, key=lambda x: x.get('hours_remaining', 999))
    offset = (page - 1) * per_page
    paginated_subs = sorted_subs[offset:offset + per_page]

    return render_template('submarines.html',
                           submarines=paginated_subs,
                           all_submarines=all_subs,  # For search
                           summary=data['summary'],
                           fc_tags=fc_tags,
                           pagination={
                               'total': total,
                               'page': page,
                               'per_page': per_page,
                               'pages': pages
                           })


@dashboard_bp.route('/api/submarines')
@login_required
def api_submarines():
    """API endpoint for paginated submarines list."""
    from app.models.tag import get_all_fc_tags_map

    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()
    fc_tags = get_all_fc_tags_map()

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    sort_by = request.args.get('sort_by', 'time', type=str)
    sort_dir = request.args.get('sort_dir', 'asc', type=str)
    search = request.args.get('search', '', type=str).lower().strip()

    per_page = min(max(per_page, 10), 100)

    all_subs = data['submarines']

    # Add tags to each submarine for search/display
    for sub in all_subs:
        sub_tags = fc_tags.get(str(sub.get('fc_id', '')), [])
        sub['tags'] = [{'name': t.name, 'color': t.color} for t in sub_tags]
        sub['tag_names'] = ' '.join(t.name for t in sub_tags).lower()

    # Apply search filter
    if search:
        all_subs = [
            sub for sub in all_subs
            if search in sub.get('name', '').lower()
            or search in sub.get('character', '').lower()
            or search in sub.get('fc_name', '').lower()
            or search in sub.get('world', '').lower()
            or search in sub.get('build', '').lower()
            or search in sub.get('route', '').lower()
            or search in sub.get('tag_names', '')
        ]

    # Sort
    sort_keys = {
        'name': lambda x: (x.get('name') or '').lower(),
        'character': lambda x: (x.get('character') or '').lower(),
        'fc': lambda x: (x.get('fc_name') or '').lower(),
        'build': lambda x: (x.get('build') or '').lower(),
        'route': lambda x: (x.get('route') or '').lower(),
        'level': lambda x: x.get('level', 0),
        'gil': lambda x: x.get('gil_per_day', 0),
        'time': lambda x: x.get('hours_remaining', 999),
    }

    sort_key = sort_keys.get(sort_by, sort_keys['time'])
    reverse = sort_dir == 'desc'
    all_subs = sorted(all_subs, key=sort_key, reverse=reverse)

    # Paginate
    total = len(all_subs)
    pages = (total + per_page - 1) // per_page if total > 0 else 1
    offset = (page - 1) * per_page
    paginated = all_subs[offset:offset + per_page]

    return jsonify({
        'submarines': paginated,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': pages
    })


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
