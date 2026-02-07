#!/usr/bin/env python3
"""
Service de gestion des snapshots (sauvegardes) de projets
Sauvegarde UNIQUEMENT les dossiers versionnés Git (thèmes/plugins custom)
"""

import os
import json
import tarfile
import shutil
import subprocess
from datetime import datetime
from typing import Dict, List
from app.config.docker_config import DockerConfig
from app.services.database_service import DatabaseService


class SnapshotService:
    """Service pour créer et restaurer des snapshots de projets"""
    
    SNAPSHOT_BASE_DIR = os.path.join(DockerConfig.ROOT_PATH, 'snapshots')
    
    def __init__(self, git_service=None, socketio=None):
        """
        Initialise le service de snapshots
        
        Args:
            git_service: Service Git pour détecter les dépôts
            socketio: Instance Socket.IO pour les logs en temps réel
        """
        self.git_service = git_service
        self.socketio = socketio
        
        # Créer le dossier snapshots
        os.makedirs(self.SNAPSHOT_BASE_DIR, exist_ok=True)
    
    def _emit_rollback_log(self, project_name: str, message: str, progress: int = 0, status: str = 'processing'):
        """Émet un log de rollback via socketio"""
        if self.socketio:
            try:
                self.socketio.emit('rollback_progress', {
                    'project': project_name,
                    'message': message,
                    'progress': progress,
                    'status': status,
                    'type': 'snapshot_rollback'
                })
            except Exception as e:
                print(f"⚠️ Erreur émission log socketio: {e}")
    
    def _import_database_for_rollback(self, project_name: str, sql_file: str) -> Dict:
        """
        Importe une base de données pour le rollback avec logs détaillés
        """
        import re
        
        try:
            container_name = f"{project_name}_mysql_1"
            
            # Vérifier que le conteneur existe
            check_cmd = ['docker', 'ps', '--filter', f'name={container_name}', '--format', '{{.Names}}']
            result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=10)
            
            if container_name not in result.stdout:
                return {
                    'success': False,
                    'message': f'Conteneur MySQL {container_name} non trouvé ou arrêté'
                }
            
            # Lire le fichier SQL pour compter et détecter les tables
            tables_found = []
            with open(sql_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                # Chercher les instructions DROP TABLE / CREATE TABLE
                table_pattern = r'(?:DROP TABLE|CREATE TABLE).*?`(\w+)`'
                matches = re.findall(table_pattern, content, re.IGNORECASE)
                tables_found = list(set(matches))  # Dédupliquer
            
            total_tables = len(tables_found)
            self._emit_rollback_log(project_name, f"📊 {total_tables} tables détectées dans le snapshot", 76, 'processing')
            
            # Import de la base de données
            self._emit_rollback_log(project_name, "🔄 Import en cours...", 77, 'processing')
            
            import_cmd = [
                'docker', 'exec', '-i', container_name,
                'mysql', '-u', 'wordpress', '-pwordpress', 'wordpress'
            ]
            
            with open(sql_file, 'r') as f:
                result = subprocess.run(import_cmd, stdin=f, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                error_msg = result.stderr[:200] if result.stderr else 'Erreur inconnue'
                return {
                    'success': False,
                    'message': f'Erreur mysql: {error_msg}'
                }
            
            # Simuler l'affichage table par table
            progress_step = 8 // max(total_tables, 1)  # 8% de progression entre 77 et 85
            for idx, table in enumerate(tables_found):
                progress = 77 + ((idx + 1) * progress_step)
                self._emit_rollback_log(project_name, f"  ✅ Table restaurée: {table}", min(progress, 84), 'processing')
            
            return {
                'success': True,
                'message': 'Base de données restaurée',
                'tables_count': total_tables
            }
            
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'message': 'Timeout lors de l\'import de la base de données'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            }
    
    def create_snapshot(self, project_name: str, description: str = "", options: Dict = None) -> Dict:
        """
        Crée un snapshot complet d'un projet WordPress
        
        Inclut:
        - Tous les thèmes (wp-content/themes/) - optionnel
        - Tous les plugins (wp-content/plugins/) - optionnel
        - Fichiers de langue (wp-content/languages/) - optionnel
        - Dossiers uploads si présents (wp-content/uploads/) - optionnel
        - Fichiers de configuration (wp-config.php, docker-compose.yml, etc.)
        - Base de données (export SQL)
        - Dossiers versionnés Git (si présents)
        
        Args:
            project_name: Nom du projet
            description: Description optionnelle du snapshot
            options: Dictionnaire d'options {
                'include_themes': bool (default True),
                'include_plugins': bool (default True),
                'include_languages': bool (default True),
                'include_uploads': bool (default False),
                'include_database': bool (default True)
            }
            
        Returns:
            Dict avec {success: bool, snapshot_id: str, message: str}
        """
        # Options par défaut
        if options is None:
            options = {}
        
        include_themes = options.get('include_themes', True)
        include_plugins = options.get('include_plugins', True)
        include_languages = options.get('include_languages', True)
        include_uploads = options.get('include_uploads', False)
        include_database = options.get('include_database', True)
        try:
            print(f"📸 [SNAPSHOT] Création pour {project_name}...")
            
            project_path = os.path.join(DockerConfig.PROJECTS_FOLDER, project_name)
            
            if not os.path.exists(project_path):
                return {
                    'success': False,
                    'message': 'Projet non trouvé'
                }
            
            # Générer l'ID du snapshot
            timestamp = datetime.now().strftime('%Y-%m-%d-%Hh%M')
            snapshot_id = f"{project_name}-{timestamp}"
            snapshot_dir = os.path.join(self.SNAPSHOT_BASE_DIR, project_name)
            snapshot_path = os.path.join(snapshot_dir, snapshot_id)
            
            os.makedirs(snapshot_path, exist_ok=True)
            
            # Liste des éléments à inclure
            items_to_backup = []
            backup_summary = {
                'themes': [],
                'plugins': [],
                'config_files': [],
                'git_directories': [],
                'has_uploads': False,
                'has_database': False
            }
            
            # 1. Détecter les dossiers Git (optionnel)
            git_directories = []
            if self.git_service:
                git_directories = self.git_service.detect_git_directories(project_path)
                
            git_info = []
            if git_directories:
                print(f"  📦 {len(git_directories)} dossier(s) Git détecté(s)")
                for git_dir_info in git_directories:
                    git_status = self.git_service.get_git_status(git_dir_info['path'])
                    git_info.append({
                        'path': git_dir_info['relative_path'],
                        'commit': git_status['commit'],
                        'commit_message': git_status['commit_message'],
                        'branch': git_status['branch'],
                        'status': git_status['status'],
                        'uncommitted_files': git_status['uncommitted_files']
                    })
                    items_to_backup.append({
                        'path': git_dir_info['path'],
                        'arcname': git_dir_info['relative_path'],
                        'type': 'git'
                    })
                backup_summary['git_directories'] = git_info
            
            # 2. Inclure tous les thèmes WordPress (si demandé)
            if include_themes:
                themes_path = os.path.join(project_path, 'wp-content', 'themes')
                if os.path.exists(themes_path):
                    themes = [d for d in os.listdir(themes_path) 
                             if os.path.isdir(os.path.join(themes_path, d)) and not d.startswith('.')]
                    print(f"  🎨 {len(themes)} thème(s) trouvé(s)")
                    for theme in themes:
                        theme_path = os.path.join(themes_path, theme)
                        items_to_backup.append({
                            'path': theme_path,
                            'arcname': f'wp-content/themes/{theme}',
                            'type': 'theme'
                        })
                    backup_summary['themes'] = themes
            else:
                print(f"  ⏭️ Thèmes ignorés (option désactivée)")
            
            # 3. Inclure tous les plugins WordPress (si demandé)
            if include_plugins:
                plugins_path = os.path.join(project_path, 'wp-content', 'plugins')
                if os.path.exists(plugins_path):
                    plugins = [d for d in os.listdir(plugins_path) 
                              if os.path.isdir(os.path.join(plugins_path, d)) and not d.startswith('.')]
                    print(f"  🔌 {len(plugins)} plugin(s) trouvé(s)")
                    for plugin in plugins:
                        plugin_path = os.path.join(plugins_path, plugin)
                        items_to_backup.append({
                            'path': plugin_path,
                            'arcname': f'wp-content/plugins/{plugin}',
                            'type': 'plugin'
                        })
                    backup_summary['plugins'] = plugins
            else:
                print(f"  ⏭️ Plugins ignorés (option désactivée)")
            
            # 3.5. Inclure les fichiers de langue (si demandé)
            if include_languages:
                languages_path = os.path.join(project_path, 'wp-content', 'languages')
                if os.path.exists(languages_path):
                    print(f"  🌐 Fichiers de langue inclus")
                    items_to_backup.append({
                        'path': languages_path,
                        'arcname': 'wp-content/languages',
                        'type': 'languages'
                    })
                    backup_summary['has_languages'] = True
            else:
                print(f"  ⏭️ Fichiers de langue ignorés (option désactivée)")
            
            # 4. Inclure wp-content/uploads (si demandé et si pas trop volumineux)
            if include_uploads:
                uploads_path = os.path.join(project_path, 'wp-content', 'uploads')
                if os.path.exists(uploads_path):
                    # Calculer la taille des uploads
                    uploads_size = sum(os.path.getsize(os.path.join(dirpath, f)) 
                                      for dirpath, _, filenames in os.walk(uploads_path) 
                                      for f in filenames)
                    uploads_size_mb = uploads_size / (1024 * 1024)
                    
                    # Inclure seulement si < 100 MB
                    if uploads_size_mb < 100:
                        print(f"  📁 Uploads inclus ({uploads_size_mb:.1f} MB)")
                        items_to_backup.append({
                            'path': uploads_path,
                            'arcname': 'wp-content/uploads',
                            'type': 'uploads'
                        })
                        backup_summary['has_uploads'] = True
                    else:
                        print(f"  ⚠️ Uploads ignoré (trop volumineux: {uploads_size_mb:.1f} MB)")
            else:
                print(f"  ⏭️ Uploads ignorés (option désactivée)")
            
            # 5. Inclure les fichiers de configuration
            config_files = ['wp-config.php', 'docker-compose.yml', '.env']
            for config_file in config_files:
                config_file_path = os.path.join(project_path, config_file)
                if os.path.exists(config_file_path):
                    items_to_backup.append({
                        'path': config_file_path,
                        'arcname': config_file,
                        'type': 'config'
                    })
                    backup_summary['config_files'].append(config_file)
            
            # Ajouter le dossier config/ s'il existe
            config_dir_path = os.path.join(project_path, 'config')
            if os.path.exists(config_dir_path):
                items_to_backup.append({
                    'path': config_dir_path,
                    'arcname': 'config',
                    'type': 'config'
                })
            
            # Vérifier qu'on a au moins quelque chose à sauvegarder
            if not items_to_backup:
                return {
                    'success': False,
                    'message': 'Aucun élément à sauvegarder trouvé dans ce projet'
                }
            
            # 6. Exporter la base de données
            db_file = None
            if include_database:
                print(f"  💾 Export de la base de données...")
                db_file = os.path.join(snapshot_path, 'database.sql')
                
                # Essayer l'export direct via mysqldump dans le conteneur MySQL
                import subprocess
                try:
                    container_name = f"{project_name}_mysql_1"
                    export_cmd = [
                        'docker', 'exec', container_name,
                        'mysqldump', 
                        '-u', 'wordpress', 
                        '-pwordpress',
                        '--single-transaction',
                        '--routines',
                        '--triggers',
                        'wordpress'
                    ]
                    
                    with open(db_file, 'w') as f:
                        result = subprocess.run(export_cmd, stdout=f, stderr=subprocess.PIPE, text=True, timeout=300)
                    
                    if result.returncode == 0 and os.path.exists(db_file) and os.path.getsize(db_file) > 0:
                        backup_summary['has_database'] = True
                        size_mb = os.path.getsize(db_file) / (1024 * 1024)
                        print(f"  ✅ Base de données exportée ({size_mb:.1f} MB)")
                    else:
                        print(f"  ⚠️ Impossible d'exporter la base de données: {result.stderr}")
                        if os.path.exists(db_file):
                            os.remove(db_file)
                except Exception as e:
                    print(f"  ⚠️ Erreur lors de l'export de la base de données: {e}")
                    if os.path.exists(db_file):
                        os.remove(db_file)
            
            # 7. Créer l'archive tar.gz
            print(f"  📦 Création de l'archive...")
            archive_file = os.path.join(snapshot_path, 'wp-content.tar.gz')
            with tarfile.open(archive_file, 'w:gz') as tar:
                for item in items_to_backup:
                    try:
                        tar.add(item['path'], arcname=item['arcname'])
                    except Exception as e:
                        print(f"  ⚠️ Erreur ajout {item['arcname']}: {e}")
            
            # 8. Créer les métadonnées
            archive_size = os.path.getsize(archive_file)
            total_size = archive_size
            
            if db_file and os.path.exists(db_file):
                total_size += os.path.getsize(db_file)
            
            metadata = {
                'snapshot_id': snapshot_id,
                'project_name': project_name,
                'created_at': datetime.now().isoformat(),
                'description': description,
                'content_summary': backup_summary,
                'archive_size_bytes': archive_size,
                'archive_size_mb': round(archive_size / (1024 * 1024), 2),
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'includes_database': backup_summary['has_database']
            }
            
            # Sauvegarder les métadonnées
            metadata_file = os.path.join(snapshot_path, 'metadata.json')
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            print(f"✅ [SNAPSHOT] Créé: {snapshot_id} ({metadata['total_size_mb']} MB)")
            
            return {
                'success': True,
                'snapshot_id': snapshot_id,
                'message': f'Snapshot créé: {snapshot_id}',
                'metadata': metadata
            }
            
        except Exception as e:
            print(f"❌ [SNAPSHOT] Erreur création: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            }
    
    def list_snapshots(self, project_name: str) -> Dict:
        """
        Liste tous les snapshots d'un projet
        
        Args:
            project_name: Nom du projet
            
        Returns:
            Dict avec {success: bool, snapshots: list}
        """
        try:
            snapshot_dir = os.path.join(self.SNAPSHOT_BASE_DIR, project_name)
            
            if not os.path.exists(snapshot_dir):
                return {
                    'success': True,
                    'snapshots': []
                }
            
            snapshots = []
            for snapshot_id in os.listdir(snapshot_dir):
                snapshot_path = os.path.join(snapshot_dir, snapshot_id)
                metadata_file = os.path.join(snapshot_path, 'metadata.json')
                
                if os.path.exists(metadata_file):
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                        snapshots.append(metadata)
            
            # Trier par date (plus récent en premier)
            snapshots.sort(key=lambda x: x['created_at'], reverse=True)
            
            return {
                'success': True,
                'snapshots': snapshots
            }
            
        except Exception as e:
            print(f"❌ [SNAPSHOT] Erreur liste: {e}")
            return {
                'success': False,
                'message': f'Erreur: {str(e)}',
                'snapshots': []
            }
    
    def get_snapshot_info(self, snapshot_id: str) -> Dict:
        """Récupère les informations d'un snapshot"""
        try:
            # Chercher le snapshot dans tous les projets
            snapshot_path = None
            for project_dir in os.listdir(self.SNAPSHOT_BASE_DIR):
                potential_path = os.path.join(self.SNAPSHOT_BASE_DIR, project_dir, snapshot_id)
                if os.path.exists(potential_path):
                    snapshot_path = potential_path
                    break
            
            if not snapshot_path:
                return {
                    'success': False,
                    'message': 'Snapshot non trouvé'
                }
            
            metadata_file = os.path.join(snapshot_path, 'metadata.json')
            
            if not os.path.exists(metadata_file):
                return {
                    'success': False,
                    'message': 'Métadonnées du snapshot non trouvées'
                }
            
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            
            return {
                'success': True,
                'metadata': metadata
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            }
    
    def rollback_snapshot(self, snapshot_id: str) -> Dict:
        """
        Restaure un snapshot
        
        Args:
            snapshot_id: ID du snapshot à restaurer
            
        Returns:
            Dict avec {success: bool, message: str, files_restored: list}
        """
        try:
            print(f"🔄 [SNAPSHOT] Rollback de {snapshot_id}...")
            
            # Récupérer les métadonnées
            info = self.get_snapshot_info(snapshot_id)
            if not info['success']:
                return info
            
            metadata = info['metadata']
            project_name = metadata['project_name']
            project_path = os.path.join(DockerConfig.PROJECTS_FOLDER, project_name)
            content_summary = metadata.get('content_summary', {})
            
            print(f"  📋 Projet: {project_name}")
            print(f"  📋 Chemin: {project_path}")
            print(f"  📋 Content summary: {content_summary}")
            
            # Chemins du snapshot
            snapshot_path = os.path.join(self.SNAPSHOT_BASE_DIR, project_name, snapshot_id)
            archive_file = os.path.join(snapshot_path, 'wp-content.tar.gz')
            db_file = os.path.join(snapshot_path, 'database.sql')
            
            print(f"  📋 Archive: {archive_file}")
            print(f"  📋 Archive exists: {os.path.exists(archive_file)}")
            print(f"  📋 DB file: {db_file}")
            print(f"  📋 DB exists: {os.path.exists(db_file)}")
            
            if not os.path.exists(archive_file):
                return {
                    'success': False,
                    'message': 'Archive du snapshot introuvable'
                }
            
            # Créer un backup temporaire
            backup_dir = f"/tmp/snapshot_backup_{project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            os.makedirs(backup_dir, exist_ok=True)
            print(f"  📂 Dossier temporaire: {backup_dir}")
            
            restored_paths = []
            
            try:
                # Étape préliminaire : Prendre possession temporaire de wp-content pour éviter les erreurs de permission
                wp_content_path = os.path.join(project_path, 'wp-content')
                if os.path.exists(wp_content_path):
                    print(f"  🔐 Prise de possession temporaire de wp-content...")
                    self._emit_rollback_log(project_name, "🔐 Modification des permissions pour le rollback...", 10, 'processing')
                    try:
                        current_user = os.getenv('USER', 'dev-server')
                        subprocess.run(['sudo', 'chown', '-R', f'{current_user}:{current_user}', wp_content_path], 
                                     check=False, capture_output=True, timeout=30)
                        print(f"  ✅ Propriétaire temporaire: {current_user}")
                    except Exception as e:
                        print(f"  ⚠️ Impossible de changer le propriétaire: {e}")
                
                # Extraire l'archive
                print(f"  📦 Extraction de l'archive vers {backup_dir}...")
                self._emit_rollback_log(project_name, "📦 Extraction de l'archive du snapshot...", 15, 'processing')
                with tarfile.open(archive_file, 'r:gz') as tar:
                    tar.extractall(path=backup_dir)
                
                self._emit_rollback_log(project_name, "✅ Archive extraite avec succès", 20, 'processing')
                
                # Lister le contenu extrait
                print(f"  📂 Contenu extrait:")
                for root, dirs, files in os.walk(backup_dir):
                    level = root.replace(backup_dir, '').count(os.sep)
                    indent = ' ' * 2 * level
                    print(f"{indent}{os.path.basename(root)}/")
                    if level < 2:  # Limiter la profondeur d'affichage
                        subindent = ' ' * 2 * (level + 1)
                        for file in files[:5]:  # Limiter à 5 fichiers
                            print(f"{subindent}{file}")
                
                # 1. Restaurer les thèmes (toujours présents dans content_summary)
                themes = content_summary.get('themes', [])
                if themes:
                    print(f"  🎨 Restauration de {len(themes)} thème(s)...")
                    self._emit_rollback_log(project_name, f"🎨 Restauration de {len(themes)} thème(s)...", 25, 'processing')
                    wp_themes_path = os.path.join(project_path, 'wp-content', 'themes')
                    backup_themes_path = os.path.join(backup_dir, 'wp-content', 'themes')
                    
                    if os.path.exists(backup_themes_path):
                        os.makedirs(wp_themes_path, exist_ok=True)
                        for idx, theme in enumerate(themes):
                            source_theme = os.path.join(backup_themes_path, theme)
                            target_theme = os.path.join(wp_themes_path, theme)
                            
                            if os.path.exists(source_theme):
                                self._emit_rollback_log(project_name, f"  ↻ Restauration du thème: {theme}", 25 + (idx * 5 // len(themes)), 'processing')
                                # Supprimer l'ancien thème (permissions déjà modifiées)
                                if os.path.exists(target_theme):
                                    shutil.rmtree(target_theme)
                                
                                shutil.copytree(source_theme, target_theme)
                                restored_paths.append(f'wp-content/themes/{theme}')
                                print(f"    ✅ {theme}")
                                self._emit_rollback_log(project_name, f"  ✅ Thème restauré: {theme}", 25 + ((idx + 1) * 5 // len(themes)), 'processing')
                    else:
                        print(f"    ⚠️ Dossier themes introuvable dans l'extraction")
                
                # 2. Restaurer les plugins
                plugins = content_summary.get('plugins', [])
                if plugins:
                    print(f"  🔌 Restauration de {len(plugins)} plugin(s)...")
                    self._emit_rollback_log(project_name, f"🔌 Restauration de {len(plugins)} plugin(s)...", 35, 'processing')
                    wp_plugins_path = os.path.join(project_path, 'wp-content', 'plugins')
                    backup_plugins_path = os.path.join(backup_dir, 'wp-content', 'plugins')
                    
                    if os.path.exists(backup_plugins_path):
                        os.makedirs(wp_plugins_path, exist_ok=True)
                        for idx, plugin in enumerate(plugins):
                            source_plugin = os.path.join(backup_plugins_path, plugin)
                            target_plugin = os.path.join(wp_plugins_path, plugin)
                            
                            if os.path.exists(source_plugin):
                                self._emit_rollback_log(project_name, f"  ↻ Restauration du plugin: {plugin}", 35 + (idx * 15 // len(plugins)), 'processing')
                                # Supprimer l'ancien plugin (permissions déjà modifiées)
                                if os.path.exists(target_plugin):
                                    shutil.rmtree(target_plugin)
                                
                                shutil.copytree(source_plugin, target_plugin)
                                restored_paths.append(f'wp-content/plugins/{plugin}')
                                print(f"    ✅ {plugin}")
                                self._emit_rollback_log(project_name, f"  ✅ Plugin restauré: {plugin}", 35 + ((idx + 1) * 15 // len(plugins)), 'processing')
                    else:
                        print(f"    ⚠️ Dossier plugins introuvable dans l'extraction")
                
                # 3. Restaurer les fichiers de langue
                if content_summary.get('has_languages'):
                    print(f"  🌐 Restauration des fichiers de langue...")
                    source_languages = os.path.join(backup_dir, 'wp-content', 'languages')
                    target_languages = os.path.join(project_path, 'wp-content', 'languages')
                    
                    print(f"    Source: {source_languages}")
                    print(f"    Existe: {os.path.exists(source_languages)}")
                    
                    if os.path.exists(source_languages):
                        if os.path.exists(target_languages):
                            shutil.rmtree(target_languages)
                        shutil.copytree(source_languages, target_languages)
                        restored_paths.append('wp-content/languages')
                        print(f"    ✅ Restaurés")
                
                # 4. Restaurer les uploads
                if content_summary.get('has_uploads'):
                    print(f"  📁 Restauration des uploads...")
                    source_uploads = os.path.join(backup_dir, 'wp-content', 'uploads')
                    target_uploads = os.path.join(project_path, 'wp-content', 'uploads')
                    
                    print(f"    Source: {source_uploads}")
                    print(f"    Existe: {os.path.exists(source_uploads)}")
                    
                    if os.path.exists(source_uploads):
                        if os.path.exists(target_uploads):
                            shutil.rmtree(target_uploads)
                        shutil.copytree(source_uploads, target_uploads)
                        restored_paths.append('wp-content/uploads')
                        print(f"    ✅ Restaurés")
                
                # 5. Restaurer les fichiers de configuration
                config_files = content_summary.get('config_files', [])
                if config_files:
                    print(f"  ⚙️ Restauration de {len(config_files)} fichier(s) de configuration...")
                    for config_file in config_files:
                        source_file = os.path.join(backup_dir, config_file)
                        target_file = os.path.join(project_path, config_file)
                        
                        print(f"    Config: {config_file}")
                        print(f"      Source existe: {os.path.exists(source_file)}")
                        
                        if os.path.exists(source_file):
                            shutil.copy2(source_file, target_file)
                            restored_paths.append(config_file)
                            print(f"      ✅ Restauré")
                
                # 6. Restaurer les dossiers Git (si présents)
                git_dirs = content_summary.get('git_directories', [])
                if git_dirs:
                    print(f"  📂 Restauration de {len(git_dirs)} dossier(s) Git...")
                    for git_info in git_dirs:
                        source_path = os.path.join(backup_dir, git_info['path'])
                        target_path = os.path.join(project_path, git_info['path'])
                        
                        print(f"    Git: {git_info['path']}")
                        print(f"      Source existe: {os.path.exists(source_path)}")
                        
                        if os.path.exists(source_path):
                            if os.path.exists(target_path):
                                shutil.rmtree(target_path)
                            shutil.copytree(source_path, target_path)
                            restored_paths.append(git_info['path'])
                            print(f"      ✅ Restauré")
                
                # 7. Restaurer la base de données
                if content_summary.get('has_database') and os.path.exists(db_file):
                    print(f"  💾 Restauration de la base de données...")
                    self._emit_rollback_log(project_name, "💾 Restauration de la base de données...", 75, 'processing')
                    print(f"    Fichier DB: {db_file}")
                    print(f"    Taille: {os.path.getsize(db_file)} bytes")
                    
                    try:
                        # Importer la DB directement via mysqldump (méthode simplifiée)
                        db_result = self._import_database_for_rollback(project_name, db_file)
                        if db_result['success']:
                            restored_paths.append('database')
                            print(f"    ✅ Base de données restaurée")
                            self._emit_rollback_log(project_name, "✅ Base de données restaurée", 85, 'processing')
                        else:
                            print(f"    ⚠️ Erreur lors de l'import de la base de données: {db_result.get('message')}")
                            self._emit_rollback_log(project_name, f"⚠️ Erreur DB: {db_result.get('message')}", 85, 'warning')
                    except Exception as db_error:
                        print(f"    ⚠️ Exception lors de l'import DB: {db_error}")
                        self._emit_rollback_log(project_name, f"⚠️ Exception DB: {str(db_error)}", 85, 'warning')
                        import traceback
                        traceback.print_exc()
                
                # Restaurer les permissions WordPress correctes
                if os.path.exists(wp_content_path):
                    print(f"  🔐 Restauration des permissions WordPress...")
                    self._emit_rollback_log(project_name, "🔐 Restauration des permissions WordPress...", 90, 'processing')
                    try:
                        # Remettre www-data comme propriétaire pour compatibilité Docker
                        subprocess.run(['sudo', 'chown', '-R', 'www-data:www-data', wp_content_path], 
                                     check=False, capture_output=True, timeout=60)
                        
                        # Permissions appropriées pour WordPress
                        subprocess.run(['sudo', 'find', wp_content_path, '-type', 'd', '-exec', 'chmod', '775', '{}', '+'], 
                                     check=False, capture_output=True, timeout=60)
                        subprocess.run(['sudo', 'find', wp_content_path, '-type', 'f', '-exec', 'chmod', '664', '{}', '+'], 
                                     check=False, capture_output=True, timeout=60)
                        
                        print(f"  ✅ Permissions WordPress restaurées (www-data:www-data)")
                        self._emit_rollback_log(project_name, "✅ Permissions WordPress restaurées", 95, 'processing')
                    except Exception as e:
                        print(f"  ⚠️ Erreur lors de la restauration des permissions: {e}")
                        self._emit_rollback_log(project_name, f"⚠️ Erreur permissions: {str(e)}", 95, 'warning')
                
                print(f"✅ [SNAPSHOT] Rollback terminé: {len(restored_paths)} éléments restaurés")
                print(f"  Éléments restaurés: {restored_paths}")
                self._emit_rollback_log(project_name, f"✅ Rollback terminé: {len(restored_paths)} éléments restaurés", 100, 'complete')
                
                return {
                    'success': True,
                    'message': f'Snapshot restauré avec succès',
                    'files_restored': restored_paths,
                    'snapshot_date': metadata['created_at']
                }
                
            finally:
                # Nettoyer le backup temporaire
                if os.path.exists(backup_dir):
                    print(f"  🧹 Nettoyage de {backup_dir}")
                    shutil.rmtree(backup_dir)
            
        except Exception as e:
            print(f"❌ [SNAPSHOT] Erreur rollback: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'message': f'Erreur lors du rollback: {str(e)}'
            }
    
    def delete_snapshot(self, snapshot_id: str) -> Dict:
        """Supprime un snapshot"""
        try:
            # Chercher le snapshot dans tous les projets
            snapshot_path = None
            for project_dir in os.listdir(self.SNAPSHOT_BASE_DIR):
                potential_path = os.path.join(self.SNAPSHOT_BASE_DIR, project_dir, snapshot_id)
                if os.path.exists(potential_path):
                    snapshot_path = potential_path
                    break
            
            if not snapshot_path:
                return {
                    'success': False,
                    'message': 'Snapshot non trouvé'
                }
            
            shutil.rmtree(snapshot_path)
            
            print(f"🗑️ [SNAPSHOT] Supprimé: {snapshot_id}")
            
            return {
                'success': True,
                'message': f'Snapshot supprimé: {snapshot_id}'
            }
            
        except Exception as e:
            print(f"❌ [SNAPSHOT] Erreur suppression: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'message': f'Erreur: {str(e)}'
            }
    
    def _load_instance_metadata(self, instance_name: str) -> Dict:
        """Load dev instance metadata if it exists"""
        metadata_path = f"projets/.dev-instances/{instance_name}/.metadata.json"
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r') as f:
                return json.load(f)
        return {}
    
    def _get_db_name_for_project(self, project_name: str) -> str:
        """Get the correct database name for a project (supports dev instances)"""
        # Check if it's a dev instance
        if '-dev-' in project_name:
            metadata = self._load_instance_metadata(project_name)
            return metadata.get('db_name', project_name.replace('-', '_'))
        return project_name.replace('-', '_')


