"""
Deployments blueprint — servers CRUD + git config + run deploy.

Routes:
  GET    /deployments
  GET    /api/servers                                (admin)
  POST   /api/servers                                (admin)
  PATCH  /api/servers/<id>                           (admin)
  DELETE /api/servers/<id>                           (admin)
  POST   /api/servers/test                           (admin)

  GET    /api/deployments?project=...                (login)
  GET    /api/deployments/<id>                       (login + owner/admin)
  GET    /api/deployments/<id>/log                   (login + owner/admin)
  POST   /api/deployments/run                        (login + can_user_deploy)
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


# ─── deployments ────────────────────────────────────────────────────


@deployments_bp.route("/api/deployments", methods=["GET"])
@login_required
def api_list_deployments():
    svc, err = _require("deployment_service")
    if err:
        return err
    project = request.args.get("project") or None
    limit = max(1, min(_coerce_int(request.args.get("limit"), 50), 500))

    if not _is_admin():
        if project and not _user_can_deploy(project):
            return jsonify(deployments=[])
        if not project:
            projects = [p for p in _list_all_projects() if _user_can_deploy(p)]
            out = []
            for p in projects:
                out.extend(svc.list_deployments(project_name=p, limit=limit))
            out.sort(key=lambda r: r.get("started_at") or "", reverse=True)
            return jsonify(deployments=out[:limit])

    return jsonify(deployments=svc.list_deployments(project_name=project, limit=limit))


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
    if project_name not in _list_all_projects():
        return jsonify(error="Unknown project."), 404
    if not branch:
        cfg = svc.get_project_git_config(project_name)
        branch = (cfg.get("git_default_branch") or "main").strip()

    if not _user_can_deploy(project_name):
        return jsonify(error="You don't have permission to deploy this project."), 403

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
        return jsonify(error=str(exc)), 400

    return jsonify(deployment_id=deployment_id, project=project_name, branch=branch), 202


# ─── helpers exposed for templates ──────────────────────────────────


@deployments_bp.route("/api/deployments/deployable-projects", methods=["GET"])
@login_required
def api_deployable_projects():
    """Return the list of projects the current user can deploy."""
    all_projects = _list_all_projects()
    if _is_admin():
        return jsonify(projects=all_projects)
    return jsonify(projects=[p for p in all_projects if _user_can_deploy(p)])
