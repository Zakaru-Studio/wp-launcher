"""Appels aux helpers exécutés en root.

L'application faisait 81 appels ``sudo chown/chmod/find/rm/rsync/cp`` sur des
chemins qu'elle composait elle-même. Tant que l'utilisateur applicatif dispose
de ``NOPASSWD: ALL``, chacun de ces appels est une porte : il suffit qu'une
seule valeur interpolée soit contrôlable pour obtenir root.

Ce module est la seule voie autorisée. Il ne prend pas de commande — seulement
une intention et un chemin — et traduit ce chemin en (projet, sous-chemin)
relatifs à la racine des projets. Les scripts appelés revalident tout de leur
côté : la validation ici est du confort et du diagnostic, celle des scripts est
la vraie frontière de sécurité, puisqu'elle tient même si ce module ment.
"""
import os
import subprocess
from typing import Optional, Tuple

from app.config.docker_config import DockerConfig

#: Répertoire d'installation des helpers. Hors du dépôt délibérément : le
#: dépôt appartient à l'utilisateur applicatif, qui pourrait donc réécrire un
#: script que sudo l'autorise à lancer en root.
ROOT_HELPERS_DIR = os.environ.get('WPL_ROOT_HELPERS_DIR', '/opt/wp-launcher-root')

DEFAULT_TIMEOUT = 300


class RootHelperError(RuntimeError):
    """Un helper racine a échoué ou refusé l'opération."""


def _script(name: str) -> str:
    return os.path.join(ROOT_HELPERS_DIR, name)


def available() -> bool:
    """Les helpers sont-ils installés ?

    Permet aux appelants de retomber sur l'ancien chemin tant que le
    déploiement n'a pas eu lieu, plutôt que d'échouer.
    """
    return os.path.isdir(ROOT_HELPERS_DIR) and os.access(
        _script('wpl-fix-perms.sh'), os.X_OK
    )


def split_project_path(path: str) -> Tuple[str, Optional[str]]:
    """Décompose un chemin absolu en (projet, sous-chemin).

    Lève ``RootHelperError`` si le chemin ne vit pas sous la racine des
    projets — un appelant qui passerait /etc doit échouer ici, pas côté root.
    """
    projects_root = os.path.realpath(DockerConfig.PROJECTS_FOLDER)
    resolved = os.path.realpath(path)

    if resolved == projects_root or not resolved.startswith(projects_root + os.sep):
        raise RootHelperError(f"Chemin hors de {projects_root}: {path}")

    relative = resolved[len(projects_root) + 1:]
    parts = relative.split(os.sep, 1)
    project = parts[0]
    subpath = parts[1] if len(parts) > 1 else None
    return project, subpath


def _run(script: str, args, timeout: int = DEFAULT_TIMEOUT) -> str:
    cmd = ['sudo', '-n', _script(script), *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RootHelperError(f"{script}: délai dépassé ({timeout}s)")
    except (FileNotFoundError, OSError) as exc:
        raise RootHelperError(f"{script}: {exc}")

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip().splitlines()
        raise RootHelperError(
            f"{script}: {detail[-1] if detail else f'code {result.returncode}'}"
        )
    return (result.stdout or '').strip()


# ─── intentions ─────────────────────────────────────────────────────────

def fix_perms(path: str, profile: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Applique un profil de permissions au chemin (voir wpl-fix-perms.sh).

    Profils : shared, www, dev, container, uploads, wp-config-lock,
    wp-config-dev, acl.
    """
    project, subpath = split_project_path(path)
    args = [project, profile] + ([subpath] if subpath else [])
    return _run('wpl-fix-perms.sh', args, timeout)


def delete_project(project_name: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Supprime les dossiers projets/ et containers/ d'un projet."""
    return _run('wpl-delete-project.sh', [project_name], timeout)


def delete_instance(parent_project: str, slug: str, timeout: int = 120) -> str:
    """Supprime une instance de dev."""
    return _run('wpl-delete-instance.sh', [parent_project, slug], timeout)


def copy_wp_content(parent_project: str, slug: str, subdir: str,
                    timeout: int = 600) -> str:
    """Copie un sous-dossier de wp-content du parent vers une instance."""
    return _run('wpl-copy-wp-content.sh', [parent_project, slug, subdir], timeout)


def write_wp_config(project_name: str, source_file: str, timeout: int = 60) -> str:
    """Écrit wp-config.php depuis un temporaire, quand l'app n'a pas les droits."""
    return _run('wpl-write-wp-config.sh', [project_name, source_file], timeout)


def reset_config(project_name: str, kind: str, timeout: int = 60) -> str:
    """Retire un fichier de configuration corrompu. kind : 'php' ou 'mysql'."""
    return _run('wpl-reset-config.sh', [project_name, kind], timeout)
