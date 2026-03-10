"""Gil configuration routes for managing per-character gil exclusions."""
from flask import Blueprint, jsonify, request
from flask_login import login_required

from app.models.gil_config import update_gil_config
from app.decorators import writable_required

gil_config_bp = Blueprint('gil_config', __name__)

ALLOWED_SETTINGS = {'excluded_from_gil'}


@gil_config_bp.route('/toggle', methods=['POST'])
@login_required
@writable_required
def toggle_setting():
    """Toggle a gil configuration setting for a character."""
    data = request.get_json() or request.form

    cid = str(data.get('cid', '')).strip()
    setting = data.get('setting', 'excluded_from_gil').strip()
    value = data.get('value')

    if not cid:
        return jsonify({'success': False, 'message': 'Character ID is required'}), 400

    if setting not in ALLOWED_SETTINGS:
        return jsonify({'success': False, 'message': f'Invalid setting: {setting}'}), 400

    if value is None:
        return jsonify({'success': False, 'message': 'Value is required'}), 400

    if isinstance(value, str):
        value = value.lower() in ('true', '1', 'yes')
    else:
        value = bool(value)

    config = update_gil_config(cid, **{setting: value})

    return jsonify({
        'success': True,
        'config': config.to_dict()
    })
