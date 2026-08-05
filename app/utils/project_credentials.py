"""Resolve a project's MySQL credentials instead of assuming the old defaults.

Projects created before credential randomisation all share
``wordpress``/``wordpress``/``rootpassword``; projects created after it each
have their own. Anything that shells out to ``mysql`` must therefore *ask*
rather than hard-code, or it will work on old projects and fail on new ones.

This module is now a thin façade over :mod:`app.utils.db_target`, which also
knows *where* the database lives (a per-project container or the shared
server). Prefer :func:`app.utils.db_target.db_target` in new code — it returns
the container name and argv builders alongside the credentials, so callers
stop reconstructing ``f"{project}_mysql_1"`` by hand.
"""
import os
import re
from typing import Dict, Optional

from app.utils.db_target import (  # noqa: F401  (re-exported for callers)
    compose_env as _compose_env,
    containers_root as _containers_root,
    db_target,
    inspect_env as _inspect_env,
)


def get_mysql_credentials(
    project_name: str,
    containers_folder: Optional[str] = None,
    container_name: Optional[str] = None,
) -> Dict[str, str]:
    """Return ``{'user', 'password', 'root_password', 'database'}`` for a project."""
    target = db_target(project_name, containers_folder, container_name)
    return {
        'user': target.user,
        'password': target.password,
        'root_password': target.root_password,
        'database': target.database,
    }


def get_root_password(
    project_name: str,
    containers_folder: Optional[str] = None,
    container_name: Optional[str] = None,
) -> str:
    """Shorthand for the common ``mysql -uroot -p<pw>`` call site."""
    return db_target(project_name, containers_folder, container_name).root_password


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
