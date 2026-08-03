#!/usr/bin/env python3
"""
Utilitaires pour gérer la version de l'application
"""
import subprocess
import os
from typing import Optional

# Version déclarée de l'application : source de vérité pour l'affichage.
# À incrémenter à chaque release, en cohérence avec le tag Git `vX.Y.Z`
# et l'entrée correspondante du CHANGELOG.
__version__ = "1.4.1"


def get_app_version() -> str:
    """
    Version affichée dans l'interface (ex. 'v1.4.0').

    Volontairement indépendante de Git : `git describe` renvoie des suffixes
    parasites (`-dirty`, `-N-gHASH`) selon l'état du dépôt, et retombe sur
    'v0.0.0-dev' en production où le `.git` est absent.
    """
    return f"v{__version__}"


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




