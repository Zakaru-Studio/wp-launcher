"""
Tests for the dev-instances feature (DevInstanceService + routes).

Covers the bugs fixed in the rework:
  - `slug` column: created, migrated on legacy DBs, persisted, and
    falls back to the CLEANED username for pre-migration rows
  - parent image / table prefix read from the parent project instead of
    being hardcoded
  - port allocation accounts for ports of stopped instances
  - compose project name normalization (`-p`) so two instances with the
    same slug on different projects don't collide
  - fail-fast when the parent project is missing
  - `list_instances_by_user` alias required by deployment_service
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.services.dev_instance_service import DevInstanceService


@pytest.fixture()
def svc(tmp_path: Path) -> DevInstanceService:
    (tmp_path / "projets").mkdir()
    (tmp_path / "containers").mkdir()
    return DevInstanceService(
        db_path=str(tmp_path / "dev_instances.db"),
        projects_folder=str(tmp_path / "projets"),
        containers_folder=str(tmp_path / "containers"),
    )


def _insert_row(db_path, *, name, owner, port, slug=None, parent="proj",
                db_name=None, ports=None):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO dev_instances "
            "(name, slug, parent_project, owner_username, port, ports, db_name, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'stopped')",
            (name, slug, parent, owner, port,
             json.dumps(ports) if ports else None, db_name or name),
        )
        conn.commit()


# ─── schema / slug ───


def test_legacy_db_without_slug_column_is_migrated(tmp_path):
    """Pre-rework databases lack the `slug` column; booting the service
    must add it instead of crashing on INSERT."""
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.execute('''
            CREATE TABLE dev_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                parent_project TEXT NOT NULL,
                owner_username TEXT NOT NULL,
                port INTEGER UNIQUE NOT NULL,
                ports TEXT,
                db_name TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'stopped'
            )
        ''')
        conn.execute(
            "INSERT INTO dev_instances (name, parent_project, owner_username, port, db_name) "
            "VALUES ('p_dev_jean-dupont', 'p', 'Jean.Dupont', 9001, 'p_dev_jean_dupont')"
        )
        conn.commit()

    svc = DevInstanceService(db_path=str(db),
                             projects_folder=str(tmp_path / "projets"),
                             containers_folder=str(tmp_path / "containers"))
    cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(dev_instances)")]
    assert "slug" in cols

    # Legacy row (slug NULL): the folder was created with the CLEANED
    # username, so the fallback must clean it too — not return the raw one.
    inst = svc.get_instance_by_name("p_dev_jean-dupont")
    assert inst.slug == "jean-dupont"


def test_slug_persisted_on_save_and_load(svc):
    from app.models.dev_instance import DevInstance

    instance = DevInstance(
        name="proj_dev_alice", slug="alice", parent_project="proj",
        owner_username="alice", port=9100, ports={"wordpress": 9100},
        db_name="proj_dev_alice",
    )
    svc._save_instance(instance)
    loaded = svc.get_instance_by_name("proj_dev_alice")
    assert loaded.slug == "alice"
    assert loaded.ports == {"wordpress": 9100}
    assert svc.instance_path(loaded).endswith("projets/proj/.dev-instances/alice")


def test_model_slug_fallback_cleans_username():
    from app.models.dev_instance import DevInstance

    inst = DevInstance(name="x", parent_project="p", owner_username="Nicolas.Tombal@example.com",
                       port=1, db_name="d")
    assert inst.slug == "nicolas-tombal"


# ─── parent introspection ───


def test_parent_wordpress_image_read_from_parent_compose(svc, tmp_path):
    parent_dir = tmp_path / "containers" / "myproj"
    parent_dir.mkdir(parents=True)
    (parent_dir / "docker-compose.yml").write_text(
        "services:\n  wordpress:\n    image: wp-launcher-wordpress:php8.4\n"
    )
    assert svc._parent_wordpress_image("myproj") == "wp-launcher-wordpress:php8.4"


def test_parent_wordpress_image_fallback_when_missing(svc):
    assert svc._parent_wordpress_image("ghost") == "wp-launcher-wordpress:latest"


def test_parent_table_prefix_read_from_wp_config(svc, tmp_path):
    proj = tmp_path / "projets" / "myproj"
    proj.mkdir(parents=True)
    (proj / "wp-config.php").write_text("<?php\n$table_prefix = 'wpx_';\n")
    assert svc._parent_table_prefix("myproj") == "wpx_"
    assert svc._parent_table_prefix("ghost") == "wp_"


def test_compose_project_name_is_unique_per_instance(svc):
    """Without -p, two instances with slug 'aurelien' on different
    projects shared the compose project name and `down` on one killed
    the other's container."""
    a = svc._compose_project_name("advance-paris_dev_aurelien")
    b = svc._compose_project_name("clpac_dev_aurelien")
    assert a != b
    assert a == "advance-paris_dev_aurelien"
    cmd = svc._compose_cmd("clpac_dev_aurelien", "up", "-d")
    assert cmd[:3] == ["docker-compose", "-p", "clpac_dev_aurelien"]


# ─── ports ───


def test_instance_ports_in_use_includes_all_allocated_ports(svc):
    _insert_row(svc.db_path, name="p_dev_a", owner="a", port=9200, slug="a",
                ports={"wordpress": 9200, "phpmyadmin": 9201, "mailpit": 9202})
    _insert_row(svc.db_path, name="p_dev_b", owner="b", port=9300, slug="b")
    used = svc._instance_ports_in_use()
    assert {9200, 9201, 9202, 9300} <= used


def test_allocate_ports_skips_extra_used_ports(monkeypatch):
    import app.services.port_service as port_service_module
    from app.services.port_service import PortService

    monkeypatch.setattr(port_service_module, "get_used_ports", lambda: [])
    monkeypatch.setattr(port_service_module, "is_port_in_use", lambda p: False)
    svc = PortService()
    start = svc.port_range_start
    # Sans extra_used_ports, le premier port de la plage serait choisi ;
    # ici il appartient à une instance arrêtée et doit être sauté.
    ports = svc.allocate_ports_for_project(extra_used_ports={start, start + 1})
    assert ports["wordpress"] == start + 2


def test_allocate_ports_skips_ports_held_by_host_processes(monkeypatch):
    """get_used_ports() ne voit que Docker et les fichiers .port — un
    service local (ex: python sur 8080) doit être détecté par le test
    socket, sinon le conteneur plante au démarrage avec
    'address already in use'."""
    import app.services.port_service as port_service_module
    from app.services.port_service import PortService

    monkeypatch.setattr(port_service_module, "get_used_ports", lambda: [])
    svc = PortService()
    start = svc.port_range_start
    busy = {start, start + 2}  # process hôtes fictifs
    monkeypatch.setattr(port_service_module, "is_port_in_use", lambda p: p in busy)

    ports = svc.allocate_ports_for_project()
    allocated = set(ports.values())
    assert busy.isdisjoint(allocated)
    assert ports["wordpress"] == start + 1


def test_allocate_ports_raises_when_range_exhausted(monkeypatch):
    import app.services.port_service as port_service_module
    from app.services.port_service import PortService

    monkeypatch.setattr(port_service_module, "get_used_ports", lambda: [])
    monkeypatch.setattr(port_service_module, "is_port_in_use", lambda p: True)
    svc = PortService()
    with pytest.raises(Exception, match="Aucun port libre"):
        svc.allocate_ports_for_project()


def test_get_used_ports_catches_ipv6_and_specific_ip_bindings(monkeypatch):
    """docker ps affiche aussi des bindings ':::8080->' (IPv6) et
    '192.168.1.21:8081->' — l'ancien motif limité à 0.0.0.0 les ratait."""
    from types import SimpleNamespace
    import app.utils.port_utils as port_utils

    fake = SimpleNamespace(
        stdout="0.0.0.0:8080->80/tcp, :::8080->80/tcp\n192.168.1.21:8081->80/tcp\n",
        returncode=0,
    )
    monkeypatch.setattr(port_utils.subprocess, "run", lambda *a, **k: fake)
    used = set(port_utils.get_used_ports())
    assert {8080, 8081} <= used


# ─── create / delete guards ───


@pytest.fixture
def root_helpers_present(monkeypatch):
    """Faire comme si /opt/wp-launcher-root était déployé.

    `create_dev_instance` vérifie d'abord la présence des helpers racine. Sur
    une machine de développement ils sont installés, donc l'assertion suivante
    est atteinte ; sur un runner CI ils ne le sont pas et la création échoue
    sur ce premier garde-fou. Sans ce stub les deux tests ci-dessous passent
    en local et échouent en CI, en testant autre chose que ce qu'ils annoncent.
    """
    import app.services.dev_instance_service as mod
    monkeypatch.setattr(mod.root_helpers, "available", lambda: True)


def test_create_fails_fast_when_parent_project_missing(svc, root_helpers_present):
    with pytest.raises(Exception, match="introuvable"):
        svc.create_dev_instance("nope", "alice")


def test_create_fails_fast_when_parent_mysql_stopped(
    svc, tmp_path, monkeypatch, root_helpers_present
):
    (tmp_path / "projets" / "myproj").mkdir(parents=True)
    monkeypatch.setattr(svc, "_parent_mysql_container", lambda parent: None)
    with pytest.raises(Exception, match="démarré"):
        svc.create_dev_instance("myproj", "alice")


def test_delete_requires_ownership(svc, monkeypatch):
    _insert_row(svc.db_path, name="p_dev_bob", owner="bob", port=9400, slug="bob")
    with pytest.raises(Exception, match="propriétaire"):
        svc.delete_instance("p_dev_bob", "mallory", is_admin=False)
    # Toujours présente
    assert svc.get_instance_by_name("p_dev_bob") is not None


# ─── deployments integration ───


def test_list_instances_by_user_alias_exists(svc):
    """deployment_service.can_user_deploy introspects this exact method
    name; without it every developer is denied deployment."""
    _insert_row(svc.db_path, name="p_dev_carl", owner="carl", port=9500, slug="carl")
    instances = svc.list_instances_by_user("carl")
    assert len(instances) == 1
    assert instances[0].parent_project == "proj"
    assert instances[0].owner_username == "carl"


# ─── HTTP layer ───


def test_create_instance_requires_auth(client):
    rv = client.post("/api/dev-instances/create", json={"parent_project": "x"},
                     follow_redirects=False)
    assert rv.status_code in (302, 400, 401, 403)
    assert rv.status_code != 500


def test_list_instances_requires_auth(client):
    rv = client.get("/api/dev-instances/list", follow_redirects=False)
    assert rv.status_code in (302, 401, 403)
