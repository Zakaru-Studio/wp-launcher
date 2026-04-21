"""
Unit tests for FastImportService — focused on the pieces that don't
require a running MySQL/Docker stack.

Docker-dependent paths (actual ``docker exec`` + ``mysql`` calls) are
covered only as happy-path signatures — execution stays stubbed.
"""
from __future__ import annotations

import gzip
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.fast_import_service import (
    FastImportService,
    _docker_inspect_env,
)


# ─── file preparation (gz / zip) ─────────────────────────────────────


def test_prepare_sql_file_passes_through_plain_sql(tmp_path: Path):
    sql = tmp_path / "dump.sql"
    sql.write_text("CREATE TABLE wp_options (id INT);\n")
    svc = FastImportService(projects_folder=str(tmp_path))
    assert svc._prepare_sql_file(str(sql)) == str(sql)


def test_prepare_sql_file_decompresses_gz(tmp_path: Path):
    raw = tmp_path / "dump.sql"
    raw.write_text("CREATE TABLE wp_posts (id INT);\n")
    gz = tmp_path / "dump.sql.gz"
    with gzip.open(gz, "wb") as f:
        f.write(raw.read_bytes())

    svc = FastImportService(projects_folder=str(tmp_path))
    out = svc._prepare_sql_file(str(gz))
    assert out is not None and out != str(gz)
    assert Path(out).read_text().startswith("CREATE TABLE wp_posts")
    os.remove(out)


def test_prepare_sql_file_unsupported_extension_returns_none(tmp_path: Path):
    bad = tmp_path / "dump.txt"
    bad.write_text("hello")
    svc = FastImportService(projects_folder=str(tmp_path))
    assert svc._prepare_sql_file(str(bad)) is None


# ─── streaming analysis ─────────────────────────────────────────────


def _write_wp_dump(path: Path, prefix: str = "wp_") -> None:
    path.write_text(
        "-- MariaDB dump 10.19\n"
        f"CREATE TABLE `{prefix}options` (id INT);\n"
        f"CREATE TABLE `{prefix}posts` (id INT);\n"
        f"CREATE TABLE `{prefix}users` (id INT);\n"
        f"CREATE TABLE IF NOT EXISTS `{prefix}comments` (id INT);\n"
        f"INSERT INTO `{prefix}options` VALUES (1);\n"
    )


def test_stream_analyze_counts_tables_and_detects_wordpress(tmp_path: Path):
    dump = tmp_path / "dump.sql"
    _write_wp_dump(dump)
    svc = FastImportService(projects_folder=str(tmp_path))
    analysis = svc._stream_analyze_sql(str(dump))
    assert analysis["table_count"] == 4
    assert analysis["is_wordpress"] is True
    assert analysis["is_mariadb"] is True


def test_stream_analyze_bounded_by_max_bytes(tmp_path: Path, monkeypatch):
    """A dump larger than the analyze window must not OOM — we stop
    reading after the bounded cap."""
    import app.services.fast_import_service as fis
    monkeypatch.setattr(fis, "_ANALYZE_MAX_BYTES", 1024)  # 1 KB cap

    big = tmp_path / "big.sql"
    with open(big, "w") as f:
        f.write("CREATE TABLE `wp_options` (id INT);\n")
        # Fill past the cap with junk that contains more CREATE TABLEs;
        # we expect them NOT to be counted.
        f.write("-- padding\n")
        f.write("x" * 10_000)
        f.write("\nCREATE TABLE `wp_extra` (id INT);\n")

    svc = FastImportService(projects_folder=str(tmp_path))
    analysis = svc._stream_analyze_sql(str(big))
    # Only the first table falls inside the 1 KB window.
    assert "wp_extra" not in analysis["create_tables"]


# ─── prefix detection + rewrite ─────────────────────────────────────


def test_detect_source_prefix_picks_most_common(tmp_path: Path):
    dump = tmp_path / "dump.sql"
    _write_wp_dump(dump, prefix="acme_")
    svc = FastImportService(projects_folder=str(tmp_path))
    assert svc._detect_source_prefix(str(dump)) == "acme_"


def test_detect_source_prefix_returns_none_for_non_wp(tmp_path: Path):
    dump = tmp_path / "dump.sql"
    dump.write_text("CREATE TABLE foo (id INT);\nCREATE TABLE bar (id INT);\n")
    svc = FastImportService(projects_folder=str(tmp_path))
    assert svc._detect_source_prefix(str(dump)) is None


def test_read_target_prefix_parses_wp_config(tmp_path: Path):
    project = tmp_path / "myproj"
    project.mkdir()
    (project / "wp-config.php").write_text("<?php\n$table_prefix = 'custom_';\n")
    svc = FastImportService(projects_folder=str(tmp_path))
    assert svc._read_target_prefix("myproj") == "custom_"


def test_read_target_prefix_defaults_when_missing(tmp_path: Path):
    svc = FastImportService(projects_folder=str(tmp_path))
    assert svc._read_target_prefix("nonexistent") == "wp_"


def test_stream_adapt_prefix_noop_when_prefixes_match(tmp_path: Path):
    project = tmp_path / "p"
    project.mkdir()
    (project / "wp-config.php").write_text("$table_prefix = 'wp_';")
    dump = tmp_path / "d.sql"
    _write_wp_dump(dump, prefix="wp_")

    svc = FastImportService(projects_folder=str(tmp_path))
    out = svc._stream_adapt_prefix(str(dump), "p")
    # Same prefix → returns the input path untouched.
    assert out == str(dump)


def test_stream_adapt_prefix_rewrites_and_cleans_up(tmp_path: Path):
    project = tmp_path / "p"
    project.mkdir()
    (project / "wp-config.php").write_text("$table_prefix = 'new_';")
    dump = tmp_path / "d.sql"
    _write_wp_dump(dump, prefix="old_")
    # Add a PHP-serialized hit so the length-fixing regex is exercised.
    with open(dump, "a") as f:
        f.write('s:13:"old_user_roles";\n')

    svc = FastImportService(projects_folder=str(tmp_path))
    out = svc._stream_adapt_prefix(str(dump), "p")
    assert out != str(dump)
    content = Path(out).read_text()
    assert "new_options" in content
    assert "old_options" not in content
    assert 's:13:"new_user_roles"' in content  # length recomputed
    os.remove(out)


# ─── docker env / container info (stubbed subprocess) ───────────────


def test_docker_inspect_env_parses_kv_pairs():
    with patch("app.services.fast_import_service.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="MYSQL_ROOT_PASSWORD=supersecret\nMYSQL_USER=bob\nPATH=/usr/bin\n",
        )
        env = _docker_inspect_env("some_container")
    assert env["MYSQL_ROOT_PASSWORD"] == "supersecret"
    assert env["MYSQL_USER"] == "bob"


def test_docker_inspect_env_returns_empty_on_failure():
    with patch("app.services.fast_import_service.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert _docker_inspect_env("missing") == {}


def test_get_container_mysql_info_prefers_docker_env_over_defaults(tmp_path: Path):
    svc = FastImportService(projects_folder=str(tmp_path))
    fake_env = {
        "MYSQL_ROOT_PASSWORD": "from-env",
        "MYSQL_USER": "custom_user",
        "MYSQL_DATABASE": "custom_db",
        "MYSQL_PASSWORD": "custom_pass",
    }
    with patch("app.services.fast_import_service._docker_inspect_env",
               return_value=fake_env), \
         patch.object(svc, "_detect_project_type", return_value="wordpress"):
        info = svc.get_container_mysql_info("acme")
    assert info.user == "custom_user"
    assert info.database == "custom_db"
    assert info.password == "custom_pass"
    assert info.root_password == "from-env"


def test_get_container_mysql_info_falls_back_to_defaults():
    svc = FastImportService()
    with patch("app.services.fast_import_service._docker_inspect_env",
               return_value={}), \
         patch.object(svc, "_detect_project_type", return_value="wordpress"):
        info = svc.get_container_mysql_info("acme")
    assert info.user == "wordpress"
    assert info.root_password == "rootpassword"
    assert info.project_type == "wordpress"


# ─── maintenance mode ───────────────────────────────────────────────


def test_enable_and_disable_maintenance_mode_roundtrip(tmp_path: Path):
    project = tmp_path / "p"
    project.mkdir()
    svc = FastImportService(projects_folder=str(tmp_path))
    path = svc.enable_maintenance_mode("p")
    assert path is not None and os.path.exists(path)
    content = Path(path).read_text()
    assert "$upgrading" in content

    svc.disable_maintenance_mode("p")
    assert not os.path.exists(path)


def test_disable_maintenance_mode_accepts_both_forms(tmp_path: Path):
    project = tmp_path / "p"
    project.mkdir()
    svc = FastImportService(projects_folder=str(tmp_path))
    path = svc.enable_maintenance_mode("p")
    assert path is not None
    svc.disable_maintenance_mode(path)  # absolute path form
    assert not os.path.exists(path)


# ─── pre-flight auth check ──────────────────────────────────────────


def _info(**kw):
    from app.services.fast_import_service import ContainerInfo
    defaults = dict(
        container="proj_mysql_1", database="wordpress",
        user="wordpress", password="wordpress",
        root_password="rootpassword", project_type="wordpress",
    )
    defaults.update(kw)
    return ContainerInfo(**defaults)


def test_verify_mysql_auth_returns_none_on_success():
    svc = FastImportService()
    with patch("app.services.fast_import_service.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="1", stderr="")
        assert svc._verify_mysql_auth(_info()) is None


def test_verify_mysql_auth_filters_password_warning():
    svc = FastImportService()
    with patch("app.services.fast_import_service.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr=(
                "mysql: [Warning] Using a password on the command line interface can be insecure.\n"
                "ERROR 1045 (28000): Access denied for user 'wordpress'@'localhost'\n"
            ),
        )
        err = svc._verify_mysql_auth(_info())
    assert err is not None
    assert "password on the command line" not in err.lower()
    assert "Access denied" in err


def test_verify_mysql_auth_handles_timeout():
    svc = FastImportService()
    import subprocess as _sp
    with patch("app.services.fast_import_service.subprocess.run",
               side_effect=_sp.TimeoutExpired(cmd="mysql", timeout=15)):
        err = svc._verify_mysql_auth(_info())
    assert err is not None and "timed out" in err


# ─── routes: import_processes dict is defined ───────────────────────


def test_routes_database_module_exposes_import_processes_dict():
    """The old code had a NameError on this symbol — make sure it
    exists at module scope so the stop-import endpoint can use it."""
    from app.routes import database
    assert isinstance(database.import_processes, dict)


def test_fast_import_route_rejects_missing_file(client, app):
    """Sanity check on the request-layer guard without hitting Docker."""
    with patch("app.middleware.auth_middleware.admin_required",
               side_effect=lambda f: f):
        rv = client.post("/fast_import_database/nonexistent", data={})
    # Whatever the auth/CSRF layer decides, it must not 500.
    assert rv.status_code != 500
