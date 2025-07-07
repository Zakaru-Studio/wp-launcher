#!/usr/bin/env python3
"""
Service d'import ultra-rapide de base de données
Utilise la méthode la plus optimisée avec mysql direct
"""

import os
import time
import subprocess
import zipfile
import gzip
import tempfile
import shutil
import re
from typing import Dict, Any, Optional

class FastImportService:
    """Service d'import ultra-rapide de base de données"""
    
    def __init__(self, socketio=None):
        self.mysql_container_prefix = "mysql"
        self.db_name = "wordpress"
        self.db_user = "wordpress"
        self.db_password = "wordpress"
        self.socketio = socketio
    
    def _emit_progress(self, project_name: str, progress: int, message: str, status: str = 'importing', table_name: str = None):
        """Émet le progrès via SocketIO"""
        if self.socketio:
            data = {
                'project': project_name,
                'progress': progress,
                'message': message,
                'status': status
            }
            if table_name:
                data['table'] = table_name
            
            self.socketio.emit('fast_import_progress', data)
            print(f"📊 [PROGRESS] {project_name}: {progress}% - {message}")
    
    def _analyze_sql_file(self, sql_file: str) -> Dict[str, Any]:
        """Analyse le fichier SQL pour compter les tables et statements"""
        try:
            print("🔍 Analyse du fichier SQL...")
            
            table_count = 0
            statement_count = 0
            create_tables = []
            
            with open(sql_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
                # Compter les CREATE TABLE
                create_table_matches = re.findall(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?`?([^`\s]+)`?', content, re.IGNORECASE)
                create_tables = create_table_matches
                table_count = len(create_tables)
                
                # Compter les statements SQL (approximatif)
                statements = content.split(';')
                statement_count = len([s for s in statements if s.strip()])
                
                file_size = os.path.getsize(sql_file)
                
                return {
                    'table_count': table_count,
                    'statement_count': statement_count,
                    'create_tables': create_tables,
                    'file_size': file_size,
                    'file_size_mb': file_size / (1024 * 1024)
                }
                
        except Exception as e:
            print(f"❌ Erreur lors de l'analyse: {e}")
            return {
                'table_count': 0,
                'statement_count': 0,
                'create_tables': [],
                'file_size': 0,
                'file_size_mb': 0
            }
    
    def _monitor_import_progress(self, project_name: str, mysql_container: str, analysis_data: Dict):
        """Surveille le progrès de l'import en temps réel"""
        try:
            expected_tables = analysis_data.get('create_tables', [])
            total_tables = len(expected_tables)
            
            if total_tables == 0:
                return
            
            print(f"📊 Surveillance du progrès pour {total_tables} tables...")
            
            imported_tables = []
            last_progress = 0
            
            # Surveiller pendant maximum 30 minutes
            max_monitoring_time = 1800  # 30 minutes
            start_time = time.time()
            
            while (time.time() - start_time) < max_monitoring_time:
                try:
                    # Vérifier quelles tables existent maintenant
                    result = subprocess.run([
                        'docker', 'exec', mysql_container,
                        'mysql', '-u', self.db_user, f'-p{self.db_password}',
                        self.db_name, '-e', 'SHOW TABLES;'
                    ], capture_output=True, text=True, timeout=10)
                    
                    if result.returncode == 0:
                        current_tables = []
                        for line in result.stdout.strip().split('\n')[1:]:  # Skip header
                            if line.strip():
                                current_tables.append(line.strip())
                        
                        # Compter les tables importées
                        newly_imported = []
                        for table in expected_tables:
                            if table in current_tables and table not in imported_tables:
                                newly_imported.append(table)
                                imported_tables.append(table)
                        
                        # Calculer le progrès
                        progress = min(95, int((len(imported_tables) / total_tables) * 100))
                        
                        # Émettre le progrès seulement s'il y a du changement
                        if progress > last_progress or newly_imported:
                            if newly_imported:
                                for table in newly_imported:
                                    self._emit_progress(
                                        project_name, 
                                        progress, 
                                        f"Table importée: {table}",
                                        'importing',
                                        table
                                    )
                            else:
                                self._emit_progress(
                                    project_name, 
                                    progress, 
                                    f"Import en cours... ({len(imported_tables)}/{total_tables} tables)",
                                    'importing'
                                )
                            last_progress = progress
                        
                        # Si toutes les tables sont importées, arrêter la surveillance
                        if len(imported_tables) >= total_tables:
                            self._emit_progress(
                                project_name, 
                                95, 
                                "Finalisation de l'import...",
                                'importing'
                            )
                            break
                    
                except subprocess.TimeoutExpired:
                    continue
                except Exception as e:
                    print(f"❌ Erreur surveillance: {e}")
                    break
                
                time.sleep(3)  # Vérifier toutes les 3 secondes
                
        except Exception as e:
            print(f"❌ Erreur surveillance progrès: {e}")
    
    def import_database(self, project_name: str, file_path: str) -> Dict[str, Any]:
        """
        Importe une base de données avec la méthode la plus rapide
        
        Args:
            project_name: Nom du projet
            file_path: Chemin vers le fichier à importer
            
        Returns:
            Dict avec success, method, speed, duration et error si applicable
        """
        start_time = time.time()
        
        try:
            print(f"🚀 FastImportService: Début import pour {project_name}")
            print(f"📁 Fichier: {file_path}")
            
            # Émettre le début du progrès
            self._emit_progress(project_name, 0, "Initialisation de l'import...", 'starting')
            
            # Préparer le fichier SQL
            sql_file = self._prepare_sql_file(file_path)
            
            if not sql_file:
                self._emit_progress(project_name, 0, "Erreur lors de la préparation du fichier", 'error')
                return {
                    'success': False,
                    'error': 'Impossible de préparer le fichier SQL'
                }
            
            self._emit_progress(project_name, 5, "Analyse du fichier SQL...", 'analyzing')
            
            # Analyser le fichier SQL
            analysis_data = self._analyze_sql_file(sql_file)
            
            # Obtenir la taille du fichier pour estimer les performances
            file_size = os.path.getsize(sql_file)
            size_mb = file_size / (1024 * 1024)
            
            print(f"📊 Taille du fichier SQL: {size_mb:.2f} MB")
            print(f"📊 Tables détectées: {analysis_data['table_count']}")
            
            self._emit_progress(
                project_name, 
                10, 
                f"Fichier analysé: {size_mb:.1f} MB, {analysis_data['table_count']} tables détectées",
                'analyzed'
            )
            
            # Effectuer l'import avec la méthode ultra-rapide
            result = self._fast_mysql_import(project_name, sql_file, analysis_data)
            
            # Nettoyer le fichier temporaire si nécessaire
            if sql_file != file_path:
                try:
                    os.remove(sql_file)
                except:
                    pass
            
            # Calculer les performances
            duration = time.time() - start_time
            speed_mb_per_sec = size_mb / duration if duration > 0 else 0
            
            print(f"⚡ Import terminé en {duration:.2f}s ({speed_mb_per_sec:.2f} MB/s)")
            
            if result['success']:
                self._emit_progress(project_name, 100, "Import terminé avec succès !", 'completed')
                return {
                    'success': True,
                    'method': 'MySQL Direct Import',
                    'speed': f"{speed_mb_per_sec:.2f} MB/s",
                    'duration': f"{duration:.2f}s",
                    'file_size': f"{size_mb:.2f} MB",
                    'tables_imported': analysis_data['table_count']
                }
            else:
                self._emit_progress(project_name, 0, f"Erreur: {result.get('error', 'Erreur inconnue')}", 'error')
                return {
                    'success': False,
                    'error': result.get('error', 'Erreur lors de l\'import')
                }
                
        except Exception as e:
            print(f"❌ Erreur FastImportService: {e}")
            self._emit_progress(project_name, 0, f"Erreur critique: {str(e)}", 'error')
            return {
                'success': False,
                'error': f'Erreur lors de l\'import: {str(e)}'
            }
    
    def _prepare_sql_file(self, file_path: str) -> Optional[str]:
        """
        Prépare le fichier SQL selon son type
        
        Args:
            file_path: Chemin vers le fichier original
            
        Returns:
            Chemin vers le fichier SQL préparé ou None en cas d'erreur
        """
        try:
            file_extension = os.path.splitext(file_path)[1].lower()
            
            if file_extension == '.sql':
                # Fichier SQL direct
                return file_path
                
            elif file_extension == '.gz':
                # Fichier gzippé
                print("📦 Décompression du fichier .gz...")
                temp_sql = tempfile.mktemp(suffix='.sql')
                
                with gzip.open(file_path, 'rb') as f_in:
                    with open(temp_sql, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                
                print(f"✅ Fichier décompressé: {temp_sql}")
                return temp_sql
                
            elif file_extension == '.zip':
                # Archive ZIP
                print("📦 Extraction de l'archive ZIP...")
                temp_dir = tempfile.mkdtemp()
                
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # Chercher le fichier SQL dans l'archive
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        if file.endswith('.sql'):
                            sql_path = os.path.join(root, file)
                            print(f"✅ Fichier SQL trouvé: {sql_path}")
                            return sql_path
                
                # Nettoyer si aucun fichier SQL trouvé
                shutil.rmtree(temp_dir)
                return None
                
            else:
                print(f"⚠️ Format de fichier non supporté: {file_extension}")
                return None
                
        except Exception as e:
            print(f"❌ Erreur lors de la préparation du fichier: {e}")
            return None
    
    def _fast_mysql_import(self, project_name: str, sql_file: str, analysis_data: Dict) -> Dict[str, Any]:
        """
        Effectue l'import avec la méthode MySQL directe ultra-rapide
        
        Args:
            project_name: Nom du projet
            sql_file: Chemin vers le fichier SQL
            analysis_data: Données d'analyse du fichier
            
        Returns:
            Dict avec success et error si applicable
        """
        try:
            print("🗂️ Préparation de l'import MySQL direct...")
            
            # Nom du conteneur MySQL
            mysql_container = f"{project_name}_{self.mysql_container_prefix}_1"
            
            self._emit_progress(project_name, 15, "Vérification de MySQL...", 'connecting')
            
            # Vérifier que le conteneur MySQL est actif
            check_cmd = [
                'docker', 'exec', mysql_container,
                'mysqladmin', '-h', 'localhost', '-u', self.db_user, 
                f'-p{self.db_password}', 'ping'
            ]
            
            result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                return {
                    'success': False,
                    'error': f'MySQL n\'est pas accessible: {result.stderr}'
                }
            
            print("✅ MySQL est accessible")
            
            # Étape 1: Supprimer et recréer la base de données
            self._emit_progress(project_name, 20, "Suppression de l'ancienne base...", 'dropping')
            print("🗑️ Suppression de l'ancienne base de données...")
            
            drop_create_cmd = [
                'docker', 'exec', mysql_container,
                'mysql', '-h', 'localhost', '-u', 'root', 
                '-prootpassword', '-e', f'''
                DROP DATABASE IF EXISTS {self.db_name};
                CREATE DATABASE {self.db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                GRANT ALL PRIVILEGES ON {self.db_name}.* TO '{self.db_user}'@'%';
                FLUSH PRIVILEGES;
                '''
            ]
            
            result = subprocess.run(drop_create_cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                print(f"⚠️ Erreur lors de la suppression/recréation: {result.stderr}")
                # Continuer quand même, peut-être que la base n'existait pas
            else:
                print("✅ Base de données supprimée et recréée")
            
            # Étape 2: Désactiver les vérifications pour un import plus rapide
            self._emit_progress(project_name, 25, "Optimisation MySQL...", 'optimizing')
            print("⚡ Activation des optimisations MySQL...")
            optimize_cmd = [
                'docker', 'exec', mysql_container,
                'mysql', '-h', 'localhost', '-u', self.db_user, 
                f'-p{self.db_password}', self.db_name,
                '-e', '''
                SET SESSION foreign_key_checks = 0;
                SET SESSION unique_checks = 0;
                SET SESSION autocommit = 0;
                SET SESSION sql_log_bin = 0;
                SET SESSION innodb_buffer_pool_size = 1024*1024*1024;
                SET SESSION innodb_lock_wait_timeout = 120;
                SET SESSION innodb_flush_log_at_trx_commit = 0;
                '''
            ]
            
            subprocess.run(optimize_cmd, capture_output=True, text=True, timeout=30)
            print("⚡ Optimisations MySQL activées")
            
            # Étape 3: Copier le fichier dans le conteneur
            self._emit_progress(project_name, 30, "Copie du fichier dans le conteneur...", 'copying')
            print("📁 Copie du fichier SQL dans le conteneur...")
            copy_cmd = ['docker', 'cp', sql_file, f'{mysql_container}:/tmp/import.sql']
            result = subprocess.run(copy_cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                return {
                    'success': False,
                    'error': f'Erreur lors de la copie du fichier: {result.stderr}'
                }
            
            print("✅ Fichier copié dans le conteneur")
            
            # Étape 4: Démarrer la surveillance du progrès en arrière-plan
            self._emit_progress(project_name, 35, "Démarrage de l'import...", 'importing')
            
            # Lancer la surveillance en arrière-plan
            import threading
            monitor_thread = threading.Thread(
                target=self._monitor_import_progress,
                args=(project_name, mysql_container, analysis_data)
            )
            monitor_thread.daemon = True
            monitor_thread.start()
            
            # Étape 5: Import ultra-rapide
            print("🚀 Démarrage de l'import ultra-rapide...")
            import_cmd = [
                'docker', 'exec', mysql_container,
                'mysql', '-h', 'localhost', '-u', self.db_user, 
                f'-p{self.db_password}', self.db_name,
                '-e', 'SOURCE /tmp/import.sql'
            ]
            
            result = subprocess.run(import_cmd, capture_output=True, text=True, timeout=1800)  # 30 minutes max
            
            if result.returncode != 0:
                return {
                    'success': False,
                    'error': f'Erreur lors de l\'import: {result.stderr}'
                }
            
            print("✅ Import terminé avec succès")
            
            # Étape 6: Réactiver les vérifications et optimiser
            self._emit_progress(project_name, 96, "Finalisation...", 'finalizing')
            print("🔧 Restauration des paramètres MySQL...")
            restore_cmd = [
                'docker', 'exec', mysql_container,
                'mysql', '-h', 'localhost', '-u', self.db_user, 
                f'-p{self.db_password}', self.db_name,
                '-e', '''
                SET SESSION foreign_key_checks = 1;
                SET SESSION unique_checks = 1;
                SET SESSION autocommit = 1;
                SET SESSION innodb_flush_log_at_trx_commit = 1;
                COMMIT;
                ANALYZE TABLE `wp_posts`, `wp_options`, `wp_postmeta`, `wp_users`;
                '''
            ]
            
            subprocess.run(restore_cmd, capture_output=True, text=True, timeout=60)
            print("🔧 Paramètres MySQL restaurés et tables optimisées")
            
            # Étape 7: Nettoyer le fichier temporaire dans le conteneur
            cleanup_cmd = ['docker', 'exec', mysql_container, 'rm', '/tmp/import.sql']
            subprocess.run(cleanup_cmd, capture_output=True, text=True, timeout=30)
            
            print("🎉 Import complet terminé avec succès!")
            return {'success': True}
            
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Timeout lors de l\'import (plus de 30 minutes)'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Erreur lors de l\'import MySQL: {str(e)}'
            }
    
    def get_container_mysql_info(self, project_name: str) -> Dict[str, str]:
        """
        Récupère les informations de connexion MySQL du conteneur
        
        Args:
            project_name: Nom du projet
            
        Returns:
            Dict avec les informations de connexion
        """
        return {
            'container': f"{project_name}_{self.mysql_container_prefix}_1",
            'database': self.db_name,
            'user': self.db_user,
            'password': self.db_password
        }
    
    def estimate_import_time(self, file_size_mb: float) -> str:
        """
        Estime le temps d'import basé sur la taille du fichier
        
        Args:
            file_size_mb: Taille du fichier en MB
            
        Returns:
            Estimation du temps d'import
        """
        # Basé sur les performances observées (environ 50-100 MB/s)
        estimated_seconds = file_size_mb / 75  # Estimation conservatrice
        
        if estimated_seconds < 60:
            return f"~{int(estimated_seconds)}s"
        elif estimated_seconds < 3600:
            return f"~{int(estimated_seconds/60)}min"
        else:
            return f"~{int(estimated_seconds/3600)}h" 