"""
Access control decorators for role-based permissions.
"""
from functools import wraps

from flask import flash, redirect, url_for, jsonify, request
from flask_login import current_user


def admin_required(f):
    """Decorator that requires admin role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.is_json:
                return jsonify({'success': False, 'message': 'Authentication required'}), 401
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('auth.login'))

        if not current_user.is_admin:
            if request.is_json:
                return jsonify({'success': False, 'message': 'Admin access required'}), 403
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard.index'))

        return f(*args, **kwargs)
    return decorated_function


def writable_required(f):
    """Decorator that blocks readonly users from modifications."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.is_json:
                return jsonify({'success': False, 'message': 'Authentication required'}), 401
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('auth.login'))

        if current_user.is_readonly:
            if request.is_json:
                return jsonify({'success': False, 'message': 'Read-only users cannot perform this action'}), 403
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))

        return f(*args, **kwargs)
    return decorated_function


def api_key_required(f):
    """Decorator that requires a valid API key via Authorization header.

    Expects: Authorization: Bearer <api_key>
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from app.models.api_key import APIKey

        auth_header = request.headers.get('Authorization', '')

        if not auth_header:
            return jsonify({
                'success': False,
                'error': 'Missing Authorization header'
            }), 401

        # Parse Bearer token
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return jsonify({
                'success': False,
                'error': 'Invalid Authorization header format. Expected: Bearer <api_key>'
            }), 401

        api_key = parts[1]

        # Validate the API key
        key_obj = APIKey.validate_key(api_key)
        if not key_obj:
            return jsonify({
                'success': False,
                'error': 'Invalid API key'
            }), 401

        # Store the validated key info in request context for logging/auditing
        request.api_key = key_obj

        return f(*args, **kwargs)
    return decorated_function
