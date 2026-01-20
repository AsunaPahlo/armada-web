"""
API Key management routes.
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

from app import db
from app.models.api_key import APIKey
from app.decorators import admin_required

api_keys_bp = Blueprint('api_keys', __name__)


@api_keys_bp.route('/')
@login_required
@admin_required
def index():
    """API key management page."""
    keys = APIKey.query.order_by(APIKey.created_at.desc()).all()
    return render_template('api_keys.html', keys=keys)


@api_keys_bp.route('/create', methods=['POST'])
@login_required
@admin_required
def create_key():
    """Create a new API key."""
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    name = data.get('name', '').strip()

    if not name:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Key name is required'}), 400
        flash('Key name is required', 'error')
        return redirect(url_for('api_keys.index'))

    # Create the API key
    api_key = APIKey.create(name=name, created_by=current_user.username)
    db.session.add(api_key)
    db.session.commit()

    if request.is_json:
        return jsonify({
            'success': True,
            'key': api_key.to_dict(include_key=True)
        })

    # For form submission, flash the key so user can copy it
    flash(f'API key created. Key: {api_key.key}', 'success')
    return redirect(url_for('api_keys.index'))


@api_keys_bp.route('/delete/<int:key_id>', methods=['POST'])
@login_required
@admin_required
def delete_key(key_id):
    """Delete an API key."""
    api_key = APIKey.query.get(key_id)
    if not api_key:
        if request.is_json:
            return jsonify({'success': False, 'message': 'API key not found'}), 404
        flash('API key not found', 'error')
        return redirect(url_for('api_keys.index'))

    name = api_key.name
    db.session.delete(api_key)
    db.session.commit()

    if request.is_json:
        return jsonify({'success': True, 'message': f'API key "{name}" deleted'})

    flash(f'API key "{name}" deleted', 'success')
    return redirect(url_for('api_keys.index'))


@api_keys_bp.route('/list')
@login_required
@admin_required
def list_keys():
    """Get all API keys as JSON (without the actual key values)."""
    keys = APIKey.query.order_by(APIKey.created_at.desc()).all()
    return jsonify([k.to_dict(include_key=False) for k in keys])
