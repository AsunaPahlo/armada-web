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
    """Main dashboard view - renders skeleton, FC data loaded via AJAX."""
    from app.models.tag import get_all_fc_tags_map

    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()

    # Only pass summary/supply to the template - FC data loaded via /api/fc-summaries
    fc_tags = get_all_fc_tags_map()
    # Collect unique tags for the filter bar
    all_tags = {}
    for tags_list in fc_tags.values():
        for tag in tags_list:
            all_tags[tag['id']] = tag

    return render_template('dashboard.html',
                           data={'summary': data.get('summary', {}),
                                 'supply_forecast': data.get('supply_forecast', {}),
                                 'fc_summaries': [],
                                 'submarines': []},
                           all_tags=list(all_tags.values()))


@dashboard_bp.route('/api/fc-summaries')
@login_required
def api_fc_summaries():
    """API endpoint for paginated FC summaries with sorting and search."""
    from app.models.tag import get_all_fc_tags_map

    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()
    if not data:
        return jsonify({'fc_summaries': [], 'total': 0, 'page': 1, 'pages': 1})

    fc_tags = get_all_fc_tags_map()
    fc_list = data.get('fc_summaries', [])

    # Add tags for search
    for fc in fc_list:
        fc_id = str(fc.get('fc_id', ''))
        tags = fc_tags.get(fc_id, [])
        fc['tags'] = tags
        fc['tag_names'] = ' '.join(t['name'] for t in tags).lower()

    # Tag filter: include_tags=1,3 means show only FCs that have tag 1 OR tag 3
    include_tags_param = request.args.get('include_tags', '', type=str).strip()
    if include_tags_param:
        include_tag_ids = set(include_tags_param.split(','))
        fc_list = [
            fc for fc in fc_list
            if any(str(t.get('id', '')) in include_tag_ids for t in fc.get('tags', []))
        ]

    # Search filter
    search = request.args.get('search', '', type=str).lower().strip()
    if search:
        def fc_matches(fc):
            if search in fc.get('fc_name', '').lower(): return True
            if search in fc.get('world', '').lower(): return True
            if fc.get('unified_character') and search in fc['unified_character'].lower(): return True
            if search in ' '.join(fc.get('accounts', [])).lower(): return True
            if search in fc.get('tag_names', ''): return True
            if search in (fc.get('notes') or '').lower(): return True
            return False
        fc_list = [fc for fc in fc_list if fc_matches(fc)]

    # Sort
    sort_by = request.args.get('sort_by', 'return', type=str)
    sort_dir = request.args.get('sort_dir', 'asc', type=str)
    sort_keys = {
        'fc': lambda x: (x.get('fc_name') or '').lower(),
        'character': lambda x: (x.get('unified_character') or '').lower(),
        'subs': lambda x: x.get('total_subs', 0),
        'ready': lambda x: x.get('ready_subs', 0),
        'mode': lambda x: x.get('mode', ''),
        'return': lambda x: x.get('soonest_return') if x.get('soonest_return') is not None else 9999,
        'gil': lambda x: x.get('gil_per_day', 0),
        'restock': lambda x: x.get('days_until_restock') if x.get('days_until_restock') is not None else 9999,
    }
    key_fn = sort_keys.get(sort_by, sort_keys['return'])
    fc_list = sorted(fc_list, key=key_fn, reverse=(sort_dir == 'desc'))

    # Compute global stats from the full filtered list (before pagination)
    fcs_with_ready = sum(1 for fc in fc_list if fc.get('ready_subs', 0) > 0)
    total_characters = sum(len(fc.get('characters', [])) for fc in fc_list)

    # Paginate
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    total = len(fc_list)

    if per_page == 0:
        paginated = fc_list
        pages = 1
    else:
        per_page = min(max(per_page, 5), 100)
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)
        offset = (page - 1) * per_page
        paginated = fc_list[offset:offset + per_page]

    return jsonify({
        'fc_summaries': paginated,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': pages,
        'summary': data.get('summary'),
        'supply_forecast': data.get('supply_forecast'),
        'fcs_with_ready': fcs_with_ready,
        'total_characters': total_characters,
    })


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

    all_subs = data['submarines']
    total = len(all_subs)

    # Handle "All" option (per_page=0 means show all)
    if per_page == 0:
        per_page = total if total > 0 else 1
        pages = 1
    else:
        per_page = min(max(per_page, 10), 100)
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

    all_subs = data['submarines']

    # Add tags to each submarine for search/display
    for sub in all_subs:
        sub_tags = fc_tags.get(str(sub.get('fc_id', '')), [])
        sub['tags'] = [{'name': t['name'], 'color': t['color']} for t in sub_tags]
        sub['tag_names'] = ' '.join(t['name'] for t in sub_tags).lower()

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

    # Handle "All" option (per_page=0 means show all)
    if per_page == 0:
        per_page = total if total > 0 else 1
        pages = 1
        paginated = all_subs
    else:
        per_page = min(max(per_page, 10), 100)
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
