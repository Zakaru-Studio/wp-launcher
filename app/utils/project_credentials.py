"""Resolve a project's MySQL credentials instead of assuming the old defaults.

Projects created before credential randomisation all share
``wordpress``/``wordpress``/``rootpassword``; projects created after it each
have their own. Anything that shells out to ``mysql`` must therefore *ask*
rather than hard-code, or it will work on old projects and fail on new ones.

Resolution order, most to least authoritative:

1. the running container's environment (``docker inspect``)
2. the project's ``docker-compose.yml`` (works while the stack is stopped)
3. the historical defaults
"""
import os
import re
import subprocess
from typing import Dict, Optional

from app.utils.security_config import (
    LEGACY_MYSQL_DATABASE,
    LEGACY_MYSQL_PASSWORD,
    LEGACY_MYSQL_ROOT_PASSWORD,
    LEGACY_MYSQL_USER,
)

_INSPECT_TIMEOUT = 5


def _inspect_env(container: str) -> Dict[str, str]:
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


def _compose_env(compose_path: str) -> Dict[str, str]:
    """Scrape MYSQL_* assignments from a compose file.

    Deliberately a regex rather than a YAML parse: the templates carry
    unresolved ``{placeholder}`` tokens and shell heredocs that trip strict
    parsers, and we only need four scalar values.
    """
    if not compose_path or not os.path.exists(compose_path):
        return {}

    try:
        with open(compose_path, 'r') as handle:
            content = handle.read()
    except OSError:
        return {}

    found: Dict[str, str] = {}
    # Accepte `KEY: value` (compose long form) et `KEY=value` (liste
    # d'environnement). La valeur peut être entre quotes ; un commentaire de
    # fin de ligne n'est retiré que s'il est précédé d'un espace, sinon un
    # mot de passe contenant '#' serait tronqué en silence.
    pattern = re.compile(
        r'^[ \t-]*(MYSQL_ROOT_PASSWORD|MYSQL_PASSWORD|MYSQL_USER|MYSQL_DATABASE)'
        r'\s*[:=]\s*(.+?)\s*$',
        re.MULTILINE,
    )
    for key, raw in pattern.findall(content):
        value = re.sub(r'\s+#.*$', '', raw).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        # Un placeholder non substitué ne vaut rien pour un appelant.
        if value and not value.startswith('{'):
            found.setdefault(key, value)
    return found


def _containers_root(containers_folder: Optional[str]) -> str:
    """Absolute containers directory.

    Never left CWD-relative: the app ``os.chdir()`` into project directories
    in several places, and at creation time the compose file is the *only*
    credential source (the container doesn't exist yet). A missed lookup here
    silently returns the legacy password and bakes it into ``wp-config.php``.
    """
    if containers_folder:
        return containers_folder
    from app.config.docker_config import DockerConfig
    return DockerConfig.CONTAINERS_FOLDER


def get_mysql_credentials(
    project_name: str,
    containers_folder: Optional[str] = None,
    container_name: Optional[str] = None,
) -> Dict[str, str]:
    """Return ``{'user', 'password', 'root_password', 'database'}`` for a project."""
    container = container_name or f'{project_name}_mysql_1'

    env = _inspect_env(container)

    # Fusion par clé, pas « tout ou rien » : un conteneur qui répond mais
    # n'expose aucun MYSQL_* (image MariaDB, collision de nom) laisserait
    # sinon le compose de côté et retomberait sur les valeurs héritées.
    if not all(k in env for k in
               ('MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_ROOT_PASSWORD', 'MYSQL_DATABASE')):
        compose = _compose_env(os.path.join(
            _containers_root(containers_folder), project_name, 'docker-compose.yml'
        ))
        for key, value in compose.items():
            env.setdefault(key, value)

    return {
        'user': env.get('MYSQL_USER') or LEGACY_MYSQL_USER,
        'password': env.get('MYSQL_PASSWORD') or LEGACY_MYSQL_PASSWORD,
        'root_password': env.get('MYSQL_ROOT_PASSWORD') or LEGACY_MYSQL_ROOT_PASSWORD,
        'database': env.get('MYSQL_DATABASE') or LEGACY_MYSQL_DATABASE,
    }


def get_mongo_password(
    project_name: str,
    containers_folder: Optional[str] = None,
    container_name: Optional[str] = None,
) -> str:
    """Root password of a project's MongoDB, for the Next.js + Mongo stack."""
    container = container_name or f'{project_name}_mongodb_1'

    env = _inspect_env(container)
    if not env.get('MONGO_INITDB_ROOT_PASSWORD'):
        compose = os.path.join(
            _containers_root(containers_folder), project_name, 'docker-compose.yml')
        if os.path.exists(compose):
            try:
                with open(compose, 'r') as handle:
                    match = re.search(
                        r'^\s*MONGO_INITDB_ROOT_PASSWORD\s*:\s*["\']?([^"\'\n#]+?)["\']?\s*$',
                        handle.read(), re.MULTILINE,
                    )
            except OSError:
                match = None
            if match and not match.group(1).startswith('{'):
                return match.group(1).strip()

    return env.get('MONGO_INITDB_ROOT_PASSWORD') or 'adminpassword'


def get_root_password(
    project_name: str,
    containers_folder: Optional[str] = None,
    container_name: Optional[str] = None,
) -> str:
    """Shorthand for the common ``mysql -uroot -p<pw>`` call site."""
    return get_mysql_credentials(project_name, containers_folder, container_name)['root_password']
