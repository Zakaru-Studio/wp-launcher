"""
Dev Instance Service for managing development instances
"""
import sqlite3
import os
import shutil
import json
from datetime import datetime
from app.models.dev_instance import DevInstance
from app.services.database_service import DatabaseService
from app.services.port_service import PortService


class DevInstanceService:
    """Service for managing development instances"""
    
    def __init__(self, db_path='data/dev_instances.db'):
        # Utiliser un chemin absolu si le chemin est relatif
        if not os.path.isabs(db_path):
            # Obtenir le répertoire racine du projet
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, db_path)
        self.db_path = db_path
        self.database_service = DatabaseService()
        self.port_service = PortService()
        self._init_database()
    
    def _init_database(self):
        """Initialize dev instances database"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dev_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                parent_project TEXT NOT NULL,
                owner_username TEXT NOT NULL,
                port INTEGER UNIQUE NOT NULL,
                ports TEXT,
                db_name TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'stopped'
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_owner ON dev_instances(owner_username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_parent ON dev_instances(parent_project)')
        
        conn.commit()
        conn.close()
    
    def create_dev_instance(self, parent_project, owner_username, socketio=None):
        """Create a new development instance"""
        import logging
        from app.utils.logger import wp_logger
        from app.utils.slug_utils import (
            generate_instance_slug,
            generate_db_name,
            sanitize_container_name,
            clean_username_for_slug
        )
        
        wp_logger.log_system_info(f"Starting dev instance creation for {parent_project} by {owner_username}")
        
        # 1. Generate slug (nom simple: juste le username nettoyé)
        clean_username = clean_username_for_slug(owner_username)
        instance_slug = clean_username  # Ex: "pancin"
        wp_logger.log_system_info(f"Instance slug: {instance_slug}")
        
        # 2. Generate full name for Docker/DB (pour compatibilité)
        instance_full_name = f"{parent_project}_dev_{instance_slug}"  # Ex: "test_dev_pancin"
        wp_logger.log_system_info(f"Instance full name: {instance_full_name}")
        
        # 3. Check if exists
        if self.get_instance_by_name(instance_full_name):
            wp_logger.log_system_info(f"ERROR: Instance {instance_full_name} already exists")
            raise Exception("Instance déjà existante")
        
        # 4. Allocate ports
        wp_logger.log_system_info(f"Allocating ports for {instance_slug}")
        ports = self.port_service.allocate_ports_for_project(enable_nextjs=False)
        port = ports['wordpress']  # Port principal WordPress
        wp_logger.log_system_info(f"Ports allocated: {ports}")
        
        # 5. Generate DB name (MySQL-safe)
        db_name = generate_db_name(parent_project, f"dev_{instance_slug}")
        wp_logger.log_system_info(f"DB name: {db_name}")
        
        # 6. Create folder structure dans le projet parent
        instance_path = os.path.join('projets', parent_project, '.dev-instances', instance_slug)
        wp_logger.log_system_info(f"Creating folder structure at {instance_path}")
        os.makedirs(f"{instance_path}/wp-content/themes", exist_ok=True)
        os.makedirs(f"{instance_path}/wp-content/plugins", exist_ok=True)
        # Note: uploads sera créé comme symlink plus bas
        wp_logger.log_system_info(f"Folder structure created")
        
        # 6-9. Copy files with proper permissions
        parent_path = f"projets/{parent_project}/wp-content"
        
        # Utiliser rsync avec sudo pour copier en préservant les permissions
        import subprocess
        
        wp_logger.log_system_info(f"Copying files from {parent_path} to {instance_path}/wp-content")
        
        # Copy theme-enfant if exists
        if os.path.exists(f"{parent_path}/themes/theme-enfant"):
            wp_logger.log_system_info(f"Copying theme-enfant")
            result = subprocess.run([
                'sudo', 'rsync', '-av',
                f"{parent_path}/themes/theme-enfant/",
                f"{instance_path}/wp-content/themes/theme-enfant/"
            ], capture_output=True, text=True)
            if result.returncode != 0:
                wp_logger.log_system_info(f"Warning: Failed to copy theme-enfant: {result.stderr}")
        
        # Symlink theme-parent if exists
        if os.path.exists(f"{parent_path}/themes/theme-parent"):
            try:
                target_link = f"{instance_path}/wp-content/themes/theme-parent"
                if not os.path.exists(target_link):
                    os.symlink(
                        f"../../../../{parent_project}/wp-content/themes/theme-parent",
                        target_link
                    )
                    wp_logger.log_system_info(f"Symlink created for theme-parent")
            except Exception as e:
                wp_logger.log_system_info(f"Warning: Failed to create symlink: {str(e)}")
        
        # Copy plugins
        if os.path.exists(f"{parent_path}/plugins"):
            wp_logger.log_system_info(f"Copying plugins")
            result = subprocess.run([
                'sudo', 'rsync', '-av',
                f"{parent_path}/plugins/",
                f"{instance_path}/wp-content/plugins/"
            ], capture_output=True, text=True)
            if result.returncode != 0:
                wp_logger.log_system_info(f"Warning: Failed to copy plugins: {result.stderr}")
        
        # Symlink uploads vers le parent (économie d'espace disque)
        parent_uploads = f"{parent_path}/uploads"
        if os.path.exists(parent_uploads):
            try:
                target_link = f"{instance_path}/wp-content/uploads"
                if not os.path.exists(target_link):
                    os.symlink(
                        f"../../../../{parent_project}/wp-content/uploads",
                        target_link
                    )
                    wp_logger.log_system_info(f"Symlink created for uploads -> parent")
            except Exception as e:
                wp_logger.log_system_info(f"Warning: Failed to create uploads symlink: {str(e)}")
        
        # Changer le propriétaire des fichiers copiés vers dev-server
        wp_logger.log_system_info(f"Changing ownership to dev-server")
        subprocess.run([
            'sudo', 'chown', '-R', 'dev-server:dev-server',
            f"{instance_path}/wp-content"
        ], capture_output=True)
        
        # 10. Clone DB
        # La base de données source s'appelle toujours 'wordpress' dans les projets WordPress
        parent_db_name = 'wordpress'
        wp_logger.log_system_info(f"Cloning database from {parent_db_name} to {db_name}")
        try:
            self.database_service.clone_database(
                source_project=parent_project,
                source_db_name=parent_db_name,
                target_db_name=db_name,
                target_port=port,
                socketio=socketio
            )
            wp_logger.log_system_info(f"Database cloned successfully")
        except Exception as e:
            wp_logger.log_system_info(f"ERROR: Failed to clone database: {str(e)}")
            raise
        
        # 10b. Vérifier que la DB a bien été créée avec les tables
        wp_logger.log_system_info(f"Verifying database {db_name} was created correctly")
        try:
            check_cmd = [
                'docker', 'exec', f'{parent_project}_mysql_1',
                'mysql', '-u', 'root', '-prootpassword', '-e',
                f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{db_name}';"
            ]
            result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                wp_logger.log_system_info(f"ERROR: Failed to verify DB: {result.stderr}")
                raise Exception(f"Échec de la vérification de la DB {db_name}")
            
            # Extraire le nombre de tables
            lines = result.stdout.strip().split('\n')
            table_count = 0
            for line in lines:
                if line.strip().isdigit():
                    table_count = int(line.strip())
                    break
            
            if table_count == 0:
                wp_logger.log_system_info(f"ERROR: DB {db_name} has 0 tables")
                raise Exception(f"Échec du clonage de la DB {db_name} - aucune table créée")
            
            wp_logger.log_system_info(f"DB verification successful: {table_count} tables found in {db_name}")
        except Exception as e:
            wp_logger.log_system_info(f"ERROR: DB verification failed: {str(e)}")
            raise
        
        # 11. Generate docker-compose.yml dans le dossier de l'instance
        wp_logger.log_system_info(f"Generating docker-compose.yml for {instance_full_name}")
        self._generate_docker_compose_in_instance(instance_path, instance_full_name, parent_project, port, db_name)
        wp_logger.log_system_info(f"docker-compose.yml generated")
        
        # 11b. Start the instance container
        wp_logger.log_system_info(f"Starting container for {instance_full_name}")
        try:
            import subprocess
            result = subprocess.run(
                ['docker-compose', 'up', '-d'],
                cwd=instance_path,
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode == 0:
                wp_logger.log_system_info(f"Container started successfully for {instance_full_name}")
            else:
                wp_logger.log_system_info(f"WARNING: Container start failed: {result.stderr}")
        except Exception as e:
            wp_logger.log_system_info(f"WARNING: Failed to start container: {str(e)}")
        
        # 12. Create metadata
        metadata = {
            'slug': instance_slug,
            'name': instance_full_name,
            'owner': owner_username,
            'parent_project': parent_project,
            'port': port,
            'ports': ports,  # Tous les ports alloués
            'db_name': db_name,
            'created_at': datetime.now().isoformat()
        }
        with open(f"{instance_path}/.metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
        
        # 13. Save to DB
        instance = DevInstance(
            name=instance_full_name,  # Nom complet pour Docker
            slug=instance_slug,  # Slug simple pour dossier
            parent_project=parent_project,
            owner_username=owner_username,
            port=port,
            ports=ports,  # Passer tous les ports
            db_name=db_name
        )
        
        wp_logger.log_system_info(f"Saving instance {instance_full_name} to database")
        self._save_instance(instance)
        wp_logger.log_system_info(f"Dev instance {instance_full_name} created successfully")
        
        return instance
    
    def _generate_docker_compose_in_instance(self, instance_path, instance_full_name, parent_project, port, db_name):
        """Generate docker-compose.yml directly in the instance folder (NEW)"""
        container_name = f"{instance_full_name}_wordpress"
        
        template = f"""version: '3.8'

services:
  wordpress:
    image: wp-launcher-wordpress:php8.2
    container_name: {container_name}
    restart: unless-stopped
    ports:
      - "{port}:80"
    volumes:
      - ./wp-content:/var/www/html/wp-content
    environment:
      WORDPRESS_DB_HOST: {parent_project}_mysql_1:3306
      WORDPRESS_DB_NAME: {db_name}
      WORDPRESS_DB_USER: root
      WORDPRESS_DB_PASSWORD: rootpassword
    networks:
      - {parent_project}_wordpress_network
    mem_limit: 256m
    cpus: '1.0'

networks:
  {parent_project}_wordpress_network:
    external: true
"""
        
        docker_compose_path = os.path.join(instance_path, 'docker-compose.yml')
        with open(docker_compose_path, 'w') as f:
            f.write(template)
    
    def _generate_docker_compose(self, instance_slug, parent_project, port, db_name):
        """Generate docker-compose.yml for dev instance (OLD - kept for compatibility)"""
        from app.utils.slug_utils import sanitize_container_name
        
        # Nettoyer le nom du container pour Docker
        clean_container_name = sanitize_container_name(instance_slug)
        
        template = f"""version: '3.8'

services:
  wordpress:
    image: wp-launcher-wordpress:php8.2
    container_name: {clean_container_name}_wordpress
    restart: unless-stopped
    ports:
      - "{port}:80"
    volumes:
      - ../../projets/.dev-instances/{instance_slug}/wp-content:/var/www/html/wp-content
    environment:
      WORDPRESS_DB_HOST: {parent_project}_mysql_1:3306
      WORDPRESS_DB_NAME: {db_name}
      WORDPRESS_DB_USER: root
      WORDPRESS_DB_PASSWORD: rootpassword
    networks:
      - {parent_project}_wordpress_network
    mem_limit: 256m
    cpus: '1.0'

networks:
  {parent_project}_wordpress_network:
    external: true
"""
        
        os.makedirs(f"containers/.dev-instances/{instance_slug}", exist_ok=True)
        with open(f"containers/.dev-instances/{instance_slug}/docker-compose.yml", 'w') as f:
            f.write(template)
    
    def _save_instance(self, instance):
        """Save instance to database"""
        import json
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        ports_json = json.dumps(instance.ports) if instance.ports else None
        
        cursor.execute('''
            INSERT INTO dev_instances (name, parent_project, owner_username, port, ports, db_name, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (instance.name, instance.parent_project, instance.owner_username, instance.port,
              ports_json, instance.db_name, datetime.now(), instance.status))
        
        instance.id = cursor.lastrowid
        conn.commit()
        conn.close()
    
    def get_instance_by_name(self, name):
        """Get instance by name"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM dev_instances WHERE name = ?', (name,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_instance(row)
        return None
    
    def get_user_instances(self, username):
        """Get all instances for a user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM dev_instances WHERE owner_username = ?', (username,))
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_instance(row) for row in rows]
    
    def get_instances_by_parent(self, parent_project):
        """Get all instances for a parent project"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM dev_instances WHERE parent_project = ?', (parent_project,))
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_instance(row) for row in rows]
    
    def list_all_instances(self):
        """List all instances"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM dev_instances')
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_instance(row) for row in rows]
    
    def delete_instance(self, name, username, is_admin=False):
        """Delete an instance - Supprime le conteneur Docker, les fichiers et la base de données"""
        import subprocess
        from app.utils.logger import wp_logger
        
        instance = self.get_instance_by_name(name)
        
        if not instance:
            raise Exception("Instance non trouvée")
        
        # Vérifier la propriété (sauf pour les admins)
        if not is_admin and instance.owner_username != username:
            raise Exception("Vous n'êtes pas propriétaire de cette instance")
        
        wp_logger.log_system_info(f"Suppression de l'instance {name} par {username} (admin: {is_admin})")
        
        # 1. Arrêter et supprimer UNIQUEMENT le conteneur WordPress de l'instance
        container_name = f"{name}_wordpress"
        try:
            # Arrêter le conteneur
            result = subprocess.run(['docker', 'stop', container_name], 
                         capture_output=True, timeout=30, text=True)
            wp_logger.log_system_info(f"Conteneur {container_name} arrêté: {result.returncode}")
            
            # Supprimer le conteneur
            result = subprocess.run(['docker', 'rm', container_name], 
                         capture_output=True, timeout=30, text=True)
            wp_logger.log_system_info(f"Conteneur {container_name} supprimé: {result.returncode}")
        except Exception as e:
            wp_logger.log_system_info(f"Erreur lors de la suppression du conteneur: {str(e)}")
            # Continuer même si le conteneur n'existe pas
        
        # 2. Supprimer les fichiers de l'instance (avec sudo car wp-content appartient à www-data)
        instance_path = os.path.join('projets', instance.parent_project, '.dev-instances', instance.slug)
        if os.path.exists(instance_path):
            try:
                result = subprocess.run(
                    ['sudo', 'rm', '-rf', instance_path],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0:
                    wp_logger.log_system_info(f"Fichiers supprimés: {instance_path}")
                else:
                    wp_logger.log_system_info(f"Erreur suppression fichiers: {result.stderr}")
            except Exception as e:
                wp_logger.log_system_info(f"Erreur lors de la suppression des fichiers: {str(e)}")
        
        # 3. Supprimer la DB MySQL
        mysql_container = f"{instance.parent_project}_mysql_1"
        drop_cmd = f"DROP DATABASE IF EXISTS {instance.db_name};"
        try:
            result = subprocess.run([
                'docker', 'exec', mysql_container,
                'mysql', '-u', 'root', '-prootpassword', '-e', drop_cmd
            ], capture_output=True, timeout=30, text=True)
            if result.returncode == 0:
                wp_logger.log_system_info(f"DB {instance.db_name} supprimée")
            else:
                wp_logger.log_system_info(f"Erreur suppression DB: {result.stderr}")
        except Exception as e:
            wp_logger.log_system_info(f"Erreur lors de la suppression de la DB: {str(e)}")
        
        # 4. Nettoyer ancien dossier containers/.dev-instances/ si existant
        old_path = f"containers/.dev-instances/{name}"
        if os.path.exists(old_path):
            try:
                shutil.rmtree(old_path)
                wp_logger.log_system_info(f"Ancien dossier supprimé: {old_path}")
            except Exception as e:
                wp_logger.log_system_info(f"Erreur suppression ancien dossier: {str(e)}")
        
        # 5. Supprimer de la DB SQLite
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM dev_instances WHERE name = ?', (name,))
        conn.commit()
        conn.close()
        wp_logger.log_system_info(f"Instance {name} supprimée de la base de données")
    
    def _row_to_instance(self, row):
        """Convert DB row to DevInstance"""
        import json
        # row: id, name, parent_project, owner_username, port, ports, db_name, created_at, status
        ports = json.loads(row[5]) if len(row) > 5 and row[5] else {'wordpress': row[4]}
        return DevInstance(
            id=row[0],
            name=row[1],
            parent_project=row[2],
            owner_username=row[3],
            port=row[4],
            ports=ports,
            db_name=row[6] if len(row) > 6 else row[5],
            created_at=row[7] if len(row) > 7 else row[6],
            status=row[8] if len(row) > 8 else row[7]
        )

