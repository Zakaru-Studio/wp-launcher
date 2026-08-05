"""Unit tests for :mod:`app.utils.db_target`.

``db_target`` is the single answer to "where does this project's database
live, and how do I authenticate to it". Roughly thirty call sites depend on
it, and the shared-server migration depends on it resolving both layouts from
the same inputs — so the resolution order is pinned here rather than left to
integration testing against a live Docker host.

Every test stubs ``inspect_env`` so nothing here needs Docker.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.utils.db_target import (
    SHARED_CONTAINER,
    DbTarget,
    compose_env,
    db_target,
    is_shared,
    wp_config_env,
)


@pytest.fixture(autouse=True)
def _no_docker():
    """No test in this module may reach a real container."""
    with patch("app.utils.db_target.inspect_env", return_value={}):
        yield


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# ─── legacy layout ──────────────────────────────────────────────────


def test_unknown_project_falls_back_to_legacy_defaults(tmp_path: Path):
    t = db_target("acme", containers_folder=str(tmp_path))
    assert t.mode == "legacy"
    assert t.container == "acme_mysql_1"
    assert (t.database, t.user, t.password) == ("wordpress", "wordpress", "wordpress")
    assert t.root_password == "rootpassword"


def test_compose_mysql_env_wins_over_defaults(tmp_path: Path):
    _write(tmp_path / "acme" / "docker-compose.yml", """
services:
  mysql:
    environment:
      MYSQL_ROOT_PASSWORD: "pw-root-from-compose"
      MYSQL_DATABASE: wordpress
      MYSQL_USER: wordpress
      MYSQL_PASSWORD: "pw-from-compose"
""")
    t = db_target("acme", containers_folder=str(tmp_path))
    assert t.password == "pw-from-compose"
    assert t.root_password == "pw-root-from-compose"


def test_unsubstituted_placeholders_are_ignored(tmp_path: Path):
    """A template that was never rendered must not yield '{mysql_password}'
    as a password — that would be baked into wp-config.php verbatim."""
    _write(tmp_path / "acme" / "docker-compose.yml", """
services:
  mysql:
    environment:
      MYSQL_ROOT_PASSWORD: "{mysql_root_password}"
      MYSQL_PASSWORD: "{mysql_password}"
""")
    t = db_target("acme", containers_folder=str(tmp_path))
    assert t.password == "wordpress"
    assert t.root_password == "rootpassword"


# ─── the WORDPRESS_DB_* fix ─────────────────────────────────────────


def test_wordpress_db_env_is_read_when_no_mysql_service(tmp_path: Path):
    """A migrated stack has no ``mysql:`` service and therefore no
    ``MYSQL_*`` keys. Reading only those would silently return the legacy
    wordpress/wordpress and lock the site out of its own schema."""
    _write(tmp_path / "acme" / "docker-compose.yml", """
services:
  wordpress:
    environment:
      WORDPRESS_DB_HOST: mysql:3306
      WORDPRESS_DB_NAME: wp_acme
      WORDPRESS_DB_USER: wp_acme_a1b2c3
      WORDPRESS_DB_PASSWORD: "pw-migrated"
""")
    t = db_target("acme", containers_folder=str(tmp_path))
    assert t.database == "wp_acme"
    assert t.user == "wp_acme_a1b2c3"
    assert t.password == "pw-migrated"


def test_explicit_mysql_env_beats_wordpress_db_alias(tmp_path: Path):
    _write(tmp_path / "acme" / "docker-compose.yml", """
services:
  mysql:
    environment:
      MYSQL_DATABASE: from_mysql_key
  wordpress:
    environment:
      WORDPRESS_DB_NAME: from_wordpress_key
""")
    assert db_target("acme", containers_folder=str(tmp_path)).database == "from_mysql_key"


# ─── shared layout ──────────────────────────────────────────────────


def _shared_sidecar(root: Path, project: str = "acme", **over) -> None:
    data = {
        "mode": "shared",
        "container": SHARED_CONTAINER,
        "host": "mysql",
        "port": 3306,
        "database": "wp_acme",
        "user": "wp_acme_a1b2c3",
        "password": "pw-shared-site",
        "root_password": "pw-shared-root",
    }
    data.update(over)
    _write(root / project / ".db.json", json.dumps(data))


def test_sidecar_switches_to_shared_layout(tmp_path: Path):
    _shared_sidecar(tmp_path)
    t = db_target("acme", containers_folder=str(tmp_path))
    assert t.mode == "shared" and t.is_shared
    assert t.container == SHARED_CONTAINER
    assert (t.database, t.user) == ("wp_acme", "wp_acme_a1b2c3")
    assert is_shared("acme", containers_folder=str(tmp_path))


def test_shared_db_host_keeps_the_mysql_alias(tmp_path: Path):
    """The shared server answers to the alias ``mysql``, which is what every
    existing wp-config.php already has — so migrating must not require
    rewriting DB_HOST in 46 files."""
    _shared_sidecar(tmp_path)
    assert db_target("acme", containers_folder=str(tmp_path)).db_host == "mysql:3306"


def test_sidecar_beats_a_stale_compose(tmp_path: Path):
    """After migration the old compose may linger as a backup. The sidecar is
    authoritative or a rollback file could redirect writes to the old DB."""
    _shared_sidecar(tmp_path)
    _write(tmp_path / "acme" / "docker-compose.yml", """
services:
  mysql:
    environment:
      MYSQL_DATABASE: wordpress
      MYSQL_PASSWORD: "stale-legacy-password"
""")
    t = db_target("acme", containers_folder=str(tmp_path))
    assert t.database == "wp_acme"
    assert t.password == "pw-shared-site"


def test_modes_coexist_in_one_tree(tmp_path: Path):
    _shared_sidecar(tmp_path, project="migrated")
    (tmp_path / "untouched").mkdir()
    assert db_target("migrated", containers_folder=str(tmp_path)).is_shared
    assert not db_target("untouched", containers_folder=str(tmp_path)).is_shared


def test_corrupt_sidecar_degrades_to_legacy(tmp_path: Path):
    _write(tmp_path / "acme" / ".db.json", "{not json")
    assert db_target("acme", containers_folder=str(tmp_path)).mode == "legacy"


# ─── wp-config.php as the last-ditch source ─────────────────────────


def test_wp_config_fills_credentials_when_compose_is_gone(tmp_path: Path):
    """Whatever wp-config says is what the running site actually connects
    with, however far the compose has drifted."""
    _write(tmp_path / "containers" / "acme" / "docker-compose.yml", "services:\n  wordpress:\n")
    _write(tmp_path / "projets" / "acme" / "wp-config.php", """<?php
define('DB_NAME', 'wp_from_config');
define('DB_USER', 'user_from_config');
define('DB_PASSWORD', 'pw-from-wpconfig');
""")
    t = db_target("acme", containers_folder=str(tmp_path / "containers"))
    assert (t.database, t.user, t.password) == (
        "wp_from_config", "user_from_config", "pw-from-wpconfig")


def test_compose_beats_wp_config(tmp_path: Path):
    _write(tmp_path / "containers" / "acme" / "docker-compose.yml", """
services:
  mysql:
    environment:
      MYSQL_PASSWORD: "pw-from-compose"
""")
    _write(tmp_path / "projets" / "acme" / "wp-config.php",
           "<?php\ndefine('DB_PASSWORD', 'pw-from-wpconfig');\n")
    t = db_target("acme", containers_folder=str(tmp_path / "containers"))
    assert t.password == "pw-from-compose"


# ─── argv builders ──────────────────────────────────────────────────


def _target(**over) -> DbTarget:
    base = dict(
        project="acme", mode="legacy", container="acme_mysql_1", host="mysql",
        port=3306, database="wordpress", user="wp_user", password="pw",
        root_password="rootpw",
    )
    base.update(over)
    return DbTarget(**base)


def test_mysql_cmd_selects_the_schema_and_authenticates_as_the_site_user():
    assert _target().mysql_cmd("-e", "SELECT 1") == [
        "docker", "exec", "acme_mysql_1",
        "mysql", "-u", "wp_user", "-ppw", "wordpress", "-e", "SELECT 1",
    ]


def test_mysql_cmd_as_root_with_no_schema_for_server_level_statements():
    cmd = _target().mysql_cmd("-e", "SHOW DATABASES", as_root=True, database="")
    assert cmd == [
        "docker", "exec", "acme_mysql_1",
        "mysql", "-u", "root", "-prootpw", "-e", "SHOW DATABASES",
    ]
    assert "wordpress" not in cmd


def test_mysql_cmd_interactive_adds_dash_i_for_stdin_streaming():
    assert _target().mysql_cmd(interactive=True)[:4] == ["docker", "exec", "-i", "acme_mysql_1"]


def test_mysqldump_cmd_puts_the_schema_last():
    assert _target().mysqldump_cmd("--single-transaction") == [
        "docker", "exec", "acme_mysql_1",
        "mysqldump", "-u", "wp_user", "-ppw", "--single-transaction", "wordpress",
    ]


def test_mysqldump_cmd_omits_the_schema_when_args_already_name_it():
    cmd = _target().mysqldump_cmd("--databases", "a", "b", database="")
    assert cmd[-3:] == ["--databases", "a", "b"]


def test_shared_target_execs_into_the_shared_container():
    t = _target(mode="shared", container=SHARED_CONTAINER, database="wp_acme")
    assert t.mysql_cmd("-e", "SELECT 1")[:3] == ["docker", "exec", SHARED_CONTAINER]
    assert t.mysqldump_cmd()[-1] == "wp_acme"


def test_defaults_file_body_sections():
    t = _target()
    assert t.defaults_file_body() == "[client]\nuser=wp_user\npassword=pw\n"
    assert t.defaults_file_body(as_root=True, section="mysqldump") == (
        "[mysqldump]\nuser=root\npassword=rootpw\n"
    )


# ─── scrapers ───────────────────────────────────────────────────────


def test_compose_env_strips_quotes_but_keeps_hash_in_passwords(tmp_path: Path):
    p = tmp_path / "docker-compose.yml"
    _write(p, '      MYSQL_PASSWORD: "pa#ss"   # a trailing comment\n')
    assert compose_env(str(p))["MYSQL_PASSWORD"] == "pa#ss"


def test_compose_env_on_missing_file_is_empty():
    assert compose_env("/nonexistent/docker-compose.yml") == {}


def test_wp_config_env_reads_the_defines(tmp_path: Path):
    p = tmp_path / "wp-config.php"
    _write(p, """<?php
define('DB_NAME', 'wp_acme');
define('DB_USER', 'wp_acme_a1b2c3');
define('DB_PASSWORD', 'pw-from-wpconfig');
define('DB_HOST', 'mysql:3306');
""")
    env = wp_config_env(str(p))
    assert env["MYSQL_DATABASE"] == "wp_acme"
    assert env["MYSQL_PASSWORD"] == "pw-from-wpconfig"


def test_wp_config_env_ignores_unrendered_placeholders(tmp_path: Path):
    p = tmp_path / "wp-config.php"
    _write(p, "<?php\ndefine('DB_NAME', '__WPL_DB_NAME__');\n")
    assert wp_config_env(str(p)) == {}
