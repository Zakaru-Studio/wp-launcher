#!/usr/bin/env python3
"""
Service de gestion Docker
"""

import os
import shutil
import subprocess
import time
from app.config.docker_config import DockerConfig
from app.utils.logger import wp_logger
from app.utils.port_preflight import resolve_port_conflicts
from app.services.config_service import ConfigService

class DockerService:
    """Service pour la gestion des conteneurs Docker"""
    
    def __init__(self, template_path=None, projects_folder=None, containers_folder=None):
        self.template_path = template_path or DockerConfig.TEMPLATE_PATH
        self.projects_folder = projects_folder or DockerConfig.PROJECTS_FOLDER
        self.containers_folder = containers_folder or DockerConfig.CONTAINERS_FOLDER
        self.config_service = ConfigService()
    
    def copy_template(self, project_path, enable_nextjs=False):
        """Copie le template docker-compose dans le projet"""
        if not os.path.exists(self.template_path):
            raise Exception(f"Template path {self.template_path} non trouvé")
        
        for item in os.listdir(self.template_path):
            # Ignorer le fichier docker-compose.yml principal si on ne veut pas Next.js
            if item == 'docker-compose.yml' and not enable_nextjs:
                continue
            # Ignorer le fichier sans Next.js si on veut Next.js
            if item == 'docker-compose-no-nextjs.yml' and enable_nextjs:
                continue
                
            src = os.path.join(self.template_path, item)
            dst = os.path.join(project_path, item)
            
            # Cas spécial: renommer docker-compose-no-nextjs.yml en docker-compose.yml
            if item == 'docker-compose-no-nextjs.yml' and not enable_nextjs:
                dst = os.path.join(project_path, 'docker-compose.yml')
            
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
    
    def configure_compose_file(self, container_path, project_name, ports, enable_nextjs=False):
        """Configure le fichier docker-compose.yml avec les bons paramètres"""
        compose_file = os.path.join(container_path, 'docker-compose.yml')
        
        if not os.path.exists(compose_file):
            raise Exception("Fichier docker-compose.yml manquant")
        
        with open(compose_file, 'r') as f:
            content = f.read()
        
        # Remplacer les placeholders de nom de projet
        content = content.replace('PROJECT_NAME', project_name)
        content = content.replace('{project_name}', project_name)
        content = content.replace('{project_hostname}', project_name)
        
        # Remplacer les placeholders de ports - Format moderne
        content = content.replace('{wordpress_port}', str(ports['wordpress']))
        content = content.replace('{phpmyadmin_port}', str(ports['phpmyadmin']))
        content = content.replace('{mailpit_port}', str(ports['mailpit']))
        content = content.replace('{smtp_port}', str(ports['smtp']))
        
        # Remplacer les placeholders de ports - Format ancien (compatibilité)
        content = content.replace('PROJECT_PORT', str(ports['wordpress']))
        content = content.replace('PROJECT_PMA_PORT', str(ports['phpmyadmin']))
        content = content.replace('PROJECT_MAILPIT_PORT', str(ports['mailpit']))
        content = content.replace('PROJECT_SMTP_PORT', str(ports['smtp']))
        
        if enable_nextjs and 'nextjs' in ports:
            content = content.replace('{nextjs_port}', str(ports['nextjs']))
            content = content.replace('PROJECT_NEXTJS_PORT', str(ports['nextjs']))
        
        with open(compose_file, 'w') as f:
            f.write(content)
    
    def configure_wp_config(self, container_path, project_name, ports):
        """Configure le fichier wp-config.php avec les bons paramètres"""
        wp_config_template = os.path.join(container_path, 'wordpress', 'wp-config.php')
        wp_config_dest = os.path.join(self.projects_folder, project_name, 'wp-config.php')
        
        if not os.path.exists(wp_config_template):
            # Le fichier wp-config.php sera créé par WordPress automatiquement
            return
        
        with open(wp_config_template, 'r') as f:
            content = f.read()
        
        # Remplacer les placeholders
        content = content.replace('PROJECT_PORT', str(ports['wordpress']))
        content = content.replace('PROJECT_HOSTNAME', f'{project_name}.local')
        
        # Créer le dossier projets s'il n'existe pas
        os.makedirs(os.path.dirname(wp_config_dest), exist_ok=True)
        
        with open(wp_config_dest, 'w') as f:
            f.write(content)
    
    def _list_existing_containers(self, project_name):
        """Return the list of docker container names belonging to this project,
        regardless of running state. Used to decide between a warm restart
        (`docker-compose start`) and a full `up -d`."""
        try:
            result = subprocess.run(
                ['docker', 'ps', '-a', '--filter', f'label=com.docker.compose.project={project_name}',
                 '--format', '{{.Names}}'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return [n for n in result.stdout.splitlines() if n.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        # Fallback: filter by name prefix (older docker-compose v1 may not set the label)
        try:
            result = subprocess.run(
                ['docker', 'ps', '-a', '--filter', f'name={project_name}_',
                 '--format', '{{.Names}}'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return [n for n in result.stdout.splitlines() if n.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return []

    def _can_warm_restart(self, container_path):
        """A warm restart (no recreate) is possible when every service in the
        compose file already has a corresponding container on the host.
        We don't try to reconcile config drift here — we just check existence.
        If config genuinely changed, the warm path will fail and we fall back."""
        project_name = os.path.basename(container_path)
        existing = self._list_existing_containers(project_name)
        if not existing:
            return False
        # Read service names from compose
        compose_path = os.path.join(container_path, 'docker-compose.yml')
        if not os.path.isfile(compose_path):
            return False
        try:
            with open(compose_path, 'r') as fh:
                compose_text = fh.read()
        except OSError:
            return False
        # Service name extraction: only inside the `services:` section, stopping
        # at the next top-level key (volumes:, networks:, configs:, secrets:).
        import re as _re
        services_block = _re.search(
            r'^services:\s*\n((?:[ \t].*\n|\s*\n)+?)(?=^[a-zA-Z]|\Z)',
            compose_text, _re.MULTILINE,
        )
        if not services_block:
            return False
        services = _re.findall(
            r'^  ([a-zA-Z0-9_-]+):\s*$', services_block.group(1), _re.MULTILINE,
        )
        if not services:
            return False
        # Match each service name as a substring of any container name
        for svc in services:
            if not any(svc in name for name in existing):
                return False
        return True

    def start_containers(self, container_path, timeout=120):
        """Démarre les conteneurs d'un projet depuis containers/"""
        project_name = os.path.basename(container_path)
        wp_logger.log_system_info(f"Démarrage conteneurs pour {project_name}",
                                 container_path=container_path,
                                 operation="docker_start")
        
        # Vérifier si c'est une instance dev
        if '-dev-' in project_name:
            # Extraire le nom du parent
            parent_name = project_name.split('-dev-')[0]
            
            # Vérifier que le parent est running
            parent_mysql = f"{parent_name}_mysql_1"
            try:
                result = subprocess.run([
                    'docker', 'inspect', '--format={{.State.Running}}', parent_mysql
                ], capture_output=True, text=True, timeout=10)
                
                is_running = result.returncode == 0 and result.stdout.strip() == 'true'
                
                if not is_running:
                    error_msg = f"Le projet parent '{parent_name}' doit être démarré d'abord"
                    wp_logger.log_system_info(f"ERREUR: {error_msg}")
                    return False, error_msg
            except Exception as e:
                error_msg = f"Impossible de vérifier le statut du parent: {str(e)}"
                wp_logger.log_system_info(f"ERREUR: {error_msg}")
                return False, error_msg
        
        # Preflight: résoudre automatiquement les conflits de port avant
        # de laisser docker-compose échouer avec "port is already allocated".
        preflight_by_kind = {}
        try:
            changed, remap, notes, preflight_by_kind = resolve_port_conflicts(
                container_path, projects_folder=self.projects_folder
            )
            for note in notes:
                print(f"[PORT_PREFLIGHT] {note}")
            if changed:
                wp_logger.log_system_info(
                    f"Port preflight a remappé des ports pour {project_name}",
                    remap=remap,
                )
        except Exception as e:
            # Ne bloque pas le démarrage : on log et on continue, docker-compose
            # signalera le conflit à l'ancienne si besoin.
            print(f"⚠️ [PORT_PREFLIGHT] Vérification préalable échouée : {e}")

        # Fast path: si tous les containers existent déjà, tenter `start` (sans recréation)
        # qui évite ~5-15s de pull/extract/network teardown. On retombe sur `up -d`
        # automatiquement si la config a drifté.
        warm_restart = self._can_warm_restart(container_path)

        original_cwd = os.getcwd()
        try:
            os.chdir(container_path)
            if warm_restart:
                print(f"⚡ [DOCKER_SERVICE] Warm restart pour {project_name} (containers existants)")
                result = subprocess.run([
                    'docker-compose', 'start'
                ], capture_output=True, text=True, timeout=timeout)
                success = result.returncode == 0
                if not success:
                    print(f"⚠️ [DOCKER_SERVICE] Warm restart échoué, fallback sur up -d")
                    warm_restart = False  # fallback path will not skip perms
                    result = subprocess.run([
                        'docker-compose', 'up', '-d'
                    ], capture_output=True, text=True, timeout=timeout)
                    success = result.returncode == 0
            else:
                result = subprocess.run([
                    'docker-compose', 'up', '-d'
                ], capture_output=True, text=True, timeout=timeout)
                success = result.returncode == 0

            # Second tour si docker-compose signale "port is already allocated"
            # ou "Bind for X.X.X.X:PORT failed" : on relance le preflight + retry.
            if not success and result.stderr and (
                'port is already allocated' in result.stderr
                or 'Bind for' in result.stderr
            ):
                print(f"⚠️ [DOCKER_SERVICE] Conflit de port détecté pour {project_name}, retry avec preflight...")
                os.chdir(original_cwd)
                try:
                    changed, remap, notes, retry_by_kind = resolve_port_conflicts(
                        container_path, projects_folder=self.projects_folder
                    )
                    for note in notes:
                        print(f"[PORT_PREFLIGHT] {note}")
                    # Merge any new remaps discovered on retry
                    preflight_by_kind.update(retry_by_kind)
                    if changed:
                        # Nettoyer les conteneurs partiellement créés avant retry
                        subprocess.run(['docker-compose', '-f',
                                        os.path.join(container_path, 'docker-compose.yml'),
                                        'down'],
                                       capture_output=True, text=True, timeout=60)
                        os.chdir(container_path)
                        result = subprocess.run([
                            'docker-compose', 'up', '-d'
                        ], capture_output=True, text=True, timeout=timeout)
                        success = result.returncode == 0
                        if success:
                            print(f"✅ [DOCKER_SERVICE] Retry réussi après remap des ports")
                except Exception as retry_err:
                    print(f"❌ [DOCKER_SERVICE] Retry preflight échoué: {retry_err}")

            # Gestion automatique de l'erreur ContainerConfig
            if not success and result.stderr and 'ContainerConfig' in result.stderr:
                print(f"⚠️ [DOCKER_SERVICE] Erreur ContainerConfig détectée pour {project_name}")
                print(f"🔄 [DOCKER_SERVICE] Nettoyage et redémarrage automatique des conteneurs...")
                
                # Arrêter complètement les conteneurs
                stop_result = subprocess.run([
                    'docker-compose', 'down'
                ], capture_output=True, text=True, timeout=60)
                
                if stop_result.returncode == 0:
                    print(f"✅ [DOCKER_SERVICE] Conteneurs arrêtés proprement")
                    
                    # Attendre 2 secondes
                    import time
                    time.sleep(2)
                    
                    # Redémarrer les conteneurs
                    print(f"🚀 [DOCKER_SERVICE] Redémarrage des conteneurs...")
                    result = subprocess.run([
                        'docker-compose', 'up', '-d'
                    ], capture_output=True, text=True, timeout=timeout)
                    
                    success = result.returncode == 0
                    
                    if success:
                        print(f"✅ [DOCKER_SERVICE] Conteneurs redémarrés avec succès après correction ContainerConfig")
                    else:
                        print(f"❌ [DOCKER_SERVICE] Échec du redémarrage après correction ContainerConfig")
                else:
                    print(f"❌ [DOCKER_SERVICE] Échec de l'arrêt des conteneurs")
            
            # Si le démarrage a réussi, corriger automatiquement les permissions
            if success:
                # Extraire le nom du projet depuis le chemin
                project_name = os.path.basename(container_path)

                # Sur warm restart : pas besoin de chown/chmod (les fichiers n'ont pas
                # bougé sur disque, les permissions sont identiques au stop précédent).
                # Sur cold start (recréation) : on fixe les permissions car les bind
                # mounts peuvent avoir été remontés et le UID/GID doit matcher.
                if warm_restart:
                    print(f"⚡ [DOCKER_SERVICE] Warm restart : skip permission fix pour {project_name}")
                else:
                    print(f"🔧 [DOCKER_SERVICE] Correction automatique des permissions après démarrage pour {project_name}")

                    import time
                    # Attendre brièvement que les containers soient bien up. On poll au
                    # lieu d'un sleep fixe : on sort dès que tous sont running ou après 5s.
                    deadline = time.time() + 5
                    expected = self._list_existing_containers(project_name)
                    while time.time() < deadline:
                        all_running = True
                        for name in expected:
                            probe = subprocess.run(
                                ['docker', 'inspect', '--format={{.State.Running}}', name],
                                capture_output=True, text=True, timeout=3,
                            )
                            if probe.returncode != 0 or probe.stdout.strip() != 'true':
                                all_running = False
                                break
                        if all_running:
                            break
                        time.sleep(0.3)

                    # Corriger les permissions pour dev-server
                    if self.fix_dev_permissions(project_name):
                        print(f"✅ [DOCKER_SERVICE] Permissions automatiquement corrigées pour {project_name}")
                    else:
                        print(f"⚠️ [DOCKER_SERVICE] Impossible de corriger automatiquement les permissions pour {project_name}")

                # Post-start DB sync: si le port WordPress a été remappé par le preflight,
                # mettre à jour wp_options.siteurl/home maintenant que MySQL est démarré.
                if 'wordpress' in preflight_by_kind:
                    old_wp_port, new_wp_port = preflight_by_kind['wordpress']
                    mysql_container = f"{project_name}_mysql_1"
                    # Attendre que MySQL soit healthy (jusqu'à 60s)
                    healthy = False
                    for _ in range(30):
                        probe = subprocess.run(
                            ['docker', 'inspect', '--format={{.State.Health.Status}}', mysql_container],
                            capture_output=True, text=True, timeout=5,
                        )
                        if probe.returncode == 0 and probe.stdout.strip() == 'healthy':
                            healthy = True
                            break
                        time.sleep(2)
                    if healthy:
                        host_ip = os.environ.get('APP_HOST', DockerConfig.LOCAL_IP)
                        new_url = f"http://{host_ip}:{new_wp_port}"
                        sql = (
                            "UPDATE wp_options "
                            f"SET option_value = '{new_url}' "
                            "WHERE option_name IN ('siteurl','home');"
                        )
                        db_sync = subprocess.run(
                            ['docker', 'exec', mysql_container, 'mysql',
                             '-uroot', '-prootpassword', 'wordpress', '--execute', sql],
                            capture_output=True, text=True, timeout=30,
                        )
                        if db_sync.returncode == 0:
                            print(f"🗃️ [DOCKER_SERVICE] wp_options URLs mises à jour ({old_wp_port} → {new_wp_port})")
                        else:
                            print(f"⚠️ [DOCKER_SERVICE] Échec sync DB URLs: {db_sync.stderr}")
                    else:
                        print(f"⚠️ [DOCKER_SERVICE] MySQL pas healthy, sync DB URLs sautée")
            
            # Log du résultat
            if success:
                wp_logger.log_docker_operation('start', project_name, True, 
                                             result.stdout,
                                             container_path=container_path,
                                             details="Conteneurs démarrés avec succès")
            else:
                wp_logger.log_docker_operation('start', project_name, False, 
                                             "",
                                             result.stderr,
                                             container_path=container_path,
                                             details="Échec démarrage conteneurs")
            
            return success, result.stderr if result.returncode != 0 else None
        except subprocess.TimeoutExpired:
            wp_logger.log_docker_operation('start', project_name, False, 
                                         "",
                                         "Timeout démarrage conteneurs",
                                         container_path=container_path)
            return False, "Timeout lors du démarrage des conteneurs"
        except Exception as e:
            wp_logger.log_docker_operation('start', project_name, False, 
                                         "",
                                         str(e),
                                         container_path=container_path,
                                         details="Exception démarrage conteneurs")
            return False, str(e)
        finally:
            os.chdir(original_cwd)
    
    def stop_containers(self, container_path, timeout=60):
        """Arrête les conteneurs d'un projet depuis containers/"""
        project_name = os.path.basename(container_path)
        wp_logger.log_system_info(f"Arrêt conteneurs pour {project_name}", 
                                 container_path=container_path,
                                 operation="docker_stop")
        
        original_cwd = os.getcwd()
        try:
            os.chdir(container_path)
            result = subprocess.run([
                'docker-compose', 'stop'
            ], capture_output=True, text=True, timeout=timeout)
            
            success = result.returncode == 0
            
            # Log du résultat
            if success:
                wp_logger.log_docker_operation('stop', project_name, True, 
                                             result.stdout,
                                             "",
                                             container_path=container_path,
                                             details="Conteneurs arrêtés avec succès")
            else:
                wp_logger.log_docker_operation('stop', project_name, False, 
                                             "",
                                             result.stderr,
                                             container_path=container_path,
                                             details="Échec arrêt conteneurs")
            
            return success, result.stderr if result.returncode != 0 else None
        except subprocess.TimeoutExpired:
            wp_logger.log_docker_operation('stop', project_name, False, 
                                         "",
                                         "Timeout arrêt conteneurs",
                                         container_path=container_path)
            return False, "Timeout lors de l'arrêt des conteneurs"
        except Exception as e:
            wp_logger.log_docker_operation('stop', project_name, False, 
                                         "",
                                         str(e),
                                         container_path=container_path,
                                         details="Exception arrêt conteneurs")
            return False, str(e)
        finally:
            os.chdir(original_cwd)
    
    def remove_containers(self, container_path, timeout=60):
        """Supprime complètement les conteneurs d'un projet depuis containers/"""
        original_cwd = os.getcwd()
        project_name = os.path.basename(container_path)
        
        wp_logger.log_system_info(f"Suppression complète conteneurs pour {project_name}", 
                                 container_path=container_path,
                                 operation="docker_remove")
        
        try:
            print(f"🗑️ [DOCKER_SERVICE] Suppression complète Docker pour {project_name}")
            
            # Étape 1: docker-compose down avec volumes
            print(f"📂 [DOCKER_SERVICE] Arrêt et suppression via docker-compose...")
            os.chdir(container_path)
            result = subprocess.run([
                'docker-compose', 'down', '-v', '--remove-orphans', '--rmi', 'local'
            ], capture_output=True, text=True, timeout=timeout)
            
            if result.returncode != 0:
                print(f"⚠️ [DOCKER_SERVICE] docker-compose down a échoué: {result.stderr}")
            else:
                print(f"✅ [DOCKER_SERVICE] docker-compose down réussi")
            
            # Étape 2: Suppression manuelle des conteneurs par pattern
            print(f"🐳 [DOCKER_SERVICE] Suppression manuelle des conteneurs...")
            patterns = [f"{project_name}_", f"{project_name}-", f"_{project_name}_", f"-{project_name}-"]
            
            for pattern in patterns:
                try:
                    # Trouver les conteneurs avec ce pattern
                    find_result = subprocess.run([
                        'docker', 'ps', '-a', '--format', '{{.Names}}'
                    ], capture_output=True, text=True, timeout=30)
                    
                    if find_result.returncode == 0:
                        containers = [name.strip() for name in find_result.stdout.split('\n') 
                                    if name.strip() and pattern in name.strip()]
                        
                        if containers:
                            print(f"🛑 [DOCKER_SERVICE] Arrêt des conteneurs: {containers}")
                            # Arrêter les conteneurs
                            subprocess.run(['docker', 'stop'] + containers, 
                                         capture_output=True, text=True, timeout=30)
                            
                            print(f"🗑️ [DOCKER_SERVICE] Suppression des conteneurs: {containers}")
                            # Supprimer les conteneurs
                            subprocess.run(['docker', 'rm', '-f'] + containers, 
                                         capture_output=True, text=True, timeout=30)
                            
                except Exception as e:
                    print(f"⚠️ [DOCKER_SERVICE] Erreur lors de la suppression des conteneurs {pattern}: {e}")
            
            # Étape 3: Suppression des volumes par pattern
            print(f"💾 [DOCKER_SERVICE] Suppression des volumes...")
            for pattern in patterns:
                try:
                    find_volumes = subprocess.run([
                        'docker', 'volume', 'ls', '--format', '{{.Name}}'
                    ], capture_output=True, text=True, timeout=30)
                    
                    if find_volumes.returncode == 0:
                        volumes = [name.strip() for name in find_volumes.stdout.split('\n') 
                                 if name.strip() and pattern in name.strip()]
                        
                        if volumes:
                            print(f"💾 [DOCKER_SERVICE] Suppression des volumes: {volumes}")
                            subprocess.run(['docker', 'volume', 'rm', '-f'] + volumes, 
                                         capture_output=True, text=True, timeout=30)
                            
                except Exception as e:
                    print(f"⚠️ [DOCKER_SERVICE] Erreur lors de la suppression des volumes {pattern}: {e}")
            
            # Étape 4: Suppression des réseaux par pattern
            print(f"🌐 [DOCKER_SERVICE] Suppression des réseaux...")
            for pattern in patterns:
                try:
                    find_networks = subprocess.run([
                        'docker', 'network', 'ls', '--format', '{{.Name}}'
                    ], capture_output=True, text=True, timeout=30)
                    
                    if find_networks.returncode == 0:
                        networks = [name.strip() for name in find_networks.stdout.split('\n') 
                                  if name.strip() and pattern in name.strip() and name.strip() not in ['bridge', 'host', 'none']]
                        
                        if networks:
                            print(f"🌐 [DOCKER_SERVICE] Suppression des réseaux: {networks}")
                            subprocess.run(['docker', 'network', 'rm'] + networks, 
                                         capture_output=True, text=True, timeout=30)
                            
                except Exception as e:
                    print(f"⚠️ [DOCKER_SERVICE] Erreur lors de la suppression des réseaux {pattern}: {e}")
            
            # Étape 5: Suppression des images personnalisées liées au projet
            print(f"🖼️ [DOCKER_SERVICE] Suppression des images personnalisées...")
            try:
                find_images = subprocess.run([
                    'docker', 'images', '--format', '{{.Repository}}:{{.Tag}}'
                ], capture_output=True, text=True, timeout=30)
                
                if find_images.returncode == 0:
                    images = [img.strip() for img in find_images.stdout.split('\n') 
                            if img.strip() and project_name.lower() in img.strip().lower()]
                    
                    if images:
                        print(f"🖼️ [DOCKER_SERVICE] Suppression des images: {images}")
                        subprocess.run(['docker', 'rmi', '-f'] + images, 
                                     capture_output=True, text=True, timeout=30)
                        
            except Exception as e:
                print(f"⚠️ [DOCKER_SERVICE] Erreur lors de la suppression des images: {e}")
            
            # Étape 6: Nettoyage des ressources orphelines
            print(f"🧹 [DOCKER_SERVICE] Nettoyage des ressources orphelines...")
            try:
                subprocess.run(['docker', 'system', 'prune', '-f'], 
                             capture_output=True, text=True, timeout=60)
                print(f"✅ [DOCKER_SERVICE] Nettoyage système terminé")
            except Exception as e:
                print(f"⚠️ [DOCKER_SERVICE] Erreur lors du nettoyage système: {e}")
            
            print(f"✅ [DOCKER_SERVICE] Suppression complète terminée pour {project_name}")
            wp_logger.log_docker_operation('remove', project_name, True, 
                                         "",
                                         "",
                                         container_path=container_path,
                                         details="Suppression complète terminée avec succès")
            return True, None
            
        except subprocess.TimeoutExpired:
            wp_logger.log_docker_operation('remove', project_name, False, 
                                         "",
                                         "Timeout suppression conteneurs",
                                         container_path=container_path)
            return False, "Timeout lors de la suppression complète des conteneurs"
        except Exception as e:
            print(f"❌ [DOCKER_SERVICE] Erreur lors de la suppression complète: {e}")
            wp_logger.log_docker_operation('remove', project_name, False, 
                                         "",
                                         str(e),
                                         container_path=container_path,
                                         details="Exception suppression conteneurs")
            return False, str(e)
        finally:
            os.chdir(original_cwd)
    
    def get_container_status(self, project_name):
        """Vérifie le statut des conteneurs d'un projet"""
        try:
            # Vérifier si les conteneurs sont en cours d'exécution
            result = subprocess.run([
                'docker', 'ps', '--format', '{{.Names}}'
            ], capture_output=True, text=True)
            
            running_containers = result.stdout.strip().split('\n')
            
            # Compter les conteneurs en cours d'exécution pour ce projet
            project_containers = [c for c in running_containers if c.startswith(f"{project_name}_")]
            
            if len(project_containers) >= 2:  # Au moins 2 conteneurs actifs
                return 'active'
            else:
                return 'inactive'
        except Exception:
            return 'inactive'
    
    def get_individual_container_status(self, container_name):
        """Vérifie le statut d'un conteneur individuel"""
        try:
            # Vérifier si le conteneur est en cours d'exécution
            result = subprocess.run([
                'docker', 'ps', '--format', '{{.Names}}'
            ], capture_output=True, text=True)
            
            running_containers = result.stdout.strip().split('\n')
            
            if container_name in running_containers:
                return 'active'
            else:
                # Vérifier si le conteneur existe mais est arrêté
                result_all = subprocess.run([
                    'docker', 'ps', '-a', '--format', '{{.Names}}'
                ], capture_output=True, text=True)
                
                all_containers = result_all.stdout.strip().split('\n')
                
                if container_name in all_containers:
                    return 'stopped'
                else:
                    return 'not_found'
        except Exception:
            return 'error'
    
    def get_container_logs(self, project_name, service_name, lines=50):
        """Récupère les logs d'un conteneur"""
        try:
            container_name = f"{project_name}_{service_name}_1"
            result = subprocess.run([
                'docker', 'logs', '--tail', str(lines), container_name
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                return result.stdout
            else:
                return f"Erreur: {result.stderr}"
        except Exception as e:
            return f"Erreur lors de la récupération des logs: {str(e)}"
    
    def execute_command(self, command, timeout=30):
        """Exécute une commande Docker générique"""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Timeout lors de l'exécution de la commande"
        except Exception as e:
            return False, "", str(e)
    
    def execute_command_in_container(self, project_name, service_name, command, timeout=30, input_data=None):
        """Exécute une commande dans un conteneur avec support pour input_data"""
        try:
            container_name = f"{project_name}_{service_name}_1"
            
            # Construire la commande docker exec
            docker_cmd = ['docker', 'exec']
            
            # Ajouter -i si on a des données d'entrée
            if input_data:
                docker_cmd.append('-i')
            
            docker_cmd.extend([container_name] + command)
            
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input_data
            )
            
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Timeout lors de l'exécution de la commande"
        except Exception as e:
            return False, "", str(e)
    
    def check_mysql_ready(self, project_name, timeout=2):
        """Vérifie si MySQL est prêt en testant la connectivité depuis WordPress avec WP-CLI"""
        success, stdout, stderr = self.execute_command_in_container(
            project_name, 
            'wordpress', 
            ['wp', 'db', 'check', '--allow-root'],
            timeout
        )
        return success
    
    def wait_for_mysql(self, project_name, max_wait_time=60):
        """Attente intelligente de MySQL"""
        print("🔍 Test instantané de MySQL...")
        if self.check_mysql_ready(project_name, timeout=1):
            print("✅ MySQL déjà prêt ! Aucune attente nécessaire.")
            return True
        
        print("⏳ MySQL pas encore prêt, attente intelligente...")
        
        # Attente progressive avec intervalles adaptatifs (optimisé pour redémarrages rapides)
        wait_phases = [
            (5, 1),    # 5 tentatives × 1 seconde = tests très rapides
            (4, 2),    # 4 tentatives × 2 secondes = redémarrage normal  
            (4, 3),    # 4 tentatives × 3 secondes = démarrage standard
            (6, 4)     # 6 tentatives × 4 secondes = démarrage lent
        ]
        
        total_attempts = 0
        start_time = time.time()
        
        for phase_attempts, interval in wait_phases:
            for attempt in range(phase_attempts):
                total_attempts += 1
                elapsed = time.time() - start_time
                
                # Arrêter si on dépasse le temps maximum
                if elapsed > max_wait_time:
                    print(f"⚠️ Timeout après {elapsed:.1f}s - MySQL peut encore être en démarrage")
                    return False
                
                # Afficher moins de logs pour ne pas encombrer
                if total_attempts % 3 == 0 or elapsed < 5:
                    print(f"⏳ Test MySQL {total_attempts} (intervalle: {interval}s)")
                
                if self.check_mysql_ready(project_name, timeout=2):
                    print(f"✅ MySQL prêt après {elapsed:.1f}s ({total_attempts} tentatives)")
                    return True
                
                time.sleep(interval)
        
        print(f"⚠️ MySQL non disponible après {max_wait_time}s d'attente")
        return False
    
    def cleanup_unused_resources(self):
        """Nettoie les ressources Docker inutilisées"""
        try:
            # Nettoyer les volumes
            subprocess.run(['docker', 'volume', 'prune', '-f'], 
                          capture_output=True, text=True)
            
            # Nettoyer les réseaux
            subprocess.run(['docker', 'network', 'prune', '-f'], 
                          capture_output=True, text=True)
            
            # Nettoyer les images inutilisées
            subprocess.run(['docker', 'image', 'prune', '-f'], 
                          capture_output=True, text=True)
            
            return True
        except Exception as e:
            print(f"Erreur lors du nettoyage Docker: {e}")
            return False 

    def create_project_structure(self, container_path, project_path, enable_nextjs=False):
        """Crée la structure de répertoires avec l'architecture containers/projets séparée"""
        # Créer le dossier des conteneurs
        os.makedirs(container_path, exist_ok=True)
        
        # Créer le dossier des fichiers éditables
        os.makedirs(project_path, exist_ok=True)
        
        # Créer les dossiers de configuration dans containers/
        php_config_dir = os.path.join(container_path, 'php-config')
        mysql_config_dir = os.path.join(container_path, 'mysql-config')
        phpmyadmin_config_dir = os.path.join(container_path, 'phpmyadmin-config')
        
        os.makedirs(php_config_dir, exist_ok=True)
        os.makedirs(mysql_config_dir, exist_ok=True)
        os.makedirs(phpmyadmin_config_dir, exist_ok=True)
        
        # Copier les fichiers de configuration vers containers/
        shutil.copy2('docker-template/php-config/php.ini', php_config_dir)
        shutil.copy2('docker-template/mysql-config/mysql.cnf', mysql_config_dir)
        shutil.copy2('docker-template/phpmyadmin-config/php.ini', phpmyadmin_config_dir)
        
        # Copier le fichier docker-compose approprié vers containers/
        if enable_nextjs:
            shutil.copy2('docker-template/docker-compose.yml', container_path)
        else:
            shutil.copy2('docker-template/docker-compose-no-nextjs.yml', 
                        os.path.join(container_path, 'docker-compose.yml'))
        
        # Créer le dossier WordPress dans containers/
        wordpress_dir = os.path.join(container_path, 'wordpress')
        os.makedirs(wordpress_dir, exist_ok=True)
        
        # Copier le fichier wp-config.php template vers containers/
        shutil.copy2('docker-template/wordpress/wp-config.php', wordpress_dir)
        
        # Créer wp-content dans projets/
        wp_content_dir = os.path.join(project_path, 'wp-content')
        
        # Créer le dossier config et les fichiers de configuration
        project_name = os.path.basename(project_path)
        self.config_service.ensure_project_config_directory(project_name)
        
        # Utiliser le wp-content de référence s'il existe
        reference_wp_content = os.path.join(os.getcwd(), 'templates', 'wp-content-reference')
        
        if os.path.exists(reference_wp_content):
            print(f"📁 [DOCKER_SERVICE] Utilisation du wp-content de référence depuis {reference_wp_content}")
            if os.path.exists(wp_content_dir):
                shutil.rmtree(wp_content_dir)
            shutil.copytree(reference_wp_content, wp_content_dir)
            print(f"✅ [DOCKER_SERVICE] wp-content de référence copié vers {wp_content_dir}")
            
            # Corriger les permissions après la copie
            print(f"🔧 [DOCKER_SERVICE] Correction des permissions wp-content...")
            self._fix_wp_content_permissions(wp_content_dir)
        else:
            print(f"⚠️ [DOCKER_SERVICE] wp-content de référence non trouvé, création des dossiers de base")
            os.makedirs(wp_content_dir, exist_ok=True)
            os.makedirs(os.path.join(wp_content_dir, 'themes'), exist_ok=True)
            os.makedirs(os.path.join(wp_content_dir, 'plugins'), exist_ok=True)
            os.makedirs(os.path.join(wp_content_dir, 'uploads'), exist_ok=True)
            
            # Corriger les permissions pour les dossiers créés
            print(f"🔧 [DOCKER_SERVICE] Correction des permissions wp-content...")
            self._fix_wp_content_permissions(wp_content_dir)
        
        print("✅ [DOCKER_SERVICE] Structure de projet avec architecture séparée créée")
        return True
    
    def setup_reference_wp_content(self, project_path):
        """Configure le wp-content de référence pour un nouveau projet WordPress"""
        try:
            wp_content_dir = os.path.join(project_path, 'wp-content')
            reference_wp_content = os.path.join(os.getcwd(), 'templates', 'wp-content-reference')
            
            if os.path.exists(reference_wp_content):
                print(f"📁 [DOCKER_SERVICE] Utilisation du wp-content de référence")
                
                # Supprimer le wp-content existant s'il existe
                if os.path.exists(wp_content_dir):
                    shutil.rmtree(wp_content_dir)
                
                # Copier le wp-content de référence
                shutil.copytree(reference_wp_content, wp_content_dir)
                
                # Créer un fichier .gitignore pour wp-content/uploads
                uploads_gitignore = os.path.join(wp_content_dir, 'uploads', '.gitignore')
                os.makedirs(os.path.dirname(uploads_gitignore), exist_ok=True)
                with open(uploads_gitignore, 'w') as f:
                    f.write("*\n!.gitignore\n")
                
                print(f"✅ [DOCKER_SERVICE] wp-content de référence configuré")
                return True
            else:
                print(f"⚠️ [DOCKER_SERVICE] wp-content de référence non trouvé")
                return False
                
        except Exception as e:
            print(f"❌ [DOCKER_SERVICE] Erreur lors de la configuration du wp-content: {e}")
            return False
    
    def create_wordpress_nextjs_project(self, container_path, project_path, project_name, ports=None):
        """Crée un projet WordPress avec Next.js en utilisant l'auto-installation par entrypoint"""
        try:
            print(f"🚀 [DOCKER_SERVICE] Création du projet WordPress+Next.js: {project_name}")
            
            # Créer la structure de base
            result = self.create_project_structure(container_path, project_path, enable_nextjs=True)
            
            if not result:
                return False
            
            # Configurer les ports dans le fichier docker-compose.yml si fournis
            if ports:
                print(f"⚙️ [DOCKER_SERVICE] Configuration des ports dans docker-compose.yml")
                self.configure_compose_file(container_path, project_name, ports, enable_nextjs=True)
            
            # Remplacer le wp-content de base par le wp-content de référence
            self.setup_reference_wp_content(project_path)
                
            # Ajouter le fichier .project_type pour identifier le type de projet
            project_type_file = os.path.join(project_path, '.project_type')
            with open(project_type_file, 'w') as f:
                f.write('wordpress_nextjs')
            
            # Créer le dossier Next.js
            nextjs_dir = os.path.join(project_path, 'nextjs')
            os.makedirs(nextjs_dir, exist_ok=True)
            
            # Créer un package.json de base pour Next.js
            package_json_content = """{
    "name": "%s-nextjs",
    "version": "1.0.0",
    "private": true,
    "scripts": {
        "dev": "next dev",
        "build": "next build",
        "start": "next start",
        "lint": "next lint"
    },
    "dependencies": {
        "next": "latest",
        "react": "^18.2.0",
        "react-dom": "^18.2.0"
    },
    "devDependencies": {
        "eslint": "^8.0.0",
        "eslint-config-next": "latest"
    }
    }""" % project_name
            
            with open(os.path.join(nextjs_dir, 'package.json'), 'w') as f:
                f.write(package_json_content)
            
            # Créer les fichiers de base WordPress (.htaccess et wp-config.php)
            print(f"📝 [DOCKER_SERVICE] Création des fichiers de base WordPress...")
            
            from app.utils.project_utils import create_wordpress_base_files
            if not create_wordpress_base_files(project_path):
                print(f"❌ [DOCKER_SERVICE] Erreur lors de la création des fichiers de base WordPress")
                return False
            
            # Mettre à jour les URLs dans wp-config.php si des ports sont fournis
            if ports:
                from app.utils.project_utils import update_project_wordpress_urls_in_files
                update_project_wordpress_urls_in_files(project_path, ports['wordpress'])
            
            # ===== MODIFICATION PRINCIPALE =====
            # Utiliser la nouvelle méthode qui comprend l'auto-installation par entrypoint
            print(f"🚀 [DOCKER_SERVICE] Démarrage avec auto-installation...")
            success, error = self.start_containers_with_auto_install(container_path, project_name)
            
            if success:
                print(f"✅ [DOCKER_SERVICE] Projet créé et WordPress auto-installé avec succès!")
            else:
                print(f"⚠️ [DOCKER_SERVICE] Projet créé mais auto-installation incomplète: {error}")
                print(f"🔧 [DOCKER_SERVICE] L'installation se terminera automatiquement en arrière-plan")
            
            print(f"✅ [DOCKER_SERVICE] Projet WordPress+Next.js créé avec wp-content de référence")
            return True
            
        except Exception as e:
            print(f"❌ [DOCKER_SERVICE] Erreur lors de la création du projet WordPress+Next.js: {e}")
            return False
    
    def install_wordpress_automatically(self, project_name, site_title=None, admin_user=None, admin_password=None, admin_email=None):
        """Installe automatiquement WordPress avec WP-CLI"""
        try:
            print(f"🚀 [DOCKER_SERVICE] Installation automatique de WordPress pour {project_name}")

            # Utiliser les valeurs de DockerConfig si non spécifiées
            admin_user = admin_user or DockerConfig.WP_ADMIN_USER
            admin_password = admin_password or DockerConfig.WP_ADMIN_PASSWORD
            admin_email = admin_email or DockerConfig.WP_ADMIN_EMAIL

            # Utiliser le nom du projet comme titre du site par défaut
            if not site_title:
                site_title = project_name.title()
            
            # Attendre que WordPress soit prêt
            print(f"⏳ Attente que WordPress soit prêt...")
            if not self.wait_for_wordpress(project_name, max_wait_time=120):
                print(f"❌ WordPress n'est pas prêt après 120 secondes")
                return False
            
            # Vérifier que WP-CLI est disponible
            print(f"🔍 Vérification de WP-CLI...")
            success, stdout, stderr = self.execute_command_in_container(
                project_name, 'wordpress',
                ['wp', '--version'],
                timeout=30
            )
            
            if not success:
                print(f"❌ WP-CLI non disponible: {stderr}")
                return False
            
            print(f"✅ WP-CLI disponible: {stdout.strip()}")
            
            # Obtenir l'URL du site
            project_port = self._get_project_port(project_name)
            site_url = f"http://{DockerConfig.LOCAL_IP}:{project_port}"
            
            print(f"🌐 URL du site: {site_url}")
            print(f"📝 Titre: {site_title}")
            print(f"👤 Admin: {admin_user}")
            print(f"📧 Email: {admin_email}")
            
            # Installer WordPress avec WP-CLI
            print(f"⚙️ Installation de WordPress...")
            install_cmd = [
                'wp', 'core', 'install',
                f'--url={site_url}',
                f'--title={site_title}',
                f'--admin_user={admin_user}',
                f'--admin_password={admin_password}',
                f'--admin_email={admin_email}',
                '--allow-root'
            ]
            
            success, stdout, stderr = self.execute_command_in_container(
                project_name, 'wordpress',
                install_cmd,
                timeout=60
            )
            
            if success:
                print(f"✅ WordPress installé avec succès!")
                print(f"🔗 URL d'administration: {site_url}/wp-admin")
                print(f"👤 Identifiants: {admin_user} / {admin_password}")
                
                # Activer les thèmes et plugins si nécessaire
                self._configure_wordpress_post_install(project_name)
                
                return True
            else:
                print(f"❌ Erreur lors de l'installation WordPress: {stderr}")
                return False
                
        except Exception as e:
            print(f"❌ [DOCKER_SERVICE] Erreur lors de l'installation automatique: {e}")
            return False
    
    def wait_for_wordpress(self, project_name, max_wait_time=120):
        """Attend que WordPress soit prêt à recevoir des commandes"""
        try:
            print(f"⏳ Attente que WordPress soit prêt...")
            
            import time
            wait_time = 0
            check_interval = 5
            
            while wait_time < max_wait_time:
                # Vérifier que le conteneur WordPress est actif
                success, stdout, stderr = self.execute_command_in_container(
                    project_name, 'wordpress',
                    ['ls', '-la', '/var/www/html/wp-config.php'],
                    timeout=10
                )
                
                if success:
                    # Vérifier que WordPress peut se connecter à MySQL
                    success, stdout, stderr = self.execute_command_in_container(
                        project_name, 'wordpress',
                        ['wp', 'db', 'check', '--allow-root'],
                        timeout=15
                    )
                    
                    if success:
                        print(f"✅ WordPress prêt après {wait_time} secondes")
                        return True
                
                print(f"⏳ WordPress pas encore prêt... ({wait_time}s/{max_wait_time}s)")
                time.sleep(check_interval)
                wait_time += check_interval
            
            print(f"❌ Timeout: WordPress non prêt après {max_wait_time} secondes")
            return False
            
        except Exception as e:
            print(f"❌ Erreur lors de l'attente WordPress: {e}")
            return False
    
    def _get_project_port(self, project_name):
        """Récupère le port principal d'un projet"""
        try:
            # Essayer de lire le port depuis le fichier .port
            port_file = os.path.join(self.containers_folder, project_name, '.port')
            if os.path.exists(port_file):
                with open(port_file, 'r') as f:
                    return int(f.read().strip())
            
            # Fallback: chercher dans docker-compose.yml
            compose_file = os.path.join(self.containers_folder, project_name, 'docker-compose.yml')
            if os.path.exists(compose_file):
                with open(compose_file, 'r') as f:
                    content = f.read()
                    # Chercher le port WordPress (format "8080:80")
                    import re
                    match = re.search(r'"(\d+):80"', content)
                    if match:
                        return int(match.group(1))
            
            # Port par défaut
            return 8080
            
        except Exception as e:
            print(f"❌ Erreur lors de la récupération du port: {e}")
            return 8080
    
    def _copy_wp_config_to_project(self, project_name):
        """Copie wp-config.php du conteneur vers le dossier du projet"""
        try:
            print(f"📁 [AUTO-INSTALL] Copie wp-config.php vers le projet...")
            
            # Copier wp-config.php depuis le conteneur vers le dossier du projet
            success, stdout, stderr = self.execute_command_in_container(
                project_name, 'wordpress',
                ['cp', '/var/www/html/wp-config.php', '/var/www/html/wp-content/../wp-config.php'],
                timeout=10
            )
            
            if success:
                print(f"✅ [AUTO-INSTALL] wp-config.php copié vers le projet")
            else:
                print(f"⚠️ [AUTO-INSTALL] Erreur lors de la copie wp-config.php: {stderr}")
                
        except Exception as e:
            print(f"⚠️ [AUTO-INSTALL] Exception lors de la copie wp-config.php: {e}")
    
    def _configure_wordpress_post_install(self, project_name):
        """Configuration post-installation WordPress"""
        try:
            print(f"🔧 [AUTO-INSTALL] Configuration post-installation...")
            
            # Configurer les permaliens
            success, stdout, stderr = self.execute_command_in_container(
                project_name, 'wordpress',
                ['wp', 'rewrite', 'structure', '/%postname%/', '--allow-root'],
                timeout=15
            )
            
            if success:
                print(f"✅ [AUTO-INSTALL] Permaliens configurés")
            
            # Configurer la langue française
            success, stdout, stderr = self.execute_command_in_container(
                project_name, 'wordpress',
                ['wp', 'language', 'core', 'install', 'fr_FR', '--allow-root'],
                timeout=30
            )
            
            if success:
                print(f"✅ [AUTO-INSTALL] Langue française installée")
            
            # Activer la langue française
            success, stdout, stderr = self.execute_command_in_container(
                project_name, 'wordpress',
                ['wp', 'site', 'switch-language', 'fr_FR', '--allow-root'],
                timeout=15
            )
            
            if success:
                print(f"✅ [AUTO-INSTALL] Langue française activée")
            
            # Configurer le fuseau horaire
            success, stdout, stderr = self.execute_command_in_container(
                project_name, 'wordpress',
                ['wp', 'option', 'update', 'timezone_string', 'Europe/Paris', '--allow-root'],
                timeout=15
            )
            
            if success:
                print(f"✅ [AUTO-INSTALL] Fuseau horaire configuré")
            
            # Supprimer le contenu par défaut
            success, stdout, stderr = self.execute_command_in_container(
                project_name, 'wordpress',
                ['wp', 'post', 'delete', '1', '--allow-root'],
                timeout=15
            )
            
            if success:
                print(f"✅ [AUTO-INSTALL] Contenu par défaut supprimé")
            
            print(f"✅ [AUTO-INSTALL] Configuration post-installation terminée")
            
        except Exception as e:
            print(f"⚠️ [AUTO-INSTALL] Erreur configuration post-installation: {e}")
    
    def fix_wordpress_permissions(self, project_name):
        """Corrige les permissions WordPress pour un projet avec nouvelle architecture"""
        try:
            wp_content_path = os.path.join(self.projects_folder, project_name, 'wp-content')
            wp_config_path = os.path.join(self.projects_folder, project_name, 'wp-config.php')
            
            if not os.path.exists(wp_content_path):
                print(f"⚠️ [DOCKER_SERVICE] Dossier wp-content non trouvé: {wp_content_path}")
                return False
            
            print(f"🔧 [DOCKER_SERVICE] Correction des permissions WordPress pour {project_name}")
            
            # Permissions pour wp-content
            result = subprocess.run([
                'sudo', 'chown', '-R', DockerConfig.WWW_USER, wp_content_path
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                print(f"❌ [DOCKER_SERVICE] Erreur chown wp-content: {result.stderr}")
                return False
            
            # Permissions des dossiers wp-content (755)
            result = subprocess.run([
                'sudo', 'find', wp_content_path, '-type', 'd', '-exec', 'chmod', '755', '{}', ';'
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                print(f"❌ [DOCKER_SERVICE] Erreur chmod dossiers wp-content: {result.stderr}")
                return False
            
            # Permissions des fichiers wp-content (644)
            result = subprocess.run([
                'sudo', 'find', wp_content_path, '-type', 'f', '-exec', 'chmod', '644', '{}', ';'
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode != 0:
                print(f"❌ [DOCKER_SERVICE] Erreur chmod fichiers wp-content: {result.stderr}")
                return False
            
            # Permissions pour wp-config.php s'il existe
            if os.path.exists(wp_config_path):
                result = subprocess.run([
                    'sudo', 'chown', DockerConfig.WWW_USER, wp_config_path
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode != 0:
                    print(f"❌ [DOCKER_SERVICE] Erreur chown wp-config: {result.stderr}")
                    return False
                
                result = subprocess.run([
                    'sudo', 'chmod', '600', wp_config_path
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode != 0:
                    print(f"❌ [DOCKER_SERVICE] Erreur chmod wp-config: {result.stderr}")
                    return False
            
            print(f"✅ [DOCKER_SERVICE] Permissions WordPress corrigées pour {project_name}")
            return True
            
        except Exception as e:
            print(f"❌ [DOCKER_SERVICE] Erreur lors de la correction des permissions: {e}")
            return False
    
    def fix_dev_permissions(self, project_name):
        """Applique les permissions de développement pour wp-config.php et wp-content avec nouvelle architecture"""
        try:
            wp_content_path = os.path.join(self.projects_folder, project_name, 'wp-content')
            wp_config_path = os.path.join(self.projects_folder, project_name, 'wp-config.php')
            
            print(f"🔧 [DOCKER_SERVICE] Application des permissions de développement pour {project_name}")
            
            # Permissions pour wp-config.php
            if os.path.exists(wp_config_path):
                result = subprocess.run([
                    'sudo', 'chown', DockerConfig.DEV_USER, wp_config_path
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode != 0:
                    print(f"❌ [DOCKER_SERVICE] Erreur chown wp-config: {result.stderr}")
                    return False
                
                result = subprocess.run([
                    'sudo', 'chmod', '644', wp_config_path
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode != 0:
                    print(f"❌ [DOCKER_SERVICE] Erreur chmod wp-config: {result.stderr}")
                    return False
                
                print(f"✅ [DOCKER_SERVICE] wp-config.php: dev-server:dev-server (644)")
            
            # Permissions pour wp-content
            if os.path.exists(wp_content_path):
                result = subprocess.run([
                    'sudo', 'chown', '-R', DockerConfig.DEV_USER, wp_content_path
                ], capture_output=True, text=True, timeout=60)
                
                if result.returncode != 0:
                    print(f"❌ [DOCKER_SERVICE] Erreur chown wp-content: {result.stderr}")
                    return False
                
                # Permissions des dossiers (755)
                result = subprocess.run([
                    'sudo', 'find', wp_content_path, '-type', 'd', '-exec', 'chmod', '755', '{}', ';'
                ], capture_output=True, text=True, timeout=60)
                
                if result.returncode != 0:
                    print(f"❌ [DOCKER_SERVICE] Erreur chmod dossiers wp-content: {result.stderr}")
                    return False
                
                # Permissions des fichiers (644)
                result = subprocess.run([
                    'sudo', 'find', wp_content_path, '-type', 'f', '-exec', 'chmod', '644', '{}', ';'
                ], capture_output=True, text=True, timeout=60)
                
                if result.returncode != 0:
                    print(f"❌ [DOCKER_SERVICE] Erreur chmod fichiers wp-content: {result.stderr}")
                    return False
                
                # Permissions spéciales pour uploads (775)
                uploads_path = os.path.join(wp_content_path, 'uploads')
                if os.path.exists(uploads_path):
                    result = subprocess.run([
                        'sudo', 'chmod', '775', uploads_path
                    ], capture_output=True, text=True, timeout=30)
                    
                    if result.returncode != 0:
                        print(f"❌ [DOCKER_SERVICE] Erreur chmod uploads: {result.stderr}")
                        return False
                    
                    result = subprocess.run([
                        'sudo', 'find', uploads_path, '-type', 'd', '-exec', 'chmod', '775', '{}', ';'
                    ], capture_output=True, text=True, timeout=60)
                    
                    if result.returncode != 0:
                        print(f"❌ [DOCKER_SERVICE] Erreur chmod dossiers uploads: {result.stderr}")
                        return False
                    
                    result = subprocess.run([
                        'sudo', 'find', uploads_path, '-type', 'f', '-exec', 'chmod', '664', '{}', ';'
                    ], capture_output=True, text=True, timeout=60)
                    
                    if result.returncode != 0:
                        print(f"❌ [DOCKER_SERVICE] Erreur chmod fichiers uploads: {result.stderr}")
                        return False
                
                print(f"✅ [DOCKER_SERVICE] wp-content: dev-server:dev-server (755/644)")
            
            print(f"✅ [DOCKER_SERVICE] Permissions de développement appliquées pour {project_name}")
            return True
            
        except Exception as e:
            print(f"❌ [DOCKER_SERVICE] Erreur lors de l'application des permissions dev: {e}")
            return False
    
    def _fix_wp_content_permissions(self, wp_content_dir):
        """Corriger les permissions du dossier wp-content"""
        try:
            import os
            import subprocess
            
            # Obtenir l'utilisateur et groupe actuels
            current_user = os.getenv('USER', 'dev-server')
            current_group = current_user  # Par défaut, même nom que l'utilisateur
            
            print(f"🔧 [DOCKER_SERVICE] Correction des permissions pour {current_user}:{current_group}")
            
            # Changer le propriétaire récursivement
            subprocess.run([
                'sudo', 'chown', '-R', f'{current_user}:{current_group}', wp_content_dir
            ], check=True)
            
            # S'assurer que le dossier uploads existe et a les bonnes permissions
            uploads_dir = os.path.join(wp_content_dir, 'uploads')
            if not os.path.exists(uploads_dir):
                os.makedirs(uploads_dir, mode=0o755, exist_ok=True)
                subprocess.run([
                    'sudo', 'chown', '-R', f'{current_user}:{current_group}', uploads_dir
                ], check=True)
            
            # Définir les permissions appropriées
            subprocess.run([
                'chmod', '-R', '755', wp_content_dir
            ], check=True)
            
            # Permissions spéciales pour uploads (écriture)
            subprocess.run([
                'chmod', '-R', '775', uploads_dir
            ], check=True)
            
            print(f"✅ [DOCKER_SERVICE] Permissions corrigées pour wp-content")
            
        except subprocess.CalledProcessError as e:
            print(f"⚠️ [DOCKER_SERVICE] Erreur lors de la correction des permissions: {e}")
        except Exception as e:
            print(f"⚠️ [DOCKER_SERVICE] Erreur inattendue lors de la correction des permissions: {e}")
    
    def restart_service(self, project_name, service_name, timeout=60):
        """Redémarre un service spécifique d'un projet"""
        try:
            container_path = os.path.join(self.containers_folder, project_name)
            
            if not os.path.exists(container_path):
                wp_logger.log_docker_operation('restart', project_name, False, 
                                             "",
                                             f"Dossier conteneur non trouvé: {container_path}")
                return False, f"Dossier conteneur non trouvé: {container_path}"
            
            original_cwd = os.getcwd()
            try:
                os.chdir(container_path)
                
                wp_logger.log_docker_operation('restart', project_name, True, 
                                             f"Redémarrage service {service_name}",
                                             "",
                                             container_path=container_path,
                                             service=service_name)
                
                result = subprocess.run([
                    'docker-compose', 'restart', service_name
                ], capture_output=True, text=True, timeout=timeout)
                
                success = result.returncode == 0
                
                if success:
                    wp_logger.log_docker_operation('restart', project_name, True, 
                                                 f"Service {service_name} redémarré avec succès",
                                                 "",
                                                 container_path=container_path,
                                                 service=service_name)
                    print(f"✅ [DOCKER_SERVICE] Service {service_name} redémarré pour {project_name}")
                else:
                    wp_logger.log_docker_operation('restart', project_name, False, 
                                                 "",
                                                 result.stderr,
                                                 container_path=container_path,
                                                 service=service_name)
                    print(f"❌ [DOCKER_SERVICE] Erreur redémarrage {service_name} pour {project_name}: {result.stderr}")
                
                return success, result.stderr if result.returncode != 0 else None
                
            finally:
                os.chdir(original_cwd)
                
        except subprocess.TimeoutExpired:
            wp_logger.log_docker_operation('restart', project_name, False, 
                                         "",
                                         f"Timeout redémarrage service {service_name}",
                                         container_path=container_path,
                                         service=service_name)
            return False, f"Timeout lors du redémarrage du service {service_name}"
        except Exception as e:
            wp_logger.log_docker_operation('restart', project_name, False, 
                                         "",
                                         str(e),
                                         container_path=container_path,
                                         service=service_name)
            return False, str(e)
    
    def restart_php_services(self, project_name, timeout=120):
        """Redémarre les services utilisant PHP (WordPress et phpMyAdmin)"""
        try:
            print(f"🔄 [DOCKER_SERVICE] Redémarrage services PHP pour {project_name}")
            
            # Redémarrer WordPress
            success1, error1 = self.restart_service(project_name, 'wordpress', timeout//2)
            
            # Redémarrer phpMyAdmin
            success2, error2 = self.restart_service(project_name, 'phpmyadmin', timeout//2)
            
            overall_success = success1 and success2
            errors = []
            if error1:
                errors.append(f"WordPress: {error1}")
            if error2:
                errors.append(f"phpMyAdmin: {error2}")
            
            if overall_success:
                print(f"✅ [DOCKER_SERVICE] Services PHP redémarrés avec succès pour {project_name}")
            else:
                print(f"⚠️ [DOCKER_SERVICE] Redémarrage partiel des services PHP pour {project_name}")
            
            return overall_success, "; ".join(errors) if errors else None
            
        except Exception as e:
            print(f"❌ [DOCKER_SERVICE] Erreur redémarrage services PHP pour {project_name}: {e}")
            return False, str(e)
    
    def restart_mysql_service(self, project_name, timeout=45):
        """Redémarre le service MySQL"""
        try:
            print(f"🔄 [DOCKER_SERVICE] Redémarrage service MySQL pour {project_name}")
            
            success, error = self.restart_service(project_name, 'mysql', timeout)
            
            if success:
                print(f"✅ [DOCKER_SERVICE] Service MySQL redémarré avec succès pour {project_name}")
                
                # Attendre que MySQL soit prêt après redémarrage (temps réduit pour config changes)
                print(f"⏳ [DOCKER_SERVICE] Attente que MySQL soit prêt...")
                if self.wait_for_mysql(project_name, max_wait_time=30):
                    print(f"✅ [DOCKER_SERVICE] MySQL prêt après redémarrage")
                else:
                    print(f"⚠️ [DOCKER_SERVICE] MySQL lent à redémarrer, mais le service est lancé")
            else:
                print(f"❌ [DOCKER_SERVICE] Erreur redémarrage MySQL pour {project_name}: {error}")
            
            return success, error
            
        except Exception as e:
            print(f"❌ [DOCKER_SERVICE] Erreur redémarrage service MySQL pour {project_name}: {e}")
            return False, str(e)
    
    def rebuild_wordpress_container(self, project_name, timeout=300):
        """Rebuild le conteneur WordPress avec une nouvelle version PHP"""
        try:
            print(f"🔄 [DOCKER_SERVICE] Rebuild conteneur WordPress pour {project_name}")
            
            container_path = os.path.join(self.containers_folder, project_name)
            
            if not os.path.exists(container_path):
                return False, f"Dossier conteneur non trouvé: {container_path}"
            
            # Lire la version PHP depuis le fichier .php_version
            version_file = os.path.join(container_path, '.php_version')
            php_version = '8.2'  # Version par défaut
            if os.path.exists(version_file):
                with open(version_file, 'r') as f:
                    php_version = f.read().strip()
            
            print(f"📦 [DOCKER_SERVICE] Version PHP: {php_version}")
            
            # Modifier le docker-compose.yml pour utiliser la bonne image
            docker_compose_path = os.path.join(container_path, 'docker-compose.yml')
            if os.path.exists(docker_compose_path):
                import re
                with open(docker_compose_path, 'r') as f:
                    content = f.read()
                
                # Remplacer l'image WordPress
                content = re.sub(
                    r'image:\s*wp-launcher-wordpress:[^\s]+',
                    f'image: wp-launcher-wordpress:php{php_version}',
                    content
                )
                
                with open(docker_compose_path, 'w') as f:
                    f.write(content)
                
                print(f"✅ [DOCKER_SERVICE] Image mise à jour vers wp-launcher-wordpress:php{php_version}")
            
            original_cwd = os.getcwd()
            try:
                os.chdir(container_path)
                
                # Faire un down complet pour éviter les erreurs ContainerConfig
                print(f"🛑 [DOCKER_SERVICE] Arrêt complet des conteneurs...")
                subprocess.run([
                    'docker-compose', 'down'
                ], capture_output=True, text=True, timeout=60)
                
                # Attendre un peu que Docker libère les ressources
                time.sleep(2)
                
                # Recréer tous les conteneurs avec la nouvelle image WordPress
                print(f"🚀 [DOCKER_SERVICE] Création des conteneurs avec PHP {php_version}...")
                result = subprocess.run([
                    'docker-compose', 'up', '-d'
                ], capture_output=True, text=True, timeout=timeout)
                
                if result.returncode == 0:
                    print(f"✅ [DOCKER_SERVICE] Conteneurs recréés avec PHP {php_version}")
                    
                    # Attendre que les conteneurs soient prêts
                    time.sleep(5)
                    
                    # Corriger les permissions après rebuild
                    self.fix_dev_permissions(project_name)
                    
                    wp_logger.log_docker_operation('rebuild', project_name, True,
                                                 f"Conteneurs recréés avec PHP {php_version}",
                                                 "",
                                                 container_path=container_path)
                    return True, None
                else:
                    # Vérifier si c'est une erreur ContainerConfig
                    if 'ContainerConfig' in result.stderr:
                        print(f"⚠️ [DOCKER_SERVICE] Erreur ContainerConfig détectée, nouvelle tentative...")
                        wp_logger.log_docker_operation('rebuild', project_name, False,
                                                     "",
                                                     "Erreur ContainerConfig, nouvelle tentative",
                                                     container_path=container_path)
                        
                        # Forcer un down avec suppression des volumes orphelins
                        subprocess.run([
                            'docker-compose', 'down', '--remove-orphans'
                        ], capture_output=True, text=True, timeout=60)
                        
                        time.sleep(3)
                        
                        # Réessayer
                        result = subprocess.run([
                            'docker-compose', 'up', '-d'
                        ], capture_output=True, text=True, timeout=timeout)
                        
                        if result.returncode == 0:
                            print(f"✅ [DOCKER_SERVICE] Conteneurs recréés avec succès après correction")
                            time.sleep(5)
                            self.fix_dev_permissions(project_name)
                            wp_logger.log_docker_operation('rebuild', project_name, True,
                                                         f"Conteneurs recréés avec PHP {php_version} après correction",
                                                         "",
                                                         container_path=container_path)
                            return True, None
                    
                    print(f"❌ [DOCKER_SERVICE] Erreur lors du rebuild: {result.stderr}")
                    wp_logger.log_docker_operation('rebuild', project_name, False,
                                                 "",
                                                 result.stderr,
                                                 container_path=container_path)
                    return False, result.stderr
                    
            finally:
                os.chdir(original_cwd)
                
        except subprocess.TimeoutExpired:
            print(f"❌ [DOCKER_SERVICE] Timeout lors du rebuild")
            return False, "Timeout lors du rebuild du conteneur"
        except Exception as e:
            print(f"❌ [DOCKER_SERVICE] Erreur rebuild conteneur: {e}")
            return False, str(e)

    def start_containers_with_auto_install(self, container_path, project_name, timeout=300):
        """Démarre les conteneurs et attend l'auto-installation complète"""
        try:
            # Étape 1: Démarrer les conteneurs
            success, error = self.start_containers(container_path, timeout=120)
            if not success:
                return False, error
            
            # Étape 2: Attendre que MySQL soit complètement prêt
            if not self.wait_for_mysql_with_custom_entrypoint(project_name, max_wait_time=180):
                return False, "MySQL non disponible"
            
            # Étape 3: Attendre l'auto-installation WordPress
            if not self.wait_for_wordpress_auto_install(project_name, max_wait_time=300):
                return False, "Auto-installation WordPress échouée"
            
            # Étape 4: Corriger les permissions automatiquement
            self.fix_dev_permissions(project_name)
            
            return True, None
            
        except Exception as e:
            return False, str(e)

    def wait_for_mysql_with_custom_entrypoint(self, project_name, max_wait_time=180):
        """Attente spécialisée pour MySQL avec entrypoint personnalisé"""
        try:
            wait_time = 0
            check_interval = 3
            
            # Phase 1: Attendre que le conteneur MySQL soit en "running"
            while wait_time < 60:
                mysql_container = f"{project_name}_mysql_1"
                status = self.get_individual_container_status(mysql_container)
                
                if status in ['active', 'running']:
                    break
                    
                time.sleep(check_interval)
                wait_time += check_interval
            else:
                return False
            
            # Phase 2: Attendre que le healthcheck MySQL soit OK
            health_wait = 0
            while health_wait < 90:
                success, stdout, stderr = self.execute_command([
                    'docker', 'inspect', '--format={{.State.Health.Status}}', 
                    f"{project_name}_mysql_1"
                ], timeout=10)
                
                if success and 'healthy' in stdout.lower():
                    break
                    
                time.sleep(3)
                health_wait += 3
            
            # Phase 3: Vérifier que WordPress peut se connecter à MySQL
            connectivity_wait = 0
            while connectivity_wait < 60:
                success, stdout, stderr = self.execute_command_in_container(
                    project_name, 'wordpress',
                    ['wp', 'db', 'check', '--allow-root'],
                    timeout=10
                )
                
                if success:
                    return True
                    
                time.sleep(5)
                connectivity_wait += 5
            
            return False
            
        except Exception as e:
            return False

    def wait_for_wordpress_auto_install(self, project_name, max_wait_time=300):
        """Attendre que l'auto-installation WordPress soit terminée"""
        try:
            wait_time = 0
            check_interval = 10
            
            while wait_time < max_wait_time:
                # Vérifier si WordPress est installé
                success, stdout, stderr = self.execute_command_in_container(
                    project_name, 'wordpress',
                    ['wp', 'core', 'is-installed', '--allow-root'],
                    timeout=15
                )
                
                if success:
                    # Vérifier que l'admin exists
                    success, stdout, stderr = self.execute_command_in_container(
                        project_name, 'wordpress',
                        ['wp', 'user', 'get', DockerConfig.WP_ADMIN_USER, '--allow-root'],
                        timeout=10
                    )

                    return True
                
                time.sleep(check_interval)
                wait_time += check_interval
            
            return False
            
        except Exception as e:
            return False

    def auto_install_wordpress_after_creation(self, project_name, container_path, wait_timeout=180, debug_logger=None):
        """Installation automatique WordPress - Version simplifiée qui fait confiance à l'entrypoint"""
        try:
            if debug_logger:
                debug_logger.step("AUTO_INSTALL_WP", f"Starting simplified auto-installation for {project_name}")
            
            print(f"🚀 [AUTO-INSTALL] Installation automatique WordPress pour {project_name}")
            print(f"📋 [AUTO-INSTALL] Méthode simplifiée - Délégation à l'entrypoint")
            
            # Étape 1: Vérifier que les conteneurs sont démarrés
            max_container_wait = 10
            for attempt in range(max_container_wait):
                mysql_status = self.get_individual_container_status(f"{project_name}_mysql_1")
                wordpress_status = self.get_individual_container_status(f"{project_name}_wordpress_1")
                
                if mysql_status in ['active', 'running'] and wordpress_status in ['active', 'running']:
                    print(f"✅ [AUTO-INSTALL] Conteneurs actifs après {attempt + 1} tentatives")
                    break
                
                print(f"⏳ [AUTO-INSTALL] Attente conteneurs... ({attempt + 1}/{max_container_wait})")
                import time
                time.sleep(2)
            else:
                print(f"❌ [AUTO-INSTALL] Conteneurs non prêts après {max_container_wait * 2}s")
                return False
            
            # Étape 2: Attendre que l'entrypoint termine son travail (installation automatique)
            print(f"⏳ [AUTO-INSTALL] Attente de l'entrypoint personnalisé (15 secondes)...")
            import time
            time.sleep(3)  # Laisser le temps à l'entrypoint de faire son travail
            
            # Étape 3: Vérifier que WP-CLI est disponible
            print(f"🔍 [AUTO-INSTALL] Vérification WP-CLI...")
            for attempt in range(5):
                success, stdout, stderr = self.execute_command_in_container(
                    project_name, 'wordpress',
                    ['wp', '--info', '--allow-root'],
                    timeout=5
                )
                
                if success and 'WP-CLI' in stdout:
                    print(f"✅ [AUTO-INSTALL] WP-CLI disponible")
                    break
                
                print(f"⏳ [AUTO-INSTALL] WP-CLI s'initialise... ({attempt + 1}/5)")
                time.sleep(3)
            else:
                print(f"⚠️ [AUTO-INSTALL] WP-CLI non disponible, mais continuons...")
            
            # Étape 4: Vérifier si WordPress est installé par l'entrypoint
            print(f"🔍 [AUTO-INSTALL] Vérification état WordPress...")
            success, stdout, stderr = self.execute_command_in_container(
                project_name, 'wordpress',
                ['wp', 'core', 'is-installed', '--allow-root'],
                timeout=10
            )
            
            project_port = self._get_project_port(project_name)
            site_url = f"http://{DockerConfig.LOCAL_IP}:{project_port}"
            
            # Installer WordPress
            print(f"🚀 [AUTO-INSTALL] Installation WordPress...")
            install_cmd = ['wp', 'core', 'install',
                          f'--url={site_url}',
                          f'--title={project_name}',
                          f'--admin_user={DockerConfig.WP_ADMIN_USER}',
                          f'--admin_password={DockerConfig.WP_ADMIN_PASSWORD}',
                          f'--admin_email={DockerConfig.WP_ADMIN_EMAIL}',
                          '--allow-root']
            
            success, stdout, stderr = self.execute_command_in_container(
                project_name, 'wordpress',
                install_cmd,
                timeout=30
            )
            
            if success:
                print(f"✅ [AUTO-INSTALL] WordPress installé manuellement!")
                print(f"🔗 [AUTO-INSTALL] Site: {site_url}")
                print(f"👤 [AUTO-INSTALL] Admin: {DockerConfig.WP_ADMIN_USER} / {DockerConfig.WP_ADMIN_PASSWORD}")
                
                if debug_logger:
                    debug_logger.success("AUTO_INSTALL_WP", f"WordPress manually installed: {site_url}")
                
                return True
            else:
                print(f"❌ [AUTO-INSTALL] Échec installation: {stderr}")
                if debug_logger:
                    debug_logger.error("AUTO_INSTALL_WP", f"Manual installation failed: {stderr}")
                return False
                
        except Exception as e:
            print(f"❌ [AUTO-INSTALL] Exception: {e}")
            if debug_logger:
                debug_logger.error("AUTO_INSTALL_WP", f"Exception: {e}")
            return False

    def create_wordpress_project(self, container_path, project_path, project_name, ports=None):
        """Crée un projet WordPress simple (sans Next.js)"""
        try:
            # Créer la structure de base
            result = self.create_project_structure(container_path, project_path, enable_nextjs=False)
            
            if not result:
                return False
            
            # Configurer les ports dans le fichier docker-compose.yml si fournis
            if ports:
                self.configure_compose_file(container_path, project_name, ports, enable_nextjs=False)
            
            # Remplacer le wp-content de base par le wp-content de référence
            self.setup_reference_wp_content(project_path)
                
            # Ajouter le fichier .project_type pour identifier le type de projet
            project_type_file = os.path.join(project_path, '.project_type')
            with open(project_type_file, 'w') as f:
                f.write('wordpress')
            
            # Créer les fichiers de base WordPress (.htaccess et wp-config.php)
            try:
                from app.utils.project_utils import create_wordpress_base_files
                create_wordpress_base_files(project_path)
            except ImportError:
                pass
            
            # Mettre à jour les URLs dans wp-config.php si des ports sont fournis
            if ports:
                try:
                    from app.utils.project_utils import update_project_wordpress_urls_in_files
                    update_project_wordpress_urls_in_files(project_path, ports['wordpress'])
                except ImportError:
                    pass
            
            # Utiliser la nouvelle méthode qui comprend l'auto-installation par entrypoint
            success, error = self.start_containers_with_auto_install(container_path, project_name)
            
            return True
            
        except Exception as e:
            return False
    
    def rebuild_containers(self, container_path, timeout=180):
        """Rebuild tous les conteneurs en préservant les volumes (équivalent à docker-compose down + up -d --force-recreate)"""
        project_name = os.path.basename(container_path)
        wp_logger.log_system_info(f"Rebuild conteneurs pour {project_name}", 
                                 container_path=container_path,
                                 operation="docker_rebuild")
        
        original_cwd = os.getcwd()
        try:
            print(f"🔄 [DOCKER_SERVICE] Rebuild complet des conteneurs pour {project_name}")
            
            os.chdir(container_path)
            
            # Étape 1: Arrêter et supprimer les conteneurs (sans supprimer les volumes)
            print(f"🛑 [DOCKER_SERVICE] Arrêt et suppression des conteneurs...")
            down_result = subprocess.run([
                'docker-compose', 'down'
            ], capture_output=True, text=True, timeout=60)
            
            if down_result.returncode != 0:
                print(f"⚠️ [DOCKER_SERVICE] Avertissement lors du down: {down_result.stderr}")
            else:
                print(f"✅ [DOCKER_SERVICE] Conteneurs arrêtés et supprimés")
            
            # Attendre que Docker libère les ressources
            time.sleep(2)
            
            # Étape 2: Recréer les conteneurs avec --force-recreate
            print(f"🚀 [DOCKER_SERVICE] Recréation des conteneurs avec --force-recreate...")
            up_result = subprocess.run([
                'docker-compose', 'up', '-d', '--force-recreate'
            ], capture_output=True, text=True, timeout=timeout)
            
            success = up_result.returncode == 0
            
            if success:
                print(f"✅ [DOCKER_SERVICE] Conteneurs recréés avec succès")
                
                # Attendre que les conteneurs se stabilisent
                time.sleep(3)
                
                # Corriger automatiquement les permissions
                print(f"🔧 [DOCKER_SERVICE] Correction automatique des permissions...")
                if self.fix_dev_permissions(project_name):
                    print(f"✅ [DOCKER_SERVICE] Permissions corrigées")
                
                wp_logger.log_docker_operation('rebuild', project_name, True, 
                                             up_result.stdout,
                                             "",
                                             container_path=container_path,
                                             details="Conteneurs recréés avec succès (volumes préservés)")
            else:
                print(f"❌ [DOCKER_SERVICE] Erreur lors du rebuild: {up_result.stderr}")
                wp_logger.log_docker_operation('rebuild', project_name, False, 
                                             "",
                                             up_result.stderr,
                                             container_path=container_path,
                                             details="Échec rebuild conteneurs")
            
            return success, up_result.stderr if up_result.returncode != 0 else None
            
        except subprocess.TimeoutExpired:
            wp_logger.log_docker_operation('rebuild', project_name, False, 
                                         "",
                                         "Timeout rebuild conteneurs",
                                         container_path=container_path)
            return False, "Timeout lors du rebuild des conteneurs"
        except Exception as e:
            wp_logger.log_docker_operation('rebuild', project_name, False, 
                                         "",
                                         str(e),
                                         container_path=container_path,
                                         details="Exception rebuild conteneurs")
            return False, str(e)
        finally:
            os.chdir(original_cwd)
    
    def get_individual_container_status(self, container_name):
        """Get status of a specific container (running/stopped)"""
        try:
            result = subprocess.run(
                ['docker', 'ps', '-a', '--filter', f'name=^{container_name}$', '--format', '{{.Status}}'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout.strip():
                status_text = result.stdout.strip().lower()
                return 'running' if 'up' in status_text else 'stopped'
            
            return 'stopped'  # Container doesn't exist or is stopped
        except Exception as e:
            wp_logger.log_system_info(f"Error checking container status: {e}")
            return 'stopped'
 