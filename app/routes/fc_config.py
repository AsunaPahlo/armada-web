"""
FC Configuration routes for managing per-FC settings.
"""
from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

from app.models.fc_config import (
    get_all_fc_configs,
    update_fc_config
)
from app.models.fc_housing import get_all_fc_housing
from app.decorators import writable_required

fc_config_bp = Blueprint('fc_config', __name__)

# Settings that can be toggled via the API
ALLOWED_SETTINGS = {'visible', 'exclude_from_supply'}


@fc_config_bp.route('/')
@login_required
def index():
    """FC configuration settings page."""
    from app.services import get_fleet_manager

    # Get all FC configs as a map
    fc_configs = get_all_fc_configs()

    # Get all FC housing data as a map
    fc_housing = get_all_fc_housing()

    # Get FC list from fleet manager (without filtering for this admin view)
    fleet = get_fleet_manager()

    # Get raw data to bypass hidden FC filtering
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
                'sub_count': sub_count,
                'visible': config.visible if config else True,
                'exclude_from_supply': config.exclude_from_supply if config else False,
                'house_address': housing.address if housing else None
            })

    # Sort by FC name
    fcs.sort(key=lambda x: x['fc_name'].lower())

    return render_template('settings/fc_config.html', fcs=fcs)


@fc_config_bp.route('/toggle', methods=['POST'])
@login_required
@writable_required
def toggle_setting():
    """Toggle a configuration setting for an FC."""
    data = request.get_json() or request.form

    fc_id = str(data.get('fc_id', '')).strip()
    setting = data.get('setting', 'visible').strip()
    value = data.get('value')

    if not fc_id:
        return jsonify({'success': False, 'message': 'FC ID is required'}), 400

    if setting not in ALLOWED_SETTINGS:
        return jsonify({'success': False, 'message': f'Invalid setting: {setting}'}), 400

    if value is None:
        return jsonify({'success': False, 'message': 'Value is required'}), 400

    # Convert value to boolean
    if isinstance(value, str):
        value = value.lower() in ('true', '1', 'yes')
    else:
        value = bool(value)

    # Update the specified setting
    config = update_fc_config(fc_id, **{setting: value})

    return jsonify({
        'success': True,
        'config': config.to_dict()
    })


@fc_config_bp.route('/all')
@login_required
def get_all_configs():
    """Get all FC configurations."""
    configs = get_all_fc_configs()
    return jsonify({fc_id: c.to_dict() for fc_id, c in configs.items()})
