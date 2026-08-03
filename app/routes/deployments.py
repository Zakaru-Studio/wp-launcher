"""
Deployments blueprint — servers CRUD + git config + run deploy.

Routes:
  GET    /deployments
  GET    /api/servers                                (admin)
  POST   /api/servers                                (admin)
  PATCH  /api/servers/<id>                           (admin)
  DELETE /api/servers/<id>                           (admin)
  POST   /api/servers/test                           (admin)

  GET    /api/deployment-projects                    (login)
  POST   /api/deployment-projects                    (login + can_user_deploy)
  DELETE /api/deployment-projects/<name>             (login + can_user_deploy)

  GET    /api/deployment-targets[?project=]          (login)
  POST   /api/deployment-targets                     (login + can_user_deploy)
  PATCH  /api/deployment-targets/<id>                (login + can_user_deploy)
  DELETE /api/deployment-targets/<id>                (login + can_user_deploy)
  POST   /api/deployment-targets/<id>/deploy         (login + can_user_deploy)
  POST   /api/deployment-targets/<id>/push-db        (login + can_user_deploy)
  POST   /api/deployment-targets/<id>/push-media     (login + can_user_deploy)

  GET    /api/deployments?project=&server_id=&branch= (login)
  GET    /api/deployments/<id>                       (login + owner/admin)
  GET    /api/deployments/<id>/log                   (login + owner/admin)
  POST   /api/deployments/run                        (login + can_user_deploy)
  POST   /api/deployments/<id>/cancel                (login + owner/admin)
  GET    /api/deployments/deployable-projects        (login)

  GET    /api/projects/<name>/git                    (login + can_user_deploy)
  PATCH  /api/projects/<name>/git                    (login + can_user_deploy)

  GET    /api/projects/<name>/deploy-paths           (login + can_user_deploy)
  GET    /api/projects/<name>/deploy-paths/<sid>     (login + can_user_deploy)
  PUT    /api/projects/<name>/deploy-paths/<sid>     (login + can_user_deploy)
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    render_template,
    request,
)

from app.middleware.auth_middleware import admin_required, login_required
from app.services import ssh_service

log = logging.getLogger(__name__)

deployments_bp = Blueprint("deployments", __name__)

PROJECTS_FOLDER = os.environ.get("WP_PROJECTS_FOLDER", "projets")

# Project name regex — same charset as git-safe identifiers.
_PROJECT_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


# ─── helpers ─────────────────────────────────────────────────────────


def _service(name: str):
    return current_app.extensions.get(name)


def _require(service_name: str):
    svc = _service(service_name)
    if svc is None:
        return None, (jsonify(error=f"{service_name} not initialized"), 500)
    return svc, None


def _list_all_projects() -> list[str]:
    svc = _service("project_service")
    if svc and hasattr(svc, "get_project_list"):
        try:
            data = svc.get_project_list()
            if isinstance(data, list):
                return [p["name"] if isinstance(p, dict) and "name" in p else str(p) for p in data]
        except Exception:  # noqa: BLE001
            log.exception("project_service.get_project_list failed; falling back to filesystem")
    if not os.path.isdir(PROJECTS_FOLDER):
        return []
    names = []
    for entry in os.listdir(PROJECTS_FOLDER):
        path = os.path.join(PROJECTS_FOLDER, entry)
        if not os.path.isdir(path):
            continue
        if os.path.exists(os.path.join(path, ".DELETED_PROJECT")):
            continue
        names.append(entry)
    return sorted(names)


def _user_can_deploy(project_name: str) -> bool:
    dep = _service("deployment_service")
    if dep is None:
        return False
    return dep.can_user_deploy(g.current_user, project_name)


def _is_admin() -> bool:
    return getattr(g.current_user, "role", None) == "admin"


def _coerce_int(value, default=None):
    """Best-effort int coercion for query args / JSON bodies."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validate_project_name(project_name: str) -> bool:
    """Reject slugs that contain slashes, path segments, or wild chars.

    Project names are interpolated into filesystem paths and used as
    SQLite keys — stick to the narrow charset that the rest of the app
    already uses.
    """
    return bool(project_name) and bool(_PROJECT_RE.match(project_name))


def _validate_deploy_path(deploy_path: str) -> tuple[bool, str]:
    """Reject unsafe deploy paths before we hand them to SSH.

    Rules:
      - must be an absolute POSIX-style path (starts with ``/``)
      - no ``..`` path segments (traversal)
      - no NUL bytes (argument-smuggling)
      - no ``~`` expansion (shell surprise)
      - must normalize to itself (no redundant ``./`` or ``//``)
    """
    if not deploy_path:
        return False, "Deploy path is empty."
    if "\x00" in deploy_path:
        return False, "Deploy path contains a NUL byte."
    if not deploy_path.startswith("/"):
        return False, "Deploy path must be absolute (start with '/')."
    if deploy_path.startswith("~"):
        return False, "Deploy path cannot start with '~'."
    segments = deploy_path.split("/")
    if ".." in segments:
        return False, "Deploy path contains '..'."
    normalized = os.path.normpath(deploy_path)
    if normalized != deploy_path.rstrip("/") or not normalized.startswith("/"):
        return False, "Deploy path must be normalized (no './' or '//')."
    return True, ""


# ─── page ────────────────────────────────────────────────────────────


@deployments_bp.route("/deployments")
@login_required
def deployments_page():
    """Servers CRUD + deployment history page.

    Any authenticated user sees the page; sensitive actions (server
    CRUD, run deploy) are gated by `admin_required` / `can_user_deploy`
    at the API layer.
    """
    return render_template("deployments.html")


@deployments_bp.route("/deployments/servers")
@admin_required
def servers_page():
    """Dedicated server management page (list / create / edit / delete).

    Server CRUD is admin-only, so — unlike the deployments page — this
    view is gated at the page level, not just the API.
    """
    return render_template("deployment_servers.html")


# ─── servers CRUD ────────────────────────────────────────────────────


@deployments_bp.route("/api/servers", methods=["GET"])
@admin_required
def api_list_servers():
    svc, err = _require("server_service")
    if err:
        return err
    servers = [s.to_public_dict() for s in svc.list_servers()]
    return jsonify(servers=servers)


@deployments_bp.route("/api/servers", methods=["POST"])
@admin_required
def api_create_server():
    svc, err = _require("server_service")
    if err:
        return err

    data = request.get_json(silent=True) or {}
    required = ("label", "env", "hostname", "ssh_user", "deploy_base_path", "private_key")
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify(error=f"Missing fields: {', '.join(missing)}"), 400

    # Validate deploy_base_path with the same rules as per-project paths.
    base_path = str(data["deploy_base_path"]).strip()
    ok, reason = _validate_deploy_path(base_path)
    if not ok:
        return jsonify(error=reason), 400

    secret_key = current_app.config.get("SECRET_KEY") or ""
    try:
        enc = ssh_service.encrypt_private_key(secret_key, data["private_key"])
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:  # noqa: BLE001
        log.exception("encrypt_private_key failed on create_server")
        return jsonify(error="Invalid private key."), 400

    try:
        server = svc.create(
            label=data["label"].strip(),
            env=data["env"],
            hostname=data["hostname"].strip(),
            ssh_user=data["ssh_user"].strip(),
            ssh_private_key_enc=enc,
            deploy_base_path=base_path,
            ssh_port=_coerce_int(data.get("ssh_port"), 22),
            host_fingerprint=(data.get("host_fingerprint") or None),
            created_by=getattr(g.current_user, "id", None),
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(server=server.to_public_dict()), 201


@deployments_bp.route("/api/servers/<int:server_id>", methods=["PATCH"])
@admin_required
def api_update_server(server_id: int):
    svc, err = _require("server_service")
    if err:
        return err
    data = request.get_json(silent=True) or {}

    payload: dict = {}
    for k in ("label", "env", "hostname", "ssh_user", "host_fingerprint"):
        if k in data and data[k] is not None:
            payload[k] = data[k]
    if "deploy_base_path" in data and data["deploy_base_path"]:
        base_path = str(data["deploy_base_path"]).strip()
        ok, reason = _validate_deploy_path(base_path)
        if not ok:
            return jsonify(error=reason), 400
        payload["deploy_base_path"] = base_path
    if "ssh_port" in data and data["ssh_port"] is not None:
        port = _coerce_int(data["ssh_port"])
        if port is None:
            return jsonify(error="ssh_port must be an integer."), 400
        payload["ssh_port"] = port
    if data.get("private_key"):
        secret_key = current_app.config.get("SECRET_KEY") or ""
        try:
            payload["ssh_private_key_enc"] = ssh_service.encrypt_private_key(
                secret_key, data["private_key"]
            )
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception:  # noqa: BLE001
            log.exception("encrypt_private_key failed on update_server")
            return jsonify(error="Invalid private key."), 400

    try:
        server = svc.update(server_id, **payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if not server:
        return jsonify(error="Server not found"), 404
    return jsonify(server=server.to_public_dict())


@deployments_bp.route("/api/servers/<int:server_id>", methods=["DELETE"])
@admin_required
def api_delete_server(server_id: int):
    svc, err = _require("server_service")
    if err:
        return err
    ok = svc.delete(server_id)
    if not ok:
        return jsonify(error="Server not found"), 404
    return jsonify(success=True)


@deployments_bp.route("/api/servers/test", methods=["POST"])
@admin_required
def api_test_server_connection():
    """Test an SSH connection with the supplied credentials.

    Accepts either a raw private key (for a brand-new server that
    isn't in the DB yet) or a server_id (to re-test an existing one).

    Returns HTTP 400 (not 200) when the connection test fails, so the
    frontend can branch on status instead of parsing the body.
    """
    data = request.get_json(silent=True) or {}
    svc_server = _service("server_service")

    hostname = data.get("hostname")
    ssh_port = _coerce_int(data.get("ssh_port"), 22)
    ssh_user = data.get("ssh_user")
    pem = data.get("private_key")
    server_id = _coerce_int(data.get("server_id"))
    expected_fp = data.get("host_fingerprint") or None

    if server_id and svc_server:
        server = svc_server.get_by_id(server_id)
        if not server:
            return jsonify(error="Server not found"), 404
        hostname = hostname or server.hostname
        ssh_port = ssh_port or server.ssh_port
        ssh_user = ssh_user or server.ssh_user
        expected_fp = expected_fp or server.host_fingerprint
        if not pem and server.ssh_private_key_enc:
            secret_key = current_app.config.get("SECRET_KEY") or ""
            try:
                pem = ssh_service.decrypt_private_key(
                    secret_key, bytes(server.ssh_private_key_enc)
                )
            except Exception:  # noqa: BLE001
                log.exception("decrypt_private_key failed for server_id=%s", server_id)
                return jsonify(error="Could not decrypt the stored key."), 400

    if not (hostname and ssh_user and pem):
        return jsonify(error="hostname, ssh_user and private_key are required"), 400

    result = ssh_service.test_connection(
        pem=pem,
        hostname=hostname,
        ssh_port=ssh_port,
        ssh_user=ssh_user,
        expected_fingerprint=expected_fp,
    )
    if result.ok:
        return jsonify(ok=True, fingerprint=result.fingerprint, error=None)
    return jsonify(ok=False, fingerprint=None, error=result.error), 400


# ─── project git config ─────────────────────────────────────────────


@deployments_bp.route("/api/projects/<project_name>/git", methods=["GET"])
@login_required
def api_get_project_git(project_name: str):
    if not _validate_project_name(project_name):
        return jsonify(error="Invalid project name."), 400
    if not (_is_admin() or _user_can_deploy(project_name)):
        return jsonify(error="Forbidden."), 403
    svc, err = _require("deployment_service")
    if err:
        return err
    cfg = svc.get_project_git_config(project_name)
    return jsonify(project_name=project_name, **cfg)


@deployments_bp.route("/api/projects/<project_name>/git", methods=["PATCH"])
@login_required
def api_set_project_git(project_name: str):
    if not _validate_project_name(project_name):
        return jsonify(error="Invalid project name."), 400
    if not _user_can_deploy(project_name):
        return jsonify(error="You don't have permission to configure this project."), 403
    svc, err = _require("deployment_service")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    cfg = svc.set_project_git_config(
        project_name,
        git_remote_url=(data.get("git_remote_url") or None),
        git_default_branch=(data.get("git_default_branch") or "main"),
    )
    return jsonify(project_name=project_name, **cfg)


# ─── per (project × server) deploy path ────────────────────────────


@deployments_bp.route("/api/projects/<project_name>/deploy-paths", methods=["GET"])
@login_required
def api_list_deploy_paths(project_name: str):
    if not _validate_project_name(project_name):
        return jsonify(error="Invalid project name."), 400
    if not (_is_admin() or _user_can_deploy(project_name)):
        return jsonify(error="Forbidden."), 403
    svc, err = _require("deployment_service")
    if err:
        return err
    paths = svc.list_deploy_paths_for_project(project_name)
    return jsonify(project_name=project_name, paths=paths)


@deployments_bp.route(
    "/api/projects/<project_name>/deploy-paths/<int:server_id>", methods=["GET"]
)
@login_required
def api_get_deploy_path(project_name: str, server_id: int):
    if not _validate_project_name(project_name):
        return jsonify(error="Invalid project name."), 400
    if not (_is_admin() or _user_can_deploy(project_name)):
        return jsonify(error="Forbidden."), 403
    svc, err = _require("deployment_service")
    if err:
        return err
    server_svc, _ = _require("server_service")
    default = ""
    if server_svc:
        server = server_svc.get_by_id(server_id)
        if server:
            default = os.path.join(server.deploy_base_path, project_name)
    return jsonify(
        project_name=project_name,
        server_id=server_id,
        deploy_path=svc.get_deploy_path(project_name, server_id),
        default_deploy_path=default,
    )


@deployments_bp.route(
    "/api/projects/<project_name>/deploy-paths/<int:server_id>", methods=["PUT"]
)
@login_required
def api_set_deploy_path(project_name: str, server_id: int):
    if not _validate_project_name(project_name):
        return jsonify(error="Invalid project name."), 400
    if not _user_can_deploy(project_name):
        return jsonify(error="You don't have permission to configure this project."), 403
    svc, err = _require("deployment_service")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    deploy_path = (data.get("deploy_path") or "").strip() or None
    if deploy_path:
        ok, reason = _validate_deploy_path(deploy_path)
        if not ok:
            return jsonify(error=reason), 400
    saved = svc.set_deploy_path(project_name, server_id, deploy_path)
    return jsonify(
        project_name=project_name,
        server_id=server_id,
        deploy_path=saved,
    )


# ─── deployment projects (folders) ──────────────────────────────────


CONTAINERS_FOLDER = os.environ.get("WP_CONTAINERS_FOLDER", "containers")


def _read_project_port(project_name: str) -> Optional[int]:
    """Read the WordPress port from ``containers/<name>/.port`` without
    touching Docker or any service. Returns None if unavailable."""
    path = os.path.join(CONTAINERS_FOLDER, project_name, ".port")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def _project_favicon_urls(project_name: str, dep_svc, server_svc) -> list[str]:
    """Best-effort favicon candidates for a project's card, tried in
    order by the frontend (which falls back to a folder icon).

    1. the local dev site (``http://<LOCAL_IP>:<port>/favicon.ico``)
    2. each connection's deploy host over https (usually the live domain)
    """
    urls: list[str] = []
    try:
        from app.config.docker_config import DockerConfig
        local_ip = DockerConfig.LOCAL_IP
    except Exception:  # noqa: BLE001
        local_ip = None

    port = _read_project_port(project_name)
    if local_ip and port:
        urls.append(f"http://{local_ip}:{port}/favicon.ico")

    if server_svc and dep_svc:
        try:
            for tg in dep_svc.list_targets(project_name=project_name):
                srv = server_svc.get_by_id(tg["server_id"])
                if srv and getattr(srv, "hostname", None):
                    urls.append(f"https://{srv.hostname}/favicon.ico")
        except Exception:  # noqa: BLE001
            pass

    # De-duplicate, preserve order.
    return list(dict.fromkeys(urls))


@deployments_bp.route("/api/deployment-projects", methods=["GET"])
@login_required
def api_list_projects():
    """List registered project folders. Non-admins only see projects
    they're allowed to deploy."""
    svc, err = _require("deployment_service")
    if err:
        return err
    projects = svc.list_projects()
    if not _is_admin():
        projects = [p for p in projects if _user_can_deploy(p["project_name"])]

    server_svc = _service("server_service")
    for p in projects:
        p["favicon_urls"] = _project_favicon_urls(p["project_name"], svc, server_svc)
    return jsonify(projects=projects)


@deployments_bp.route("/api/deployment-projects", methods=["POST"])
@login_required
def api_create_project():
    svc, err = _require("deployment_service")
    if err:
        return err
    data = request.get_json(silent=True) or {}
    project_name = (data.get("project") or "").strip() if isinstance(data.get("project"), str) else ""

    if not _validate_project_name(project_name):
        return jsonify(error="Invalid project name."), 400
    if not _user_can_deploy(project_name):
        return jsonify(error="You don't have permission to configure this project."), 403
    if project_name not in _list_all_projects():
        return jsonify(error="Unknown project."), 404

    try:
        project = svc.create_project(project_name, created_by=getattr(g.current_user, "id", None))
    except ValueError as exc:
        return jsonify(error=str(exc)), 409
    return jsonify(project=project), 201


@deployments_bp.route("/api/deployment-projects/<project_name>", methods=["DELETE"])
@login_required
def api_delete_project(project_name: str):
    if not _validate_project_name(project_name):
        return jsonify(error="Invalid project name."), 400
    svc, err = _require("deployment_service")
    if err:
        return err
    if not svc.get_project(project_name):
        return jsonify(error="Project not found."), 404
    if not _user_can_deploy(project_name):
        return jsonify(error="Forbidden."), 403
    svc.delete_project(project_name)
    return jsonify(success=True)


# ─── deployment targets (connections) ───────────────────────────────


@deployments_bp.route("/api/deployment-targets", methods=["GET"])
@login_required
def api_list_targets():
    """List saved targets (connections), optionally scoped to one
    project. Non-admins only see targets for projects they can deploy."""
    svc, err = _require("deployment_service")
    if err:
        return err
    project = request.args.get("project") or None
    if project and not _validate_project_name(project):
        return jsonify(error="Invalid project name."), 400
    targets = svc.list_targets(project_name=project)
    if not _is_admin():
        targets = [t for t in targets if _user_can_deploy(t["project_name"])]
    return jsonify(targets=targets)


@deployments_bp.route("/api/deployment-targets", methods=["POST"])
@login_required
def api_create_target():
    svc, err = _require("deployment_service")
    if err:
        return err
    server_svc, err = _require("server_service")
    if err:
        return err
    data = request.get_json(silent=True) or {}

    label = (data.get("label") or "").strip()
    project_name = (data.get("project") or "").strip() if isinstance(data.get("project"), str) else ""
    server_id = _coerce_int(data.get("server_id"))
    branch_raw = data.get("branch")
    branch = branch_raw.strip() if isinstance(branch_raw, str) else ""

    if not label:
        return jsonify(error="A target label is required."), 400
    if not _validate_project_name(project_name):
        return jsonify(error="Invalid project name."), 400
    if server_id is None:
        return jsonify(error="server_id must be an integer."), 400
    if not _user_can_deploy(project_name):
        return jsonify(error="You don't have permission to configure this project."), 403
    if project_name not in _list_all_projects():
        return jsonify(error="Unknown project."), 404
    if server_svc.get_by_id(server_id) is None:
        return jsonify(error="Server not found."), 404
    if not branch:
        cfg = svc.get_project_git_config(project_name)
        branch = (cfg.get("git_default_branch") or "main").strip()

    try:
        target = svc.create_target(
            label=label,
            project_name=project_name,
            server_id=server_id,
            branch=branch,
            created_by=getattr(g.current_user, "id", None),
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(target=target), 201


@deployments_bp.route("/api/deployment-targets/<int:target_id>", methods=["PATCH"])
@login_required
def api_update_target(target_id: int):
    svc, err = _require("deployment_service")
    if err:
        return err
    server_svc, err = _require("server_service")
    if err:
        return err
    target = svc.get_target(target_id)
    if not target:
        return jsonify(error="Target not found."), 404
    if not _user_can_deploy(target["project_name"]):
        return jsonify(error="Forbidden."), 403

    data = request.get_json(silent=True) or {}
    payload: dict = {}
    if "label" in data and data["label"] is not None:
        payload["label"] = str(data["label"])
    if "server_id" in data and data["server_id"] is not None:
        sid = _coerce_int(data["server_id"])
        if sid is None:
            return jsonify(error="server_id must be an integer."), 400
        if server_svc.get_by_id(sid) is None:
            return jsonify(error="Server not found."), 404
        payload["server_id"] = sid
    if "branch" in data and data["branch"] is not None:
        payload["branch"] = str(data["branch"])

    try:
        updated = svc.update_target(target_id, **payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if not updated:
        return jsonify(error="Target not found."), 404
    return jsonify(target=updated)


@deployments_bp.route("/api/deployment-targets/<int:target_id>", methods=["DELETE"])
@login_required
def api_delete_target(target_id: int):
    svc, err = _require("deployment_service")
    if err:
        return err
    target = svc.get_target(target_id)
    if not target:
        return jsonify(error="Target not found."), 404
    if not _user_can_deploy(target["project_name"]):
        return jsonify(error="Forbidden."), 403
    svc.delete_target(target_id)
    return jsonify(success=True)


@deployments_bp.route("/api/deployment-targets/<int:target_id>/deploy", methods=["POST"])
@login_required
def api_deploy_target(target_id: int):
    """One-click redeploy of a saved target: no re-entry of project /
    server / branch. Reuses the same worker as the manual deploy."""
    svc, err = _require("deployment_service")
    if err:
        return err
    target = svc.get_target(target_id)
    if not target:
        return jsonify(error="Target not found."), 404
    project_name = target["project_name"]
    if not _user_can_deploy(project_name):
        return jsonify(error="You don't have permission to deploy this project."), 403
    if project_name not in _list_all_projects():
        return jsonify(error="Unknown project."), 404

    try:
        deployment_id = svc.run(
            project_name=project_name,
            server_id=target["server_id"],
            branch=target["branch"],
            triggered_by=getattr(g.current_user, "id", None),
            app=current_app._get_current_object(),
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        msg = str(exc)
        status = 409 if "already running" in msg else 400
        return jsonify(error=msg), status

    return jsonify(
        deployment_id=deployment_id,
        project=project_name,
        branch=target["branch"],
        server_id=target["server_id"],
    ), 202


@deployments_bp.route("/api/deployment-targets/<int:target_id>/push-db", methods=["POST"])
@login_required
def api_push_db_target(target_id: int):
    """Push the project's dev database onto the connection's server.

    The remote DB credentials are read from the site's own wp-config.php
    at run time, so nothing has to be configured here. Same permission
    gate as a code deploy — this overwrites the remote database (a
    timestamped backup is taken remotely first).
    """
    svc, err = _require("deployment_service")
    if err:
        return err
    target = svc.get_target(target_id)
    if not target:
        return jsonify(error="Target not found."), 404
    project_name = target["project_name"]
    if not _user_can_deploy(project_name):
        return jsonify(error="You don't have permission to deploy this project."), 403
    if project_name not in _list_all_projects():
        return jsonify(error="Unknown project."), 404

    try:
        deployment_id = svc.run_db_push(
            project_name=project_name,
            server_id=target["server_id"],
            branch=target["branch"],
            triggered_by=getattr(g.current_user, "id", None),
            app=current_app._get_current_object(),
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        msg = str(exc)
        status = 409 if "already running" in msg else 400
        return jsonify(error=msg), status

    return jsonify(
        deployment_id=deployment_id,
        project=project_name,
        server_id=target["server_id"],
        kind="db",
    ), 202


@deployments_bp.route("/api/deployment-targets/<int:target_id>/push-media", methods=["POST"])
@login_required
def api_push_media_target(target_id: int):
    """Sync the project's dev wp-content/uploads onto the server.

    Additive: files are created and updated, never deleted remotely, so
    media uploaded straight onto the target survive the sync.
    """
    svc, err = _require("deployment_service")
    if err:
        return err
    target = svc.get_target(target_id)
    if not target:
        return jsonify(error="Target not found."), 404
    project_name = target["project_name"]
    if not _user_can_deploy(project_name):
        return jsonify(error="You don't have permission to deploy this project."), 403
    if project_name not in _list_all_projects():
        return jsonify(error="Unknown project."), 404

    try:
        deployment_id = svc.run_media_push(
            project_name=project_name,
            server_id=target["server_id"],
            branch=target["branch"],
            triggered_by=getattr(g.current_user, "id", None),
            app=current_app._get_current_object(),
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        msg = str(exc)
        status = 409 if "already running" in msg else 400
        return jsonify(error=msg), status

    return jsonify(
        deployment_id=deployment_id,
        project=project_name,
        server_id=target["server_id"],
        kind="media",
    ), 202


# ─── deployments ────────────────────────────────────────────────────


@deployments_bp.route("/api/deployments", methods=["GET"])
@login_required
def api_list_deployments():
    svc, err = _require("deployment_service")
    if err:
        return err
    project = request.args.get("project") or None
    server_id = _coerce_int(request.args.get("server_id"))
    branch = request.args.get("branch") or None
    limit = max(1, min(_coerce_int(request.args.get("limit"), 50), 500))

    if not _is_admin():
        if project and not _user_can_deploy(project):
            return jsonify(deployments=[])
        if not project:
            projects = [p for p in _list_all_projects() if _user_can_deploy(p)]
            out = []
            for p in projects:
                out.extend(svc.list_deployments(
                    project_name=p, server_id=server_id, branch=branch, limit=limit
                ))
            out.sort(key=lambda r: r.get("started_at") or "", reverse=True)
            return jsonify(deployments=out[:limit])

    return jsonify(deployments=svc.list_deployments(
        project_name=project, server_id=server_id, branch=branch, limit=limit
    ))


@deployments_bp.route("/api/deployments/<int:deployment_id>", methods=["GET"])
@login_required
def api_get_deployment(deployment_id: int):
    svc, err = _require("deployment_service")
    if err:
        return err
    dep = svc.get_deployment(deployment_id)
    if not dep:
        return jsonify(error="Deployment not found"), 404
    if not _is_admin() and not _user_can_deploy(dep["project_name"]):
        return jsonify(error="Forbidden"), 403
    return jsonify(deployment=dep)


@deployments_bp.route("/api/deployments/<int:deployment_id>/log", methods=["GET"])
@login_required
def api_get_deployment_log(deployment_id: int):
    svc, err = _require("deployment_service")
    if err:
        return err
    dep = svc.get_deployment(deployment_id)
    if not dep:
        return jsonify(error="Deployment not found"), 404
    if not _is_admin() and not _user_can_deploy(dep["project_name"]):
        return jsonify(error="Forbidden"), 403
    content = svc.read_log(deployment_id) or ""
    return jsonify(deployment_id=deployment_id, status=dep["status"], log=content)


@deployments_bp.route("/api/deployments/run", methods=["POST"])
@login_required
def api_run_deployment():
    svc, err = _require("deployment_service")
    if err:
        return err
    data = request.get_json(silent=True) or {}

    project_name = (data.get("project") or "").strip() if isinstance(data.get("project"), str) else ""
    server_id = _coerce_int(data.get("server_id"))
    branch_raw = data.get("branch")
    branch = branch_raw.strip() if isinstance(branch_raw, str) else ""

    if not project_name:
        return jsonify(error="project is required"), 400
    if not _validate_project_name(project_name):
        return jsonify(error="Invalid project name."), 400
    if server_id is None:
        return jsonify(error="server_id must be an integer"), 400

    # Permission BEFORE existence: an unauthorized caller learns nothing
    # about which project slugs exist on this instance.
    if not _user_can_deploy(project_name):
        return jsonify(error="You don't have permission to deploy this project."), 403
    if project_name not in _list_all_projects():
        return jsonify(error="Unknown project."), 404
    if not branch:
        cfg = svc.get_project_git_config(project_name)
        branch = (cfg.get("git_default_branch") or "main").strip()

    try:
        deployment_id = svc.run(
            project_name=project_name,
            server_id=server_id,
            branch=branch,
            triggered_by=getattr(g.current_user, "id", None),
            app=current_app._get_current_object(),
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        # Includes the "already running on this server" guard → 409 reads
        # better than 400 for a state conflict.
        msg = str(exc)
        status = 409 if "already running" in msg else 400
        return jsonify(error=msg), status

    return jsonify(deployment_id=deployment_id, project=project_name, branch=branch), 202


@deployments_bp.route("/api/deployments/<int:deployment_id>/cancel", methods=["POST"])
@login_required
def api_cancel_deployment(deployment_id: int):
    """Cancel a running deployment (owner of the project, or admin)."""
    svc, err = _require("deployment_service")
    if err:
        return err
    dep = svc.get_deployment(deployment_id)
    if not dep:
        return jsonify(error="Deployment not found"), 404
    if not _is_admin() and not _user_can_deploy(dep["project_name"]):
        return jsonify(error="Forbidden"), 403
    if dep["status"] != "running":
        return jsonify(error="Deployment is not running."), 409
    if not svc.cancel(deployment_id):
        # Row says running but no live worker owns it (e.g. app restarted
        # mid-deploy before the reaper). Nothing to signal.
        return jsonify(error="No cancellable worker for this deployment."), 409
    return jsonify(success=True, deployment_id=deployment_id), 202


# ─── helpers exposed for templates ──────────────────────────────────


@deployments_bp.route("/api/deployments/deployable-projects", methods=["GET"])
@login_required
def api_deployable_projects():
    """Return the list of projects the current user can deploy."""
    all_projects = _list_all_projects()
    if _is_admin():
        return jsonify(projects=all_projects)
    return jsonify(projects=[p for p in all_projects if _user_can_deploy(p)])
