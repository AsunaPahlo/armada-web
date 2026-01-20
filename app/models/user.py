"""
User model for basic authentication
"""
from datetime import datetime, timedelta

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager


class User(UserMixin, db.Model):
    """Simple user model for authentication."""

    __tablename__ = 'users'

    ROLE_ADMIN = 'admin'
    ROLE_READONLY = 'readonly'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_READONLY)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Lockout fields
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_failed_login = db.Column(db.DateTime, nullable=True)

    @property
    def is_admin(self):
        """Check if user has admin role."""
        return self.role == self.ROLE_ADMIN

    @property
    def is_readonly(self):
        """Check if user has readonly role."""
        return self.role == self.ROLE_READONLY

    def set_password(self, password):
        """Hash and set the user password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check if provided password matches hash."""
        return check_password_hash(self.password_hash, password)

    @property
    def is_locked(self):
        """Check if account is currently locked."""
        if self.locked_until is None:
            return False
        return datetime.utcnow() < self.locked_until

    def record_failed_login(self):
        """Record a failed login attempt. Locks account after 5 failures."""
        self.failed_login_attempts += 1
        self.last_failed_login = datetime.utcnow()
        if self.failed_login_attempts >= 5:
            self.locked_until = datetime.utcnow() + timedelta(minutes=30)
        db.session.commit()

    def record_successful_login(self):
        """Reset failed login counter after successful login."""
        self.failed_login_attempts = 0
        self.locked_until = None
        self.last_failed_login = None
        db.session.commit()

    def unlock(self):
        """Unlock the account and reset failed attempts counter."""
        self.locked_until = None
        self.failed_login_attempts = 0
        self.last_failed_login = None
        db.session.commit()

    def __repr__(self):
        return f'<User {self.username}>'


@login_manager.user_loader
def load_user(user_id):
    """Flask-Login user loader callback."""
    return User.query.get(int(user_id))
