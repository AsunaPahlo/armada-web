"""
Authentication routes
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.models.user import User

auth_bp = Blueprint('auth', __name__)


def ensure_admin_exists():
    """Create default admin user if none exists."""
    if User.query.count() == 0:
        admin = User(
            username=current_app.config['ADMIN_USERNAME'],
            role=User.ROLE_ADMIN
        )
        admin.set_password(current_app.config['ADMIN_PASSWORD'])
        db.session.add(admin)
        db.session.commit()


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    # Ensure admin user exists
    ensure_admin_exists()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter(User.username.ilike(username)).first()

        if user:
            # Check if account is locked
            if user.is_locked:
                flash('Account is locked. Please try again later.', 'error')
            elif user.check_password(password):
                user.record_successful_login()
                login_user(user, remember=True)
                next_page = request.args.get('next')
                return redirect(next_page or url_for('dashboard.index'))
            else:
                user.record_failed_login()
                flash('Invalid username or password', 'error')
        else:
            flash('Invalid username or password', 'error')

    # Check if default credentials are still in use (show hint only if unchanged)
    show_default_hint = False
    default_username = current_app.config['ADMIN_USERNAME']
    default_password = current_app.config['ADMIN_PASSWORD']
    default_user = User.query.filter(User.username.ilike(default_username)).first()
    if default_user and default_user.check_password(default_password):
        show_default_hint = True

    return render_template('auth/login.html', show_default_hint=show_default_hint)


@auth_bp.route('/logout')
@login_required
def logout():
    """Handle user logout."""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Handle password change."""
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not current_user.check_password(current_password):
            flash('Current password is incorrect', 'error')
        elif new_password != confirm_password:
            flash('New passwords do not match', 'error')
        elif len(new_password) < 8:
            flash('Password must be at least 8 characters', 'error')
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash('Password changed successfully', 'success')
            return redirect(url_for('dashboard.index'))

    return render_template('auth/change_password.html')
