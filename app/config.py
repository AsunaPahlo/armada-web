"""
Flask application configuration
"""
import os
from pathlib import Path


class Config:
    """Base configuration class."""

    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'armada-dev-secret-key-change-in-production'

    # Session cookie security
    SESSION_COOKIE_HTTPONLY = True  # Prevent JavaScript access to session cookie
    SESSION_COOKIE_SAMESITE = 'Lax'  # Prevent CSRF by blocking cross-site cookie sending
    # SESSION_COOKIE_SECURE = True  # Uncomment if using HTTPS (breaks HTTP access)

    # Database
    BASEDIR = Path(__file__).parent.parent
    DATA_DIR = BASEDIR / 'data'
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{DATA_DIR / "armada.db"}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Armada specific
    ACCOUNTS_CONFIG_PATH = DATA_DIR / 'accounts.json'

    # Timer refresh interval (seconds) for background updates
    TIMER_REFRESH_INTERVAL = 30

    # Initial admin user (only used on first run when no users exist)
    ADMIN_USERNAME = os.environ.get('ARMADA_USERNAME') or 'admin'
    ADMIN_PASSWORD = os.environ.get('ARMADA_PASSWORD') or 'armada'
