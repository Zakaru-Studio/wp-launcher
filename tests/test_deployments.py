"""
Smoke tests for the Deployments feature.

Exercises the pieces that don't need a live SSH server:
  - Fernet encrypt/decrypt round-trip for a sample private key
  - ServerService CRUD against a tmp SQLite file
  - DeploymentService permission gating (admin vs developer)
  - /deployments page renders and API routes enforce CSRF + auth
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import ssh_service
from app.services.deployment_service import DeploymentService
from app.services.server_service import ServerService


# Sample key — a minimal Ed25519 PEM just for round-trip validation.
# Not a real secret; paramiko isn't asked to load it here.
_SAMPLE_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    "QyNTUxOQAAACB7X9g1X7Z4n2kC8xQhPnJ9qA4y5m7LdW4zQhZAAAAAAAAAAAAAAA==\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)


# ─── Fernet round-trip ───


def test_fernet_roundtrip_restores_pem():
    secret = "test-secret-key-for-unit-tests-only-long-enough"
    enc = ssh_service.encrypt_private_key(secret, _SAMPLE_KEY)
    assert isinstance(enc, bytes) and enc != _SAMPLE_KEY.encode()
    dec = ssh_service.decrypt_private_key(secret, enc)
    assert dec == _SAMPLE_KEY


def test_fernet_rejects_non_pem_input():
    with pytest.raises(ValueError):
        ssh_service.encrypt_private_key("secret", "not a pem")


def test_fernet_decrypt_fails_when_secret_changes():
    enc = ssh_service.encrypt_private_key("secret-A", _SAMPLE_KEY)
    with pytest.raises(RuntimeError):
        ssh_service.decrypt_private_key("secret-B", enc)


def test_redact_private_keys_masks_pem():
    blob = "before\n" + _SAMPLE_KEY + "\nafter"
    redacted = ssh_service.redact_private_keys(blob)
    assert "PRIVATE KEY" not in redacted
    assert "REDACTED_PRIVATE_KEY" in redacted


# ─── ServerService CRUD ───


@pytest.fixture()
def tmp_server_service(tmp_path: Path) -> ServerService:
    db = tmp_path / "deployments.db"
    return ServerService(db_path=str(db))


def test_server_service_create_and_list(tmp_server_service):
    s = tmp_server_service.create(
        label="acme-prod",
        env="production",
        hostname="deploy.example.com",
        ssh_user="deploy",
        ssh_private_key_enc=b"fakeblob",
        deploy_base_path="/var/www",
    )
    assert s.id is not None and s.label == "acme-prod"
    assert tmp_server_service.get_by_id(s.id).label == "acme-prod"
    assert tmp_server_service.list_servers()[0].label == "acme-prod"


def test_server_service_rejects_duplicate_label(tmp_server_service):
    kw = dict(
        label="dup",
        env="staging",
        hostname="h",
        ssh_user="u",
        ssh_private_key_enc=b"x",
        deploy_base_path="/p",
    )
    tmp_server_service.create(**kw)
    with pytest.raises(ValueError):
        tmp_server_service.create(**kw)


def test_server_service_rejects_invalid_env(tmp_server_service):
    with pytest.raises(ValueError):
        tmp_server_service.create(
            label="x",
            env="preprod",   # not in {staging, production}
            hostname="h",
            ssh_user="u",
            ssh_private_key_enc=b"x",
            deploy_base_path="/p",
        )


def test_server_service_update_and_delete(tmp_server_service):
    s = tmp_server_service.create(
        label="s1", env="staging", hostname="h1",
        ssh_user="u", ssh_private_key_enc=b"x", deploy_base_path="/p",
    )
    updated = tmp_server_service.update(s.id, hostname="h2", host_fingerprint="SHA256:abc")
    assert updated.hostname == "h2"
    assert updated.host_fingerprint == "SHA256:abc"
    assert tmp_server_service.delete(s.id) is True
    assert tmp_server_service.get_by_id(s.id) is None


# ─── to_public_dict hides the private key ───


def test_server_to_public_dict_hides_key(tmp_server_service):
    s = tmp_server_service.create(
        label="hidden", env="staging", hostname="h",
        ssh_user="u", ssh_private_key_enc=b"secret-bytes", deploy_base_path="/p",
    )
    public = s.to_public_dict()
    assert public["has_private_key"] is True
    assert "ssh_private_key_enc" not in public
    # and SSHes into every JSON field, not just the flag
    assert "private_key" not in public


# ─── DeploymentService permission + branch validation ───


@pytest.fixture()
def tmp_deployment_service(tmp_path: Path, tmp_server_service) -> DeploymentService:
    return DeploymentService(
        db_path=str(tmp_path / "deployments.db"),
        log_dir=str(tmp_path / "logs"),
        server_service=tmp_server_service,
        socketio=None,
    )


def test_deploy_path_override_roundtrip(tmp_deployment_service, tmp_server_service):
    s = tmp_server_service.create(
        label="box", env="staging", hostname="h", ssh_user="u",
        ssh_private_key_enc=b"x", deploy_base_path="/var/www",
    )
    # No override yet → resolve_deploy_path falls back to base/project.
    assert tmp_deployment_service.get_deploy_path("acme", s.id) is None
    assert tmp_deployment_service.resolve_deploy_path("acme", s) == "/var/www/acme"

    # Store a custom path
    tmp_deployment_service.set_deploy_path("acme", s.id, "/srv/apps/acme-prod")
    assert tmp_deployment_service.get_deploy_path("acme", s.id) == "/srv/apps/acme-prod"
    assert tmp_deployment_service.resolve_deploy_path("acme", s) == "/srv/apps/acme-prod"

    # Other projects on the same server stay on the default
    assert tmp_deployment_service.resolve_deploy_path("other", s) == "/var/www/other"

    # Listing returns the overrides
    paths = tmp_deployment_service.list_deploy_paths_for_project("acme")
    assert len(paths) == 1 and paths[0]["server_id"] == s.id

    # Clearing the override removes the row
    tmp_deployment_service.set_deploy_path("acme", s.id, None)
    assert tmp_deployment_service.get_deploy_path("acme", s.id) is None
    assert tmp_deployment_service.list_deploy_paths_for_project("acme") == []


def test_deployment_service_project_git_config(tmp_deployment_service):
    cfg = tmp_deployment_service.get_project_git_config("myproj")
    assert cfg["git_remote_url"] is None
    assert cfg["git_default_branch"] == "main"

    tmp_deployment_service.set_project_git_config(
        "myproj",
        git_remote_url="git@github.com:org/repo.git",
        git_default_branch="release",
    )
    cfg = tmp_deployment_service.get_project_git_config("myproj")
    assert cfg["git_remote_url"] == "git@github.com:org/repo.git"
    assert cfg["git_default_branch"] == "release"


def test_deployment_service_can_user_deploy_admin(tmp_deployment_service):
    admin = SimpleNamespace(role="admin", username="alice", id=1)
    assert tmp_deployment_service.can_user_deploy(admin, "any-project") is True


def test_deployment_service_can_user_deploy_dev_without_instance(tmp_deployment_service, app):
    dev = SimpleNamespace(role="developer", username="bob", id=2)
    with app.test_request_context():
        # No dev_instance_service in this test context → returns False.
        assert tmp_deployment_service.can_user_deploy(dev, "any-project") is False


def test_run_rejects_bad_branch(tmp_deployment_service, tmp_server_service):
    s = tmp_server_service.create(
        label="s", env="staging", hostname="h", ssh_user="u",
        ssh_private_key_enc=b"x", deploy_base_path="/p",
        host_fingerprint="SHA256:fake",
    )

    class FakeApp:
        pass

    with pytest.raises(ValueError):
        tmp_deployment_service.run(
            project_name="p",
            server_id=s.id,
            branch="bad branch name",       # space → invalid
            triggered_by=None,
            app=FakeApp(),
        )


def test_run_requires_pinned_fingerprint(tmp_deployment_service, tmp_server_service):
    s = tmp_server_service.create(
        label="s2", env="staging", hostname="h", ssh_user="u",
        ssh_private_key_enc=b"x", deploy_base_path="/p",
        host_fingerprint=None,             # not pinned yet
    )

    class FakeApp:
        pass

    with pytest.raises(RuntimeError):
        tmp_deployment_service.run(
            project_name="p",
            server_id=s.id,
            branch="main",
            triggered_by=None,
            app=FakeApp(),
        )


# ─── HTTP layer ───


def test_deployments_page_requires_auth(client):
    rv = client.get("/deployments", follow_redirects=False)
    assert rv.status_code in (302, 401, 403)


def test_list_servers_rejects_unauth(client):
    rv = client.get("/api/servers", follow_redirects=False)
    assert rv.status_code in (302, 401, 403)


def test_run_deployment_rejects_csrf(client):
    # No CSRF token, no auth → must be rejected (not 200, not crash).
    rv = client.post("/api/deployments/run", json={"project": "x"}, follow_redirects=False)
    assert rv.status_code in (302, 400, 401, 403)
