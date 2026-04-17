"""
Smoke tests. Don't require Docker, DB or network — just prove the app boots
and core modules import without errors.
"""
import importlib

import pytest


# ---------------------------------------------------------------- imports


@pytest.mark.parametrize(
    "modname",
    [
        "app",
        "app.middleware.auth_middleware",
        "app.services.permission_service",
        "app.services.docker_service",
        "app.services.database_service",
        "app.services.snapshot_service",
        "app.services.clone_service",
        "app.services.port_service",
        "app.utils.logger",
        "app.utils.debug_logger",
        "app.utils.port_utils",
        "app.utils.port_conflict_resolver",
        "app.utils.database_utils",
        "app.utils.project_utils",
        "app.models.user",
        "app.models.project",
    ],
)
def test_module_imports(modname):
    """Each module must import cleanly."""
    importlib.import_module(modname)


def test_logger_shim_delegates():
    """Historical callers use `create_debug_logger` — must still work."""
    from app.utils.debug_logger import create_debug_logger

    logger = create_debug_logger("smoke-test-project")
    logger.step("smoke step")
    logger.info("smoke info")
    logger.close()


def test_port_utils_shim():
    """port_conflict_resolver re-exports port_utils symbols."""
    from app.utils import port_conflict_resolver, port_utils

    assert port_conflict_resolver.get_used_ports is port_utils.get_used_ports


# ---------------------------------------------------------------- app boot


def test_app_boots(app):
    assert app is not None
    assert "csrf" in app.extensions


def test_csrf_active(app):
    from flask_wtf.csrf import CSRFProtect

    assert isinstance(app.extensions["csrf"], CSRFProtect)


def test_session_cookies_hardened(app):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Strict"
    # SECURE defaults to False for local HTTP; just assert it exists
    assert "SESSION_COOKIE_SECURE" in app.config


# ------------------------------------------------------------- endpoints


def test_login_page_reachable(client):
    """Login page must render without auth."""
    rv = client.get("/login")
    # Could be 200 (form) or 302 (redirect to GitHub OAuth if enforced)
    assert rv.status_code in (200, 302)


def test_index_redirects_when_unauth(client):
    """Dashboard must not be reachable without a session."""
    rv = client.get("/", follow_redirects=False)
    assert rv.status_code in (302, 401, 403)


def test_destructive_route_rejects_unauth(client):
    """Mutating routes must reject unauthenticated requests."""
    rv = client.post("/create_project", data={}, follow_redirects=False)
    # Expect redirect to login (302) or 401/403
    assert rv.status_code in (302, 401, 403, 405)


# ---------------------------------------------------------- auth middleware


def test_auth_middleware_raises_without_extension(app):
    """If user_service is missing, middleware must abort, not silently pass."""
    from unittest.mock import patch

    from app.middleware.auth_middleware import _ensure_auth_configured
    from werkzeug.exceptions import InternalServerError

    with app.test_request_context():
        # Patch extensions to remove user_service
        with patch.dict(app.extensions, clear=True):
            with pytest.raises(InternalServerError):
                _ensure_auth_configured()
