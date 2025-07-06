#!/usr/bin/env python3
"""
Service de gestion des bases de données
"""

import os
import tempfile
import threading
from utils.file_utils import extract_zip, detect_file_encoding, get_file_size_mb
from services.docker_service import DockerService

class DatabaseService:
    """Service pour la gestion des bases de données MySQL"""
    
    def __init__(self, socketio=None):
        self.socketio = socketio
        self.docker_service = DockerService()
    
    def import_database(self, project_path, db_file_path, project_name):
        """Importe la base de données dans le conteneur MySQL avec progress bar"""
        try:
            print(f"🔍 DEBUG: Début import DB pour {project_name}")
            print(f"🔍 DEBUG: Chemin projet: {project_path}")
            print(f"🔍 DEBUG: Fichier DB: {db_file_path}")
            
            # Envoyer le statut initial
            self._emit_progress(project_name, 0, 'Initialisation...', 'starting')
            
            # Vérifier que le fichier existe
            if not os.path.exists(db_file_path):
                raise Exception(f"Fichier de base de données non trouvé: {db_file_path}")
            
            self._emit_progress(project_name, 10, 'Vérification du fichier...', 'checking')
            
            # Traiter le fichier selon son type
            sql_content, detected_encoding = self._process_db_file(db_file_path, project_name)
            
            if sql_content is None:
                raise Exception("Impossible de lire le fichier SQL avec les encodages supportés")
            
            # Attendre que MySQL soit prêt
            self._emit_progress(project_name, 25, 'Attente de MySQL...', 'waiting')
            
            if not self.docker_service.wait_for_mysql(project_name, max_wait_time=60):
                raise Exception("MySQL n'est pas prêt après 1 minute d'attente intelligente")
            
            # Effectuer l'import
            self._emit_progress(project_name, 40, 'Import en cours...', 'importing')
            
            success = self._perform_import(project_name, sql_content, detected_encoding)
            
            if success:
                self._emit_progress(project_name, 100, 'Import terminé avec succès !', 'completed')
                return True
            else:
                self._emit_progress(project_name, 0, 'Erreur lors de l\'import', 'error')
                return False
                
        except Exception as e:
            print(f"❌ Erreur lors de l'import: {e}")
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
        """Effectue l'import SQL dans MySQL"""
        try:
            # Créer un fichier temporaire avec le contenu SQL
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False, encoding=encoding) as temp_sql:
                temp_sql.write(sql_content)
                temp_sql_path = temp_sql.name
            
            try:
                # Copier le fichier SQL dans le conteneur
                print("📋 Copie du fichier SQL dans le conteneur...")
                success, stdout, stderr = self.docker_service.execute_command_in_container(
                    project_name, 'mysql', 
                    ['cp', temp_sql_path, f'/tmp/import.sql'],
                    timeout=30
                )
                
                if not success:
                    # Alternative: utiliser docker cp
                    import subprocess
                    container_name = f"{project_name}_mysql_1"
                    result = subprocess.run([
                        'docker', 'cp', temp_sql_path, f'{container_name}:/tmp/import.sql'
                    ], capture_output=True, text=True)
                    
                    if result.returncode != 0:
                        raise Exception(f"Erreur lors de la copie du fichier SQL: {result.stderr}")
                
                print("✅ Fichier SQL copié dans le conteneur")
                
                # Importer la base de données
                print("🗃️ Import de la base de données...")
                file_size_mb = len(sql_content.encode(encoding)) / (1024 * 1024)
                print(f"📊 Taille du fichier: {file_size_mb:.1f} MB")
                
                # Déterminer la méthode d'import selon la taille
                if file_size_mb > 50:
                    # Grosse base : import par chunks
                    return self._import_large_database(project_name, encoding)
                else:
                    # Base normale : import direct
                    return self._import_standard_database(project_name)
                    
            finally:
                # Nettoyer le fichier temporaire
                if os.path.exists(temp_sql_path):
                    os.unlink(temp_sql_path)
                    
        except Exception as e:
            print(f"❌ Erreur lors de l'import SQL: {e}")
            return False
    
    def _import_standard_database(self, project_name):
        """Import standard pour les bases de données de taille normale"""
        try:
            success, stdout, stderr = self.docker_service.execute_command_in_container(
                project_name, 'mysql',
                ['mysql', '-u', 'wordpress', '-pwordpress', 'wordpress'],
                timeout=300  # 5 minutes max
            )
            
            if success:
                print("✅ Base de données importée avec succès")
                return True
            else:
                print(f"❌ Erreur lors de l'import: {stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Erreur import standard: {e}")
            return False
    
    def _import_large_database(self, project_name, encoding):
        """Import optimisé pour les grosses bases de données"""
        try:
            print("🚀 Import optimisé pour grosse base de données...")
            
            # Utiliser mysql avec des paramètres optimisés
            success, stdout, stderr = self.docker_service.execute_command_in_container(
                project_name, 'mysql',
                [
                    'mysql', 
                    '-u', 'wordpress', 
                    '-pwordpress',
                    '--max_allowed_packet=1G',
                    '--innodb_buffer_pool_size=256M',
                    '--default-character-set=utf8mb4',
                    'wordpress'
                ],
                timeout=1800  # 30 minutes max
            )
            
            if success:
                print("✅ Grosse base de données importée avec succès")
                return True
            else:
                print(f"❌ Erreur lors de l'import de la grosse base: {stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Erreur import grosse base: {e}")
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