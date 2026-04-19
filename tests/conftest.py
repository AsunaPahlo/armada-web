"""Pytest configuration — provides Flask app + in-memory DB fixtures."""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-production')
os.environ.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')


@pytest.fixture
def app():
    """Create a Flask app bound to an in-memory SQLite DB, clean per test."""
    from app import create_app, db as _db

    flask_app = create_app()
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False

    with flask_app.app_context():
        _db.drop_all()
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    """Yield the SQLAlchemy db instance bound to the test app."""
    from app import db as _db
    return _db


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
