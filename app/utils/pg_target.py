"""Where a Payload project's Postgres database lives, and how to reach it.

The Postgres counterpart of :mod:`app.utils.db_target`, deliberately much
smaller: Payload projects only ever run their own ``<project>_postgres_1``
container (no shared server, no legacy credentials to fall back on).

Every command goes through ``docker exec`` on that container. The official
``postgres`` image trusts connections on the local socket, so no password is
passed on the command line — which also keeps it out of ``ps`` output.

Resolution order for the credentials, each source filling what the previous
one lacked:

1. ``containers/<project>/.db.json`` (written at creation, ``engine: postgres``)
2. the running container's ``POSTGRES_*`` env
3. the ``POSTGRES_*`` assignments of the project's docker-compose.yml
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.config.docker_config import DockerConfig
from app.utils.db_target import DB_SIDECAR, inspect_env

_ENV_KEYS = ('POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD')

_COMPOSE_ENV_RE = re.compile(
    r'^[ \t-]*(' + '|'.join(_ENV_KEYS) + r')\s*[:=]\s*(.+?)\s*$',
    re.MULTILINE,
)


def _containers_folder(containers_folder: Optional[str]) -> str:
    return containers_folder or DockerConfig.CONTAINERS_FOLDER


def write_sidecar(project_name: str, database: str, user: str, password: str,
                  containers_folder: Optional[str] = None) -> str:
    """Record a Payload project's database credentials. Returns the path."""
    path = os.path.join(_containers_folder(containers_folder), project_name, DB_SIDECAR)
    with open(path, 'w') as fh:
        json.dump({'engine': 'postgres', 'database': database,
                   'user': user, 'password': password}, fh, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _read_sidecar(project_name: str, containers_folder: Optional[str]) -> Dict[str, str]:
    path = os.path.join(_containers_folder(containers_folder), project_name, DB_SIDECAR)
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get('engine') != 'postgres':
        return {}
    env = {}
    for key, source in (('POSTGRES_DB', 'database'), ('POSTGRES_USER', 'user'),
                        ('POSTGRES_PASSWORD', 'password')):
        if data.get(source):
            env[key] = str(data[source])
    return env


def _compose_env(compose_path: str) -> Dict[str, str]:
    try:
        with open(compose_path) as fh:
            text = fh.read()
    except OSError:
        return {}
    env = {}
    for key, value in _COMPOSE_ENV_RE.findall(text):
        env.setdefault(key, value.strip().strip('"\''))
    return env


@dataclass(frozen=True)
class PgTarget:
    project: str
    container: str
    database: str
    user: str
    password: str

    @property
    def app_container(self) -> str:
        """The Payload (Next.js) container that holds connections open."""
        return f'{self.project}_payload_1'

    def internal_uri(self) -> str:
        """``DATABASE_URI`` as seen from the compose network."""
        return f'postgres://{self.user}:{self.password}@postgres:5432/{self.database}'

    # ─── argv builders ────────────────────────────────────────────────

    def docker_exec(self, *argv: str, interactive: bool = False) -> List[str]:
        cmd = ['docker', 'exec']
        if interactive:
            cmd.append('-i')
        cmd.append(self.container)
        cmd.extend(argv)
        return cmd

    def psql_cmd(self, *args: str, database: Optional[str] = None,
                 interactive: bool = False) -> List[str]:
        """``psql`` stopping at the first error, on the project database by
        default. Pass ``database='postgres'`` to DROP/CREATE the project one."""
        return self.docker_exec(
            'psql', '-v', 'ON_ERROR_STOP=1', '-q', '-U', self.user,
            '-d', database or self.database, *args,
            interactive=interactive,
        )

    def pg_dump_cmd(self, *args: str) -> List[str]:
        return self.docker_exec('pg_dump', '-U', self.user, '-d', self.database, *args)

    def pg_restore_cmd(self, *args: str) -> List[str]:
        return self.docker_exec(
            'pg_restore', '-U', self.user, '-d', self.database, *args,
            interactive=True,
        )


def pg_target(project_name: str, containers_folder: Optional[str] = None) -> PgTarget:
    """Resolve a Payload project's database. Never raises."""
    container = f'{project_name}_postgres_1'
    env = _read_sidecar(project_name, containers_folder)

    if not all(key in env for key in _ENV_KEYS):
        for key, value in inspect_env(container).items():
            if key in _ENV_KEYS:
                env.setdefault(key, value)

    if not all(key in env for key in _ENV_KEYS):
        compose = os.path.join(_containers_folder(containers_folder), project_name,
                               'docker-compose.yml')
        for key, value in _compose_env(compose).items():
            env.setdefault(key, value)

    return PgTarget(
        project=project_name,
        container=container,
        database=env.get('POSTGRES_DB', project_name),
        user=env.get('POSTGRES_USER', project_name),
        password=env.get('POSTGRES_PASSWORD', ''),
    )
