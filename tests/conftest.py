"""
Pytest configuration and shared fixtures.

Ensures the project root is on sys.path so `from app import ...` works
when pytest is invoked from any working directory.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault('SECRET_KEY', 'pytest-secret-key-not-for-production')


@pytest.fixture(scope='session')
def app():
    """Boot a Flask app once per test session."""
    from app import create_app, create_socketio_instance, init_app_services

    app = create_app()
    socketio = create_socketio_instance(app)
    init_app_services(app, socketio)
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
    )
    return app


@pytest.fixture()
def client(app):
    """Flask test client."""
    return app.test_client()
