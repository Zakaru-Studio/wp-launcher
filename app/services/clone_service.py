#!/usr/bin/env python3
"""
Service de clonage de projets WordPress
"""

import os
import shutil
import json
from typing import Dict, Optional
from app.models.project import Project
from app.config.docker_config import DockerConfig
from app.utils.project_utils import secure_project_name
from app.utils.port_utils import find_free_port_for_project


class CloneService:
    """Service pour cloner des projets WordPress existants"""
    
    def __init__(self, docker_service=None, database_service=None, wpcli_service=None):
        """
        Initialise le service de clonage
        
        Args:
            docker_service: Service Docker pour gérer les conteneurs
            database_service: Service de base de données pour export/import
            wpcli_service: Service WP-CLI pour search-replace
        """
        self.docker = docker_service
        self.database = database_service
        self.wpcli = wpcli_service
        self.projects_folder = DockerConfig.PROJECTS_FOLDER
        self.containers_folder = DockerConfig.CONTAINERS_FOLDER
    
    def validate_clone_params(self, source_name: str, target_name: str) -> Dict:
        """
        Valide les paramètres de clonage
        
        Args:
            source_name: Nom du projet source
            target_name: Nom du projet cible
            
        Returns:
            Dict avec {valid: bool, reason: str}
        """
        # Vérifier que le projet source existe
        source_project = Project(source_name, self.projects_folder, self.containers_folder)
        if not source_project.exists:
            return {
                'valid': False,
                'reason': f'Le projet source "{source_name}" n\'existe pas'
            }
        
        # Sécuriser le nom cible
        safe_target_name = secure_project_name(target_name)
        
        # Vérifier que le projet cible n'existe pas
        target_project = Project(safe_target_name, self.projects_folder, self.containers_folder)
        if target_project.exists:
            return {
                'valid': False,
                'reason': f'Le projet "{safe_target_name}" existe déjà'
            }
        
        # Vérifier l'espace disque
        source_size = self._get_directory_size(source_project.path)
        free_space = shutil.disk_usage(self.projects_folder).free
        
        if source_size * 1.5 > free_space:  # Besoin de 150% de l'espace source
            return {
                'valid': False,
                'reason': f'Espace disque insuffisant (besoin: {source_size * 1.5 / 1024 / 1024:.1f}MB, disponible: {free_space / 1024 / 1024:.1f}MB)'
            }
        
        return {
            'valid': True,
            'reason': '',
            'safe_target_name': safe_target_name
        }
    
    def clone_project(self, source_name: str, target_name: str, options: Dict = None) -> Dict:
        """
        Clone un projet complet
        
        Args:
            source_name: Nom du projet source
            target_name: Nom du projet cible
            options: Options de clonage {
                'clone_database': bool - Cloner la base de données (défaut: True)
                'clone_plugins': bool - Cloner les plugins (défaut: True)
                'clone_themes': bool - Cloner les thèmes (défaut: True)
                'clone_uploads': bool - Cloner les uploads (défaut: False)
            }
            
        Returns:
            Dict avec {success: bool, message: str, project_info: dict}
        """
        if options is None:
            options = {}
        
        clone_database = options.get('clone_database', True)
        clone_plugins = options.get('clone_plugins', True)
        clone_themes = options.get('clone_themes', True)
        clone_uploads = options.get('clone_uploads', False)
        
        try:
            print(f"🔄 [CLONE] Début du clonage: {source_name} → {target_name}")
            
            # Validation
            validation = self.validate_clone_params(source_name, target_name)
            if not validation['valid']:
                return {
                    'success': False,
                    'message': validation['reason']
                }
            
            target_name = validation['safe_target_name']
            
            # Étape 1: Copier les fichiers du projet
            print(f"📁 [CLONE] Copie des fichiers projet...")
            copy_result = self._copy_project_files(source_name, target_name, clone_plugins, clone_themes, clone_uploads)
            if not copy_result['success']:
                return copy_result
            
            # Étape 2: Copier la configuration Docker
            print(f"🐳 [CLONE] Copie de la configuration Docker...")
            config_result = self._copy_container_config(source_name, target_name)
            if not config_result['success']:
                self._cleanup_failed_clone(target_name)
                return config_result
            
            # Étape 3: Attribuer de nouveaux ports
            print(f"🔌 [CLONE] Attribution de nouveaux ports...")
            ports_result = self._assign_new_ports(target_name)
            if not ports_result['success']:
                self._cleanup_failed_clone(target_name)
                return ports_result
            
            # Étape 4: Mettre à jour docker-compose.yml
            print(f"⚙️ [CLONE] Mise à jour docker-compose.yml...")
            compose_result = self._update_docker_compose(target_name, ports_result['ports'])
            if not compose_result['success']:
                self._cleanup_failed_clone(target_name)
                return compose_result
            
            # Étape 5: Cloner la base de données (optionnel)
            if clone_database:
                print(f"💾 [CLONE] Clonage de la base de données...")
                db_result = self._clone_database(source_name, target_name, ports_result['ports'])
                if not db_result['success']:
                    print(f"⚠️ [CLONE] Échec du clonage DB, mais projet créé")
                    # Ne pas échouer complètement, juste avertir
            
            # Étape 6: Mettre à jour wp-config.php avec les nouvelles URLs
            print(f"🔧 [CLONE] Mise à jour wp-config.php...")
            self._update_wp_config(target_name, ports_result['ports'])
            
            # Étape 7: Fixer les permissions
            print(f"🔐 [CLONE] Correction des permissions...")
            self._fix_permissions(target_name)
            
            print(f"✅ [CLONE] Clonage terminé avec succès!")
            
            # Informations du projet cloné
            target_project = Project(target_name, self.projects_folder, self.containers_folder)
            
            return {
                'success': True,
                'message': f'Projet cloné avec succès: {source_name} → {target_name}',
                'project_info': {
                    'name': target_name,
                    'ports': ports_result['ports'],
                    'urls': self._generate_urls(target_name, ports_result['ports']),
                    'database_cloned': clone_database,
                    'uploads_cloned': clone_uploads
                }
            }
            
        except Exception as e:
            print(f"❌ [CLONE] Erreur: {e}")
            import traceback
            traceback.print_exc()
            self._cleanup_failed_clone(target_name)
            return {
                'success': False,
                'message': f'Erreur lors du clonage: {str(e)}'
            }
    
    def _copy_project_files(self, source_name: str, target_name: str, clone_plugins: bool = True, clone_themes: bool = True, clone_uploads: bool = False) -> Dict:
        """Copie les fichiers du projet"""
        try:
            source_path = os.path.join(self.projects_folder, source_name)
            target_path = os.path.join(self.projects_folder, target_name)
            
            # Créer le dossier cible
            os.makedirs(target_path, exist_ok=True)
            
            # Exclusions par défaut
            exclude_patterns = ['.git', 'node_modules', '__pycache__', '*.pyc']
            
            # Exclusions conditionnelles
            if not clone_plugins:
                exclude_patterns.append('wp-content/plugins')
            if not clone_themes:
                exclude_patterns.append('wp-content/themes')
            if not clone_uploads:
                exclude_patterns.append('wp-content/uploads')
            
            # Copier récursivement
            self._copy_directory_selective(source_path, target_path, exclude_patterns)
            
            return {'success': True}
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur copie fichiers: {str(e)}'
            }
    
    def _copy_container_config(self, source_name: str, target_name: str) -> Dict:
        """Copie la configuration Docker"""
        try:
            source_path = os.path.join(self.containers_folder, source_name)
            target_path = os.path.join(self.containers_folder, target_name)
            
            # Copier tout le dossier container
            shutil.copytree(source_path, target_path)
            
            return {'success': True}
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur copie config Docker: {str(e)}'
            }
    
    def _assign_new_ports(self, project_name: str) -> Dict:
        """Attribue de nouveaux ports au projet cloné"""
        try:
            # Récupérer les ports réellement utilisés (conteneurs actifs uniquement)
            import subprocess
            import re
            
            used_ports = set()
            
            # Récupérer les ports des conteneurs Docker actifs
            try:
                result = subprocess.run(
                    ['docker', 'ps', '--format', '{{.Ports}}'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in result.stdout.strip().split('\n'):
                    if line:
                        port_matches = re.findall(r'0\.0\.0\.0:(\d+)->', line)
                        used_ports.update(int(port) for port in port_matches)
            except Exception as e:
                print(f"⚠️ [CLONE] Erreur récupération ports Docker: {e}")
            
            # Ajouter les ports des fichiers .port existants (pour les projets arrêtés)
            containers_folder = self.containers_folder
            if os.path.exists(containers_folder):
                for proj in os.listdir(containers_folder):
                    proj_path = os.path.join(containers_folder, proj)
                    if os.path.isdir(proj_path):
                        for port_file in ['.port', '.pma_port', '.mailpit_port', '.smtp_port']:
                            port_file_path = os.path.join(proj_path, port_file)
                            if os.path.exists(port_file_path):
                                try:
                                    with open(port_file_path, 'r') as f:
                                        port = int(f.read().strip())
                                        used_ports.add(port)
                                except:
                                    pass
            
            print(f"🔍 [CLONE] Ports utilisés détectés: {sorted(list(used_ports))[:20]}...")
            
            # Trouver des ports libres pour chaque service
            def find_free_port(start_range: int) -> int:
                for port in range(start_range, start_range + 1000):
                    if port not in used_ports:
                        used_ports.add(port)
                        print(f"✅ [CLONE] Port libre trouvé: {port}")
                        return port
                raise Exception(f"Aucun port libre trouvé dans la plage {start_range}")
            
            ports = {
                'wordpress': find_free_port(8000),
                'phpmyadmin': find_free_port(8100),
                'mailpit': find_free_port(8200),
                'smtp': find_free_port(1025)
            }
            
            # Sauvegarder les ports
            self._save_project_ports(project_name, ports)
            
            return {
                'success': True,
                'ports': ports
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur attribution ports: {str(e)}'
            }
    
    def _update_docker_compose(self, project_name: str, ports: Dict) -> Dict:
        """Met à jour le docker-compose.yml avec le nouveau nom et ports"""
        try:
            compose_file = os.path.join(self.containers_folder, project_name, 'docker-compose.yml')
            
            if not os.path.exists(compose_file):
                return {
                    'success': False,
                    'message': 'Fichier docker-compose.yml non trouvé'
                }
            
            # Lire le contenu
            with open(compose_file, 'r') as f:
                content = f.read()
            
            # Remplacer le nom du projet dans les noms de conteneurs
            # Pattern: container_name: old-project_service_1 -> container_name: new-project_service_1
            import re
            
            # Extraire l'ancien nom de projet depuis les container_name existants
            old_project_match = re.search(r'container_name:\s*["\']?([^_"\']+)_\w+_\d+["\']?', content)
            if old_project_match:
                old_project_name = old_project_match.group(1)
                # Remplacer tous les noms de conteneurs
                content = re.sub(
                    rf'container_name:\s*["\']?{re.escape(old_project_name)}_(\w+)_(\d+)["\']?',
                    f'container_name: {project_name}_\\1_\\2',
                    content
                )
            
            # Remplacer le nom du projet dans les variables
            content = content.replace('PROJECT_NAME', project_name)
            content = content.replace('{project_name}', project_name)
            
            # Remplacer les ports dans les variables
            content = content.replace('{wordpress_port}', str(ports['wordpress']))
            content = content.replace('{phpmyadmin_port}', str(ports['phpmyadmin']))
            content = content.replace('{mailpit_port}', str(ports['mailpit']))
            content = content.replace('{smtp_port}', str(ports['smtp']))
            
            # Remplacer TOUS les ports de manière simple et directe
            # Format: "0.0.0.0:PORT:80" ou "PORT:80"
            
            # Remplacer tous les mappings de port vers 80 (WordPress et PhpMyAdmin)
            # On garde une liste des ports trouvés pour les remplacer dans l'ordre
            port_mappings_80 = re.findall(r'"(?:0\.0\.0\.0:)?(\d+):80"', content)
            if len(port_mappings_80) >= 2:
                # Premier port :80 trouvé = WordPress
                content = re.sub(
                    rf'"(?:0\.0\.0\.0:)?{port_mappings_80[0]}:80"',
                    f'"0.0.0.0:{ports["wordpress"]}:80"',
                    content,
                    count=1
                )
                # Deuxième port :80 trouvé = PhpMyAdmin
                content = re.sub(
                    rf'"(?:0\.0\.0\.0:)?{port_mappings_80[1]}:80"',
                    f'"0.0.0.0:{ports["phpmyadmin"]}:80"',
                    content,
                    count=1
                )
            
            # Remplacer les ports Mailpit (8025 pour web UI, 1025 pour SMTP)
            content = re.sub(r'"(?:0\.0\.0\.0:)?(\d+):8025"', f'"0.0.0.0:{ports["mailpit"]}:8025"', content)
            content = re.sub(r'"(?:0\.0\.0\.0:)?(\d+):1025"', f'"0.0.0.0:{ports["smtp"]}:1025"', content)
            
            # Remplacer aussi les URLs dans les variables d'environnement
            # WP_HOME, PMA_ABSOLUTE_URI, etc.
            if len(port_mappings_80) >= 1:
                content = re.sub(
                    rf'http://192\.168\.1\.21:{port_mappings_80[0]}',
                    f'http://{DockerConfig.LOCAL_IP}:{ports["wordpress"]}',
                    content
                )
            if len(port_mappings_80) >= 2:
                content = re.sub(
                    rf'http://192\.168\.1\.21:{port_mappings_80[1]}',
                    f'http://{DockerConfig.LOCAL_IP}:{ports["phpmyadmin"]}',
                    content
                )
            
            # Remplacer les chemins qui pointent vers le projet source
            content = re.sub(
                rf'/projets/{re.escape(old_project_name)}/',
                f'/projets/{project_name}/',
                content
            )
            
            # Écrire le fichier mis à jour
            with open(compose_file, 'w') as f:
                f.write(content)
            
            print(f"✅ [CLONE] docker-compose.yml mis à jour pour {project_name}")
            
            return {'success': True}
            
        except Exception as e:
            print(f"❌ [CLONE] Erreur mise à jour docker-compose: {e}")
            return {
                'success': False,
                'message': f'Erreur mise à jour docker-compose: {str(e)}'
            }
    
    def _clone_database(self, source_name: str, target_name: str, ports: Dict) -> Dict:
        """Clone la base de données et effectue le search-replace"""
        try:
            if not self.wpcli:
                return {
                    'success': False,
                    'message': 'Service WP-CLI non disponible'
                }
            
            # Démarrer le conteneur cible pour avoir une DB vide
            if self.docker:
                container_path = os.path.join(self.containers_folder, target_name)
                self.docker.start_containers(container_path)
                
                # Attendre que MySQL soit prêt
                import time
                time.sleep(10)
            
            # Export DB source
            print(f"📤 [CLONE] Export de la DB source...")
            export_file = f"/tmp/{source_name}_clone_export.sql"
            export_result = self.wpcli.execute_command(source_name, f'db export {export_file}')
            
            if not export_result['success']:
                return {
                    'success': False,
                    'message': f'Erreur export DB: {export_result["error"]}'
                }
            
            # Import DB cible
            print(f"📥 [CLONE] Import dans la DB cible...")
            # Copier le fichier SQL dans le conteneur cible
            import subprocess
            container_name = f"{target_name}_wordpress_1"
            subprocess.run([
                'docker', 'cp',
                export_file,
                f'{container_name}:{export_file}'
            ], check=True)
            
            import_result = self.wpcli.execute_command(target_name, f'db import {export_file}')
            
            if not import_result['success']:
                return {
                    'success': False,
                    'message': f'Erreur import DB: {import_result["error"]}'
                }
            
            # Search-replace des URLs
            print(f"🔄 [CLONE] Search-replace des URLs...")
            source_url = f"http://{DockerConfig.LOCAL_IP}:{self._get_source_port(source_name)}"
            target_url = f"http://{DockerConfig.LOCAL_IP}:{ports['wordpress']}"
            
            sr_result = self.wpcli.search_replace(target_name, source_url, target_url, dry_run=False)
            
            if not sr_result['success']:
                print(f"⚠️ [CLONE] Warning: Search-replace a échoué: {sr_result.get('error')}")
            
            # Nettoyer le fichier temporaire
            try:
                os.remove(export_file)
            except:
                pass
            
            return {'success': True}
            
        except Exception as e:
            print(f"❌ [CLONE] Erreur clonage DB: {e}")
            return {
                'success': False,
                'message': f'Erreur clonage DB: {str(e)}'
            }
    
    def _get_source_port(self, source_name: str) -> int:
        """Récupère le port WordPress du projet source"""
        port_file = os.path.join(self.containers_folder, source_name, '.port')
        try:
            with open(port_file, 'r') as f:
                return int(f.read().strip())
        except:
            return 8000
    
    def _save_project_ports(self, project_name: str, ports: Dict):
        """Sauvegarde les ports du projet"""
        container_path = os.path.join(self.containers_folder, project_name)
        
        # Sauvegarder chaque port dans son fichier
        for key, port in ports.items():
            if key == 'wordpress':
                file_name = '.port'
            else:
                file_name = f'.{key}_port'
            
            port_file = os.path.join(container_path, file_name)
            with open(port_file, 'w') as f:
                f.write(str(port))
    
    def _update_wp_config(self, project_name: str, ports: Dict):
        """Met à jour wp-config.php avec les nouvelles URLs"""
        try:
            wp_config_path = os.path.join(self.projects_folder, project_name, 'wp-config.php')
            
            if not os.path.exists(wp_config_path):
                print(f"⚠️ [CLONE] wp-config.php non trouvé")
                return
            
            # Lire le fichier
            with open(wp_config_path, 'r') as f:
                content = f.read()
            
            # Construire les nouvelles URLs
            new_url = f"http://{DockerConfig.LOCAL_IP}:{ports['wordpress']}"
            new_content_url = f"http://{DockerConfig.LOCAL_IP}:{ports['wordpress']}/wp-content"
            
            print(f"🔧 [CLONE] Mise à jour wp-config.php:")
            print(f"   - WP_HOME: {new_url}")
            print(f"   - WP_SITEURL: {new_url}")
            print(f"   - WP_CONTENT_URL: {new_content_url}")
            
            import re
            
            # Mettre à jour WP_HOME
            if "define( 'WP_HOME'" in content or "define('WP_HOME'" in content:
                content = re.sub(
                    r"define\s*\(\s*['\"]WP_HOME['\"]\s*,\s*['\"][^'\"]+['\"]\s*\)\s*;",
                    f"define( 'WP_HOME', '{new_url}' );",
                    content
                )
                print(f"✅ [CLONE] WP_HOME mis à jour")
            else:
                # Ajouter WP_HOME si inexistant
                php_tag_pos = content.find('<?php')
                if php_tag_pos != -1:
                    insert_pos = content.find('\n', php_tag_pos) + 1
                    content = content[:insert_pos] + f"\ndefine( 'WP_HOME', '{new_url}' );\n" + content[insert_pos:]
                    print(f"✅ [CLONE] WP_HOME ajouté")
            
            # Mettre à jour WP_SITEURL
            if "define( 'WP_SITEURL'" in content or "define('WP_SITEURL'" in content:
                content = re.sub(
                    r"define\s*\(\s*['\"]WP_SITEURL['\"]\s*,\s*['\"][^'\"]+['\"]\s*\)\s*;",
                    f"define( 'WP_SITEURL', '{new_url}' );",
                    content
                )
                print(f"✅ [CLONE] WP_SITEURL mis à jour")
            else:
                # Ajouter WP_SITEURL si inexistant
                php_tag_pos = content.find('<?php')
                if php_tag_pos != -1:
                    insert_pos = content.find('\n', php_tag_pos) + 1
                    content = content[:insert_pos] + f"\ndefine( 'WP_SITEURL', '{new_url}' );\n" + content[insert_pos:]
                    print(f"✅ [CLONE] WP_SITEURL ajouté")
            
            # Mettre à jour WP_CONTENT_URL (IMPORTANT!)
            if "define( 'WP_CONTENT_URL'" in content or "define('WP_CONTENT_URL'" in content:
                content = re.sub(
                    r"define\s*\(\s*['\"]WP_CONTENT_URL['\"]\s*,\s*['\"][^'\"]+['\"]\s*\)\s*;",
                    f"define('WP_CONTENT_URL', '{new_content_url}');",
                    content
                )
                print(f"✅ [CLONE] WP_CONTENT_URL mis à jour")
            else:
                # Ajouter WP_CONTENT_URL si inexistant
                # Le placer après WP_CONTENT_DIR si possible
                if "define('WP_CONTENT_DIR'" in content or "define( 'WP_CONTENT_DIR'" in content:
                    content = re.sub(
                        r"(define\s*\(\s*['\"]WP_CONTENT_DIR['\"][^;]+;)",
                        f"\\1\ndefine('WP_CONTENT_URL', '{new_content_url}');",
                        content,
                        count=1
                    )
                    print(f"✅ [CLONE] WP_CONTENT_URL ajouté après WP_CONTENT_DIR")
            
            # Écrire le fichier modifié
            with open(wp_config_path, 'w') as f:
                f.write(content)
            
            print(f"✅ [CLONE] wp-config.php complètement mis à jour")
            
        except Exception as e:
            import traceback
            print(f"❌ [CLONE] Erreur mise à jour wp-config.php: {e}")
            print(traceback.format_exc())
    
    def _fix_permissions(self, project_name: str):
        """Fixe les permissions du projet cloné"""
        try:
            project_path = os.path.join(self.projects_folder, project_name)
            current_user = os.getenv('USER', 'dev-server')
            
            import subprocess
            subprocess.run([
                'sudo', 'chown', '-R', f'{current_user}:www-data', project_path
            ], capture_output=True, timeout=120)

            # sudo requis : le chown précédent a changé le groupe vers www-data,
            # les fichiers antérieurement owned par www-data ne sont pas writable
            # sans privilèges.
            subprocess.run([
                'sudo', 'find', project_path, '-type', 'd', '-exec', 'chmod', '775', '{}', '+'
            ], capture_output=True, timeout=120)

            subprocess.run([
                'sudo', 'find', project_path, '-type', 'f', '-exec', 'chmod', '664', '{}', '+'
            ], capture_output=True, timeout=120)
            
        except Exception as e:
            print(f"⚠️ [CLONE] Erreur permissions: {e}")
    
    def _cleanup_failed_clone(self, target_name: str):
        """Nettoie un clonage échoué"""
        try:
            print(f"🧹 [CLONE] Nettoyage du clonage échoué...")
            
            target_project_path = os.path.join(self.projects_folder, target_name)
            target_container_path = os.path.join(self.containers_folder, target_name)
            
            if os.path.exists(target_project_path):
                shutil.rmtree(target_project_path, ignore_errors=True)
            
            if os.path.exists(target_container_path):
                shutil.rmtree(target_container_path, ignore_errors=True)
                
        except Exception as e:
            print(f"⚠️ [CLONE] Erreur nettoyage: {e}")
    
    def _copy_directory_selective(self, src: str, dst: str, exclude_patterns: list):
        """Copie un dossier en excluant certains patterns"""
        import fnmatch
        
        for item in os.listdir(src):
            # Vérifier si l'item doit être exclu
            should_exclude = False
            for pattern in exclude_patterns:
                if fnmatch.fnmatch(item, pattern):
                    should_exclude = True
                    break
            
            if should_exclude:
                continue
            
            src_path = os.path.join(src, item)
            dst_path = os.path.join(dst, item)
            
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src_path, dst_path)
    
    def _get_directory_size(self, path: str) -> int:
        """Calcule la taille d'un dossier en octets"""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    total_size += os.path.getsize(filepath)
        return total_size
    
    def _generate_urls(self, project_name: str, ports: Dict) -> Dict:
        """Génère les URLs du projet"""
        return {
            'wordpress': f"http://{DockerConfig.LOCAL_IP}:{ports['wordpress']}",
            'wordpress_admin': f"http://{DockerConfig.LOCAL_IP}:{ports['wordpress']}/wp-admin",
            'phpmyadmin': f"http://{DockerConfig.LOCAL_IP}:{ports['phpmyadmin']}",
            'mailpit': f"http://{DockerConfig.LOCAL_IP}:{ports['mailpit']}"
        }

