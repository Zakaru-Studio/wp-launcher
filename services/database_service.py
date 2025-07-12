#!/usr/bin/env python3
"""
Service de gestion des bases de données
"""

import os
import tempfile
import threading
from utils.file_utils import extract_zip, get_file_size_mb
from utils.database_utils import detect_file_encoding
from services.docker_service import DockerService

class DatabaseService:
    """Service pour la gestion des bases de données MySQL"""
    
    def __init__(self, socketio=None):
        self.socketio = socketio
        self.docker_service = DockerService()
    
    def import_database(self, project_path, db_file_path, project_name):
        """Importe la base de données dans le conteneur MySQL avec progress bar"""
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
                self._emit_progress(project_name, 100, 'Import terminé avec succès !', 'completed')
                return True
            else:
                print(f"❌ [DB_IMPORT] Import échoué")
                self._emit_progress(project_name, 0, 'Erreur lors de l\'import', 'error')
                return False
                
        except Exception as e:
            print(f"❌ [DB_IMPORT] Erreur lors de l'import: {e}")
            self._emit_progress(project_name, 0, f'Erreur: {str(e)}', 'error')
            return False
    
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
                return sql_content, detected_encoding
        else:
            sql_file = db_file_path
            print(f"📄 Utilisation du fichier SQL: {os.path.basename(sql_file)}")
            
            # Détecter l'encodage du fichier SQL
            print("🔍 Détection de l'encodage du fichier SQL...")
            detected_encoding, sql_content = detect_file_encoding(sql_file)
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
                'project': project_name,
                'progress': progress,
                'message': message,
                'status': status
            })
    
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