#!/usr/bin/env python3
"""
Service de gestion des bases de données
"""

import os
import tempfile
import threading
import time
from app.utils.file_utils import extract_zip, get_file_size_mb
from app.utils.database_utils import detect_file_encoding
from app.services.docker_service import DockerService
from app.utils.logger import wp_logger
from app.config.docker_config import DockerConfig

class DatabaseService:
    """Service pour la gestion des bases de données MySQL"""
    
    def __init__(self, socketio=None):
        self.socketio = socketio
        self.docker_service = DockerService()
    
    def import_database(self, project_path, db_file_path, project_name):
        """Importe la base de données dans le conteneur MySQL avec progress bar"""
        # Log du début de l'opération
        wp_logger.log_database_operation('import', project_name, True, 
                                        f"Début import DB: {db_file_path}",
                                        file_path=db_file_path,
                                        project_path=project_path)
        
        # Créer le fichier de maintenance
        maintenance_file = self._enable_maintenance_mode(project_name)
        
        try:
            print(f"🔍 [DB_IMPORT] Début import DB pour {project_name}")
            print(f"🔍 [DB_IMPORT] Chemin projet: {project_path}")
            print(f"🔍 [DB_IMPORT] Fichier DB: {db_file_path}")
            print(f"🔍 [DB_IMPORT] Nom du conteneur MySQL: {project_name}_mysql_1")
            
            # Envoyer le statut initial
            self._emit_progress(project_name, 0, 'Initialisation...', 'starting')
            
            # Vérifier que le fichier existe
            if not os.path.exists(db_file_path):
                print(f"❌ [DB_IMPORT] Fichier de base de données non trouvé: {db_file_path}")
                raise Exception(f"Fichier de base de données non trouvé: {db_file_path}")
            
            file_size = os.path.getsize(db_file_path)
            print(f"📊 [DB_IMPORT] Taille du fichier: {file_size} bytes ({file_size/1024/1024:.2f} MB)")
            
            self._emit_progress(project_name, 10, 'Vérification du fichier...', 'checking')
            
            # Traiter le fichier selon son type
            print(f"🔍 [DB_IMPORT] Traitement du fichier...")
            sql_content, detected_encoding = self._process_db_file(db_file_path, project_name)
            
            if sql_content is None:
                print(f"❌ [DB_IMPORT] Impossible de lire le fichier SQL avec les encodages supportés")
                raise Exception("Impossible de lire le fichier SQL avec les encodages supportés")
            
            print(f"✅ [DB_IMPORT] Fichier SQL traité avec succès")
            print(f"📊 [DB_IMPORT] Encodage détecté: {detected_encoding}")
            print(f"📊 [DB_IMPORT] Taille du contenu SQL: {len(sql_content)} caractères")
            
            # Attendre que MySQL soit prêt
            self._emit_progress(project_name, 25, 'Attente de MySQL...', 'waiting')
            print(f"⏳ [DB_IMPORT] Attente de MySQL...")
            
            if not self.docker_service.wait_for_mysql(project_name, max_wait_time=60):
                print(f"❌ [DB_IMPORT] MySQL n'est pas prêt après 1 minute d'attente")
                raise Exception("MySQL n'est pas prêt après 1 minute d'attente intelligente")
            
            print(f"✅ [DB_IMPORT] MySQL est prêt")
            
            # Effectuer l'import
            self._emit_progress(project_name, 40, 'Import en cours...', 'importing')
            print(f"🚀 [DB_IMPORT] Début de l'import...")
            
            success = self._perform_import(project_name, sql_content, detected_encoding)
            
            if success:
                print(f"✅ [DB_IMPORT] Import terminé avec succès !")
                
                # Effectuer le search-replace pour remplacer les URLs
                self._emit_progress(project_name, 90, 'Remplacement des URLs...', 'replacing_urls')
                print(f"🔄 [DB_IMPORT] Début du search-replace pour {project_name}")
                
                try:
                    self._perform_url_replacement(project_name)
                    print(f"✅ [DB_IMPORT] Search-replace terminé avec succès !")
                except Exception as e:
                    print(f"⚠️ [DB_IMPORT] Search-replace échoué (non bloquant): {e}")
                    # Ne pas bloquer l'import si le search-replace échoue
                
                wp_logger.log_database_operation('import', project_name, True, 
                                               "Import DB terminé avec succès",
                                               file_path=db_file_path,
                                               encoding=detected_encoding)
                self._emit_progress(project_name, 100, 'Import terminé avec succès !', 'completed')
                return True
            else:
                print(f"❌ [DB_IMPORT] Import échoué")
                wp_logger.log_database_operation('import', project_name, False, 
                                               "Échec de l'import DB",
                                               file_path=db_file_path)
                self._emit_progress(project_name, 0, 'Erreur lors de l\'import', 'error')
                return False
                
        except Exception as e:
            print(f"❌ [DB_IMPORT] Erreur lors de l'import: {e}")
            wp_logger.log_database_operation('import', project_name, False, 
                                           f"Exception durant l'import: {str(e)}",
                                           file_path=db_file_path,
                                           error=str(e))
            self._emit_progress(project_name, 0, f'Erreur: {str(e)}', 'error')
            return False
        finally:
            # Désactiver le mode maintenance dans tous les cas
            self._disable_maintenance_mode(maintenance_file)
    
    def _process_db_file(self, db_file_path, project_name):
        """Traite le fichier de base de données (ZIP ou SQL)"""
        if db_file_path.endswith('.zip'):
            print("📦 Extraction de l'archive ZIP...")
            self._emit_progress(project_name, 15, 'Extraction de l\'archive...', 'extracting')
            
            with tempfile.TemporaryDirectory() as temp_dir:
                extract_zip(db_file_path, temp_dir)
                # Chercher le fichier .sql dans l'extraction
                sql_files = [f for f in os.listdir(temp_dir) if f.endswith('.sql')]
                if not sql_files:
                    raise Exception("Aucun fichier .sql trouvé dans l'archive")
                sql_file = os.path.join(temp_dir, sql_files[0])
                print(f"📄 Fichier SQL trouvé: {sql_files[0]}")
                
                self._emit_progress(project_name, 20, 'Détection de l\'encodage...', 'analyzing')
                
                # Détecter l'encodage du fichier SQL extrait
                detected_encoding, sql_content = detect_file_encoding(sql_file)
                
                # Adapter les préfixes de table
                self._emit_progress(project_name, 22, 'Adaptation des préfixes de table...', 'processing')
                sql_content = self._detect_and_replace_table_prefix(sql_content, project_name)
                
                return sql_content, detected_encoding
        else:
            sql_file = db_file_path
            print(f"📄 Utilisation du fichier SQL: {os.path.basename(sql_file)}")
            
            # Détecter l'encodage du fichier SQL
            print("🔍 Détection de l'encodage du fichier SQL...")
            detected_encoding, sql_content = detect_file_encoding(sql_file)
            
            # Adapter les préfixes de table
            self._emit_progress(project_name, 22, 'Adaptation des préfixes de table...', 'processing')
            sql_content = self._detect_and_replace_table_prefix(sql_content, project_name)
            
            return sql_content, detected_encoding
    
    def _perform_import(self, project_name, sql_content, encoding):
        """Effectue l'import de la base de données avec plusieurs méthodes de fallback"""
        try:
            print(f"🔍 [PERFORM_IMPORT] Début de l'import pour {project_name}")
            print(f"🔍 [PERFORM_IMPORT] Encodage: {encoding}")
            print(f"🔍 [PERFORM_IMPORT] Taille du contenu: {len(sql_content)} caractères")
            
            # Analyser le contenu SQL
            lines = sql_content.split('\n')
            non_empty_lines = [line for line in lines if line.strip() and not line.strip().startswith('--')]
            sql_statements = sql_content.split(';')
            actual_statements = [stmt for stmt in sql_statements if stmt.strip()]
            
            print(f"📊 [PERFORM_IMPORT] Analyse du contenu SQL:")
            print(f"   - Nombre de lignes: {len(lines)}")
            print(f"   - Lignes non vides: {len(non_empty_lines)}")
            print(f"   - Statements SQL: {len(actual_statements)}")
            
            # Vérifier si c'est une base de données WordPress
            wp_keywords = ['wp_options', 'wp_posts', 'wp_users', 'wp_comments']
            found_wp_keywords = [kw for kw in wp_keywords if kw in sql_content.lower()]
            print(f"📊 [PERFORM_IMPORT] Mots-clés WordPress trouvés: {found_wp_keywords}")
            
            if not found_wp_keywords:
                print(f"⚠️ [PERFORM_IMPORT] Attention: Le fichier SQL ne semble pas contenir de tables WordPress standard")
            
            # Copier le contenu SQL dans le conteneur
            print(f"📋 [PERFORM_IMPORT] Copie du fichier SQL dans le conteneur...")
            container_name = f"{project_name}_mysql_1"
            
            # Créer un fichier temporaire local
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', encoding=encoding, delete=False, suffix='.sql') as temp_file:
                temp_file.write(sql_content)
                temp_file_path = temp_file.name
            
            print(f"📋 [PERFORM_IMPORT] Fichier temporaire créé: {temp_file_path}")
            
            # Copier le fichier dans le conteneur
            copy_success, copy_stdout, copy_stderr = self.docker_service.execute_command(
                ['docker', 'cp', temp_file_path, f'{container_name}:/tmp/import.sql'],
                timeout=60
            )
            
            # Nettoyer le fichier temporaire
            os.unlink(temp_file_path)
            
            if not copy_success:
                print(f"❌ [PERFORM_IMPORT] Erreur lors de la copie du fichier: {copy_stderr}")
                return False
            
            print(f"✅ [PERFORM_IMPORT] Fichier SQL copié dans le conteneur")
            
            # Déterminer la méthode d'import selon la taille
            file_size_mb = len(sql_content.encode(encoding)) / 1024 / 1024
            print(f"📊 [PERFORM_IMPORT] Taille estimée: {file_size_mb:.2f} MB")
            
            if file_size_mb > 100:
                print(f"🚀 [PERFORM_IMPORT] Fichier volumineux détecté, utilisation de la méthode optimisée")
                return self._import_large_database(project_name, encoding)
            else:
                print(f"🚀 [PERFORM_IMPORT] Fichier standard, utilisation de la méthode normale")
                return self._import_standard_database(project_name)
                    
        except Exception as e:
            print(f"❌ [PERFORM_IMPORT] Erreur lors de l'import SQL: {e}")
            return False
    
    def _import_standard_database(self, project_name):
        """Import standard pour les bases de données de taille normale"""
        try:
            print(f"🔍 [STANDARD_IMPORT] Début de l'import standard pour {project_name}")
            container_name = f"{project_name}_mysql_1"
            
            # Vérifier que le conteneur existe et est actif
            print(f"🔍 [STANDARD_IMPORT] Vérification du conteneur {container_name}")
            check_success, check_stdout, check_stderr = self.docker_service.execute_command(
                ['docker', 'ps', '--filter', f'name={container_name}', '--format', '{{.Names}}'],
                timeout=10
            )
            
            if not check_success or container_name not in check_stdout:
                print(f"❌ [STANDARD_IMPORT] Conteneur non trouvé ou non actif: {check_stderr}")
                return False
            
            print(f"✅ [STANDARD_IMPORT] Conteneur {container_name} trouvé et actif")
            
            # Étape 1: Supprimer et recréer la base de données
            print(f"🗑️ [STANDARD_IMPORT] Suppression et recréation de la base de données...")
            drop_success, drop_stdout, drop_stderr = self.docker_service.execute_command_in_container(
                project_name, 'mysql',
                ['mysql', '-u', 'root', '-prootpassword', '-e', '''
                DROP DATABASE IF EXISTS wordpress;
                CREATE DATABASE wordpress CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                GRANT ALL PRIVILEGES ON wordpress.* TO 'wordpress'@'%';
                FLUSH PRIVILEGES;
                '''],
                timeout=60
            )
            
            if drop_success:
                print(f"✅ [STANDARD_IMPORT] Base de données supprimée et recréée")
            else:
                print(f"⚠️ [STANDARD_IMPORT] Erreur lors de la suppression/recréation: {drop_stderr}")
                # Continuer quand même
            
            # Vérifier que le fichier SQL existe dans le conteneur
            print(f"🔍 [STANDARD_IMPORT] Vérification du fichier SQL dans le conteneur...")
            file_success, file_stdout, file_stderr = self.docker_service.execute_command_in_container(
                project_name, 'mysql',
                ['ls', '-la', '/tmp/import.sql'],
                timeout=10
            )
            
            if not file_success:
                print(f"❌ [STANDARD_IMPORT] Fichier SQL non trouvé dans le conteneur: {file_stderr}")
                return False
            
            print(f"✅ [STANDARD_IMPORT] Fichier SQL trouvé dans le conteneur:")
            print(f"   {file_stdout.strip()}")
            
            # Méthode 1: Import direct via mysql commande
            print(f"🚀 [STANDARD_IMPORT] Méthode 1: Import direct via mysql...")
            
            # Importer depuis le fichier temporaire dans le conteneur
            success, stdout, stderr = self.docker_service.execute_command_in_container(
                project_name, 'mysql',
                ['mysql', '-u', 'wordpress', '-pwordpress', 'wordpress', '-e', 'source /tmp/import.sql'],
                timeout=300  # 5 minutes max
            )
            
            if success:
                print("✅ [STANDARD_IMPORT] Import réussi avec la méthode 1")
                return True
            else:
                print(f"❌ [STANDARD_IMPORT] Erreur méthode 1: {stderr}")
                print(f"📋 [STANDARD_IMPORT] Output: {stdout}")
                
                # Méthode 2: Import via redirection
                print("🔄 [STANDARD_IMPORT] Méthode 2: Import via redirection...")
                
                # Lire le fichier depuis le conteneur et l'importer
                read_success, file_content, read_stderr = self.docker_service.execute_command_in_container(
                    project_name, 'mysql',
                    ['cat', '/tmp/import.sql'],
                    timeout=60
                )
                
                if read_success and file_content:
                    print(f"✅ [STANDARD_IMPORT] Fichier SQL lu depuis le conteneur ({len(file_content)} caractères)")
                    
                    # Importer via stdin
                    import_success, import_stdout, import_stderr = self.docker_service.execute_command_in_container(
                        project_name, 'mysql',
                        ['mysql', '-u', 'wordpress', '-pwordpress', 'wordpress'],
                        input_data=file_content,
                        timeout=300
                    )
                    
                    if import_success:
                        print("✅ [STANDARD_IMPORT] Import réussi avec la méthode 2")
                        return True
                    else:
                        print(f"❌ [STANDARD_IMPORT] Erreur méthode 2: {import_stderr}")
                        print(f"📋 [STANDARD_IMPORT] Output: {import_stdout}")
                        
                        # Méthode 3: Import par chunks
                        print("🔄 [STANDARD_IMPORT] Méthode 3: Import par chunks...")
                        return self._import_by_chunks(project_name, file_content)
                else:
                    print(f"❌ [STANDARD_IMPORT] Impossible de lire le fichier SQL: {read_stderr}")
                    return False
                    
        except Exception as e:
            print(f"❌ [STANDARD_IMPORT] Erreur lors de l'import standard: {e}")
            return False
    
    def _import_large_database(self, project_name, encoding):
        """Import optimisé pour les grosses bases de données"""
        try:
            print(f"🔍 [LARGE_IMPORT] Début de l'import optimisé pour {project_name}")
            container_name = f"{project_name}_mysql_1"
            
            # Vérifier que le conteneur existe et est actif
            print(f"🔍 [LARGE_IMPORT] Vérification du conteneur {container_name}")
            check_success, check_stdout, check_stderr = self.docker_service.execute_command(
                ['docker', 'ps', '--filter', f'name={container_name}', '--format', '{{.Names}}'],
                timeout=10
            )
            
            if not check_success or container_name not in check_stdout:
                print(f"❌ [LARGE_IMPORT] Conteneur non trouvé ou non actif: {check_stderr}")
                return False
            
            print(f"✅ [LARGE_IMPORT] Conteneur {container_name} trouvé et actif")
            
            # Étape 1: Supprimer et recréer la base de données
            print(f"🗑️ [LARGE_IMPORT] Suppression et recréation de la base de données...")
            drop_success, drop_stdout, drop_stderr = self.docker_service.execute_command_in_container(
                project_name, 'mysql',
                ['mysql', '-u', 'root', '-prootpassword', '-e', '''
                DROP DATABASE IF EXISTS wordpress;
                CREATE DATABASE wordpress CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                GRANT ALL PRIVILEGES ON wordpress.* TO 'wordpress'@'%';
                FLUSH PRIVILEGES;
                '''],
                timeout=60
            )
            
            if drop_success:
                print(f"✅ [LARGE_IMPORT] Base de données supprimée et recréée")
            else:
                print(f"⚠️ [LARGE_IMPORT] Erreur lors de la suppression/recréation: {drop_stderr}")
                # Continuer quand même
            
            # Utiliser mysql avec des paramètres optimisés pour importer depuis le fichier
            print(f"🚀 [LARGE_IMPORT] Import avec paramètres optimisés...")
            success, stdout, stderr = self.docker_service.execute_command_in_container(
                project_name, 'mysql',
                [
                    'mysql', 
                    '-u', 'wordpress', 
                    '-pwordpress',
                    '--max_allowed_packet=1G',
                    '--default-character-set=utf8mb4',
                    'wordpress',
                    '-e', 'source /tmp/import.sql'
                ],
                timeout=1800  # 30 minutes max
            )
            
            if success:
                print("✅ [LARGE_IMPORT] Import réussi avec la méthode optimisée")
                return True
            else:
                print(f"❌ [LARGE_IMPORT] Erreur lors de l'import optimisé: {stderr}")
                print(f"📋 [LARGE_IMPORT] Output: {stdout}")
                
                # Fallback vers la méthode standard
                print("🔄 [LARGE_IMPORT] Fallback vers la méthode standard...")
                return self._import_standard_database(project_name)
                
        except Exception as e:
            print(f"❌ [LARGE_IMPORT] Erreur lors de l'import optimisé: {e}")
            return False
    
    def _import_by_chunks(self, project_name, sql_content):
        """Import par chunks pour les cas difficiles"""
        try:
            print(f"🔍 [CHUNK_IMPORT] Début de l'import par chunks pour {project_name}")
            
            # Diviser le contenu en statements
            statements = sql_content.split(';')
            total_statements = len(statements)
            print(f"📊 [CHUNK_IMPORT] {total_statements} statements à importer")
            
            success_count = 0
            error_count = 0
            
            for i, statement in enumerate(statements):
                if statement.strip():
                    try:
                        chunk_success, chunk_stdout, chunk_stderr = self.docker_service.execute_command_in_container(
                            project_name, 'mysql',
                            ['mysql', '-u', 'wordpress', '-pwordpress', 'wordpress'],
                            input_data=statement + ';',
                            timeout=30
                        )
                        
                        if chunk_success:
                            success_count += 1
                        else:
                            error_count += 1
                            if 'Duplicate entry' not in chunk_stderr:
                                print(f"❌ [CHUNK_IMPORT] Erreur statement {i+1}: {chunk_stderr}")
                        
                        if i % 100 == 0:
                            print(f"📊 [CHUNK_IMPORT] Progress: {i}/{total_statements} statements (succès: {success_count}, erreurs: {error_count})")
                    
                    except Exception as e:
                        error_count += 1
                        print(f"❌ [CHUNK_IMPORT] Exception statement {i+1}: {e}")
            
            print(f"📊 [CHUNK_IMPORT] Import terminé: {success_count} succès, {error_count} erreurs")
            
            # Considérer l'import comme réussi si au moins 80% des statements ont réussi
            success_rate = success_count / max(1, success_count + error_count)
            print(f"📊 [CHUNK_IMPORT] Taux de réussite: {success_rate:.2%}")
            
            if success_rate >= 0.8:
                print("✅ [CHUNK_IMPORT] Import considéré comme réussi")
                return True
            else:
                print("❌ [CHUNK_IMPORT] Trop d'erreurs, import considéré comme échoué")
                return False
                
        except Exception as e:
            print(f"❌ [CHUNK_IMPORT] Erreur lors de l'import par chunks: {e}")
            return False
    
    def create_clean_database(self, project_path, project_name):
        """Crée une base de données WordPress vierge prête pour l'installation"""
        try:
            print(f"🐳 Conteneur MySQL: {project_name}_mysql_1")
            
            # Attendre que MySQL soit prêt
            print("🧠 Attente silencieuse de la disponibilité MySQL...")
            
            if not self.docker_service.wait_for_mysql(project_name, max_wait_time=60):
                print("❌ MySQL n'est pas prêt après 60 tentatives")
                return False
            
            # Créer la base de données WordPress vierge
            print("🗃️ Création de la base de données WordPress vierge...")
            success, stdout, stderr = self.docker_service.execute_command_in_container(
                project_name, 'mysql',
                [
                    'mysql', '-u', 'wordpress', '-pwordpress', 
                    '-e', 'CREATE DATABASE IF NOT EXISTS wordpress DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'
                ],
                timeout=30
            )
            
            if not success:
                print(f"❌ Erreur lors de la création de la base: {stderr}")
                return False
            
            print("✅ Base de données WordPress vierge créée avec succès")
            return True
            
        except Exception as e:
            print(f"❌ Erreur lors de la création de la base de données: {e}")
            return False
    
    def export_database(self, project_name, export_path):
        """Exporte la base de données d'un projet"""
        try:
            print(f"📤 Export de la base de données pour {project_name}")
            
            # Vérifier que MySQL est prêt
            if not self.docker_service.check_mysql_ready(project_name):
                return False, "MySQL n'est pas accessible"
            
            # Effectuer l'export
            success, stdout, stderr = self.docker_service.execute_command_in_container(
                project_name, 'mysql',
                [
                    'mysqldump', 
                    '-u', 'wordpress', 
                    '-pwordpress',
                    '--single-transaction',
                    '--routines',
                    '--triggers',
                    'wordpress'
                ],
                timeout=300
            )
            
            if success:
                # Sauvegarder le dump
                with open(export_path, 'w') as f:
                    f.write(stdout)
                print(f"✅ Base de données exportée vers {export_path}")
                return True, None
            else:
                print(f"❌ Erreur export: {stderr}")
                return False, stderr
                
        except Exception as e:
            print(f"❌ Erreur lors de l'export: {e}")
            return False, str(e)
    
    def _emit_progress(self, project_name, progress, message, status):
        """Émet un événement de progression via SocketIO"""
        if self.socketio:
            self.socketio.emit('import_progress', {
                'type': 'database_import',
                'project': project_name,
                'progress': progress,
                'message': message,
                'status': status
            })
    
    def _enable_maintenance_mode(self, project_name):
        """Active le mode maintenance WordPress"""
        from app.config.app_config import PROJECTS_FOLDER
        
        try:
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
    
    def _disable_maintenance_mode(self, maintenance_file):
        """Désactive le mode maintenance WordPress"""
        try:
            if maintenance_file and os.path.exists(maintenance_file):
                os.remove(maintenance_file)
                print(f"✅ [MAINTENANCE] Mode maintenance désactivé")
        except Exception as e:
            print(f"⚠️ [MAINTENANCE] Erreur lors de la désactivation du mode maintenance: {e}")
    
    def _detect_and_replace_table_prefix(self, sql_content, project_name):
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
            # 1. Dans les noms de tables avec backticks (CREATE TABLE, DROP TABLE, INSERT INTO, etc.)
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
            
            # 4. Dans les meta_key de wp_usermeta (capabilities, user_level, etc.)
            meta_keys = ['capabilities', 'user_level', 'user-settings', 'user-settings-time', 
                         'dashboard_quick_press_last_post_id', 'user-avatar', 'metaboxhidden',
                         'closedpostboxes', 'primary_blog', 'source_domain']
            
            for meta_key in meta_keys:
                # Remplacer dans les valeurs SQL
                sql_content = sql_content.replace(
                    f"'{source_prefix}{meta_key}'",
                    f"'{target_prefix}{meta_key}'"
                )
                sql_content = sql_content.replace(
                    f'"{source_prefix}{meta_key}"',
                    f'"{target_prefix}{meta_key}"'
                )
            
            # 5. Remplacer dans les données sérialisées PHP (pour capabilities, etc.)
            # Format: s:XX:"wp_capabilities" où XX est la longueur
            def replace_serialized(match):
                old_str = match.group(1)
                new_str = old_str.replace(source_prefix, target_prefix)
                new_len = len(new_str)
                return f's:{new_len}:"{new_str}"'
            
            # Rechercher et remplacer les chaînes sérialisées contenant le préfixe
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
            # En cas d'erreur, retourner le SQL original
            return sql_content
    
    def _perform_url_replacement(self, project_name):
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
    
    def import_database_async(self, project_path, db_file_path, project_name):
        """Lance l'import de base de données en arrière-plan"""
        def run_import():
            try:
                result = self.import_database(project_path, db_file_path, project_name)
                self._emit_progress(
                    project_name, 
                    100 if result else 0, 
                    'Import terminé' if result else 'Erreur lors de l\'import', 
                    'completed' if result else 'error'
                )
            except Exception as e:
                self._emit_progress(project_name, 0, f'Erreur: {str(e)}', 'error')
        
        # Lancer dans un thread séparé
        import_thread = threading.Thread(target=run_import)
        import_thread.daemon = True
        import_thread.start()
        
        return import_thread
    
    # ==================== DEV INSTANCES SUPPORT ====================
    
    def clone_database(self, source_project, source_db_name, target_db_name, target_port, socketio=None):
        """
        Clone une base de données MySQL dans le MÊME conteneur MySQL (MySQL partagé).
        
        Args:
            source_project: Nom du projet source (pour trouver le conteneur MySQL)
            source_db_name: Nom de la DB source (ex: 'projet_principal')
            target_db_name: Nom de la DB cible (ex: 'projet_principal_dev_alice')
            target_port: Port HTTP de l'instance cible (pour update wp_options)
            socketio: Pour envoyer des logs en temps réel
        """
        import subprocess
        
        try:
            if socketio:
                socketio.emit('db_clone_progress', {
                    'step': 1,
                    'total': 5,
                    'message': f'Export de {source_db_name}...'
                })
            
            # 1. Export DB source
            export_file = f'/tmp/clone_{target_db_name}_{int(time.time())}.sql'
            mysql_container = f"{source_project}_mysql_1"
            
            # Vérifier que le conteneur existe et est actif
            check_cmd = ['docker', 'ps', '--filter', f'name={mysql_container}', '--format', '{{.Names}}']
            check_result = subprocess.run(check_cmd, capture_output=True, text=True)
            
            if mysql_container not in check_result.stdout:
                # Essayer sans le _1
                mysql_container_alt = f"{source_project}_mysql"
                check_result_alt = subprocess.run(['docker', 'ps', '--filter', f'name={mysql_container_alt}', '--format', '{{.Names}}'], 
                                                 capture_output=True, text=True)
                if mysql_container_alt in check_result_alt.stdout:
                    mysql_container = mysql_container_alt
                else:
                    raise Exception(f"Conteneur MySQL introuvable pour le projet {source_project}. Vérifiez que le projet est démarré.")
            
            # Export avec redirection correcte
            export_cmd = ['docker', 'exec', mysql_container, 'mysqldump', '-u', 'root', '-prootpassword', source_db_name]
            with open(export_file, 'w') as f:
                result = subprocess.run(export_cmd, stdout=f, stderr=subprocess.PIPE, text=True)
                if result.returncode != 0:
                    # Vérifier si le conteneur existe
                    check_container = subprocess.run(['docker', 'ps', '-a', '--filter', f'name={mysql_container}', '--format', '{{.Names}}'], 
                                                    capture_output=True, text=True)
                    if mysql_container not in check_container.stdout:
                        raise Exception(f"Conteneur MySQL introuvable: {mysql_container}. Conteneurs disponibles: {check_container.stdout.strip()}")
                    raise Exception(f"Erreur mysqldump: {result.stderr}")
            
            if socketio:
                socketio.emit('db_clone_progress', {
                    'step': 2,
                    'total': 5,
                    'message': f'Création de la DB {target_db_name}...'
                })
            
            # 2. Créer nouvelle DB
            create_db_cmd = f"docker exec {mysql_container} mysql -u root -prootpassword -e 'CREATE DATABASE IF NOT EXISTS {target_db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'"
            subprocess.run(create_db_cmd, shell=True, check=True)
            
            if socketio:
                socketio.emit('db_clone_progress', {
                    'step': 3,
                    'total': 5,
                    'message': 'Import des données...'
                })
            
            # 3. Import dans nouvelle DB
            import_cmd = ['docker', 'exec', '-i', mysql_container, 'mysql', '-u', 'root', '-prootpassword', target_db_name]
            with open(export_file, 'r') as f:
                result = subprocess.run(import_cmd, stdin=f, stderr=subprocess.PIPE, text=True)
                if result.returncode != 0:
                    raise Exception(f"Erreur mysql import: {result.stderr}")
            
            if socketio:
                socketio.emit('db_clone_progress', {
                    'step': 4,
                    'total': 5,
                    'message': 'Mise à jour des URLs WordPress...'
                })
            
            # 4. Mettre à jour les URLs WordPress
            update_url_cmd = f"""docker exec {mysql_container} mysql -u root -prootpassword {target_db_name} -e "UPDATE wp_options SET option_value = 'http://{DockerConfig.LOCAL_IP}:{target_port}' WHERE option_name IN ('siteurl', 'home');" """
            subprocess.run(update_url_cmd, shell=True, check=True)
            
            if socketio:
                socketio.emit('db_clone_progress', {
                    'step': 5,
                    'total': 5,
                    'message': 'Nettoyage...'
                })
            
            # 5. Nettoyer fichier temporaire
            if os.path.exists(export_file):
                os.remove(export_file)
            
            return {'success': True}
            
        except Exception as e:
            if socketio:
                socketio.emit('db_clone_progress', {
                    'error': True,
                    'message': f'Erreur: {str(e)}'
                })
            raise Exception(f"Erreur lors du clonage de la DB: {str(e)}")
    
    def export_database_with_db_name(self, project_name, db_name=None, output_file=None):
        """
        Export une base de données (compatible instances dev).
        
        Args:
            project_name: Nom du projet (pour retrouver le conteneur MySQL)
            db_name: Nom de la DB (optionnel, par défaut = project_name formaté)
            output_file: Chemin du fichier de sortie
        """
        import subprocess
        from datetime import datetime
        
        if db_name is None:
            db_name = project_name.replace('-', '_')
        
        if output_file is None:
            output_file = f'backups/{db_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.sql'
        
        # Utiliser le conteneur MySQL du projet parent
        # Si c'est une instance dev, extraire le projet parent du nom
        if '-dev-' in project_name:
            parent_project = project_name.split('-dev-')[0]
            mysql_container = f"{parent_project}_mysql"
        else:
            mysql_container = f"{project_name}_mysql"
        
        cmd = f"docker exec {mysql_container} mysqldump -u root -proot_password {db_name} > {output_file}"
        subprocess.run(cmd, shell=True, check=True)
        
        return output_file
    
    def import_database_with_db_name(self, project_name, db_name=None, import_file=None):
        """
        Import une base de données (compatible instances dev).
        """
        import subprocess
        
        if db_name is None:
            db_name = project_name.replace('-', '_')
        
        # Même logique pour trouver le bon conteneur MySQL
        if '-dev-' in project_name:
            parent_project = project_name.split('-dev-')[0]
            mysql_container = f"{parent_project}_mysql"
        else:
            mysql_container = f"{project_name}_mysql"
        
        cmd = f"docker exec -i {mysql_container} mysql -u root -proot_password {db_name} < {import_file}"
        subprocess.run(cmd, shell=True, check=True) 