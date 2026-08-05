"""Resolve *where* a project's database lives, and how to talk to it.

Historically every project ran its own ``mysql:8.0`` container named
``<project>_mysql_1``, holding a database called ``wordpress`` owned by a user
called ``wordpress``. Roughly thirty call sites across the codebase encoded
that layout by hand — the container name as an f-string, the credentials as
literals — which is why a project created after password randomisation would
work in some features and silently fail in others.

This module is the single place that answers the question. Callers ask for a
:class:`DbTarget` and get the container to ``docker exec`` into, the host the
site should connect to, and the schema/user/password to use, without caring
whether the project owns a MySQL server or shares one.

Two layouts are supported and coexist indefinitely:

``legacy``
    One MySQL container per project (``<project>_mysql_1``), schema
    ``wordpress``. What every existing project uses.

``shared``
    One server for the whole host (``wpl_mysql``), one schema and one
    dedicated user per project. Marked by a ``.db.json`` sidecar in the
    project's ``containers/`` directory.

Resolution order, most to least authoritative:

1. ``containers/<project>/.db.json`` — survives ``docker-compose down`` and is
   readable while the stack is stopped, which is exactly when the compose
   fallback below is least trustworthy
2. the running container's environment (``docker inspect``)
3. the project's ``docker-compose.yml``
4. ``projets/<project>/wp-config.php`` — what the site itself actually uses
5. the historical defaults
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.utils.security_config import (
    LEGACY_MYSQL_DATABASE,
    LEGACY_MYSQL_PASSWORD,
    LEGACY_MYSQL_ROOT_PASSWORD,
    LEGACY_MYSQL_USER,
)

_INSPECT_TIMEOUT = 5

#: Sidecar marking a project as living on the shared server.
DB_SIDECAR = '.db.json'

#: Container name of the shared server, and the network alias sites use.
#: The alias is deliberately ``mysql`` so that the ``DB_HOST`` already baked
#: into every existing ``wp-config.php`` keeps resolving after a migration.
SHARED_CONTAINER = 'wpl_mysql'
SHARED_HOST = 'mysql'
SHARED_PORT = 3306


# ─── low-level environment scraping ─────────────────────────────────────


def inspect_env(container: str) -> Dict[str, str]:
    """Container ``Config.Env`` as a dict; empty when unreachable."""
    try:
        result = subprocess.run(
            ['docker', 'inspect',
             '--format', '{{range .Config.Env}}{{println .}}{{end}}', container],
            capture_output=True, text=True, timeout=_INSPECT_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}
    if result.returncode != 0:
        return {}

    env: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        if '=' in line:
            key, _, value = line.partition('=')
            env[key.strip()] = value
    return env


# Both spellings matter. A per-project stack declares ``MYSQL_*`` on its mysql
# service; a shared-mode stack has no mysql service at all and only carries
# ``WORDPRESS_DB_*`` on the wordpress service. Reading just the former would
# make a stopped shared project resolve to the legacy defaults and bake
# ``wordpress``/``wordpress`` into a rewritten wp-config.
_ENV_ALIASES = {
    'WORDPRESS_DB_NAME': 'MYSQL_DATABASE',
    'WORDPRESS_DB_USER': 'MYSQL_USER',
    'WORDPRESS_DB_PASSWORD': 'MYSQL_PASSWORD',
}

_COMPOSE_KEYS = (
    'MYSQL_ROOT_PASSWORD', 'MYSQL_PASSWORD', 'MYSQL_USER', 'MYSQL_DATABASE',
    'WORDPRESS_DB_PASSWORD', 'WORDPRESS_DB_USER', 'WORDPRESS_DB_NAME',
    'WORDPRESS_DB_HOST',
)

_COMPOSE_ENV_RE = re.compile(
    r'^[ \t-]*(' + '|'.join(_COMPOSE_KEYS) + r')\s*[:=]\s*(.+?)\s*$',
    re.MULTILINE,
)


def compose_env(compose_path: str) -> Dict[str, str]:
    """Scrape database env assignments from a compose file.

    Deliberately a regex rather than a YAML parse: the templates carry
    unresolved ``{placeholder}`` tokens and shell heredocs that trip strict
    parsers, and we only need a handful of scalar values.

    ``WORDPRESS_DB_*`` keys are normalised onto their ``MYSQL_*`` equivalents
    so callers see one vocabulary, but an explicit ``MYSQL_*`` always wins.
    """
    if not compose_path or not os.path.exists(compose_path):
        return {}

    try:
        with open(compose_path, 'r') as handle:
            content = handle.read()
    except OSError:
        return {}

    found: Dict[str, str] = {}
    aliased: Dict[str, str] = {}
    # La valeur peut être entre quotes ; un commentaire de fin de ligne n'est
    # retiré que s'il est précédé d'un espace, sinon un mot de passe
    # contenant '#' serait tronqué en silence.
    for key, raw in _COMPOSE_ENV_RE.findall(content):
        value = re.sub(r'\s+#.*$', '', raw).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        # Un placeholder non substitué ne vaut rien pour un appelant.
        if not value or value.startswith('{'):
            continue
        if key in _ENV_ALIASES:
            aliased.setdefault(_ENV_ALIASES[key], value)
        else:
            found.setdefault(key, value)

    for key, value in aliased.items():
        found.setdefault(key, value)
    return found


_WP_CONFIG_RE = {
    'MYSQL_DATABASE': re.compile(r"""define\(\s*['"]DB_NAME['"]\s*,\s*['"]([^'"]*)['"]"""),
    'MYSQL_USER': re.compile(r"""define\(\s*['"]DB_USER['"]\s*,\s*['"]([^'"]*)['"]"""),
    'MYSQL_PASSWORD': re.compile(r"""define\(\s*['"]DB_PASSWORD['"]\s*,\s*['"]([^'"]*)['"]"""),
}


def wp_config_env(wp_config_path: str) -> Dict[str, str]:
    """Scrape ``DB_NAME``/``DB_USER``/``DB_PASSWORD`` out of a wp-config.php.

    Last-ditch source, but the most *truthful* one: whatever is in here is
    what the running site actually connects with, however the compose drifted.
    """
    if not wp_config_path or not os.path.exists(wp_config_path):
        return {}
    try:
        with open(wp_config_path, 'r', encoding='utf-8', errors='replace') as handle:
            content = handle.read()
    except OSError:
        return {}

    found: Dict[str, str] = {}
    for key, pattern in _WP_CONFIG_RE.items():
        match = pattern.search(content)
        if match and match.group(1) and not match.group(1).startswith('__WPL_'):
            found[key] = match.group(1)
    return found


def containers_root(containers_folder: Optional[str] = None) -> str:
    """Absolute containers directory.

    Never left CWD-relative: the app runs subprocesses with varying working
    directories, and at creation time the compose file is the *only*
    credential source (the container doesn't exist yet). A missed lookup here
    silently returns the legacy password and bakes it into ``wp-config.php``.
    """
    if containers_folder:
        return containers_folder
    from app.config.docker_config import DockerConfig
    return DockerConfig.CONTAINERS_FOLDER


def _projects_root(containers_folder: Optional[str] = None) -> str:
    """Absolute projects directory, consistent with ``containers_folder``.

    ``containers/`` and ``projets/`` are siblings under the app root. When a
    caller overrides the containers directory it means "look at this tree,
    not the live one", so the wp-config fallback has to follow it there —
    otherwise an override reads a sidecar from the given tree and a password
    from the real one.
    """
    from app.config.docker_config import DockerConfig
    if containers_folder and os.path.abspath(containers_folder) != os.path.abspath(
        DockerConfig.CONTAINERS_FOLDER
    ):
        return os.path.join(os.path.dirname(os.path.abspath(containers_folder)), 'projets')
    return DockerConfig.PROJECTS_FOLDER


# ─── the target ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DbTarget:
    """Everything needed to reach one project's database.

    ``container`` is what to ``docker exec`` into; ``host`` is what the site
    connects to over the Docker network. They differ in shared mode
    (``wpl_mysql`` vs the ``mysql`` alias) and are effectively interchangeable
    in legacy mode.
    """

    project: str
    mode: str  # 'shared' | 'legacy'
    container: str
    host: str
    port: int
    database: str
    user: str
    password: str
    root_password: str

    @property
    def is_shared(self) -> bool:
        return self.mode == 'shared'

    @property
    def db_host(self) -> str:
        """Value for ``DB_HOST`` / ``WORDPRESS_DB_HOST``."""
        return f'{self.host}:{self.port}'

    # ─── argv builders ────────────────────────────────────────────────

    def docker_exec(self, *argv: str, interactive: bool = False) -> List[str]:
        """``docker exec [-i] <container> <argv...>``."""
        cmd = ['docker', 'exec']
        if interactive:
            cmd.append('-i')
        cmd.append(self.container)
        cmd.extend(argv)
        return cmd

    def mysql_cmd(
        self,
        *args: str,
        as_root: bool = False,
        interactive: bool = False,
        database: Optional[str] = None,
    ) -> List[str]:
        """argv for a ``mysql`` client run inside the server's container.

        Pass ``database=''`` for a server-level command (``CREATE DATABASE``,
        ``SHOW DATABASES``) that must not pre-select a schema.
        """
        client = ['mysql']
        client.extend(self._auth_flags(as_root))
        db = self.database if database is None else database
        if db:
            client.append(db)
        client.extend(args)
        return self.docker_exec(*client, interactive=interactive)

    def mysqldump_cmd(self, *args: str, as_root: bool = False,
                      database: Optional[str] = None) -> List[str]:
        """argv for a ``mysqldump`` run inside the server's container.

        Credentials go on the command line rather than a temp defaults-file.
        Generated passwords are alphanumeric by construction
        (:func:`app.utils.security_config.generate_password`), so there is
        nothing to quote, and this avoids the write-then-``rm`` dance that
        leaks a 0600 file into the container on every failure path.

        Pass ``database=''`` when ``args`` already names what to dump
        (``--databases a b``, or a schema followed by a table list).
        """
        dump = ['mysqldump']
        dump.extend(self._auth_flags(as_root))
        dump.extend(args)
        db = self.database if database is None else database
        if db:
            dump.append(db)
        return self.docker_exec(*dump)

    def _auth_flags(self, as_root: bool) -> List[str]:
        """No ``-h``: inside the server's own container the default is the
        unix socket, which is faster than TCP for streamed imports and is
        what every call site did before. ``'<user>'@'%'`` matches socket
        connections, so the grants in shared mode work unchanged."""
        if as_root:
            return ['-u', 'root', f'-p{self.root_password}']
        return ['-u', self.user, f'-p{self.password}']

    def defaults_file_body(self, as_root: bool = False, section: str = 'client') -> str:
        """Contents of a ``--defaults-file`` for callers that stream one in."""
        user = 'root' if as_root else self.user
        password = self.root_password if as_root else self.password
        return f"[{section}]\nuser={user}\npassword={password}\n"


# ─── resolution ─────────────────────────────────────────────────────────


def read_sidecar(project_name: str, containers_folder: Optional[str] = None) -> Dict[str, str]:
    """Parse ``containers/<project>/.db.json``; empty dict when absent."""
    path = os.path.join(containers_root(containers_folder), project_name, DB_SIDECAR)
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _nextjs_defaults(project_name: str,
                     containers_folder: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Next.js+MySQL stacks name the schema and user after the project.

    Detected from the filesystem rather than ``docker ps`` so it still works
    for a stopped stack — which is precisely when the caller has no other
    source for these values.
    """
    if os.path.isdir(os.path.join(_projects_root(containers_folder), project_name, 'client')):
        return {'MYSQL_DATABASE': project_name, 'MYSQL_USER': project_name}
    return None


def db_target(
    project_name: str,
    containers_folder: Optional[str] = None,
    container_name: Optional[str] = None,
) -> DbTarget:
    """Resolve where ``project_name``'s database lives. Never raises."""
    sidecar = read_sidecar(project_name, containers_folder)
    shared = sidecar.get('mode') == 'shared'

    if container_name:
        container = container_name
    elif shared:
        container = sidecar.get('container') or SHARED_CONTAINER
    else:
        container = f'{project_name}_mysql_1'

    env: Dict[str, str] = {}

    # 1. sidecar
    for key, source in (('MYSQL_DATABASE', 'database'), ('MYSQL_USER', 'user'),
                        ('MYSQL_PASSWORD', 'password'),
                        ('MYSQL_ROOT_PASSWORD', 'root_password')):
        value = sidecar.get(source)
        if value:
            env[key] = str(value)

    # 2. running container. Merged key by key, not all-or-nothing: a container
    # that answers but exposes no MYSQL_* (shared server, name collision)
    # would otherwise shadow the compose and fall through to the legacy values.
    needed = ('MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_ROOT_PASSWORD', 'MYSQL_DATABASE')
    if not all(key in env for key in needed):
        probe = f'{project_name}_wordpress_1' if shared else container
        for key, value in inspect_env(probe).items():
            if key in _ENV_ALIASES:
                env.setdefault(_ENV_ALIASES[key], value)
            elif key in _COMPOSE_KEYS:
                env.setdefault(key, value)

    # 3. compose
    if not all(key in env for key in needed):
        for key, value in compose_env(os.path.join(
            containers_root(containers_folder), project_name, 'docker-compose.yml'
        )).items():
            env.setdefault(key, value)

    # 4. wp-config.php — carries no root password, so it can only ever fill
    # the site-level triple.
    if not all(key in env for key in ('MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DATABASE')):
        for key, value in wp_config_env(os.path.join(
            _projects_root(containers_folder), project_name, 'wp-config.php'
        )).items():
            env.setdefault(key, value)

    # 5. defaults
    fallback = _nextjs_defaults(project_name, containers_folder) or {}
    host = SHARED_HOST if shared else 'mysql'
    port = SHARED_PORT
    if shared:
        host = sidecar.get('host') or SHARED_HOST
        try:
            port = int(sidecar.get('port') or SHARED_PORT)
        except (TypeError, ValueError):
            port = SHARED_PORT

    return DbTarget(
        project=project_name,
        mode='shared' if shared else 'legacy',
        container=container,
        host=host,
        port=port,
        database=env.get('MYSQL_DATABASE') or fallback.get('MYSQL_DATABASE') or LEGACY_MYSQL_DATABASE,
        user=env.get('MYSQL_USER') or fallback.get('MYSQL_USER') or LEGACY_MYSQL_USER,
        password=env.get('MYSQL_PASSWORD') or LEGACY_MYSQL_PASSWORD,
        root_password=env.get('MYSQL_ROOT_PASSWORD') or LEGACY_MYSQL_ROOT_PASSWORD,
    )


def is_shared(project_name: str, containers_folder: Optional[str] = None) -> bool:
    """Whether a project has been migrated to the shared server."""
    return read_sidecar(project_name, containers_folder).get('mode') == 'shared'
