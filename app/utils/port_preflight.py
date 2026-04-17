"""
Port preflight for `docker-compose up`.

Before starting a project's containers, verify that every host port declared
in the project's docker-compose.yml is actually free. If a conflict is
detected (another container or host process already owns the port), pick a
free port and rewrite:

- docker-compose.yml  (the `0.0.0.0:OLD:INT` binding, plus WP_HOME/PMA_ABSOLUTE_URI env vars)
- sidecar .port files (.port, .pma_port, .mailpit_port, .smtp_port)
- projets/<name>/wp-config.php (WP_HOME, WP_SITEURL) when the WordPress port changes
- wp_options.siteurl/home in MySQL when the WordPress port changes and MySQL is reachable

The goal: an `errno EADDRINUSE` on `docker-compose up` should never reach the user.
"""
from __future__ import annotations

import logging
import os
import re
import socket
import subprocess
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


# Docker-compose port bindings we care about.
# Format: "0.0.0.0:HOST:CONTAINER"  or  "HOST:CONTAINER"
_PORT_LINE_RE = re.compile(
    r'^(?P<indent>\s*-\s*["\']?)'          # "- " or '- "'
    r'(?P<ip>(?:\d+\.\d+\.\d+\.\d+:)?)'    # optional IP prefix
    r'(?P<host>\d+)'                        # host port (captured)
    r':(?P<container>\d+)'                  # container port
    r'(?P<trail>["\']?.*)$',                # closing quote + comment
    re.MULTILINE,
)


# ─── low-level helpers ────────────────────────────────────────────────────────


def is_host_port_free(port: int) -> bool:
    """True if we can bind 0.0.0.0:PORT right now. That's what docker-proxy
    needs when `docker-compose up` runs."""
    for family, addr in ((socket.AF_INET, ("0.0.0.0", port)),
                         (socket.AF_INET6, ("::", port))):
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
                sock.bind(addr)
            except OSError:
                return False
    return True


def _container_owning_port(port: int) -> Optional[str]:
    """If a running Docker container already publishes this port, return its name.
    Returns None if the port is held by something else (or nothing).
    """
    try:
        result = subprocess.run(
            ['docker', 'ps', '--filter', f'publish={port}', '--format', '{{.Names}}'],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    names = [n for n in result.stdout.splitlines() if n.strip()]
    return names[0] if names else None


# ─── docker-compose port discovery ────────────────────────────────────────────


def _iter_compose_ports(compose_text: str) -> List[Tuple[int, int, str]]:
    """Return [(host_port, container_port, raw_line), ...] found in compose text."""
    out = []
    for m in _PORT_LINE_RE.finditer(compose_text):
        try:
            host = int(m.group('host'))
            container = int(m.group('container'))
        except ValueError:
            continue
        out.append((host, container, m.group(0)))
    return out


def _classify_port(container_port: int) -> str:
    """Guess which sidecar file this port corresponds to, based on the
    container-side port of the binding. Stable across generated compose files."""
    if container_port == 80:
        # Can be WP (wordpress service) or phpMyAdmin. We disambiguate later
        # using the surrounding service name from the compose.
        return 'wordpress_or_pma'
    if container_port == 8025:
        return 'mailpit'
    if container_port == 1025:
        return 'smtp'
    return 'unknown'


# A service declaration is at exactly 2 spaces of indent (standard docker-compose).
# Narrower than "2-4 spaces" to avoid matching nested keys like "ports:" (4 sp).
_SERVICE_HEADER_RE = re.compile(r'^  ([a-zA-Z0-9_-]+):\s*$', re.MULTILINE)


def _classify_binding(compose_text: str, binding_match_start: int,
                      container_port: int) -> str:
    """Walk back from the binding's position to find the enclosing service name,
    then map that to a canonical tag ('wordpress', 'phpmyadmin', 'mailpit',
    'smtp', or 'unknown')."""
    prefix = compose_text[:binding_match_start]
    service = None
    for match in _SERVICE_HEADER_RE.finditer(prefix):
        service = match.group(1)
    if service == 'mailpit':
        return 'mailpit' if container_port == 8025 else 'smtp'
    if service == 'wordpress':
        return 'wordpress'
    if service == 'phpmyadmin':
        return 'phpmyadmin'
    # Fallback on container-side heuristic
    heuristic = _classify_port(container_port)
    if heuristic == 'wordpress_or_pma':
        return 'unknown'  # we can't decide safely
    return heuristic


# ─── side-effects after a port change ─────────────────────────────────────────


def _sidecar_file(container_path: str, kind: str) -> Optional[str]:
    mapping = {
        'wordpress': '.port',
        'phpmyadmin': '.pma_port',
        'mailpit': '.mailpit_port',
        'smtp': '.smtp_port',
    }
    name = mapping.get(kind)
    return os.path.join(container_path, name) if name else None


def _write_sidecar_port(container_path: str, kind: str, new_port: int) -> None:
    path = _sidecar_file(container_path, kind)
    if path is None:
        return
    try:
        with open(path, 'w') as fh:
            fh.write(str(new_port))
    except OSError as e:
        log.warning("Could not write %s: %s", path, e)


def _update_wp_config(projects_folder: str, project_name: str,
                      old_port: int, new_port: int) -> bool:
    """Rewrite WP_HOME / WP_SITEURL in projets/<project>/wp-config.php."""
    wp_config = os.path.join(projects_folder, project_name, 'wp-config.php')
    if not os.path.isfile(wp_config):
        return False
    try:
        with open(wp_config, 'r') as fh:
            content = fh.read()
    except OSError:
        return False
    pattern = (
        r"'(WP_HOME|WP_SITEURL)'\s*,\s*'http://([^:/'\"]+):"
        + str(old_port)
        + r"'"
    )
    new_content = re.sub(
        pattern,
        lambda m: f"'{m.group(1)}', 'http://{m.group(2)}:{new_port}'",
        content,
    )
    if new_content != content:
        try:
            with open(wp_config, 'w') as fh:
                fh.write(new_content)
            return True
        except OSError as e:
            log.warning("Failed to write wp-config.php: %s", e)
    return False


def _update_wp_db_urls(project_name: str, new_port: int) -> bool:
    """Best-effort: update wp_options.siteurl/home via docker exec if MySQL is up."""
    container = f"{project_name}_mysql_1"
    try:
        probe = subprocess.run(
            ['docker', 'inspect', '--format={{.State.Running}}', container],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    if probe.returncode != 0 or probe.stdout.strip() != 'true':
        return False

    # Derive host IP from env/config; default to localhost for the DB rewrite target
    host_ip = os.environ.get('APP_HOST', '127.0.0.1')
    new_url = f"http://{host_ip}:{new_port}"
    sql = (
        "UPDATE wp_options "
        f"SET option_value = '{new_url}' "
        "WHERE option_name IN ('siteurl','home');"
    )
    try:
        result = subprocess.run(
            ['docker', 'exec', container, 'mysql',
             '-uroot', '-prootpassword', 'wordpress', '--execute', sql],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


# ─── main entry point ─────────────────────────────────────────────────────────


def _replace_port_in_compose(compose_text: str, old_port: int, new_port: int) -> str:
    """Update every occurrence of old_port as a host binding AND any
    `WP_HOME`/`PMA_ABSOLUTE_URI` env var carrying it."""
    # Port binding lines.
    def repl_binding(m: 're.Match[str]') -> str:
        if int(m.group('host')) != old_port:
            return m.group(0)
        return (
            m.group('indent') + m.group('ip') +
            str(new_port) + ':' + m.group('container') + m.group('trail')
        )
    compose_text = _PORT_LINE_RE.sub(repl_binding, compose_text)

    # URL-bearing env vars (WP_HOME, PMA_ABSOLUTE_URI).
    url_re = re.compile(
        r'(WP_HOME|PMA_ABSOLUTE_URI)\s*:\s*"?(http://[^:"\s]+):' + str(old_port)
    )
    compose_text = url_re.sub(
        lambda m: f"{m.group(1)}: \"{m.group(2)}:{new_port}",
        compose_text,
    )

    return compose_text


def resolve_port_conflicts(
    container_path: str,
    projects_folder: str = None,
) -> Tuple[bool, Dict[int, int], List[str], Dict[str, Tuple[int, int]]]:
    """
    Pre-flight port check + remediation.

    Returns (changed, remap, warnings, by_kind) where:
      - changed: True if at least one port was reassigned
      - remap: {old_host_port: new_host_port}
      - warnings: human-readable notes about actions taken or skipped
      - by_kind: {kind: (old_port, new_port)} where kind ∈ {'wordpress',
        'phpmyadmin', 'mailpit', 'smtp', 'unknown'}. Callers can use this to
        trigger post-start follow-ups (e.g. updating wp_options in MySQL
        once the container is healthy).
    """
    warnings: List[str] = []
    remap: Dict[int, int] = {}
    by_kind: Dict[str, Tuple[int, int]] = {}

    compose_path = os.path.join(container_path, 'docker-compose.yml')
    if not os.path.isfile(compose_path):
        warnings.append(f"docker-compose.yml not found at {compose_path}")
        return False, remap, warnings, by_kind

    project_name = os.path.basename(os.path.normpath(container_path))

    with open(compose_path, 'r') as fh:
        compose_text = fh.read()

    # Collect all host:container port bindings and their classification
    bindings: List[Tuple[int, int, str]] = []
    for m in _PORT_LINE_RE.finditer(compose_text):
        try:
            host = int(m.group('host'))
            container = int(m.group('container'))
        except ValueError:
            continue
        kind = _classify_binding(compose_text, m.start(), container)
        bindings.append((host, container, kind))

    if not bindings:
        return False, remap, warnings

    # Track newly picked ports so we don't pick the same one twice during this pass.
    picked_this_run: set = set()

    for host_port, container_port, kind in bindings:
        # If the port is free OR owned by one of our own project's containers,
        # leave it alone. Docker will happily re-bind it after `docker-compose down`.
        if is_host_port_free(host_port):
            continue

        owner = _container_owning_port(host_port)
        # Our own running container: docker-compose up will handle it via
        # recreate. Only treat as conflict if owned by a *different* project.
        if owner and owner.startswith(project_name + '_'):
            continue

        # Need to remap.
        new_port = _find_free_port_avoiding(picked_this_run)
        if new_port is None:
            warnings.append(
                f"⚠️ Aucun port libre trouvé pour remplacer {host_port} ({kind})"
            )
            continue

        picked_this_run.add(new_port)
        remap[host_port] = new_port
        by_kind[kind] = (host_port, new_port)

        compose_text = _replace_port_in_compose(compose_text, host_port, new_port)
        _write_sidecar_port(container_path, kind, new_port)

        note = f"🔀 Port {kind} remappé {host_port} → {new_port}"
        if owner:
            note += f" (occupé par container '{owner}')"
        warnings.append(note)

        # For the WordPress port, extra fix-ups:
        if kind == 'wordpress' and projects_folder:
            if _update_wp_config(projects_folder, project_name, host_port, new_port):
                warnings.append(f"✏️ wp-config.php mis à jour ({host_port} → {new_port})")
            if _update_wp_db_urls(project_name, new_port):
                warnings.append(f"🗃️ wp_options.siteurl/home mis à jour en DB")

    if remap:
        with open(compose_path, 'w') as fh:
            fh.write(compose_text)

    return bool(remap), remap, warnings, by_kind


def _find_free_port_avoiding(avoid: set, start: int = 8080, end: int = 9000) -> Optional[int]:
    """Find a host port that is bind-free AND not in the `avoid` set. Also
    avoids ports already referenced by any project's sidecar file so we don't
    step on another project's reserved (but not yet bound) port."""
    reserved = _collect_reserved_ports()
    port = start
    while port <= end:
        if port not in avoid and port not in reserved and is_host_port_free(port):
            return port
        port += 1
    return None


def _collect_reserved_ports() -> set:
    """Scan containers/*/{.port,.pma_port,.mailpit_port,.smtp_port} to gather
    every host port already reserved by any project."""
    reserved: set = set()
    root = os.environ.get('WP_LAUNCHER_CONTAINERS', None)
    if not root:
        # Best guess relative to this file: <repo>/containers
        here = os.path.dirname(os.path.abspath(__file__))
        # utils/ → app/ → repo root
        repo_root = os.path.normpath(os.path.join(here, '..', '..'))
        root = os.path.join(repo_root, 'containers')
    if not os.path.isdir(root):
        return reserved
    for entry in os.listdir(root):
        project_dir = os.path.join(root, entry)
        if not os.path.isdir(project_dir):
            continue
        for fname in ('.port', '.pma_port', '.mailpit_port', '.smtp_port'):
            path = os.path.join(project_dir, fname)
            if not os.path.isfile(path):
                continue
            try:
                reserved.add(int(open(path).read().strip()))
            except (ValueError, OSError):
                pass
    return reserved
