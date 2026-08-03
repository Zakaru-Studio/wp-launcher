"""
Dev Instance Service for managing development instances

Une instance dev = un conteneur WordPress isolé qui partage le MySQL et
les uploads du projet parent, avec sa propre copie des thèmes/plugins et
un clone de la base de données.

Arborescence : projets/<parent>/.dev-instances/<slug>/
  - wp-content/ (thèmes+plugins copiés, uploads symlinké vers le parent)
  - docker-compose.yml (réseau externe du parent, image du parent)
  - .metadata.json
"""
import sqlite3
import os
import re
import shutil
import json
import subprocess
from datetime import datetime
from app.models.dev_instance import DevInstance
from app.services.database_service import DatabaseService
from app.services.port_service import PortService
from app.utils import security_config
from app.utils.project_credentials import get_root_password
from app.utils.slug_utils import clean_username_for_slug, generate_db_name


# Image de repli si on ne peut pas lire celle du projet parent.
_DEFAULT_WP_IMAGE = 'wp-launcher-wordpress:latest'


class DevInstanceService:
    """Service for managing development instances"""

    def __init__(self, db_path='data/dev_instances.db', projects_folder='projets',
                 containers_folder='containers'):
        # Utiliser un chemin absolu si le chemin est relatif
        if not os.path.isabs(db_path):
            # Obtenir le répertoire racine du projet
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, db_path)
        self.db_path = db_path
        self.projects_folder = projects_folder
        self.containers_folder = containers_folder
        self.database_service = DatabaseService()
        self.port_service = PortService()
        self._init_database()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self):
        """Initialize dev instances database"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        conn = self._connect()
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
                status TEXT DEFAULT 'stopped',
                slug TEXT
            )
        ''')

        # Migration : les bases créées avant l'ajout de la colonne `slug`
        # ne l'ont pas — sans elle, le dossier de l'instance est résolu
        # depuis le username brut, qui peut différer du slug nettoyé
        # utilisé à la création (ex: "Jean.Dupont" -> "jean-dupont").
        columns = [r['name'] for r in cursor.execute('PRAGMA table_info(dev_instances)')]
        if 'slug' not in columns:
            cursor.execute('ALTER TABLE dev_instances ADD COLUMN slug TEXT')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_owner ON dev_instances(owner_username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_parent ON dev_instances(parent_project)')

        conn.commit()
        conn.close()

    # ─── helpers ──────────────────────────────────────────────────────

    def instance_path(self, instance):
        """Dossier de l'instance sur disque."""
        return os.path.join(self.projects_folder, instance.parent_project,
                            '.dev-instances', instance.slug)

    def _compose_project_name(self, instance_full_name):
        """Nom de projet docker-compose unique pour l'instance.

        Sans `-p`, docker-compose dérive le nom du projet du dossier
        courant — ici le slug (ex: "aurelien"). Deux instances du même
        développeur sur deux projets différents auraient alors le MÊME
        nom de projet compose, et un `down` sur l'une supprimerait le
        conteneur de l'autre.
        """
        return re.sub(r'[^a-z0-9_-]', '', instance_full_name.lower())

    def _compose_cmd(self, instance_full_name, *args):
        return ['docker-compose', '-p', self._compose_project_name(instance_full_name)] + list(args)

    def _parent_mysql_container(self, parent_project):
        """Nom du conteneur MySQL du parent s'il tourne, sinon None."""
        result = subprocess.run(['docker', 'ps', '--format', '{{.Names}}'],
                                capture_output=True, text=True, timeout=15)
        names = set(result.stdout.split())
        for candidate in (f"{parent_project}_mysql_1", f"{parent_project}_mysql"):
            if candidate in names:
                return candidate
        return None

    def _parent_wordpress_image(self, parent_project):
        """Image WordPress du projet parent (même version PHP que le parent).

        Lue dans containers/<parent>/docker-compose.yml ; l'ancienne
        valeur codée en dur (php8.2) cassait les instances dès que le
        parent tournait sur une autre version de PHP.
        """
        compose_path = os.path.join(self.containers_folder, parent_project, 'docker-compose.yml')
        try:
            with open(compose_path, 'r', encoding='utf-8') as f:
                content = f.read()
            match = re.search(r'image:\s*(wp-launcher-wordpress:\S+)', content)
            if match:
                return match.group(1)
        except OSError:
            pass
        return _DEFAULT_WP_IMAGE

    def _parent_table_prefix(self, parent_project):
        """Préfixe de tables WordPress du parent (par défaut wp_)."""
        wp_config = os.path.join(self.projects_folder, parent_project, 'wp-config.php')
        try:
            with open(wp_config, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            match = re.search(r"\$table_prefix\s*=\s*['\"]([A-Za-z0-9_]+)['\"]", content)
            if match:
                return match.group(1)
        except OSError:
            pass
        return 'wp_'

    def _instance_ports_in_use(self):
        """Tous les ports déjà alloués à des instances (même arrêtées).

        get_used_ports() ne voit que les conteneurs actifs et les
        fichiers .port des projets — une instance arrêtée libérait donc
        son port en apparence, et la création suivante plantait sur
        UNIQUE constraint failed: dev_instances.port.
        """
        used = set()
        conn = self._connect()
        for row in conn.execute('SELECT port, ports FROM dev_instances'):
            if row['port']:
                used.add(int(row['port']))
            if row['ports']:
                try:
                    used.update(int(p) for p in json.loads(row['ports']).values() if p)
                except (ValueError, TypeError):
                    pass
        conn.close()
        return used

    # ─── création ─────────────────────────────────────────────────────

    def create_dev_instance(self, parent_project, owner_username, socketio=None):
        """Create a new development instance"""
        from app.utils.logger import wp_logger

        wp_logger.log_system_info(f"Starting dev instance creation for {parent_project} by {owner_username}")

        # 0. Le projet parent doit exister et son MySQL doit tourner —
        # on échoue AVANT de copier quoi que ce soit, pas au milieu.
        parent_path = os.path.join(self.projects_folder, parent_project)
        if not os.path.isdir(parent_path):
            raise Exception(f"Projet parent introuvable: {parent_project}")
        mysql_container = self._parent_mysql_container(parent_project)
        if mysql_container is None:
            raise Exception(
                f"Le projet parent '{parent_project}' doit être démarré "
                "(conteneur MySQL introuvable)."
            )

        # 1. Generate slug (nom simple: juste le username nettoyé)
        instance_slug = clean_username_for_slug(owner_username)
        if not instance_slug:
            raise Exception(f"Impossible de générer un slug pour '{owner_username}'")

        # 2. Nom complet pour Docker/DB
        instance_full_name = f"{parent_project}_dev_{instance_slug}"
        wp_logger.log_system_info(f"Instance slug: {instance_slug}, full name: {instance_full_name}")

        # 3. Check if exists
        if self.get_instance_by_name(instance_full_name):
            raise Exception("Instance déjà existante")

        # 4. Allocate ports — en excluant ceux des instances arrêtées
        ports = self.port_service.allocate_ports_for_project(
            enable_nextjs=False,
            extra_used_ports=self._instance_ports_in_use(),
        )
        port = ports['wordpress']
        wp_logger.log_system_info(f"Ports allocated: {ports}")

        # 5. Generate DB name (MySQL-safe)
        db_name = generate_db_name(parent_project, f"dev_{instance_slug}")

        instance_path = os.path.join(parent_path, '.dev-instances', instance_slug)
        db_created = False
        try:
            # 6. Structure de dossiers + copie des fichiers
            self._copy_parent_files(parent_project, instance_path)

            # 7. Clone DB (la DB source s'appelle toujours 'wordpress')
            wp_logger.log_system_info(f"Cloning database wordpress -> {db_name}")
            db_created = True  # à partir d'ici, un DROP de nettoyage a du sens
            self.database_service.clone_database(
                source_project=parent_project,
                source_db_name='wordpress',
                target_db_name=db_name,
                target_port=port,
                socketio=socketio
            )

            # 8. Vérifier que la DB clonée contient des tables
            self._verify_cloned_db(parent_project, db_name)

            # 9. docker-compose.yml de l'instance
            self._generate_docker_compose_in_instance(
                instance_path, instance_full_name, parent_project, port, db_name,
                db_host=mysql_container,
            )

            # 10. Démarrage du conteneur — fatal si ça échoue : une
            # instance enregistrée mais sans conteneur n'est qu'une
            # source de confusion dans l'UI.
            wp_logger.log_system_info(f"Starting container for {instance_full_name}")
            result = subprocess.run(
                self._compose_cmd(instance_full_name, 'up', '-d'),
                cwd=instance_path,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode != 0:
                raise Exception(f"Échec du démarrage du conteneur: {result.stderr.strip()}")

            # 11. Metadata
            metadata = {
                'slug': instance_slug,
                'name': instance_full_name,
                'owner': owner_username,
                'parent_project': parent_project,
                'port': port,
                'ports': ports,
                'db_name': db_name,
                'created_at': datetime.now().isoformat()
            }
            with open(os.path.join(instance_path, '.metadata.json'), 'w') as f:
                json.dump(metadata, f, indent=2)

            # 12. Save to DB
            instance = DevInstance(
                name=instance_full_name,
                slug=instance_slug,
                parent_project=parent_project,
                owner_username=owner_username,
                port=port,
                ports=ports,
                db_name=db_name,
                status='running'
            )
            self._save_instance(instance)
            wp_logger.log_system_info(f"Dev instance {instance_full_name} created successfully")
            return instance

        except Exception:
            # Rollback : sans ce nettoyage, chaque échec laissait un
            # dossier orphelin et une DB à moitié importée qui
            # parasitaient les tentatives suivantes.
            wp_logger.log_system_info(f"Creation failed — cleaning up {instance_full_name}")
            self._cleanup_failed_creation(
                instance_path, instance_full_name, parent_project,
                db_name if db_created else None
            )
            raise

    def _copy_parent_files(self, parent_project, instance_path):
        """Copie wp-content du parent vers l'instance.

        - thèmes : TOUS copiés (l'ancienne version ne copiait que des
          noms codés en dur 'theme-enfant'/'theme-parent', donc les
          vrais projets démarraient sans aucun thème)
        - plugins, mu-plugins, languages : copiés s'ils existent
        - uploads : symlink vers le parent (économie d'espace disque)
        """
        from app.utils.logger import wp_logger

        parent_wp_content = os.path.join(self.projects_folder, parent_project, 'wp-content')
        target_wp_content = os.path.join(instance_path, 'wp-content')
        os.makedirs(target_wp_content, exist_ok=True)

        for subdir in ('themes', 'plugins', 'mu-plugins', 'languages'):
            source = os.path.join(parent_wp_content, subdir)
            if not os.path.isdir(source):
                continue
            wp_logger.log_system_info(f"Copying {subdir} from parent")
            result = subprocess.run(
                ['sudo', 'rsync', '-a', '--exclude=.git',
                 f"{source}/", os.path.join(target_wp_content, subdir) + '/'],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                raise Exception(f"Échec de la copie de {subdir}: {result.stderr.strip()}")

        # uploads : symlink relatif vers le parent
        parent_uploads = os.path.join(parent_wp_content, 'uploads')
        target_link = os.path.join(target_wp_content, 'uploads')
        if os.path.isdir(parent_uploads) and not os.path.lexists(target_link):
            os.symlink(f"../../../../{parent_project}/wp-content/uploads", target_link)
            wp_logger.log_system_info("Symlink created for uploads -> parent")

        # Propriété des fichiers copiés
        subprocess.run(
            ['sudo', 'chown', '-R', 'dev-server:dev-server', target_wp_content],
            capture_output=True, timeout=120
        )

    def _verify_cloned_db(self, parent_project, db_name):
        """Vérifie que la DB clonée contient au moins une table."""
        from app.utils.logger import wp_logger

        mysql_container = self._parent_mysql_container(parent_project)
        if mysql_container is None:
            raise Exception("Conteneur MySQL du parent introuvable pendant la vérification")

        result = subprocess.run(
            ['docker', 'exec', mysql_container,
             'mysql', '-u', 'root', f'-p{get_root_password(parent_project, container_name=mysql_container)}', '-N', '-e',
             f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{db_name}';"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise Exception(f"Échec de la vérification de la DB {db_name}: {result.stderr.strip()}")

        try:
            table_count = int(result.stdout.strip().split('\n')[-1])
        except (ValueError, IndexError):
            table_count = 0

        if table_count == 0:
            raise Exception(f"Échec du clonage de la DB {db_name} - aucune table créée")
        wp_logger.log_system_info(f"DB verification successful: {table_count} tables in {db_name}")

    def _cleanup_failed_creation(self, instance_path, instance_full_name, parent_project, db_name):
        """Supprime les artefacts d'une création échouée (best-effort)."""
        from app.utils.logger import wp_logger

        # Conteneur éventuellement démarré
        try:
            subprocess.run(['docker', 'rm', '-f', f"{instance_full_name}_wordpress"],
                           capture_output=True, timeout=30)
        except Exception as e:
            wp_logger.log_system_info(f"Cleanup: container removal failed: {e}")

        # Dossier de l'instance
        if instance_path and os.path.isdir(instance_path):
            try:
                subprocess.run(['sudo', 'rm', '-rf', instance_path],
                               capture_output=True, timeout=60)
                wp_logger.log_system_info(f"Cleanup: removed {instance_path}")
            except Exception as e:
                wp_logger.log_system_info(f"Cleanup: folder removal failed: {e}")

        # DB clonée partiellement
        if db_name:
            mysql_container = self._parent_mysql_container(parent_project)
            if mysql_container:
                try:
                    subprocess.run(
                        ['docker', 'exec', mysql_container,
                         'mysql', '-u', 'root', f'-p{get_root_password(parent_project, container_name=mysql_container)}', '-e',
                         f"DROP DATABASE IF EXISTS `{db_name}`;"],
                        capture_output=True, timeout=30
                    )
                    wp_logger.log_system_info(f"Cleanup: dropped DB {db_name}")
                except Exception as e:
                    wp_logger.log_system_info(f"Cleanup: DB drop failed: {e}")

    def _generate_docker_compose_in_instance(self, instance_path, instance_full_name,
                                             parent_project, port, db_name, db_host=None):
        """Generate docker-compose.yml directly in the instance folder"""
        container_name = f"{instance_full_name}_wordpress"
        image = self._parent_wordpress_image(parent_project)
        table_prefix = self._parent_table_prefix(parent_project)
        # Nom RÉEL du conteneur MySQL du parent : certains projets sont
        # nommés <parent>_mysql (sans _1) — le détecter plutôt que de
        # supposer le suffixe.
        if db_host is None:
            db_host = self._parent_mysql_container(parent_project) or f"{parent_project}_mysql_1"

        # L'instance se connecte au MySQL du parent : elle doit donc utiliser
        # le mot de passe root de ce parent, désormais propre à chaque projet.
        db_password = get_root_password(parent_project, container_name=db_host)
        site_bind = security_config.site_bind_address()

        template = f"""version: '3.8'

services:
  wordpress:
    image: {image}
    container_name: {container_name}
    restart: unless-stopped
    ports:
      - "{site_bind}:{port}:80"
    volumes:
      - ./wp-content:/var/www/html/wp-content
    environment:
      WORDPRESS_DB_HOST: {db_host}:3306
      WORDPRESS_DB_NAME: {db_name}
      WORDPRESS_DB_USER: root
      WORDPRESS_DB_PASSWORD: "{db_password}"
      WORDPRESS_TABLE_PREFIX: {table_prefix}
    networks:
      - {parent_project}_wordpress_network
    mem_limit: 256m
    cpus: '1.0'

networks:
  {parent_project}_wordpress_network:
    external: true
"""

        os.makedirs(instance_path, exist_ok=True)
        docker_compose_path = os.path.join(instance_path, 'docker-compose.yml')
        with open(docker_compose_path, 'w') as f:
            f.write(template)

    # ─── start / stop ─────────────────────────────────────────────────

    def start_instance(self, name):
        """Démarre le conteneur d'une instance. Raises on failure."""
        instance = self.get_instance_by_name(name)
        if not instance:
            raise Exception("Instance non trouvée")
        path = self.instance_path(instance)
        if not os.path.isdir(path):
            raise Exception("Dossier d'instance non trouvé")
        if self._parent_mysql_container(instance.parent_project) is None:
            raise Exception(
                f"Le projet parent '{instance.parent_project}' doit être "
                "démarré avant l'instance."
            )
        result = subprocess.run(
            self._compose_cmd(name, 'up', '-d'),
            cwd=path, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            raise Exception(result.stderr.strip() or 'Échec du démarrage')
        self._update_status(name, 'running')

    def stop_instance(self, name):
        """Arrête le conteneur d'une instance. Raises on failure."""
        instance = self.get_instance_by_name(name)
        if not instance:
            raise Exception("Instance non trouvée")
        path = self.instance_path(instance)
        if not os.path.isdir(path):
            raise Exception("Dossier d'instance non trouvé")
        result = subprocess.run(
            self._compose_cmd(name, 'down'),
            cwd=path, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            # Fallback : conteneurs créés avant l'introduction de `-p`
            # (label de projet compose différent)
            fallback = subprocess.run(['docker', 'rm', '-f', f"{name}_wordpress"],
                                      capture_output=True, text=True, timeout=60)
            if fallback.returncode != 0:
                raise Exception(result.stderr.strip() or 'Échec de l\'arrêt')
        self._update_status(name, 'stopped')

    def _update_status(self, name, status):
        conn = self._connect()
        conn.execute('UPDATE dev_instances SET status = ? WHERE name = ?', (status, name))
        conn.commit()
        conn.close()

    # ─── persistence ──────────────────────────────────────────────────

    def _save_instance(self, instance):
        """Save instance to database"""
        conn = self._connect()
        cursor = conn.cursor()

        ports_json = json.dumps(instance.ports) if instance.ports else None

        cursor.execute('''
            INSERT INTO dev_instances (name, slug, parent_project, owner_username, port, ports, db_name, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (instance.name, instance.slug, instance.parent_project, instance.owner_username,
              instance.port, ports_json, instance.db_name,
              datetime.now().isoformat(sep=' '), instance.status))

        instance.id = cursor.lastrowid
        conn.commit()
        conn.close()

    def get_instance_by_name(self, name):
        """Get instance by name"""
        conn = self._connect()
        row = conn.execute('SELECT * FROM dev_instances WHERE name = ?', (name,)).fetchone()
        conn.close()
        return self._row_to_instance(row) if row else None

    def get_user_instances(self, username):
        """Get all instances for a user"""
        conn = self._connect()
        rows = conn.execute('SELECT * FROM dev_instances WHERE owner_username = ?',
                            (username,)).fetchall()
        conn.close()
        return [self._row_to_instance(row) for row in rows]

    # Alias attendu par deployment_service.can_user_deploy — sans lui,
    # les développeurs ne pouvaient jamais déployer leurs projets.
    def list_instances_by_user(self, username):
        return self.get_user_instances(username)

    def get_instances_by_parent(self, parent_project):
        """Get all instances for a parent project"""
        conn = self._connect()
        rows = conn.execute('SELECT * FROM dev_instances WHERE parent_project = ?',
                            (parent_project,)).fetchall()
        conn.close()
        return [self._row_to_instance(row) for row in rows]

    def list_all_instances(self):
        """List all instances"""
        conn = self._connect()
        rows = conn.execute('SELECT * FROM dev_instances').fetchall()
        conn.close()
        return [self._row_to_instance(row) for row in rows]

    # ─── suppression ──────────────────────────────────────────────────

    def delete_instance(self, name, username, is_admin=False):
        """Delete an instance - Supprime le conteneur Docker, les fichiers et la base de données"""
        from app.utils.logger import wp_logger

        instance = self.get_instance_by_name(name)

        if not instance:
            raise Exception("Instance non trouvée")

        # Vérifier la propriété (sauf pour les admins)
        if not is_admin and instance.owner_username != username:
            raise Exception("Vous n'êtes pas propriétaire de cette instance")

        wp_logger.log_system_info(f"Suppression de l'instance {name} par {username} (admin: {is_admin})")

        # 1. Supprimer le conteneur WordPress de l'instance (rm -f couvre
        # les conteneurs créés avec ou sans `-p`)
        container_name = f"{name}_wordpress"
        try:
            result = subprocess.run(['docker', 'rm', '-f', container_name],
                                    capture_output=True, timeout=60, text=True)
            wp_logger.log_system_info(f"Conteneur {container_name} supprimé: {result.returncode}")
        except Exception as e:
            wp_logger.log_system_info(f"Erreur lors de la suppression du conteneur: {str(e)}")
            # Continuer même si le conteneur n'existe pas

        # 2. Supprimer les fichiers de l'instance (avec sudo car wp-content peut appartenir à www-data)
        instance_path = self.instance_path(instance)
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

        # 3. Supprimer la DB MySQL (si le parent tourne encore)
        mysql_container = self._parent_mysql_container(instance.parent_project)
        if mysql_container:
            try:
                result = subprocess.run([
                    'docker', 'exec', mysql_container,
                    'mysql', '-u', 'root', f'-p{get_root_password(instance.parent_project, container_name=mysql_container)}', '-e',
                    f"DROP DATABASE IF EXISTS `{instance.db_name}`;"
                ], capture_output=True, timeout=30, text=True)
                if result.returncode == 0:
                    wp_logger.log_system_info(f"DB {instance.db_name} supprimée")
                else:
                    wp_logger.log_system_info(f"Erreur suppression DB: {result.stderr}")
            except Exception as e:
                wp_logger.log_system_info(f"Erreur lors de la suppression de la DB: {str(e)}")
        else:
            wp_logger.log_system_info(
                f"Parent {instance.parent_project} arrêté — DB {instance.db_name} non supprimée"
            )

        # 4. Nettoyer ancien dossier containers/.dev-instances/ si existant
        old_path = os.path.join(self.containers_folder, '.dev-instances', name)
        if os.path.exists(old_path):
            try:
                shutil.rmtree(old_path)
                wp_logger.log_system_info(f"Ancien dossier supprimé: {old_path}")
            except Exception as e:
                wp_logger.log_system_info(f"Erreur suppression ancien dossier: {str(e)}")

        # 5. Supprimer de la DB SQLite
        conn = self._connect()
        conn.execute('DELETE FROM dev_instances WHERE name = ?', (name,))
        conn.commit()
        conn.close()
        wp_logger.log_system_info(f"Instance {name} supprimée de la base de données")

    def _row_to_instance(self, row):
        """Convert DB row to DevInstance (accès par nom, plus par index)."""
        keys = row.keys()
        ports = None
        if 'ports' in keys and row['ports']:
            try:
                ports = json.loads(row['ports'])
            except (ValueError, TypeError):
                ports = None
        if not ports:
            ports = {'wordpress': row['port']}

        # Fallback slug pour les lignes d'avant la colonne `slug` : le
        # dossier a été créé avec le username NETTOYÉ, pas le brut.
        slug = row['slug'] if 'slug' in keys and row['slug'] else None
        if not slug:
            slug = clean_username_for_slug(row['owner_username'])

        return DevInstance(
            id=row['id'],
            name=row['name'],
            slug=slug,
            parent_project=row['parent_project'],
            owner_username=row['owner_username'],
            port=row['port'],
            ports=ports,
            db_name=row['db_name'],
            created_at=row['created_at'],
            status=row['status'] if 'status' in keys else 'stopped'
        )
