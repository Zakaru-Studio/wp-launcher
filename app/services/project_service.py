#!/usr/bin/env python3
"""
Service d'orchestration pour la gestion des projets
Fournit une couche d'abstraction pour les opérations sur les projets
"""

import os
from app.models.project import Project
from app.config.docker_config import DockerConfig
from app.utils.logger import wp_logger


class ProjectService:
    """Service d'orchestration pour la gestion des projets"""
    
    def __init__(self, docker_service=None, permission_service=None, database_service=None):
        self.docker = docker_service
        self.permissions = permission_service
        self.database = database_service
        self.projects_folder = DockerConfig.PROJECTS_FOLDER
        self.containers_folder = DockerConfig.CONTAINERS_FOLDER
    
    def get_project_list(self):
        """Récupère la liste des projets"""
        projects = []
        
        if not os.path.exists(self.projects_folder):
            return []
        
        for project_name in os.listdir(self.projects_folder):
            project_path = os.path.join(self.projects_folder, project_name)
            
            if not os.path.isdir(project_path):
                continue
                
            # Ignorer les dossiers marqués comme supprimés
            deleted_marker = os.path.join(project_path, '.DELETED_PROJECT')
            if os.path.exists(deleted_marker):
                continue
            
            projects.append(project_name)
        
        return projects
    
    def get_project_status(self, project_name):
        """Récupère le statut d'un projet"""
        project = Project(project_name, self.projects_folder, self.containers_folder)
        
        if not project.exists:
            return {
                'success': False,
                'message': 'Projet non trouvé',
                'status': 'not_found'
            }
        
        if not project.is_valid:
            return {
                'success': False,
                'message': 'Projet invalide',
                'status': 'invalid'
            }
        
        # Obtenir le statut des conteneurs
        if self.docker:
            container_status = self.docker.get_container_status(project_name)
            return {
                'success': True,
                'status': container_status,
                'project_name': project_name,
                'port': project.port if hasattr(project, 'port') else None
            }
        
        return {
            'success': False,
            'message': 'Service Docker non disponible',
            'status': 'unknown'
        }
    
    def start_project(self, project_name):
        """Démarre un projet"""
        wp_logger.log_operation_start('start', project_name)
        
        project = Project(project_name, self.projects_folder, self.containers_folder)
        
        if not project.exists:
            error_msg = 'Projet non trouvé'
            wp_logger.log_operation_error('start', project_name, error_msg, 
                                        context="Project validation", 
                                        project_path=project.path)
            return {'success': False, 'message': error_msg}
        
        if not project.is_valid:
            error_msg = 'Projet invalide (fichier docker-compose.yml manquant)'
            wp_logger.log_operation_error('start', project_name, error_msg, 
                                        context="Docker compose validation", 
                                        container_path=project.container_path)
            return {'success': False, 'message': error_msg}
        
        # Démarrer les conteneurs
        if self.docker:
            success, error = self.docker.start_containers(project.container_path)
            if success:
                wp_logger.log_operation_success('start', project_name, 
                                              "Conteneurs démarrés avec succès",
                                              container_path=project.container_path)
                
                project_url = f'http://{DockerConfig.LOCAL_IP}:{project.port}'
                
                return {
                    'success': True,
                    'message': f'Projet {project_name} démarré avec succès',
                    'project_url': project_url,
                    'project_name': project_name
                }
            else:
                wp_logger.log_operation_error('start', project_name, f'Erreur Docker: {error}', 
                                            context="Docker container startup", 
                                            container_path=project.container_path)
                return {
                    'success': False,
                    'message': f'Erreur lors du démarrage: {error}'
                }
        else:
            error_msg = 'Service Docker non disponible'
            wp_logger.log_operation_error('start', project_name, error_msg, 
                                        context="Service availability check")
            return {'success': False, 'message': error_msg}
    
    def stop_project(self, project_name):
        """Arrête un projet"""
        wp_logger.log_operation_start('stop', project_name)
        
        project = Project(project_name, self.projects_folder, self.containers_folder)
        
        if not project.exists:
            error_msg = 'Projet non trouvé'
            wp_logger.log_operation_error('stop', project_name, error_msg, 
                                        context="Project validation", 
                                        project_path=project.path)
            return {'success': False, 'message': error_msg}
        
        if not project.is_valid:
            error_msg = 'Projet invalide (fichier docker-compose.yml manquant)'
            wp_logger.log_operation_error('stop', project_name, error_msg, 
                                        context="Docker compose validation", 
                                        container_path=project.container_path)
            return {'success': False, 'message': error_msg}
        
        # Arrêter les conteneurs
        if self.docker:
            success, error = self.docker.stop_containers(project.container_path)
            if success:
                wp_logger.log_operation_success('stop', project_name, 
                                              "Conteneurs arrêtés avec succès",
                                              container_path=project.container_path)
                return {
                    'success': True,
                    'message': f'Projet {project_name} arrêté avec succès'
                }
            else:
                wp_logger.log_operation_error('stop', project_name, f'Erreur Docker: {error}', 
                                            context="Docker container shutdown", 
                                            container_path=project.container_path)
                return {
                    'success': False,
                    'message': f'Erreur lors de l\'arrêt: {error}'
                }
        else:
            error_msg = 'Service Docker non disponible'
            wp_logger.log_operation_error('stop', project_name, error_msg, 
                                        context="Service availability check")
            return {'success': False, 'message': error_msg}
    
    def restart_project(self, project_name):
        """Redémarre un projet"""
        wp_logger.log_operation_start('restart', project_name)
        
        # Vérifier que le projet existe
        project_path = os.path.join(self.containers_folder, project_name)
        if not os.path.exists(project_path):
            return {
                'success': False,
                'message': f'Le projet {project_name} n\'existe pas'
            }
        
        if not self.docker:
            return {
                'success': False,
                'message': 'Service Docker non disponible'
            }
        
        # Arrêter le projet
        print(f"🛑 [RESTART_PROJECT] Arrêt du projet {project_name}...")
        stop_result = self.docker.stop_project(project_name)
        
        if not stop_result['success']:
            return {
                'success': False,
                'message': f'Erreur lors de l\'arrêt: {stop_result["message"]}'
            }
        
        # Démarrer le projet
        print(f"▶️ [RESTART_PROJECT] Démarrage du projet {project_name}...")
        start_result = self.docker.start_project(project_name)
        
        if start_result['success']:
            project_url = f"http://{DockerConfig.LOCAL_IP}:{start_result.get('port', 'unknown')}"
            
            wp_logger.log_operation_success('restart', project_name, 
                                          context=f"Project restarted successfully on port {start_result.get('port')}")
            
            return {
                'success': True,
                'message': f'Projet {project_name} redémarré avec succès',
                'project_url': project_url,
                'details': {
                    'port': start_result.get('port'),
                    'nextjs_port': start_result.get('nextjs_port'),
                    'phpmyadmin_port': start_result.get('phpmyadmin_port'),
                    'mailpit_port': start_result.get('mailpit_port')
                }
            }
        else:
            wp_logger.log_operation_error('restart', project_name, 
                                        Exception(start_result['message']), 
                                        context="Failed to start after stop")
            return {
                'success': False,
                'message': f'Erreur lors du démarrage: {start_result["message"]}'
            }
    
    def delete_project(self, project_name):
        """Supprime un projet"""
        wp_logger.log_operation_start('delete', project_name)
        
        project = Project(project_name, self.projects_folder, self.containers_folder)
        
        if not project.exists:
            return {'success': False, 'message': 'Projet non trouvé'}
        
        try:
            # Arrêter les conteneurs si le service Docker est disponible
            if self.docker and project.is_valid:
                print(f"🛑 Arrêt des conteneurs...")
                self.docker.stop_containers(project.container_path)
            
            # Supprimer les conteneurs et volumes
            if self.docker:
                print(f"🗑️  Suppression des conteneurs et volumes...")
                # Utiliser docker-compose down pour supprimer tout
                import subprocess
                try:
                    subprocess.run(
                        ['docker-compose', 'down', '-v', '--remove-orphans'],
                        cwd=project.container_path,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                except Exception as e:
                    print(f"⚠️ Avertissement lors de la suppression des conteneurs: {e}")
            
            # Supprimer les snapshots du projet
            print(f"📸 Suppression des snapshots du projet {project_name}...")
            self._delete_project_snapshots(project_name)
            
            # Supprimer les dossiers (utiliser le script de suppression sécurisé avec sudo)
            import subprocess
            
            print(f"🗑️  Suppression des dossiers du projet {project_name}...")
            
            # Utiliser le script de suppression sécurisé avec sudo
            script_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                'scripts',
                'delete_project_folders.sh'
            )
            
            try:
                result = subprocess.run(
                    ['sudo', script_path, project_name],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True
                )
                print(result.stdout)
                if result.stderr:
                    print(f"⚠️  Warnings: {result.stderr}")
            except subprocess.CalledProcessError as e:
                print(f"❌ Erreur lors de la suppression: {e.stderr}")
                raise Exception(f"Échec de la suppression des dossiers: {e.stderr}")
            
            wp_logger.log_operation_success('delete', project_name, "Projet supprimé avec succès")
            
            return {
                'success': True,
                'message': f'Projet {project_name} supprimé avec succès'
            }
            
        except Exception as e:
            wp_logger.log_operation_error('delete', project_name, e, 
                                        context="Error during project deletion")
            return {
                'success': False,
                'message': f'Erreur lors de la suppression: {str(e)}'
            }
    
    def _delete_project_snapshots(self, project_name):
        """Supprime tous les snapshots d'un projet"""
        import shutil
        
        snapshots_base_dir = 'snapshots'
        project_snapshots_dir = os.path.join(snapshots_base_dir, project_name)
        
        if os.path.exists(project_snapshots_dir):
            try:
                print(f"  🗑️  Suppression du dossier snapshots: {project_snapshots_dir}")
                shutil.rmtree(project_snapshots_dir)
                print(f"  ✅ Snapshots supprimés")
            except Exception as e:
                print(f"  ⚠️  Erreur suppression snapshots: {e}")
                # Ne pas bloquer la suppression du projet si les snapshots échouent
        else:
            print(f"  ℹ️  Aucun snapshot trouvé pour {project_name}")

