"""
User management routes.
"""
import secrets
import string

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user

from app import db
from app.models.user import User
from app.decorators import admin_required

users_bp = Blueprint('users', __name__)


def generate_random_password(length=12):
    """Generate a random password."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


@users_bp.route('/')
@login_required
@admin_required
def index():
    """User management page."""
    users = User.query.order_by(User.username).all()
    return render_template('users/index.html', users=users)


@users_bp.route('/create', methods=['POST'])
@login_required
@admin_required
def create_user():
    """Create a new user."""
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    role = data.get('role', User.ROLE_READONLY).strip()

    if not username:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Username is required'}), 400
        flash('Username is required', 'error')
        return redirect(url_for('users.index'))

    if not password:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Password is required'}), 400
        flash('Password is required', 'error')
        return redirect(url_for('users.index'))

    if len(password) < 4:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Password must be at least 4 characters'}), 400
        flash('Password must be at least 4 characters', 'error')
        return redirect(url_for('users.index'))

    # Validate role
    if role not in [User.ROLE_ADMIN, User.ROLE_READONLY]:
        role = User.ROLE_READONLY

    # Check for duplicate username (case-insensitive)
    existing = User.query.filter(User.username.ilike(username)).first()
    if existing:
        if request.is_json:
            return jsonify({'success': False, 'message': f'Username "{username}" already exists'}), 400
        flash(f'Username "{username}" already exists', 'error')
        return redirect(url_for('users.index'))

    user = User(username=username, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    if request.is_json:
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role
            }
        })

    flash(f'User "{username}" created successfully', 'success')
    return redirect(url_for('users.index'))


@users_bp.route('/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """Delete a user."""
    # Cannot delete self
    if user_id == current_user.id:
        if request.is_json:
            return jsonify({'success': False, 'message': 'You cannot delete yourself'}), 400
        flash('You cannot delete yourself', 'error')
        return redirect(url_for('users.index'))

    user = User.query.get(user_id)
    if not user:
        if request.is_json:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        flash('User not found', 'error')
        return redirect(url_for('users.index'))

    username = user.username
    db.session.delete(user)
    db.session.commit()

    if request.is_json:
        return jsonify({'success': True, 'message': f'User "{username}" deleted'})

    flash(f'User "{username}" deleted', 'success')
    return redirect(url_for('users.index'))


@users_bp.route('/change-role/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def change_role(user_id):
    """Change a user's role."""
    # Cannot change own role
    if user_id == current_user.id:
        if request.is_json:
            return jsonify({'success': False, 'message': 'You cannot change your own role'}), 400
        flash('You cannot change your own role', 'error')
        return redirect(url_for('users.index'))

    user = User.query.get(user_id)
    if not user:
        if request.is_json:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        flash('User not found', 'error')
        return redirect(url_for('users.index'))

    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    new_role = data.get('role', '').strip()

    if new_role not in [User.ROLE_ADMIN, User.ROLE_READONLY]:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Invalid role'}), 400
        flash('Invalid role', 'error')
        return redirect(url_for('users.index'))

    user.role = new_role
    db.session.commit()

    if request.is_json:
        return jsonify({
            'success': True,
            'message': f'User "{user.username}" role changed to {new_role}',
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role
            }
        })

    flash(f'User "{user.username}" role changed to {new_role}', 'success')
    return redirect(url_for('users.index'))


@users_bp.route('/change-username/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def change_username(user_id):
    """Change a user's username."""
    user = User.query.get(user_id)
    if not user:
        if request.is_json:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        flash('User not found', 'error')
        return redirect(url_for('users.index'))

    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    new_username = data.get('username', '').strip()

    if not new_username:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Username is required'}), 400
        flash('Username is required', 'error')
        return redirect(url_for('users.index'))

    if len(new_username) > 80:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Username must be 80 characters or less'}), 400
        flash('Username must be 80 characters or less', 'error')
        return redirect(url_for('users.index'))

    # Check for duplicate username (case-insensitive, but allow keeping the same name)
    if new_username.lower() != user.username.lower():
        existing = User.query.filter(User.username.ilike(new_username)).first()
        if existing:
            if request.is_json:
                return jsonify({'success': False, 'message': f'Username "{new_username}" already exists'}), 400
            flash(f'Username "{new_username}" already exists', 'error')
            return redirect(url_for('users.index'))

    old_username = user.username
    user.username = new_username
    db.session.commit()

    if request.is_json:
        return jsonify({
            'success': True,
            'message': f'Username changed from "{old_username}" to "{new_username}"',
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role
            }
        })

    flash(f'Username changed from "{old_username}" to "{new_username}"', 'success')
    return redirect(url_for('users.index'))


@users_bp.route('/reset-password/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def reset_password(user_id):
    """Reset a user's password."""
    user = User.query.get(user_id)
    if not user:
        if request.is_json:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        flash('User not found', 'error')
        return redirect(url_for('users.index'))

    # Check if a new password was provided
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    new_password = data.get('password', '').strip()

    # If no password provided, generate a random one
    if not new_password:
        new_password = generate_random_password()

    if len(new_password) < 4:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Password must be at least 4 characters'}), 400
        flash('Password must be at least 4 characters', 'error')
        return redirect(url_for('users.index'))

    user.set_password(new_password)
    db.session.commit()

    if request.is_json:
        return jsonify({
            'success': True,
            'message': f'Password reset for "{user.username}"',
            'new_password': new_password
        })

    flash(f'Password reset for "{user.username}". New password: {new_password}', 'success')
    return redirect(url_for('users.index'))


@users_bp.route('/unlock/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def unlock_user(user_id):
    """Unlock a user's account."""
    user = User.query.get(user_id)
    if not user:
        if request.is_json:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        flash('User not found', 'error')
        return redirect(url_for('users.index'))

    user.unlock()

    if request.is_json:
        return jsonify({
            'success': True,
            'message': f'Account "{user.username}" has been unlocked'
        })

    flash(f'Account "{user.username}" has been unlocked', 'success')
    return redirect(url_for('users.index'))
