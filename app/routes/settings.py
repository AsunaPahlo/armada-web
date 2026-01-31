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
