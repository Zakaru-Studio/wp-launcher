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
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import paramiko
import pytest

from app.services import ssh_service
from app.services.deployment_service import DeploymentService
from app.services.server_service import ServerService


# Sample key — a minimal Ed25519 PEM just for round-trip validation.
# Not a real secret; paramiko isn't asked to load it here.
# Built by concatenation so the literal PEM markers don't appear together in
# source (avoids false-positive hits from secret scanners like gitleaks).
_PEM_BEGIN = "-----" + "BEGIN " + "OPENSSH PRIVATE KEY" + "-----"
_PEM_END = "-----" + "END " + "OPENSSH PRIVATE KEY" + "-----"
_SAMPLE_KEY = (
    f"{_PEM_BEGIN}\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    "QyNTUxOQAAACB7X9g1X7Z4n2kC8xQhPnJ9qA4y5m7LdW4zQhZAAAAAAAAAAAAAAA==\n"
    f"{_PEM_END}\n"
)


# ─── Fernet round-trip ───


def test_fernet_roundtrip_restores_pem():
    secret = "test-secret-key-for-unit-tests-only-long-enough"
    enc = ssh_service.encrypt_private_key(secret, _SAMPLE_KEY)
    assert isinstance(enc, bytes) and enc != _SAMPLE_KEY.encode()
    # The current scheme prepends a 1-byte version to the Fernet token.
    assert enc[0] == 1
    dec = ssh_service.decrypt_private_key(secret, enc)
    assert dec == _SAMPLE_KEY


def test_fernet_rejects_non_pem_input():
    with pytest.raises(ValueError):
        ssh_service.encrypt_private_key("secret", "not a pem")


def test_fernet_decrypt_fails_when_secret_changes():
    enc = ssh_service.encrypt_private_key("secret-A", _SAMPLE_KEY)
    with pytest.raises(RuntimeError):
        ssh_service.decrypt_private_key("secret-B", enc)


def test_fernet_decrypt_accepts_legacy_unversioned_tokens():
    """Back-compat: tokens written before the version prefix existed
    start with Fernet's 'g' base64 marker. They must still decrypt."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    import base64 as _b64

    secret = "back-compat-secret-key-long-enough-for-test"
    raw = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"wp-launcher-servers",
        info=b"ssh-keys",
    ).derive(secret.encode())
    legacy_token = Fernet(_b64.urlsafe_b64encode(raw)).encrypt(_SAMPLE_KEY.encode())
    assert legacy_token[:1] == b"g"  # sanity: this is the legacy shape
    assert ssh_service.decrypt_private_key(secret, legacy_token) == _SAMPLE_KEY


def test_redact_private_keys_masks_pem():
    blob = "before\n" + _SAMPLE_KEY + "\nafter"
    redacted = ssh_service.redact_private_keys(blob)
    assert "PRIVATE KEY" not in redacted
    assert "REDACTED_PRIVATE_KEY" in redacted


# ─── Host-key fingerprint pinning ───


class _FakeKey:
    """Stub paramiko PKey whose asbytes() yields deterministic bytes,
    so we can control the SHA256 fingerprint the policy computes."""
    def __init__(self, payload: bytes):
        self._payload = payload

    def asbytes(self):
        return self._payload


def _fingerprint_for(payload: bytes) -> str:
    import base64 as _b64
    import hashlib as _h
    digest = _h.sha256(payload).digest()
    return "SHA256:" + _b64.b64encode(digest).decode("ascii").rstrip("=")


def test_pinned_host_key_policy_accepts_matching_fingerprint():
    policy = ssh_service._PinnedHostKeyPolicy()
    payload = b"legit-host-key"
    policy.expected_fingerprint = _fingerprint_for(payload)
    # Should not raise.
    policy.missing_host_key(client=None, hostname="srv", key=_FakeKey(payload))
    assert policy.observed_fingerprint == policy.expected_fingerprint


def test_pinned_host_key_policy_rejects_mismatch():
    policy = ssh_service._PinnedHostKeyPolicy()
    policy.expected_fingerprint = _fingerprint_for(b"expected-key")
    with pytest.raises(ssh_service.HostKeyMismatchError) as exc:
        policy.missing_host_key(client=None, hostname="srv", key=_FakeKey(b"attacker-key"))
    assert exc.value.expected == policy.expected_fingerprint
    assert exc.value.observed == _fingerprint_for(b"attacker-key")
    assert "srv" in str(exc.value)


def test_pinned_host_key_policy_first_contact_records_fingerprint():
    policy = ssh_service._PinnedHostKeyPolicy()
    policy.expected_fingerprint = None
    policy.missing_host_key(client=None, hostname="srv", key=_FakeKey(b"new-host"))
    assert policy.observed_fingerprint == _fingerprint_for(b"new-host")


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


def test_delete_server_cascades_to_deploy_paths_and_deployments(tmp_path):
    """Enabling PRAGMA foreign_keys + the FK on project_server_deploy_paths
    should wipe dependent rows when a server is deleted, rather than
    leaving orphans behind."""
    db = tmp_path / "deployments.db"
    srv = ServerService(db_path=str(db))
    dep = DeploymentService(
        db_path=str(db),
        log_dir=str(tmp_path / "logs"),
        server_service=srv,
        socketio=None,
    )
    s = srv.create(
        label="cascade", env="staging", hostname="h", ssh_user="u",
        ssh_private_key_enc=b"x", deploy_base_path="/p",
        host_fingerprint="SHA256:fake",
    )
    dep.set_deploy_path("acme", s.id, "/srv/apps/acme")
    # Insert a deployment row directly to exercise the FK cascade.
    with sqlite3.connect(str(db)) as raw:
        raw.execute("PRAGMA foreign_keys = ON")
        raw.execute(
            "INSERT INTO deployments (project_name, server_id, branch, status, "
            "triggered_by, started_at, log_file) VALUES "
            "('acme', ?, 'main', 'success', NULL, '2026-01-01', '')",
            (s.id,),
        )
        raw.commit()

    assert srv.delete(s.id) is True
    # Both dependent tables should be empty now.
    assert dep.get_deploy_path("acme", s.id) is None
    with sqlite3.connect(str(db)) as raw:
        raw.execute("PRAGMA foreign_keys = ON")
        cnt = raw.execute(
            "SELECT COUNT(*) FROM deployments WHERE server_id = ?", (s.id,)
        ).fetchone()[0]
    assert cnt == 0


# ─── to_public_dict hides the private key ───


def test_server_to_public_dict_hides_key(tmp_server_service):
    s = tmp_server_service.create(
        label="hidden", env="staging", hostname="h",
        ssh_user="u", ssh_private_key_enc=b"secret-bytes", deploy_base_path="/p",
    )
    public = s.to_public_dict()
    assert public["has_private_key"] is True
    assert "ssh_private_key_enc" not in public
    # Tighter: no value in the dict should carry private-key material.
    for value in public.values():
        assert "PRIVATE KEY" not in str(value)
        assert "secret-bytes" not in str(value)


# ─── DeploymentService permission + branch validation ───


@pytest.fixture()
def tmp_deployment_service(tmp_path: Path, tmp_server_service) -> DeploymentService:
    # Reuse the same on-disk DB as tmp_server_service so both services
    # share the tables (production wiring does the same).
    return DeploymentService(
        db_path=tmp_server_service.db_path,
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


def test_can_user_deploy_developer_with_matching_instance(tmp_deployment_service, app):
    """Dev with an active instance on the project → allowed."""
    dev = SimpleNamespace(role="developer", username="bob", id=2)
    fake = MagicMock()
    fake.list_instances_by_user = MagicMock(return_value=[
        SimpleNamespace(parent_project="acme", owner_username="bob"),
    ])
    app.extensions["dev_instance_service"] = fake
    try:
        with app.test_request_context():
            assert tmp_deployment_service.can_user_deploy(dev, "acme") is True
            assert tmp_deployment_service.can_user_deploy(dev, "other") is False
    finally:
        app.extensions.pop("dev_instance_service", None)


def test_deployment_service_can_user_deploy_dev_without_instance(tmp_deployment_service, app):
    dev = SimpleNamespace(role="developer", username="bob", id=2)
    with app.test_request_context():
        # No dev_instance_service in this test context → returns False.
        assert tmp_deployment_service.can_user_deploy(dev, "any-project") is False


@pytest.mark.parametrize("bad_branch", [
    "",                   # empty
    "a" * 101,            # too long
    "main;rm -rf /",      # shell metachar
    "$(whoami)",          # command substitution
    "`id`",               # backtick substitution
    "../../etc/passwd",   # path traversal
    "a\nb",               # newline
    "-upload-pack=/evil", # leading dash (weaponizable git option)
    "foo..bar",           # doubled-dot path segment
])
def test_run_rejects_dangerous_branch_names(tmp_deployment_service, tmp_server_service, bad_branch):
    s = tmp_server_service.create(
        label=f"s-{hash(bad_branch)}", env="staging", hostname="h", ssh_user="u",
        ssh_private_key_enc=b"x", deploy_base_path="/p",
        host_fingerprint="SHA256:fake",
    )

    class FakeApp:
        pass

    with pytest.raises(ValueError):
        tmp_deployment_service.run(
            project_name="p",
            server_id=s.id,
            branch=bad_branch,
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


def test_reap_stale_running_rows_on_service_startup(tmp_path):
    """A row left in 'running' after a prior crash must be failed by
    the reaper when the DeploymentService re-boots; otherwise UIs spin
    forever."""
    db = tmp_path / "deployments.db"
    srv = ServerService(db_path=str(db))
    dep1 = DeploymentService(
        db_path=str(db),
        log_dir=str(tmp_path / "logs"),
        server_service=srv,
        socketio=None,
    )
    with sqlite3.connect(str(db)) as raw:
        raw.execute(
            "INSERT INTO deployments (project_name, server_id, branch, status, "
            "triggered_by, started_at, log_file) VALUES "
            "('p', 1, 'main', 'running', NULL, '2026-01-01T00:00:00+00:00', '')"
        )
        raw.commit()

    # Booting a fresh service should reap the stale row.
    DeploymentService(
        db_path=str(db),
        log_dir=str(tmp_path / "logs"),
        server_service=srv,
        socketio=None,
    )
    with sqlite3.connect(str(db)) as raw:
        raw.row_factory = sqlite3.Row
        row = raw.execute(
            "SELECT status, finished_at FROM deployments WHERE project_name='p'"
        ).fetchone()
    assert row["status"] == "failed"
    assert row["finished_at"] is not None


def test_emit_writes_redacted_line_to_log_file(tmp_deployment_service, tmp_server_service, tmp_path):
    """The production guarantee — 'private keys never leak into log
    files' — is exercised through the real _emit path, not just the
    redaction helper in isolation."""
    s = tmp_server_service.create(
        label="emit", env="staging", hostname="h", ssh_user="u",
        ssh_private_key_enc=b"x", deploy_base_path="/p",
        host_fingerprint="SHA256:fake",
    )
    with sqlite3.connect(tmp_deployment_service.db_path) as raw:
        cur = raw.cursor()
        cur.execute(
            "INSERT INTO deployments (project_name, server_id, branch, status, "
            "triggered_by, started_at, log_file) "
            "VALUES (?, ?, 'main', 'running', NULL, '2026-01-01T00:00:00+00:00', '')",
            ("p", s.id),
        )
        dep_id = cur.lastrowid
        log_path = os.path.join(tmp_deployment_service.log_dir, f"{dep_id}.log")
        cur.execute("UPDATE deployments SET log_file = ? WHERE id = ?", (log_path, dep_id))
        raw.commit()

    tmp_deployment_service._emit(dep_id, log_path, _SAMPLE_KEY, stream="stdout")
    with open(log_path) as fh:
        contents = fh.read()
    assert "PRIVATE KEY" not in contents
    assert "REDACTED_PRIVATE_KEY" in contents


# ─── HTTP layer ───


def test_deployments_page_requires_auth(client):
    rv = client.get("/deployments", follow_redirects=False)
    # @login_required redirects to /login for HTML requests.
    assert rv.status_code == 302
    assert "/login" in (rv.headers.get("Location") or "")


def test_list_servers_rejects_unauth(client):
    """Unauthenticated API call must not return data; precise status
    depends on the auth decorator's JSON/HTML branch."""
    rv = client.get("/api/servers", follow_redirects=False)
    assert rv.status_code in (302, 401, 403)
    # And it must not leak server data when denied.
    if rv.is_json:
        assert "servers" not in (rv.get_json() or {})


def test_run_deployment_rejects_unauth_without_body_crash(client):
    """Unauth POST must fail cleanly, not 500 with a traceback."""
    rv = client.post("/api/deployments/run", json={"project": "x"}, follow_redirects=False)
    # Either CSRF (if enabled), or login redirect (302), or auth (401/403).
    assert rv.status_code in (302, 400, 401, 403)
    assert rv.status_code != 500


def test_coerce_int_handles_bogus_types():
    """Route-layer guard: non-scalar server_id / limit values must
    coerce to None rather than crash the request with a TypeError."""
    from app.routes.deployments import _coerce_int

    assert _coerce_int(None) is None
    assert _coerce_int("") is None
    assert _coerce_int({"nope": 1}) is None
    assert _coerce_int([1, 2, 3]) is None
    assert _coerce_int("abc") is None
    assert _coerce_int("42") == 42
    assert _coerce_int(42) == 42
    assert _coerce_int("abc", default=7) == 7


@pytest.mark.parametrize("bad_path", [
    "relative/path",          # not absolute
    "~/home",                 # tilde expansion
    "/var/www/../etc/passwd", # traversal
    "/var/www/./foo",         # redundant './'
    "/var//www",              # doubled slash
    "/var/www\x00foo",        # NUL injection
    "",                       # empty
])
def test_validate_deploy_path_rejects_unsafe(bad_path):
    from app.routes.deployments import _validate_deploy_path
    ok, reason = _validate_deploy_path(bad_path)
    assert ok is False and reason
