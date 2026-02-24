#!/usr/bin/env python3
"""
Service centralisé pour la gestion MySQL
Factorisation de toute la logique MySQL dupliquée
"""

import subprocess
import time
import os
from app.config.database_config import DatabaseConfig
from app.config.docker_config import DockerConfig
from app.utils.logger import wp_logger

class MySQLManager:
    """Gestionnaire centralisé pour toutes les opérations MySQL"""
    
    def __init__(self, socketio=None):
        self.socketio = socketio
        self.config = DatabaseConfig
        
    def check_connection(self, project_name, timeout=None):
        """Vérifie si MySQL est accessible dans un conteneur"""
        timeout = timeout or self.config.CONNECTION_TIMEOUT
        
        try:
            container_name = f"{project_name}_mysql_1"
            result = subprocess.run([
                'docker', 'exec', container_name, 
                'mysql', 
                f'-u{self.config.DEFAULT_USER}', 
                f'-p{self.config.DEFAULT_PASSWORD}', 
                '-e', 'SELECT 1'
            ], capture_output=True, text=True, timeout=timeout)
            
            return result.returncode == 0
            
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False
    
    def wait_for_ready(self, project_name, max_wait_time=None):
        """Attente intelligente que MySQL soit prêt"""
        max_wait_time = max_wait_time or self.config.WAIT_TIMEOUT
        
        print("🔍 Test instantané de MySQL...")
        if self.check_connection(project_name, timeout=1):
            print("✅ MySQL déjà prêt ! Aucune attente nécessaire.")
            return True
        
        print("⏳ MySQL pas encore prêt, attente intelligente...")
        
        # Attente progressive avec intervalles adaptatifs
        wait_phases = [
            (3, 1),    # 3 tentatives × 1 seconde = tests rapides
            (5, 2),    # 5 tentatives × 2 secondes = redémarrage normal  
            (8, 3),    # 8 tentatives × 3 secondes = démarrage standard
            (10, 5)    # 10 tentatives × 5 secondes = gros démarrage
        ]
        
        total_attempts = 0
        start_time = time.time()
        
        for phase_attempts, interval in wait_phases:
            for attempt in range(phase_attempts):
                total_attempts += 1
                elapsed = time.time() - start_time
                
                # Arrêter si on dépasse le temps maximum
                if elapsed > max_wait_time:
                    print(f"❌ Timeout après {elapsed:.1f}s d'attente")
                    return False
                
                print(f"⏳ Test MySQL {total_attempts} (intervalle: {interval}s)")
                
                if self.check_connection(project_name, timeout=3):
                    print(f"✅ MySQL prêt après {elapsed:.1f}s ({total_attempts} tentatives)")
                    return True
                
                time.sleep(interval)
        
        print(f"❌ MySQL non disponible après {max_wait_time}s d'attente")
        return False
    
    def execute_commands(self, project_name, commands, database=None):
        """Exécute des commandes MySQL dans un conteneur"""
        database = database or self.config.DEFAULT_DB
        container_name = f"{project_name}_mysql_1"
        
        if isinstance(commands, str):
            commands = [commands]
        
        results = []
        for command in commands:
            try:
                result = subprocess.run([
                    'docker', 'exec', '-i', container_name,
                    'mysql',
                    f'-u{self.config.DEFAULT_USER}',
                    f'-p{self.config.DEFAULT_PASSWORD}',
                    database
                ], input=command, capture_output=True, text=True, timeout=30)
                
                results.append({
                    'command': command,
                    'success': result.returncode == 0,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                })
                
            except subprocess.TimeoutExpired:
                results.append({
                    'command': command,
                    'success': False,
                    'stdout': '',
                    'stderr': 'Timeout lors de l\'exécution'
                })
            except Exception as e:
                results.append({
                    'command': command,
                    'success': False,
                    'stdout': '',
                    'stderr': str(e)
                })
        
        return results
    
    def execute_commands_as_root(self, project_name, commands, database=None):
        """Exécute des commandes MySQL en tant que root"""
        database = database or self.config.DEFAULT_DB
        container_name = f"{project_name}_mysql_1"
        
        if isinstance(commands, str):
            commands = [commands]
        
        results = []
        for command in commands:
            try:
                result = subprocess.run([
                    'docker', 'exec', '-i', container_name,
                    'mysql',
                    f'-uroot',
                    f'-p{self.config.ROOT_PASSWORD}',
                    database
                ], input=command, capture_output=True, text=True, timeout=30)
                
                results.append({
                    'command': command,
                    'success': result.returncode == 0,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                })
                
            except Exception as e:
                results.append({
                    'command': command,
                    'success': False,
                    'stdout': '',
                    'stderr': str(e)
                })
        
        return results
    
    def create_clean_database(self, project_name):
        """Crée une base de données WordPress propre"""
        print(f"🗃️ Création d'une base de données propre pour {project_name}")
        
        commands = [
            f"DROP DATABASE IF EXISTS {self.config.DEFAULT_DB};",
            f"CREATE DATABASE {self.config.DEFAULT_DB} CHARACTER SET {self.config.CHARSET} COLLATE {self.config.COLLATION};"
        ]
        
        results = self.execute_commands_as_root(project_name, commands, database='mysql')
        
        for result in results:
            if not result['success']:
                print(f"❌ Erreur SQL: {result['stderr']}")
                return False
        
        print(f"✅ Base de données {self.config.DEFAULT_DB} créée avec succès")
        return True
    
    def import_sql_file(self, project_name, sql_file_path, progress_callback=None):
        """Importe un fichier SQL optimisé pour les gros fichiers (plusieurs GB)"""
        if not os.path.exists(sql_file_path):
            print(f"❌ Fichier SQL non trouvé: {sql_file_path}")
            wp_logger.log_database_operation('mysql_import', project_name, False, 
                                           f"Fichier SQL non trouvé: {sql_file_path}",
                                           file_path=sql_file_path)
            return False
        
        # Obtenir la taille du fichier
        file_size = os.path.getsize(sql_file_path)
        file_size_mb = file_size / (1024 * 1024)
        print(f"📁 Taille du fichier SQL: {file_size_mb:.2f} MB")
        
        # Log du début de l'opération
        wp_logger.log_database_operation('mysql_import', project_name, True, 
                                       f"Début import MySQL: {sql_file_path} ({file_size_mb:.2f} MB)",
                                       file_path=sql_file_path,
                                       file_size_mb=f"{file_size_mb:.2f}")
        
        container_name = f"{project_name}_mysql_1"
        
        if progress_callback:
            progress_callback(f"Démarrage import fichier {file_size_mb:.1f}MB...", 5)
        
        # Pour les gros fichiers (>100MB), utiliser une approche streaming
        if file_size_mb > 100:
            return self._import_large_sql_file(project_name, sql_file_path, progress_callback)
        else:
            return self._import_standard_sql_file(project_name, sql_file_path, progress_callback)
    
    def _import_large_sql_file(self, project_name, sql_file_path, progress_callback=None):
        """Import optimisé pour les gros fichiers SQL (streaming sans charger en mémoire)"""
        container_name = f"{project_name}_mysql_1"
        
        try:
            if progress_callback:
                progress_callback("Configuration import haute performance...", 10)
            
            # Copier le fichier dans le conteneur pour éviter le streaming via stdin
            temp_file_in_container = f"/tmp/import_{int(time.time())}.sql"
            
            # Étape 1: Copier le fichier dans le conteneur
            copy_cmd = [
                'docker', 'cp', sql_file_path, 
                f"{container_name}:{temp_file_in_container}"
            ]
            
            copy_result = subprocess.run(copy_cmd, capture_output=True, text=True, timeout=300)
            if copy_result.returncode != 0:
                print(f"❌ Erreur lors de la copie dans le conteneur: {copy_result.stderr}")
                return False
            
            if progress_callback:
                progress_callback("Fichier copié, démarrage import...", 20)
            
            # Étape 2: Exécuter l'import avec mysql optimisé
            import_cmd = [
                'docker', 'exec', container_name,
                'mysql',
                '--quick',  # Ne pas mettre en cache les résultats
                '--lock-tables=false',  # Éviter le verrouillage
                '--single-transaction',  # Import transactionnel
                '--routines',  # Importer les procédures stockées
                '--triggers',  # Importer les triggers
                f'-u{self.config.DEFAULT_USER}',
                f'-p{self.config.DEFAULT_PASSWORD}',
                self.config.DEFAULT_DB
            ]
            
            if progress_callback:
                progress_callback("Import en cours...", 30)
            
            # Exécuter l'import avec un timeout étendu pour les gros fichiers
            with open(sql_file_path, 'rb') as sql_file:
                # Déterminer timeout en fonction de la taille
                file_size_gb = os.path.getsize(sql_file_path) / (1024 * 1024 * 1024)
                timeout = max(1800, int(file_size_gb * 600))  # Minimum 30min, +10min par GB
                
                print(f"🕒 Timeout configuré: {timeout}s pour fichier de {file_size_gb:.2f}GB")
                
                # Utiliser l'import direct depuis le fichier dans le conteneur
                direct_import_cmd = [
                    'docker', 'exec', container_name,
                    'sh', '-c', 
                    f'mysql --quick --lock-tables=false --single-transaction '
                    f'-u{self.config.DEFAULT_USER} -p{self.config.ROOT_PASSWORD} '
                    f'{self.config.DEFAULT_DB} < {temp_file_in_container}'
                ]
                
                result = subprocess.run(
                    direct_import_cmd, 
                    capture_output=True, 
                    text=True, 
                    timeout=timeout
                )
            
            if progress_callback:
                progress_callback("Nettoyage fichier temporaire...", 90)
            
            # Nettoyer le fichier temporaire
            cleanup_cmd = ['docker', 'exec', container_name, 'rm', '-f', temp_file_in_container]
            subprocess.run(cleanup_cmd, capture_output=True)
            
            if result.returncode == 0:
                if progress_callback:
                    progress_callback("Import haute performance terminé !", 100)
                print(f"✅ Import SQL haute performance réussi pour {project_name}")
                wp_logger.log_database_operation('mysql_import_large', project_name, True, 
                                               "Import SQL haute performance réussi",
                                               file_path=sql_file_path,
                                               file_size_gb=f"{file_size_gb:.2f}")
                return True
            else:
                print(f"❌ Erreur lors de l'import SQL: {result.stderr}")
                wp_logger.log_database_operation('mysql_import_large', project_name, False, 
                                               f"Erreur import SQL haute performance: {result.stderr}",
                                               file_path=sql_file_path,
                                               error=result.stderr)
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ Timeout lors de l'import SQL haute performance")
            return False
        except Exception as e:
            print(f"❌ Erreur lors de l'import SQL haute performance: {e}")
            return False
    
    def _import_standard_sql_file(self, project_name, sql_file_path, progress_callback=None):
        """Import standard pour les fichiers de taille normale"""
        container_name = f"{project_name}_mysql_1"
        
        try:
            # Détecter l'encodage et lire le fichier
            sql_content = self._read_sql_file_with_encoding(sql_file_path)
            if sql_content is None:
                return False
            
            if progress_callback:
                progress_callback("Import en cours...", 10)
            
            # Importer le contenu SQL
            result = subprocess.run([
                'docker', 'exec', '-i', container_name,
                'mysql',
                f'-u{self.config.DEFAULT_USER}',
                f'-p{self.config.DEFAULT_PASSWORD}',
                self.config.DEFAULT_DB
            ], input=sql_content, capture_output=True, text=True, timeout=self.config.IMPORT_TIMEOUT)
            
            if result.returncode == 0:
                if progress_callback:
                    progress_callback("Import standard terminé", 100)
                print(f"✅ Import SQL standard réussi pour {project_name}")
                return True
            else:
                print(f"❌ Erreur lors de l'import SQL: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ Timeout lors de l'import SQL standard")
            return False
        except Exception as e:
            print(f"❌ Erreur lors de l'import SQL standard: {e}")
            return False
    
    def _read_sql_file_with_encoding(self, sql_file_path):
        """Lit un fichier SQL en détectant automatiquement l'encodage"""
        try:
            # Essayer UTF-8 en premier
            with open(sql_file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            # Essayer avec d'autres encodages
            for encoding in self.config.SUPPORTED_ENCODINGS[1:]:
                try:
                    with open(sql_file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    print(f"📄 Fichier lu avec l'encodage: {encoding}")
                    return content
                except UnicodeDecodeError:
                    continue
            
            print("❌ Impossible de lire le fichier SQL avec les encodages supportés")
            return None
    
    def export_database(self, project_name, export_path, progress_callback=None):
        """Exporte la base de données vers un fichier SQL optimisé pour les gros volumes"""
        import tempfile
        container_name = f"{project_name}_mysql_1"

        try:
            if progress_callback:
                progress_callback("Démarrage export optimisé...", 10)

            # Créer un fichier de configuration MySQL temporaire
            with tempfile.NamedTemporaryFile(mode='w', suffix='.cnf', delete=False) as config_file:
                config_file.write("[mysqldump]\n")
                config_file.write(f"user={self.config.DEFAULT_USER}\n")
                config_file.write(f"password={self.config.DEFAULT_PASSWORD}\n")
                config_path = config_file.name

            try:
                # Copier le fichier de config dans le conteneur
                subprocess.run(
                    ['docker', 'cp', config_path, f"{container_name}:/tmp/.mysqldump.cnf"],
                    check=True,
                    capture_output=True
                )

                # Commande mysqldump optimisée pour les gros volumes
                export_cmd = [
                    'docker', 'exec', container_name,
                    'mysqldump',
                    '--defaults-file=/tmp/.mysqldump.cnf',
                    '--quick',  # Récupérer les lignes une par une
                    '--lock-tables=false',  # Éviter le verrouillage
                    '--single-transaction',  # Export transactionnel
                    '--routines',  # Exporter les procédures stockées
                    '--triggers',  # Exporter les triggers
                    '--complete-insert',  # Insérer avec noms de colonnes
                    '--extended-insert',  # Grouper les INSERT
                    '--hex-blob',  # Encoder les BLOB en hexadécimal
                    '--no-tablespaces',  # Éviter PROCESS privilege requirement
                    self.config.DEFAULT_DB
                ]

                if progress_callback:
                    progress_callback("Export de la base de données...", 30)

                # Exécuter l'export avec timeout étendu
                result = subprocess.run(
                    export_cmd,
                    stdout=open(export_path, 'w', encoding='utf-8'),
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=1800  # 30 minutes max
                )

                if result.returncode == 0:
                    # Vérifier la taille du fichier exporté
                    export_size = os.path.getsize(export_path)
                    export_size_mb = export_size / (1024 * 1024)

                    if progress_callback:
                        progress_callback(f"Export terminé ({export_size_mb:.1f}MB)", 100)

                    print(f"✅ Export réussi: {export_path} ({export_size_mb:.2f}MB)")
                    return True
                else:
                    print(f"❌ Erreur lors de l'export: {result.stderr}")
                    if os.path.exists(export_path):
                        os.remove(export_path)  # Supprimer le fichier incomplet
                    return False

            finally:
                # Nettoyer le fichier temporaire
                subprocess.run(['docker', 'exec', container_name, 'rm', '-f', '/tmp/.mysqldump.cnf'],
                              capture_output=True)
                os.unlink(config_path)

        except subprocess.TimeoutExpired:
            print("❌ Timeout lors de l'export")
            if os.path.exists(export_path):
                os.remove(export_path)
            return False
        except Exception as e:
            print(f"❌ Erreur lors de l'export: {e}")
            if os.path.exists(export_path):
                os.remove(export_path)
            return False
    
    def update_wordpress_urls(self, project_name, old_url, new_url):
        """Met à jour les URLs WordPress dans la base de données"""
        print(f"🔄 Mise à jour des URLs: {old_url} → {new_url}")
        
        # Commandes SQL pour mettre à jour les URLs
        update_commands = [
            f"UPDATE wp_options SET option_value = '{new_url}' WHERE option_name = 'home';",
            f"UPDATE wp_options SET option_value = '{new_url}' WHERE option_name = 'siteurl';",
            f"UPDATE wp_posts SET post_content = REPLACE(post_content, '{old_url}', '{new_url}');",
            f"UPDATE wp_postmeta SET meta_value = REPLACE(meta_value, '{old_url}', '{new_url}');",
            f"UPDATE wp_comments SET comment_content = REPLACE(comment_content, '{old_url}', '{new_url}');"
        ]
        
        results = self.execute_commands(project_name, update_commands)
        
        success_count = sum(1 for r in results if r['success'])
        
        if success_count == len(update_commands):
            print(f"✅ URLs mises à jour avec succès ({success_count}/{len(update_commands)})")
            return True
        else:
            print(f"⚠️ Mise à jour partielle des URLs ({success_count}/{len(update_commands)})")
            return False
    
    def optimize_database(self, project_name):
        """Optimise la base de données MySQL"""
        print(f"⚡ Optimisation de la base de données pour {project_name}")
        
        optimize_commands = [
            "OPTIMIZE TABLE wp_posts;",
            "OPTIMIZE TABLE wp_options;", 
            "OPTIMIZE TABLE wp_postmeta;",
            "OPTIMIZE TABLE wp_comments;",
            "OPTIMIZE TABLE wp_commentmeta;",
            "OPTIMIZE TABLE wp_users;",
            "OPTIMIZE TABLE wp_usermeta;"
        ]
        
        results = self.execute_commands(project_name, optimize_commands)
        
        success_count = sum(1 for r in results if r['success'])
        print(f"✅ Tables optimisées: {success_count}/{len(optimize_commands)}")
        
        return success_count > 0
    
    def _emit_progress(self, project_name, message, progress=None):
        """Émet un événement de progression via SocketIO"""
        if self.socketio:
            self.socketio.emit('database_progress', {
                'project': project_name,
                'message': message,
                'progress': progress,
                'timestamp': time.time()
            })
        else:
            print(f"📊 {project_name}: {message}" + (f" ({progress}%)" if progress else ""))