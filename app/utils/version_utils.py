#!/usr/bin/env python3
"""
Utilitaires pour gérer la version de l'application
"""
import subprocess
import os
from typing import Optional

def get_git_version() -> str:
    """
    Récupère la version depuis le dernier tag Git.
    Si aucun tag n'existe, retourne 'v0.0.0-dev'
    
    Returns:
        str: Version au format 'vX.Y.Z' ou 'vX.Y.Z-commits-hash' si des commits après le tag
    """
    try:
        # Vérifier si on est dans un dépôt Git
        git_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.git')
        if not os.path.exists(git_dir):
            return 'v0.0.0-dev'
        
        # Récupérer le dernier tag
        result = subprocess.run(
            ['git', 'describe', '--tags', '--always', '--dirty'],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(__file__)),
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
                cwd=os.path.dirname(os.path.dirname(__file__)),
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
        'version': get_git_version(),
        'commit_hash': None,
        'branch': None,
        'commit_date': None
    }
    
    try:
        git_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.git')
        if not os.path.exists(git_dir):
            return info
        
        cwd = os.path.dirname(os.path.dirname(__file__))
        
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




