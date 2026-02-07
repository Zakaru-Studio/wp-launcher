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
from app.utils.logger import wp_logger

class FastImportService:
    """Service d'import ultra-rapide de base de données"""
    
    def __init__(self, socketio=None):
        self.mysql_container_prefix = "mysql"
        self.db_name = "wordpress"
        self.db_user = "wordpress"
        self.db_password = "wordpress"
        self.socketio = socketio
    
    def _emit_progress(self, project_name: str, progress: int, message: str, status: str = 'importing', table_name: Optional[str] = None):
        """Émet le progrès via SocketIO"""
        if self.socketio:
            data = {
                'type': 'database_import',
                'project': project_name,
                'progress': progress,
                'message': message,
                'status': status
            }
            if table_name:
                data['table'] = table_name
            
            self.socketio.emit('import_progress', data)
            print(f"📊 [PROGRESS] {project_name}: {progress}% - {message}")
    
    def _detect_file_encoding(self, sql_file: str) -> str:
        """Détecte l'encodage du fichier SQL"""
        try:
            import chardet
        except ImportError:
            print("⚠️ chardet non disponible, utilisation d'UTF-8")
            return 'utf-8'
        
        try:
            # Lire les premiers 64KB pour détecter l'encodage
            with open(sql_file, 'rb') as f:
                raw_data = f.read(65536)
                
            result = chardet.detect(raw_data)
            encoding_result = result.get('encoding')
            if encoding_result is None:
                detected_encoding = 'utf-8'
            else:
                detected_encoding = str(encoding_result)
            confidence = result.get('confidence', 0)
            
            print(f"🔍 Encodage détecté: {detected_encoding} (confiance: {confidence:.2f})")
            
            # Vérifier que l'encodage fonctionne
            try:
                with open(sql_file, 'r', encoding=detected_encoding) as f:
                    f.read(1024)  # Test de lecture
                return detected_encoding
            except UnicodeDecodeError:
                print(f"⚠️ Encodage {detected_encoding} invalide, utilisation d'UTF-8")
                return 'utf-8'
                
        except Exception as e:
            print(f"⚠️ Erreur détection encodage: {e}, utilisation d'UTF-8")
            return 'utf-8'
    
    def _analyze_sql_file(self, sql_file: str) -> Dict[str, Any]:
        """Analyse le fichier SQL pour compter les tables et statements"""
        try:
            print("🔍 Analyse du fichier SQL...")
            
            # Détecter l'encodage du fichier
            encoding = self._detect_file_encoding(sql_file)
            
            table_count = 0
            statement_count = 0
            create_tables = []
            is_mariadb = False
            is_wordpress = False
            
            with open(sql_file, 'r', encoding=encoding, errors='ignore') as f:
                # Lire le début du fichier pour identifier le type
                header = f.read(1024)
                f.seek(0)
                content = f.read()
                
                # Détecter MariaDB
                if 'MariaDB dump' in header or 'MariaDB' in header:
                    is_mariadb = True
                    print("📊 Type de dump détecté: MariaDB")
                elif 'MySQL dump' in header or 'mysqldump' in header:
                    print("📊 Type de dump détecté: MySQL")
                
                # Détecter WordPress
                wp_keywords = ['wp_options', 'wp_posts', 'wp_users', 'wp_comments']
                found_wp_keywords = [kw for kw in wp_keywords if kw in content.lower()]
                if found_wp_keywords:
                    is_wordpress = True
                    print(f"📊 WordPress détecté (tables: {', '.join(found_wp_keywords)})")
                
                # Compter les CREATE TABLE avec support MariaDB/MySQL
                create_table_patterns = [
                    r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?`?([^`\s]+)`?',
                    r'CREATE\s+TABLE\s+`?([^`\s]+)`?'
                ]
                
                for pattern in create_table_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    create_tables.extend(matches)
                
                # Supprimer les doublons et filtrer
                create_tables = list(set([table for table in create_tables if table and not table.startswith('`')]))
                table_count = len(create_tables)
                
                # Compter les statements SQL (plus précis)
                statements = [s.strip() for s in content.split(';') if s.strip() and not s.strip().startswith('--')]
                statement_count = len(statements)
                
                file_size = os.path.getsize(sql_file)
                
                print(f"📊 Analyse terminée: {table_count} tables, {statement_count} statements")
                
                return {
                    'table_count': table_count,
                    'statement_count': statement_count,
                    'create_tables': create_tables,
                    'file_size': file_size,
                    'file_size_mb': file_size / (1024 * 1024),
                    'encoding': encoding,
                    'is_mariadb': is_mariadb,
                    'is_wordpress': is_wordpress,
                    'wp_tables': found_wp_keywords if is_wordpress else []
                }
                
        except Exception as e:
            print(f"❌ Erreur lors de l'analyse: {e}")
            return {
                'table_count': 0,
                'statement_count': 0,
                'create_tables': [],
                'file_size': 0,
                'file_size_mb': 0,
                'encoding': 'utf-8',
                'is_mariadb': False,
                'is_wordpress': False,
                'wp_tables': []
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
                    mysql_info = self.get_container_mysql_info(project_name)
                    result = subprocess.run([
                        'docker', 'exec', mysql_container,
                        'mysql', '-u', mysql_info['user'], f'-p{mysql_info["password"]}',
                        mysql_info['database'], '-e', 'SHOW TABLES;'
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
        
        # Créer le fichier de maintenance
        maintenance_file = self._enable_maintenance_mode(project_name)
        
        try:
            print(f"🚀 FastImportService: Début import pour {project_name}")
            print(f"📁 Fichier: {file_path}")
            
            # Log du début de l'opération
            wp_logger.log_database_operation('fast_import', project_name, True, 
                                           f"Début fast import: {file_path}",
                                           file_path=file_path)
            
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
            
            # Adapter les préfixes de table
            self._emit_progress(project_name, 3, "Adaptation des préfixes de table...", 'processing')
            sql_file = self._adapt_table_prefix(project_name, sql_file)
            
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
                # Effectuer le search-replace pour remplacer les URLs
                self._emit_progress(project_name, 90, 'Remplacement des URLs...', 'replacing_urls')
                print(f"🔄 [FAST_IMPORT] Début du search-replace pour {project_name}")
                
                try:
                    self._perform_url_replacement(project_name)
                    print(f"✅ [FAST_IMPORT] Search-replace terminé avec succès !")
                except Exception as e:
                    print(f"⚠️ [FAST_IMPORT] Search-replace échoué (non bloquant): {e}")
                    # Ne pas bloquer l'import si le search-replace échoue
                
                wp_logger.log_database_operation('fast_import', project_name, True, 
                                               f"Fast import terminé avec succès ({speed_mb_per_sec:.2f} MB/s)",
                                               file_path=file_path,
                                               duration=f"{duration:.2f}s",
                                               file_size=f"{size_mb:.2f} MB",
                                               tables_count=analysis_data['table_count'])
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
                wp_logger.log_database_operation('fast_import', project_name, False, 
                                               f"Fast import échoué: {result.get('error', 'Erreur inconnue')}",
                                               file_path=file_path,
                                               duration=f"{duration:.2f}s")
                self._emit_progress(project_name, 0, f"Erreur: {result.get('error', 'Erreur inconnue')}", 'error')
                return {
                    'success': False,
                    'error': result.get('error', 'Erreur lors de l\'import')
                }
                
        except Exception as e:
            print(f"❌ Erreur FastImportService: {e}")
            wp_logger.log_database_operation('fast_import', project_name, False, 
                                           f"Exception critique durant fast import: {str(e)}",
                                           file_path=file_path,
                                           error=str(e))
            self._emit_progress(project_name, 0, f"Erreur critique: {str(e)}", 'error')
            return {
                'success': False,
                'error': f'Erreur lors de l\'import: {str(e)}'
            }
        finally:
            # Désactiver le mode maintenance dans tous les cas
            self._disable_maintenance_mode(maintenance_file)
    
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
            
            # Récupérer les credentials dynamiques
            mysql_info = self.get_container_mysql_info(project_name)
            mysql_container = mysql_info['container']
            db_name = mysql_info['database']
            db_user = mysql_info['user']
            db_password = mysql_info['password']
            
            print(f"🔑 Utilisation des credentials: {db_user}@{db_name}")
            
            self._emit_progress(project_name, 15, "Vérification de MySQL...", 'connecting')
            
            # Vérifier que le conteneur MySQL est actif
            check_cmd = [
                'docker', 'exec', mysql_container,
                'mysqladmin', '-h', 'localhost', '-u', db_user, 
                f'-p{db_password}', 'ping'
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
                DROP DATABASE IF EXISTS {db_name};
                CREATE DATABASE {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                GRANT ALL PRIVILEGES ON {db_name}.* TO '{db_user}'@'%';
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
                'mysql', '-h', 'localhost', '-u', db_user, 
                f'-p{db_password}', db_name,
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
                'mysql', '-h', 'localhost', '-u', db_user, 
                f'-p{db_password}', db_name,
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
    
    def _detect_project_type(self, project_name: str) -> str:
        """
        Détecte le type de projet basé sur les conteneurs Docker actifs
        
        Args:
            project_name: Nom du projet
            
        Returns:
            'nextjs' pour Next.js+MySQL, 'wordpress' pour WordPress
        """
        try:
            # Vérifier si les conteneurs Next.js existent
            result = subprocess.run(['docker', 'ps', '--filter', f'name={project_name}_client_1', '--format', '{{.Names}}'], 
                                  capture_output=True, text=True)
            
            if result.returncode == 0 and f'{project_name}_client_1' in result.stdout:
                print(f"🔍 Projet détecté comme Next.js: {project_name}")
                return 'nextjs'
            
            # Vérifier si les conteneurs WordPress existent
            result = subprocess.run(['docker', 'ps', '--filter', f'name={project_name}_wordpress_1', '--format', '{{.Names}}'], 
                                  capture_output=True, text=True)
            
            if result.returncode == 0 and f'{project_name}_wordpress_1' in result.stdout:
                print(f"🔍 Projet détecté comme WordPress: {project_name}")
                return 'wordpress'
                
        except Exception as e:
            print(f"❌ Erreur lors de la détection du type de projet: {e}")
            
        # Par défaut, considérer comme WordPress
        print(f"🔍 Type de projet inconnu, défaut WordPress: {project_name}")
        return 'wordpress'

    def get_container_mysql_info(self, project_name: str) -> Dict[str, str]:
        """
        Récupère les informations de connexion MySQL du conteneur
        Détecte automatiquement le type de projet pour utiliser les bons credentials
        
        Args:
            project_name: Nom du projet
            
        Returns:
            Dict avec les informations de connexion
        """
        # Détecter le type de projet
        project_type = self._detect_project_type(project_name)
        
        if project_type == 'nextjs':
            # Projet Next.js+MySQL
            return {
                'container': f"{project_name}_{self.mysql_container_prefix}_1",
                'database': project_name,
                'user': project_name,
                'password': 'projectpassword'
            }
        else:
            # Projet WordPress (défaut)
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
    
    def _enable_maintenance_mode(self, project_name: str) -> Optional[str]:
        """Active le mode maintenance WordPress"""
        try:
            from app.config.app_config import PROJECTS_FOLDER
            maintenance_file = os.path.join(PROJECTS_FOLDER, project_name, '.maintenance')
            
            # Créer le fichier .maintenance avec le format WordPress
            maintenance_content = f"<?php $upgrading = {int(time.time())}; ?>"
            
            with open(maintenance_file, 'w', encoding='utf-8') as f:
                f.write(maintenance_content)
            
            print(f"🔧 [MAINTENANCE] Mode maintenance activé pour {project_name}")
            return maintenance_file
            
        except Exception as e:
            print(f"⚠️ [MAINTENANCE] Erreur lors de l'activation du mode maintenance: {e}")
            return None
    
    def _disable_maintenance_mode(self, maintenance_file: Optional[str]):
        """Désactive le mode maintenance WordPress"""
        try:
            if maintenance_file and os.path.exists(maintenance_file):
                os.remove(maintenance_file)
                print(f"✅ [MAINTENANCE] Mode maintenance désactivé")
        except Exception as e:
            print(f"⚠️ [MAINTENANCE] Erreur lors de la désactivation du mode maintenance: {e}")
    
    def _adapt_table_prefix(self, project_name: str, sql_file: str) -> str:
        """
        Adapte le préfixe de table dans le fichier SQL
        
        Args:
            project_name: Nom du projet
            sql_file: Chemin vers le fichier SQL
            
        Returns:
            Chemin vers le fichier SQL modifié
        """
        try:
            # Lire le fichier SQL
            encoding = self._detect_file_encoding(sql_file)
            with open(sql_file, 'r', encoding=encoding, errors='ignore') as f:
                sql_content = f.read()
            
            # Détecter et remplacer le préfixe
            sql_content = self._detect_and_replace_table_prefix(sql_content, project_name)
            
            # Écrire dans un nouveau fichier temporaire
            temp_sql = tempfile.mktemp(suffix='_adapted.sql')
            with open(temp_sql, 'w', encoding='utf-8') as f:
                f.write(sql_content)
            
            # Supprimer l'ancien fichier si c'était un fichier temporaire
            if sql_file.startswith(tempfile.gettempdir()):
                try:
                    os.remove(sql_file)
                except:
                    pass
            
            return temp_sql
            
        except Exception as e:
            print(f"⚠️ [PREFIX] Erreur lors de l'adaptation du préfixe: {e}")
            # En cas d'erreur, retourner le fichier original
            return sql_file
    
    def _detect_and_replace_table_prefix(self, sql_content: str, project_name: str) -> str:
        """Détecte et remplace le préfixe de table WordPress dans le SQL"""
        import re
        from app.config.app_config import PROJECTS_FOLDER
        
        try:
            # Lire le préfixe cible depuis wp-config.php
            wp_config_path = os.path.join(PROJECTS_FOLDER, project_name, 'wp-config.php')
            target_prefix = 'wp_'  # Par défaut
            
            if os.path.exists(wp_config_path):
                with open(wp_config_path, 'r', encoding='utf-8') as f:
                    config_content = f.read()
                    # Extraire le préfixe depuis $table_prefix = 'xyz_';
                    prefix_match = re.search(r"\$table_prefix\s*=\s*['\"]([^'\"]+)['\"]", config_content)
                    if prefix_match:
                        target_prefix = prefix_match.group(1)
                        print(f"🔍 [PREFIX] Préfixe cible trouvé dans wp-config.php: {target_prefix}")
            
            # Détecter le préfixe source dans le SQL
            # Rechercher les tables WordPress communes
            wp_tables = ['options', 'posts', 'users', 'comments', 'postmeta', 'usermeta', 
                         'terms', 'term_relationships', 'term_taxonomy', 'termmeta', 
                         'commentmeta', 'links']
            
            detected_prefixes = []
            for table in wp_tables:
                # Rechercher CREATE TABLE ou INSERT INTO avec préfixe
                patterns = [
                    rf'CREATE TABLE[^`]*`?(\w+)_{table}`?',
                    rf'INSERT INTO[^`]*`?(\w+)_{table}`?',
                    rf'DROP TABLE[^`]*`?(\w+)_{table}`?'
                ]
                for pattern in patterns:
                    matches = re.findall(pattern, sql_content, re.IGNORECASE)
                    detected_prefixes.extend(matches)
            
            if not detected_prefixes:
                print(f"⚠️ [PREFIX] Aucun préfixe WordPress détecté dans le SQL")
                return sql_content
            
            # Prendre le préfixe le plus courant
            from collections import Counter
            prefix_counts = Counter(detected_prefixes)
            source_prefix = prefix_counts.most_common(1)[0][0] + '_'
            print(f"🔍 [PREFIX] Préfixe source détecté dans le SQL: {source_prefix}")
            
            # Si les préfixes sont identiques, pas besoin de remplacer
            if source_prefix == target_prefix:
                print(f"ℹ️ [PREFIX] Les préfixes sont identiques ({source_prefix}), pas de remplacement nécessaire")
                return sql_content
            
            print(f"🔄 [PREFIX] Remplacement: {source_prefix} → {target_prefix}")
            
            # Remplacer le préfixe dans tout le SQL
            # 1. Dans les noms de tables avec backticks
            sql_content = re.sub(
                rf'`{re.escape(source_prefix)}(\w+)`',
                rf'`{target_prefix}\1`',
                sql_content
            )
            
            # 2. Dans les noms de tables sans backticks
            sql_content = re.sub(
                rf'\s{re.escape(source_prefix)}(\w+)\s',
                rf' {target_prefix}\1 ',
                sql_content
            )
            
            # 3. Dans les valeurs des options (wp_user_roles, etc.)
            sql_content = sql_content.replace(
                f"'{source_prefix}user_roles'",
                f"'{target_prefix}user_roles'"
            )
            sql_content = sql_content.replace(
                f'"{source_prefix}user_roles"',
                f'"{target_prefix}user_roles"'
            )
            
            # 4. Dans les meta_key de wp_usermeta
            meta_keys = ['capabilities', 'user_level', 'user-settings', 'user-settings-time', 
                         'dashboard_quick_press_last_post_id', 'user-avatar', 'metaboxhidden',
                         'closedpostboxes', 'primary_blog', 'source_domain']
            
            for meta_key in meta_keys:
                sql_content = sql_content.replace(
                    f"'{source_prefix}{meta_key}'",
                    f"'{target_prefix}{meta_key}'"
                )
                sql_content = sql_content.replace(
                    f'"{source_prefix}{meta_key}"',
                    f'"{target_prefix}{meta_key}"'
                )
            
            # 5. Remplacer dans les données sérialisées PHP
            sql_content = re.sub(
                rf's:(\d+):"({re.escape(source_prefix)}\w+)"',
                lambda m: f's:{len(m.group(2).replace(source_prefix, target_prefix))}:"{m.group(2).replace(source_prefix, target_prefix)}"',
                sql_content
            )
            
            print(f"✅ [PREFIX] Remplacement de préfixe terminé")
            return sql_content
            
        except Exception as e:
            print(f"⚠️ [PREFIX] Erreur lors du remplacement de préfixe: {e}")
            import traceback
            traceback.print_exc()
            return sql_content
    
    def _perform_url_replacement(self, project_name: str):
        """Remplace les URLs dans la base de données WordPress avec wp-cli search-replace"""
        import subprocess
        
        try:
            # Obtenir le port du projet
            from app.config.docker_config import DockerConfig
            container_path = os.path.join(DockerConfig.CONTAINERS_FOLDER, project_name)
            port_file = os.path.join(container_path, '.port')
            
            if not os.path.exists(port_file):
                print(f"⚠️ [URL_REPLACE] Fichier .port introuvable pour {project_name}")
                return
            
            with open(port_file, 'r') as f:
                port = f.read().strip()
            
            if not port:
                print(f"⚠️ [URL_REPLACE] Pas de port trouvé pour {project_name}")
                return
            
            local_url = f"http://{DockerConfig.LOCAL_IP}:{port}"
            print(f"🔗 [URL_REPLACE] URL locale: {local_url}")
            
            # Détecter l'ancienne URL dans la base de données
            # On va utiliser wp-cli pour récupérer l'URL actuelle
            wp_container = f"{project_name}_wordpress_1"
            
            # Récupérer l'URL actuelle depuis wp_options
            get_url_cmd = [
                'docker', 'exec', wp_container,
                'wp', 'option', 'get', 'siteurl',
                '--allow-root'
            ]
            
            try:
                result = subprocess.run(
                    get_url_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    old_url = result.stdout.strip()
                    print(f"🔗 [URL_REPLACE] Ancienne URL détectée: {old_url}")
                    
                    # Ne faire le remplacement que si l'URL est différente
                    if old_url and old_url != local_url:
                        print(f"🔄 [URL_REPLACE] Remplacement: {old_url} → {local_url}")
                        
                        # Commande wp-cli search-replace
                        search_replace_cmd = [
                            'docker', 'exec', wp_container,
                            'wp', 'search-replace',
                            old_url,
                            local_url,
                            '--skip-columns=guid',  # Ne pas toucher aux GUIDs
                            '--allow-root'
                        ]
                        
                        replace_result = subprocess.run(
                            search_replace_cmd,
                            capture_output=True,
                            text=True,
                            timeout=300  # 5 minutes max
                        )
                        
                        if replace_result.returncode == 0:
                            print(f"✅ [URL_REPLACE] Remplacement WP-CLI réussi !")
                            print(f"📊 [URL_REPLACE] Résultat: {replace_result.stdout}")
                            
                            # Si Elementor est installé, utiliser aussi son outil de remplacement
                            print(f"🔄 [URL_REPLACE] Vérification de la présence d'Elementor...")
                            
                            check_elementor_cmd = [
                                'docker', 'exec', wp_container,
                                'wp', 'plugin', 'is-installed', 'elementor',
                                '--allow-root'
                            ]
                            
                            elementor_check = subprocess.run(
                                check_elementor_cmd,
                                capture_output=True,
                                timeout=30
                            )
                            
                            if elementor_check.returncode == 0:
                                print(f"✅ [URL_REPLACE] Elementor détecté, lancement du remplacement Elementor...")
                                
                                elementor_replace_cmd = [
                                    'docker', 'exec', wp_container,
                                    'wp', 'elementor', 'replace-urls',
                                    old_url, local_url,
                                    '--force',
                                    '--allow-root'
                                ]
                                
                                elementor_result = subprocess.run(
                                    elementor_replace_cmd,
                                    capture_output=True,
                                    text=True,
                                    timeout=300
                                )
                                
                                if elementor_result.returncode == 0:
                                    print(f"✅ [URL_REPLACE] Remplacement Elementor terminé avec succès")
                                    print(f"📊 [URL_REPLACE] Résultat Elementor: {elementor_result.stdout}")
                                else:
                                    print(f"⚠️ [URL_REPLACE] Remplacement Elementor a échoué (non bloquant):")
                                    print(elementor_result.stderr)
                            else:
                                print(f"ℹ️ [URL_REPLACE] Elementor non installé, remplacement WP-CLI uniquement")
                        else:
                            print(f"❌ [URL_REPLACE] Erreur: {replace_result.stderr}")
                    else:
                        print(f"ℹ️ [URL_REPLACE] L'URL est déjà correcte, pas de remplacement nécessaire")
                else:
                    print(f"⚠️ [URL_REPLACE] Impossible de récupérer l'URL: {result.stderr}")
                    
            except subprocess.TimeoutExpired:
                print(f"⚠️ [URL_REPLACE] Timeout lors de la récupération de l'URL")
            except Exception as e:
                print(f"⚠️ [URL_REPLACE] Erreur lors de la récupération de l'URL: {e}")
                
        except Exception as e:
            print(f"❌ [URL_REPLACE] Erreur lors du remplacement des URLs: {e}")
            raise 