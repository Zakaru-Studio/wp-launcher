#!/usr/bin/env python3
"""
Utilitaires pour gérer la version de l'application
"""
import subprocess
import time
import os
from typing import Optional

# Repli de dernier recours, utilisé seulement si ni l'archive ni le dépôt Git
# ne renseignent la version. Le CI vérifie qu'il correspond au tag publié
# (job `version` de .github/workflows/ci.yml), donc il ne peut pas dériver en
# silence.
__version__ = "1.6.0"

# Fichier porteur du jeton de substitution. `git archive` y remplace
# $Format:%(describe:tags)$ par le tag du commit archivé — y compris pour les
# archives générées automatiquement par GitHub sur une release.
_VERSION_FILE = os.path.join(os.path.dirname(__file__), '_version.txt')

# Marqueur d'un jeton NON substitué : présent tant qu'on lit le fichier
# depuis un dépôt Git plutôt que depuis une archive.
_UNSUBSTITUTED = '$Format:'


def _version_from_archive() -> Optional[str]:
    """Version injectée par `git archive` à la création de l'archive."""
    try:
        with open(_VERSION_FILE, 'r') as handle:
            value = handle.read().strip()
    except OSError:
        return None
    if not value or value.startswith(_UNSUBSTITUTED):
        return None
    return value


def _version_from_git() -> Optional[str]:
    """Dernier tag atteignable, sans suffixe.

    `--abbrev=0` volontairement : `git describe` seul ajoute `-N-gHASH` et
    `-dirty` selon l'état de l'arbre, ce qui n'a pas sa place dans une version
    affichée à l'utilisateur.
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    if not os.path.exists(os.path.join(root_dir, '.git')):
        return None
    try:
        result = subprocess.run(
            ['git', 'describe', '--tags', '--abbrev=0'],
            capture_output=True, text=True, cwd=root_dir, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


#: Cache de la version résolue : (valeur, instant). `git describe` lance un
#: sous-processus, inutile de le refaire à chaque rendu de page — mais la
#: figer à l'import l'afficherait périmée après une mise à jour.
_cache: tuple = (None, 0.0)
_CACHE_TTL_SECONDS = 30


def get_app_version(refresh: bool = False) -> str:
    """
    Version affichée dans l'interface (ex. 'v1.5.0').

    Trois sources, de la plus fiable à la moins fiable :

    1. la substitution faite par `git archive` — c'est le cas d'une release
       téléchargée, où le `.git` est absent ;
    2. le dernier tag du dépôt, pour une installation clonée ;
    3. la constante déclarée, si aucune des deux n'est disponible.

    L'ensemble suit donc le tag automatiquement : publier `v1.5.1` suffit à
    faire changer la version affichée, sans édition de code.

    Le résultat est mis en cache 30 s. Assez pour ne pas relancer
    `git describe` à chaque rendu de page, assez court pour qu'un changement
    de tag se voie sans redémarrer le processus.
    """
    global _cache
    cached, fetched_at = _cache
    if cached and not refresh and (time.monotonic() - fetched_at) < _CACHE_TTL_SECONDS:
        return cached

    version = _version_from_archive() or _version_from_git()
    resolved = (
        (version if version.startswith('v') else f'v{version}')
        if version else f"v{__version__}"
    )
    _cache = (resolved, time.monotonic())
    return resolved


def get_git_version() -> str:
    """
    Récupère la version depuis le dernier tag Git.
    Si aucun tag n'existe, retourne 'v0.0.0-dev'
    
    Returns:
        str: Version au format 'vX.Y.Z' ou 'vX.Y.Z-commits-hash' si des commits après le tag
    """
    try:
        # Vérifier si on est dans un dépôt Git
        # app/utils/ -> app/ -> racine du projet
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        git_dir = os.path.join(root_dir, '.git')
        if not os.path.exists(git_dir):
            return 'v0.0.0-dev'

        # Récupérer le dernier tag
        result = subprocess.run(
            ['git', 'describe', '--tags', '--always', '--dirty'],
            capture_output=True,
            text=True,
            cwd=root_dir,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            version = result.stdout.strip()
            
            # Si le résultat ne commence pas par 'v', l'ajouter
            if not version.startswith('v'):
                # C'est probablement juste un hash de commit
                return f'v0.0.0-dev-{version[:7]}'
            
            return version
        else:
            # Essayer de récupérer au moins le hash du commit actuel
            hash_result = subprocess.run(
                ['git', 'rev-parse', '--short', 'HEAD'],
                capture_output=True,
                text=True,
                cwd=root_dir,
                timeout=5
            )

            if hash_result.returncode == 0 and hash_result.stdout.strip():
                return f'v0.0.0-dev-{hash_result.stdout.strip()}'
            
            return 'v0.0.0-dev'
            
    except subprocess.TimeoutExpired:
        print("⚠️ Timeout lors de la récupération de la version Git")
        return 'v0.0.0-dev'
    except FileNotFoundError:
        print("⚠️ Git n'est pas installé ou pas accessible")
        return 'v0.0.0-dev'
    except Exception as e:
        print(f"⚠️ Erreur lors de la récupération de la version Git: {e}")
        return 'v0.0.0-dev'

def get_version_info() -> dict:
    """
    Récupère les informations détaillées de version
    
    Returns:
        dict: Dictionnaire avec version, commit_hash, branch, etc.
    """
    info = {
        'version': get_app_version(),
        # État Git conservé à titre de diagnostic (peut différer de la
        # version déclarée si le dépôt n'est pas taggé / arbre modifié).
        'git_describe': get_git_version(),
        'commit_hash': None,
        'branch': None,
        'commit_date': None
    }
    
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        git_dir = os.path.join(root_dir, '.git')
        if not os.path.exists(git_dir):
            return info

        cwd = root_dir
        
        # Hash du commit
        hash_result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5
        )
        if hash_result.returncode == 0:
            info['commit_hash'] = hash_result.stdout.strip()
        
        # Branche actuelle
        branch_result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5
        )
        if branch_result.returncode == 0:
            info['branch'] = branch_result.stdout.strip()
        
        # Date du dernier commit
        date_result = subprocess.run(
            ['git', 'log', '-1', '--format=%ci'],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5
        )
        if date_result.returncode == 0:
            info['commit_date'] = date_result.stdout.strip()
            
    except Exception as e:
        print(f"⚠️ Erreur lors de la récupération des infos de version: {e}")
    
    return info




