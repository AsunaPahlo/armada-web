"""
Unified Settings page routes.
Provides a single settings page with AJAX-loaded sections.
"""
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user

from app import db
from app.decorators import writable_required, admin_required

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/')
@login_required
def index():
    """Main settings page with sidebar navigation."""
    return render_template('settings/index.html')


# =============================================================================
# AJAX Partial Endpoints - return HTML fragments for each section
# =============================================================================

@settings_bp.route('/partial/general')
@login_required
def partial_general():
    """General app settings partial."""
    from app.models.app_settings import AppSettings
    settings = AppSettings.get_all()
    return render_template('settings/partials/general.html', settings=settings)


@settings_bp.route('/partial/tags')
@login_required
def partial_tags():
    """Tags management partial."""
    from app.services import get_fleet_manager
    from app.models.tag import get_all_tags, get_all_fc_tags_map

    tags = get_all_tags()
    fc_tags_map = get_all_fc_tags_map()

    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()

    fcs = []
    for fc in data.get('fc_summaries', []):
        fc_id = str(fc.get('fc_id', ''))
        chars = fc.get('characters', [])
        char_name = chars[0].get('name', '') if chars else ''
        char_world = chars[0].get('world', '') if chars else ''
        accounts = fc.get('accounts', [])
        client_nickname = accounts[0] if accounts else ''

        fcs.append({
            'fc_id': fc_id,
            'fc_name': fc.get('fc_name', 'Unknown'),
            'character': char_name,
            'world': char_world,
            'client_nickname': client_nickname,
            'tags': fc_tags_map.get(fc_id, [])
        })

    fcs.sort(key=lambda x: x['fc_name'].lower())

    return render_template('settings/partials/tags.html', tags=tags, fcs=fcs)


@settings_bp.route('/partial/fc-config')
@login_required
def partial_fc_config():
    """FC Configuration partial."""
    from app.services import get_fleet_manager
    from app.models.fc_config import get_all_fc_configs
    from app.models.fc_housing import get_all_fc_housing

    # Get all FC configs as a map
    fc_configs = get_all_fc_configs()
    fc_housing = get_all_fc_housing()

    # Get FC list from fleet manager (without filtering for this admin view)
    fleet = get_fleet_manager()
    accounts = fleet.get_data(force_refresh=True)

    # Build FC list with character info
    fcs = []
    seen_fc_ids = set()

    for account in accounts:
        for char in account.characters:
            fc_id = char.fc_id
            fc_id_str = str(fc_id) if fc_id else 'unknown'

            if fc_id_str in seen_fc_ids:
                continue
            seen_fc_ids.add(fc_id_str)

            fc_info = account.fc_data.get(fc_id)
            fc_name = fc_info.name if fc_info and fc_info.name else f"FC-{fc_id}"

            # Get config for this FC (defaults to visible=True)
            config = fc_configs.get(fc_id_str)

            # Get housing for this FC
            housing = fc_housing.get(fc_id_str)

            # Count submarines for this FC
            sub_count = 0
            for acc in accounts:
                for c in acc.characters:
                    if str(c.fc_id) == fc_id_str:
                        sub_count += len(c.submarines)

            fcs.append({
                'fc_id': fc_id_str,
                'fc_name': fc_name,
                'character': char.name,
                'world': char.world,
                'client_nickname': account.nickname,
                'sub_count': sub_count,
                'visible': config.visible if config else True,
                'exclude_from_supply': config.exclude_from_supply if config else False,
                'house_address': housing.address if housing else None
            })

    fcs.sort(key=lambda x: x['fc_name'].lower())

    return render_template('settings/partials/fc_config.html', fcs=fcs)


@settings_bp.route('/partial/gil-config')
@login_required
def partial_gil_config():
    """Gil character exclusion partial."""
    from sqlalchemy import func
    from app.models.gil_record import GilRecord
    from app.models.gil_config import get_all_gil_configs

    gil_configs = get_all_gil_configs()

    # Get latest record per character
    latest = (
        db.session.query(
            GilRecord.cid,
            func.max(GilRecord.record_date).label('max_date')
        )
        .group_by(GilRecord.cid)
        .subquery()
    )

    records = (
        db.session.query(GilRecord)
        .join(latest, db.and_(
            GilRecord.cid == latest.c.cid,
            GilRecord.record_date == latest.c.max_date
        ))
        .order_by(GilRecord.character_name)
        .all()
    )

    characters = []
    for r in records:
        config = gil_configs.get(r.cid)
        characters.append({
            'cid': r.cid,
            'character_name': r.character_name,
            'world': r.world,
            'client_nickname': r.client_nickname,
            'total_gil': r.gil_player + r.gil_retainer,
            'excluded_from_gil': config.excluded_from_gil if config else False,
        })

    return render_template('settings/partials/gil_config.html', characters=characters)


@settings_bp.route('/partial/alerts')
@login_required
def partial_alerts():
    """Alert settings partial."""
    from app.models.alert import AlertSettings, AlertHistory

    settings = AlertSettings.get_settings()

    # Get recent alert history
    recent_alerts = AlertHistory.query.order_by(
        AlertHistory.created_at.desc()
    ).limit(50).all()

    return render_template('settings/partials/alerts.html', settings=settings, recent_alerts=recent_alerts)


@settings_bp.route('/partial/route-overrides')
@login_required
def partial_route_overrides():
    """Route overrides partial."""
    from app.models.route_override import get_all_route_overrides
    from app.models.lumina import RouteStats
    from app.services import get_fleet_manager

    overrides = get_all_route_overrides()

    # Get known routes from RouteStats + existing overrides
    known_routes = set(r.route_name for r in RouteStats.query.all())
    override_names = set(o.route_name for o in overrides)

    # Get unrecognized routes from live fleet data
    unrecognized = set()
    try:
        fleet = get_fleet_manager()
        accounts = fleet.get_data()
        for account in accounts:
            for char in account.characters:
                for sub in char.submarines:
                    if sub.route_name and sub.route_name not in known_routes and sub.route_name not in override_names:
                        unrecognized.add(sub.route_name)
    except Exception:
        pass

    return render_template(
        'settings/partials/route_overrides.html',
        overrides=overrides,
        unrecognized=sorted(unrecognized),
    )


@settings_bp.route('/partial/export')
@login_required
def partial_export():
    """Export data partial."""
    return render_template('settings/partials/export.html')


@settings_bp.route('/partial/api-keys')
@login_required
@admin_required
def partial_api_keys():
    """API Keys management partial (admin only)."""
    from app.models.api_key import APIKey

    keys = APIKey.query.order_by(APIKey.created_at.desc()).all()

    return render_template('settings/partials/api_keys.html', keys=keys)


@settings_bp.route('/partial/users')
@login_required
@admin_required
def partial_users():
    """User management partial (admin only)."""
    from app.models.user import User

    users = User.query.order_by(User.username).all()

    return render_template('settings/partials/users.html', users=users)


# =============================================================================
# API Endpoints for settings updates
# =============================================================================

@settings_bp.route('/api/general', methods=['POST'])
@login_required
@admin_required
def update_general_settings():
    """Update general app settings."""
    from app.models.app_settings import AppSettings

    data = request.get_json() or {}

    # Update scheduler settings
    if 'rebuild_window_start' in data:
        AppSettings.set('rebuild_window_start', int(data['rebuild_window_start']))
    if 'rebuild_window_end' in data:
        AppSettings.set('rebuild_window_end', int(data['rebuild_window_end']))

    # Update material costs
    if 'ceruleum_price_per_stack' in data:
        AppSettings.set('ceruleum_price_per_stack', int(data['ceruleum_price_per_stack']))
    if 'repair_kit_price_per_stack' in data:
        AppSettings.set('repair_kit_price_per_stack', int(data['repair_kit_price_per_stack']))

    return jsonify({'success': True})


@settings_bp.route('/api/route-overrides', methods=['POST'])
@login_required
@writable_required
def add_route_override():
    """Add a route override."""
    import re
    from app.models.route_override import RouteOverride
    from app.models.lumina import RouteStats

    data = request.get_json() or {}
    route = str(data.get('route', '')).strip().upper()

    if not route or not re.match(r'^[A-Z]{1,10}$', route):
        return jsonify({'success': False, 'message': 'Invalid route name. Use 1-10 uppercase letters.'}), 400

    gil_per_day = data.get('gil_per_day')
    if gil_per_day is not None and gil_per_day != '':
        try:
            gil_per_day = int(gil_per_day)
            if gil_per_day < 0:
                return jsonify({'success': False, 'message': 'Gil/day must be positive.'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Gil/day must be a number.'}), 400
    else:
        gil_per_day = None

    # Check if already in RouteStats
    if RouteStats.query.filter_by(route_name=route).first():
        return jsonify({'success': False, 'message': f'Route {route} already exists in the database.'}), 400

    # Check for duplicate override
    if RouteOverride.query.filter_by(route_name=route).first():
        return jsonify({'success': False, 'message': f'Route {route} is already overridden.'}), 400

    override = RouteOverride(route_name=route, gil_per_day=gil_per_day)
    db.session.add(override)
    db.session.commit()

    return jsonify({'success': True})


@settings_bp.route('/api/route-overrides/<route_name>', methods=['DELETE'])
@login_required
@writable_required
def remove_route_override(route_name):
    """Remove a route override."""
    from app.models.route_override import RouteOverride

    route_upper = route_name.strip().upper()
    override = RouteOverride.query.filter_by(route_name=route_upper).first()

    if not override:
        return jsonify({'success': False, 'message': 'Override not found.'}), 404

    db.session.delete(override)
    db.session.commit()

    return jsonify({'success': True})


@settings_bp.route('/api/update-lumina', methods=['POST'])
@login_required
@admin_required
def update_lumina_data():
    """Manually trigger Lumina game data update."""
    from app.services.lumina_service import lumina_service

    is_ajax = request.headers.get('Content-Type') == 'application/json' or request.is_json

    try:
        results = lumina_service.update_all(force=True)
        total_updated = sum(r.get('count', 0) for r in results.values() if isinstance(r, dict))

        if is_ajax:
            return jsonify({
                'success': True,
                'message': f'Lumina data updated. {total_updated} total records.',
                'results': results
            })
    except Exception as e:
        import traceback
        traceback.print_exc()

        if is_ajax:
            return jsonify({'success': False, 'message': f'Error updating Lumina data: {e}'}), 500

    return jsonify({'success': False, 'message': 'Unknown error'}), 500


@settings_bp.route('/api/plugin-data', methods=['GET'])
@login_required
@admin_required
def list_plugin_data():
    """List all plugin data entries with summary info."""
    from app.services import get_fleet_manager
    from app.routes.websocket import get_connected_plugins

    fleet = get_fleet_manager()
    connected = set(get_connected_plugins())
    metadata = fleet.get_plugin_metadata()

    entries = []
    with fleet._lock:
        for plugin_id, accounts_data in fleet._plugin_data_raw.items():
            meta = metadata.get(plugin_id, {})

            # Count characters and submarines
            char_count = 0
            sub_count = 0
            fc_ids = set()
            for account in accounts_data:
                for char in account.get('characters', []):
                    char_count += 1
                    sub_count += len(char.get('submarines', []))
                    fc_id = char.get('fc_id', 0)
                    if fc_id and fc_id != 0:
                        fc_ids.add(str(fc_id))

            entries.append({
                'plugin_id': plugin_id,
                'connected': plugin_id in connected,
                'received_at': meta.get('received_at'),
                'account_count': len(accounts_data),
                'character_count': char_count,
                'submarine_count': sub_count,
                'fc_count': len(fc_ids),
            })

    return jsonify({'entries': entries})


@settings_bp.route('/api/plugin-data/<plugin_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_plugin_data(plugin_id):
    """Delete a specific plugin data entry."""
    from app.services import get_fleet_manager

    fleet = get_fleet_manager()

    if plugin_id not in fleet._plugin_data_raw:
        return jsonify({'success': False, 'message': 'Plugin data not found'}), 404

    fleet.clear_plugin_data(plugin_id)

    return jsonify({'success': True, 'message': f'Cleared data for "{plugin_id}"'})
