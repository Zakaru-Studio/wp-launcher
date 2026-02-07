#!/usr/bin/env python3
"""
Service Git pour détecter et gérer les dépôts Git dans les projets
"""

import os
import subprocess
from typing import List, Dict


class GitService:
    """Service pour gérer les opérations Git dans les projets"""
    
    def detect_git_directories(self, project_path: str) -> List[Dict]:
        """
        Détecte tous les dossiers .git dans un projet
        
        Args:
            project_path: Chemin absolu du projet
            
        Returns:
            Liste de dict avec {path: str, relative_path: str}
        """
        git_dirs = []
        
        try:
            for root, dirs, files in os.walk(project_path):
                if '.git' in dirs:
                    relative_path = os.path.relpath(root, project_path)
                    git_dirs.append({
                        'path': root,
                        'relative_path': relative_path if relative_path != '.' else '/'
                    })
                    # Ne pas descendre dans .git
                    dirs.remove('.git')
            
            return git_dirs
            
        except Exception as e:
            print(f"❌ [GIT] Erreur détection Git: {e}")
            return []
    
    def get_git_status(self, git_dir: str) -> Dict:
        """
        Récupère le statut Git d'un dépôt
        
        Args:
            git_dir: Chemin du dossier contenant .git
            
        Returns:
            Dict avec {commit, branch, status, uncommitted_files}
        """
        try:
            # Commit actuel
            commit_result = subprocess.run(
                ['git', 'log', '-1', '--format=%H|%s'],
                cwd=git_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            commit_info = "unknown"
            commit_message = ""
            if commit_result.returncode == 0 and commit_result.stdout.strip():
                parts = commit_result.stdout.strip().split('|', 1)
                commit_info = parts[0][:7]  # Short hash
                commit_message = parts[1] if len(parts) > 1 else ""
            
            # Branche actuelle
            branch_result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=git_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
            
            # Statut (fichiers modifiés)
            status_result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=git_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            uncommitted_files = []
            if status_result.returncode == 0:
                lines = status_result.stdout.strip().split('\n')
                uncommitted_files = [line.strip() for line in lines if line.strip()]
            
            is_clean = len(uncommitted_files) == 0
            
            return {
                'commit': commit_info,
                'commit_message': commit_message,
                'branch': branch,
                'status': 'clean' if is_clean else 'modified',
                'uncommitted_files': uncommitted_files
            }
            
        except subprocess.TimeoutExpired:
            return {
                'commit': 'timeout',
                'commit_message': '',
                'branch': 'unknown',
                'status': 'error',
                'uncommitted_files': []
            }
        except Exception as e:
            print(f"❌ [GIT] Erreur statut Git pour {git_dir}: {e}")
            return {
                'commit': 'error',
                'commit_message': '',
                'branch': 'unknown',
                'status': 'error',
                'uncommitted_files': []
            }
    
    def is_clean(self, git_dir: str) -> bool:
        """Vérifie si un dépôt Git est propre (pas de modif non commises)"""
        status = self.get_git_status(git_dir)
        return status['status'] == 'clean'
    
    def get_uncommitted_files(self, git_dir: str) -> List[str]:
        """Récupère la liste des fichiers modifiés non commités"""
        status = self.get_git_status(git_dir)
        return status['uncommitted_files']


