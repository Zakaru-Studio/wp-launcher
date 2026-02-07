#!/usr/bin/env python3
"""
Service de gestion des permissions
Centralise toute la logique de gestion des permissions (chmod/chown)
"""

import os
import subprocess
import pwd
from app.config.docker_config import DockerConfig


class PermissionService:
    """Service pour la gestion des permissions des projets"""
    
    def __init__(self, projects_folder=None):
        self.projects_folder = projects_folder or DockerConfig.PROJECTS_FOLDER
        self.current_user = os.getenv('USER', 'dev-server')
    
    def fix_wp_content_permissions_robust(self, wp_content_path, debug_logger=None):
        """Corriger robustement les permissions wp-content (compatible Docker WordPress)"""
        try:
            if not os.path.exists(wp_content_path):
                return True
            
            if debug_logger:
                debug_logger.step("ROBUST_FIX_PERMISSIONS", f"Fixing permissions for {wp_content_path} (Docker compatible)")
            
            print(f"🔧 [ROBUST] Correction permissions: {wp_content_path}")
            
            # Utiliser www-data comme groupe pour la compatibilité Docker WordPress
            subprocess.run(['sudo', 'chown', '-R', f'{self.current_user}:www-data', wp_content_path], 
                          check=True, capture_output=True)
            
            # Définir les permissions appropriées pour permettre l'écriture par le groupe
            subprocess.run(['find', wp_content_path, '-type', 'd', '-exec', 'chmod', '775', '{}', '+'], 
                          check=True, capture_output=True)
            subprocess.run(['find', wp_content_path, '-type', 'f', '-exec', 'chmod', '664', '{}', '+'], 
                          check=True, capture_output=True)
            
            # S'assurer que uploads existe et a les bonnes permissions
            uploads_dir = os.path.join(wp_content_path, 'uploads')
            if not os.path.exists(uploads_dir):
                os.makedirs(uploads_dir, mode=0o775, exist_ok=True)
                subprocess.run(['sudo', 'chown', f'{self.current_user}:www-data', uploads_dir], 
                              check=True, capture_output=True)
            
            subprocess.run(['sudo', 'chown', '-R', f'{self.current_user}:www-data', uploads_dir], 
                          check=True, capture_output=True)
            subprocess.run(['chmod', '-R', '775', uploads_dir], 
                          check=True, capture_output=True)
            
            print(f"✅ [ROBUST] Permissions appliquées: {self.current_user}:www-data (775/664)")
            
            if debug_logger:
                debug_logger.success("ROBUST_FIX_PERMISSIONS", "Docker-compatible permissions fixed successfully")
            
            return True
            
        except subprocess.CalledProcessError as e:
            if debug_logger:
                debug_logger.warning("ROBUST_FIX_PERMISSIONS", f"Permission fix failed: {e}")
            return False
        except Exception as e:
            if debug_logger:
                debug_logger.error("ROBUST_FIX_PERMISSIONS", f"Unexpected error: {e}")
            return False
    
    def fix_project_permissions(self, project_name):
        """Applique les permissions correctes à un projet existant"""
        from app.utils.project_utils import secure_project_name, get_project_type, apply_automatic_project_permissions
        
        # Sécuriser le nom du projet
        project_name = secure_project_name(project_name)
        
        # Vérifier que le projet existe
        editable_path = os.path.join(self.projects_folder, project_name)
        if not os.path.exists(editable_path):
            return {'success': False, 'message': f'Projet {project_name} non trouvé'}
        
        # Déterminer le type de projet
        project_type = get_project_type(editable_path)
        
        # Appliquer les permissions
        success = apply_automatic_project_permissions(editable_path, project_type)
        
        if success:
            print(f"✅ Permissions corrigées pour {project_name}")
            return {
                'success': True, 
                'message': f'Permissions corrigées pour {project_name}',
                'project_name': project_name
            }
        else:
            print(f"❌ Échec de la correction des permissions pour {project_name}")
            return {
                'success': False, 
                'message': f'Échec de la correction des permissions pour {project_name}'
            }
    
    def fix_permissions_with_docker_stop(self, project_name, docker_service=None):
        """Corrige les permissions d'un projet en arrêtant Docker si nécessaire"""
        from app.models.project import Project
        from app.config.docker_config import DockerConfig
        
        # Vérifier que le projet existe
        project = Project(project_name, DockerConfig.PROJECTS_FOLDER, DockerConfig.CONTAINERS_FOLDER)
        if not project.exists:
            return {'success': False, 'message': 'Projet non trouvé'}
        
        print(f"🔧 [FIX_PERMISSIONS] Correction des permissions pour: {project_name}")
        
        # Obtenir l'utilisateur actuel
        current_user = pwd.getpwuid(os.getuid()).pw_name
        print(f"📋 [FIX_PERMISSIONS] Utilisateur actuel: {current_user}")
        
        # Chemin du projet
        project_path = project.path
        print(f"📂 [FIX_PERMISSIONS] Chemin du projet: {project_path}")
        
        # Arrêter COMPLÈTEMENT le projet pour éviter les conflits
        was_running = False
        if docker_service:
            container_status = docker_service.get_container_status(project_name)
            if container_status == 'active':
                print(f"🛑 [FIX_PERMISSIONS] Arrêt COMPLET du projet...")
                docker_service.stop_containers(project.container_path)
                was_running = True
                
                # Attendre un peu que Docker libère complètement les fichiers
                import time
                time.sleep(2)
                print(f"⏳ [FIX_PERMISSIONS] Attente de libération des fichiers...")
        
        # Corriger les permissions du projet
        success = self._fix_directory_permissions(project_path, f"projet {project_name}", current_user)
        
        # Redémarrer le projet s'il était en cours d'exécution
        if was_running and docker_service:
            print(f"🚀 [FIX_PERMISSIONS] Redémarrage du projet...")
            start_success, start_error = docker_service.start_containers(project.container_path)
            if not start_success:
                print(f"⚠️ [FIX_PERMISSIONS] Erreur lors du redémarrage: {start_error}")
        
        if success:
            return {
                'success': True,
                'message': f'Permissions corrigées avec succès pour {project_name}',
                'details': {
                    'project_path': project_path,
                    'owner': current_user,
                    'restarted': was_running
                }
            }
        else:
            return {
                'success': False,
                'message': f'Erreur lors de la correction des permissions pour {project_name}'
            }
    
    def fix_permissions_simple(self, project_name):
        """Corrige simplement les permissions d'un projet sans vérifications Docker"""
        from app.utils.project_utils import set_project_permissions
        
        project_path = os.path.join(self.projects_folder, project_name)
        print(f"📂 [FIX_PERMISSIONS_SIMPLE] Chemin testé: {project_path}")
        
        if not os.path.exists(project_path):
            return {'success': False, 'message': f'Projet {project_name} non trouvé'}
        
        print(f"🔧 [FIX_PERMISSIONS_SIMPLE] Correction des permissions pour: {project_name}")
        
        # Obtenir l'utilisateur actuel
        current_user = pwd.getpwuid(os.getuid()).pw_name
        print(f"📋 [FIX_PERMISSIONS_SIMPLE] Utilisateur: {current_user}")
        
        # Appliquer les permissions directement
        success = set_project_permissions(project_path, current_user)
        
        if success:
            return {
                'success': True,
                'message': f'Permissions corrigées avec succès pour {project_name}',
                'details': {
                    'project_path': project_path,
                    'owner': current_user
                }
            }
        else:
            return {
                'success': False,
                'message': f'Erreur lors de la correction des permissions pour {project_name}'
            }
    
    def fix_wordpress_permissions(self, project_name):
        """Corrige les permissions WordPress pour www-data (wp-content, uploads, plugins, themes)"""
        from app.utils.project_utils import secure_project_name
        
        # Sécuriser le nom du projet
        project_name = secure_project_name(project_name)
        
        # Chemin du projet
        project_path = os.path.join(self.projects_folder, project_name)
        
        print(f"🔧 [FIX_WP_PERMISSIONS] Correction permissions WordPress pour: {project_name}")
        print(f"📂 [FIX_WP_PERMISSIONS] Chemin: {project_path}")
        
        if not os.path.exists(project_path):
            return {
                'success': False,
                'message': f'Projet {project_name} non trouvé'
            }
        
        # Chemin wp-content
        wp_content_path = os.path.join(project_path, 'wp-content')
        
        if not os.path.exists(wp_content_path):
            return {
                'success': False,
                'message': f'Le dossier wp-content n\'existe pas pour ce projet'
            }
        
        # Exécuter les commandes de correction de permissions
        commands_executed = []
        errors = []
        
        try:
            # 1. Corriger le propriétaire de wp-content
            result = subprocess.run(
                ['sudo', 'chown', 'www-data:www-data', wp_content_path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                commands_executed.append('chown www-data:www-data wp-content')
                print(f"✅ Propriétaire wp-content changé")
            else:
                errors.append(f'chown wp-content: {result.stderr}')
            
            # 2. Chmod wp-content
            result = subprocess.run(
                ['sudo', 'chmod', '775', wp_content_path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                commands_executed.append('chmod 775 wp-content')
                print(f"✅ Permissions wp-content modifiées")
            else:
                errors.append(f'chmod wp-content: {result.stderr}')
            
            # 3. Corriger récursivement tous les sous-dossiers WordPress nécessaires
            wp_subdirs = ['uploads', 'plugins', 'themes', 'upgrade', 'updraft', 'cache', 'languages', 'mu-plugins', 'wflogs']
            for subdir in wp_subdirs:
                subdir_path = os.path.join(wp_content_path, subdir)
                if os.path.exists(subdir_path):
                    self._fix_subdirectory_permissions(subdir_path, subdir, commands_executed, errors)
            
            # Résumé
            if errors:
                print(f"⚠️ [FIX_WP_PERMISSIONS] Corrections avec erreurs: {len(errors)} erreur(s)")
                return {
                    'success': False,
                    'message': f'Permissions partiellement corrigées avec {len(errors)} erreur(s)',
                    'commands_executed': commands_executed,
                    'errors': errors
                }
            else:
                print(f"✅ [FIX_WP_PERMISSIONS] Toutes les permissions corrigées avec succès")
                return {
                    'success': True,
                    'message': f'Permissions WordPress corrigées avec succès pour {project_name}',
                    'commands_executed': commands_executed
                }
        
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'message': 'Timeout lors de la correction des permissions'
            }
        except Exception as e:
            print(f"❌ [FIX_WP_PERMISSIONS] Erreur: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'message': f'Erreur lors de la correction: {str(e)}'
            }
    
    def _fix_directory_permissions(self, path, description, current_user):
        """Fonction helper pour corriger les permissions d'un dossier"""
        try:
            print(f"🔧 [FIX_PERMISSIONS] Correction de {description}: {path}")
            
            # Propriétaire: current_user:www-data pour compatibilité Docker WordPress
            result = subprocess.run([
                'sudo', 'chown', '-R', f'{current_user}:www-data', path
            ], capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                print(f"✅ [FIX_PERMISSIONS] Propriétaire modifié pour {description} ({current_user}:www-data)")
            else:
                print(f"⚠️ [FIX_PERMISSIONS] Erreur chown pour {description}: {result.stderr}")
                return False

            # Permissions des dossiers (775 - www-data peut écrire)
            result = subprocess.run([
                'find', path, '-type', 'd', '-exec', 'chmod', '775', '{}', '+'
            ], capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                print(f"✅ [FIX_PERMISSIONS] Permissions dossiers 775 pour {description}")
            else:
                print(f"⚠️ [FIX_PERMISSIONS] Erreur permissions dossiers: {result.stderr}")

            # Permissions des fichiers (664 - www-data peut écrire)
            result = subprocess.run([
                'find', path, '-type', 'f', '-exec', 'chmod', '664', '{}', '+'
            ], capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                print(f"✅ [FIX_PERMISSIONS] Permissions fichiers 664 pour {description}")
            else:
                print(f"⚠️ [FIX_PERMISSIONS] Erreur permissions fichiers: {result.stderr}")
            
            return True
            
        except subprocess.TimeoutExpired:
            print(f"❌ [FIX_PERMISSIONS] Timeout lors de la correction de {description}")
            return False
        except Exception as e:
            print(f"❌ [FIX_PERMISSIONS] Erreur lors de la correction de {description}: {e}")
            return False
    
    def _fix_subdirectory_permissions(self, path, name, commands_executed, errors):
        """Fonction helper pour corriger les permissions d'un sous-dossier WordPress"""
        result = subprocess.run(
            ['sudo', 'chown', '-R', 'www-data:www-data', path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            commands_executed.append(f'chown -R www-data:www-data {name}')
            print(f"✅ Propriétaire {name} changé récursivement")
        else:
            errors.append(f'chown {name}: {result.stderr}')
        
        result = subprocess.run(
            ['sudo', 'chmod', '-R', '775', path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            commands_executed.append(f'chmod -R 775 {name}')
            print(f"✅ Permissions {name} modifiées récursivement")
        else:
            errors.append(f'chmod {name}: {result.stderr}')
    
    def set_directory_permissions(self, path, user, group, mode):
        """Définit les permissions d'un répertoire de manière générique"""
        try:
            # Changer le propriétaire
            subprocess.run(['sudo', 'chown', '-R', f'{user}:{group}', path], 
                          check=True, capture_output=True, timeout=30)
            
            # Changer les permissions
            subprocess.run(['sudo', 'chmod', '-R', mode, path], 
                          check=True, capture_output=True, timeout=30)
            
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"❌ Erreur lors de la définition des permissions: {e}")
            return False
    
    def set_file_permissions_recursive(self, path, dir_mode, file_mode):
        """Définit les permissions des fichiers et dossiers récursivement"""
        try:
            # Permissions des dossiers
            subprocess.run(['find', path, '-type', 'd', '-exec', 'chmod', dir_mode, '{}', '+'], 
                          check=True, capture_output=True, timeout=30)
            
            # Permissions des fichiers
            subprocess.run(['find', path, '-type', 'f', '-exec', 'chmod', file_mode, '{}', '+'], 
                          check=True, capture_output=True, timeout=30)
            
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"❌ Erreur lors de la définition des permissions récursives: {e}")
            return False


