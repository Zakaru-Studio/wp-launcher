"""
Tests for the backups feature (MonitoringService + /api/backups routes).

Covers the robustness fixes:
  - safe (type, filename) resolution — no path traversal, strict charset
  - delete by (type, filename) instead of a client-supplied path
  - project-name parsing tolerant to underscores
  - async run: single-flight lock + status reporting
  - HTTP layer: auth required, no 500 on unauth
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.services.monitoring_service import MonitoringService


@pytest.fixture()
def svc(tmp_path: Path) -> MonitoringService:
    (tmp_path / "mysql").mkdir()
    (tmp_path / "mongodb").mkdir()
    return MonitoringService(
        backup_dir=str(tmp_path),
        backup_script=str(tmp_path / "fake_backup.sh"),
    )


def _touch(path: Path, content: bytes = b"data") -> None:
    path.write_bytes(content)


# ─── resolve_backup_file ───


def test_resolve_valid_mysql_backup(svc, tmp_path):
    _touch(tmp_path / "mysql" / "acme_20260101_120000.sql.gz")
    resolved = svc.resolve_backup_file("mysql", "acme_20260101_120000.sql.gz")
    assert resolved == str(tmp_path / "mysql" / "acme_20260101_120000.sql.gz")


@pytest.mark.parametrize("bad_name", [
    "../secret.sql",                 # traversal (slash rejected by charset)
    "..%2Fsecret.sql",               # encoded slash
    "/etc/passwd",                   # absolute
    "foo.sql; rm -rf /",             # shell chars
    "",                              # empty
    ".hidden.sql",                   # leading dot
    "name.txt",                      # wrong extension
    "a" * 300 + ".sql",              # oversized
])
def test_resolve_rejects_unsafe_filenames(svc, bad_name):
    assert svc.resolve_backup_file("mysql", bad_name) is None


def test_resolve_rejects_unknown_type(svc):
    assert svc.resolve_backup_file("postgres", "a_20260101_120000.sql") is None


def test_resolve_rejects_mismatched_extension_for_type(svc):
    # .sql is a MySQL extension; it must not resolve under mongodb.
    assert svc.resolve_backup_file("mongodb", "a_20260101_120000.sql") is None


def test_resolve_does_not_escape_via_symlink(svc, tmp_path):
    """A symlink inside the backup dir pointing outside must not resolve."""
    outside = tmp_path.parent / "outside_target.sql"
    _touch(outside)
    link = tmp_path / "mysql" / "evil_20260101_120000.sql"
    os.symlink(outside, link)
    assert svc.resolve_backup_file("mysql", "evil_20260101_120000.sql") is None


# ─── delete_backup ───


def test_delete_backup_removes_file(svc, tmp_path):
    f = tmp_path / "mysql" / "acme_20260101_120000.sql"
    _touch(f)
    result = svc.delete_backup("mysql", "acme_20260101_120000.sql")
    assert result["success"] is True
    assert not f.exists()


def test_delete_backup_unknown_file_fails_cleanly(svc):
    result = svc.delete_backup("mysql", "ghost_20260101_120000.sql")
    assert result["success"] is False


def test_delete_backup_rejects_traversal(svc, tmp_path):
    victim = tmp_path.parent / "victim.sql"
    _touch(victim)
    result = svc.delete_backup("mysql", "../victim.sql")
    assert result["success"] is False
    assert victim.exists()  # nothing got deleted outside the backup dir


# ─── list_backups ───


def test_list_backups_parses_project_with_underscores(svc, tmp_path):
    _touch(tmp_path / "mysql" / "my_shop_eu_20260101_120000.sql.gz")
    _touch(tmp_path / "mongodb" / "my_shop_eu_20260101_120000.tar.gz")
    data = svc.list_backups()
    assert data["success"] is True
    assert data["backups"]["mysql"][0]["project"] == "my_shop_eu"
    assert data["backups"]["mongodb"][0]["project"] == "my_shop_eu"


def test_list_backups_does_not_expose_absolute_paths(svc, tmp_path):
    _touch(tmp_path / "mysql" / "acme_20260101_120000.sql")
    data = svc.list_backups()
    assert "path" not in data["backups"]["mysql"][0]


def test_list_backups_includes_storage_stats(svc, tmp_path):
    _touch(tmp_path / "mysql" / "acme_20260101_120000.sql", b"x" * 2048)
    data = svc.list_backups()
    assert data["storage"]["total_mb"] >= 0
    assert "mysql" in data["storage"]["per_type_mb"]


def test_list_backups_ignores_report_files(svc, tmp_path):
    _touch(tmp_path / "mysql" / "backup_report_20260101_120000.txt")
    data = svc.list_backups()
    assert data["total_mysql"] == 0


# ─── async run ───


def test_run_backup_async_rejects_invalid_type(svc):
    result = svc.run_backup_async("postgres")
    assert result["started"] is False


def test_run_backup_async_requires_existing_script(svc):
    result = svc.run_backup_async("all")
    assert result["started"] is False
    assert "Script" in result["error"]


def test_run_backup_async_single_flight(svc, tmp_path):
    """While a run is in flight, a second one must be refused with
    already_running instead of stacking concurrent mysqldumps."""
    script = tmp_path / "fake_backup.sh"
    script.write_text("#!/bin/sh\nsleep 0.5\nexit 0\n")
    script.chmod(0o755)

    first = svc.run_backup_async("all")
    assert first["started"] is True

    second = svc.run_backup_async("all")
    assert second["started"] is False
    assert second.get("already_running") is True

    # Wait for completion and check the recorded state.
    for _ in range(50):
        if svc.get_backup_run_status().get("status") != "running":
            break
        time.sleep(0.1)
    status = svc.get_backup_run_status()
    assert status["status"] == "success"
    assert status.get("finished_at")


def test_run_backup_async_records_failure(svc, tmp_path):
    script = tmp_path / "fake_backup.sh"
    script.write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
    script.chmod(0o755)

    assert svc.run_backup_async("mysql")["started"] is True
    for _ in range(50):
        if svc.get_backup_run_status().get("status") != "running":
            break
        time.sleep(0.1)
    status = svc.get_backup_run_status()
    assert status["status"] == "failed"
    assert "boom" in (status.get("error") or "")


# ─── HTTP layer ───


def test_list_backups_requires_auth(client):
    rv = client.get("/api/backups", follow_redirects=False)
    assert rv.status_code in (302, 401, 403)


def test_run_backup_requires_auth(client):
    rv = client.post("/api/backups/run", json={"type": "all"}, follow_redirects=False)
    assert rv.status_code in (302, 400, 401, 403)
    assert rv.status_code != 500


def test_delete_backup_requires_auth(client):
    rv = client.delete(
        "/api/backups/mysql/acme_20260101_120000.sql", follow_redirects=False
    )
    assert rv.status_code in (302, 400, 401, 403)
    assert rv.status_code != 500


def test_download_backup_requires_auth(client):
    rv = client.get(
        "/api/backups/mysql/acme_20260101_120000.sql/download", follow_redirects=False
    )
    assert rv.status_code in (302, 401, 403)
    assert rv.status_code != 500
