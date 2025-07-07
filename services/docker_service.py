#!/usr/bin/env python3
"""
Service de gestion Docker
"""

import os
import shutil
import subprocess
import time

class DockerService:
    """Service pour la gestion des conteneurs Docker"""
    
    def __init__(self, template_path='docker-template', projects_folder='projets', containers_folder='containers'):
        self.template_path = template_path
        self.projects_folder = projects_folder
        self.containers_folder = containers_folder
    
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
        
        # Remplacer les placeholders
        content = content.replace('PROJECT_NAME', project_name)
        content = content.replace('{project_name}', project_name)
        content = content.replace('PROJECT_PORT', str(ports['wordpress']))
        content = content.replace('PROJECT_PMA_PORT', str(ports['phpmyadmin']))
        content = content.replace('PROJECT_MAILPIT_PORT', str(ports['mailpit']))
        content = content.replace('PROJECT_SMTP_PORT', str(ports['smtp']))
        
        if enable_nextjs and 'nextjs' in ports:
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
    
    def start_containers(self, container_path, timeout=120):
        """Démarre les conteneurs d'un projet depuis containers/"""
        original_cwd = os.getcwd()
        try:
            os.chdir(container_path)
            result = subprocess.run([
                'docker-compose', 'up', '-d'
            ], capture_output=True, text=True, timeout=timeout)
            
            success = result.returncode == 0
            
            # Si le démarrage a réussi, corriger automatiquement les permissions
            if success:
                # Extraire le nom du projet depuis le chemin
                project_name = os.path.basename(container_path)
                print(f"🔧 [DOCKER_SERVICE] Correction automatique des permissions après démarrage pour {project_name}")
                
                # Attendre 3 secondes que les conteneurs se stabilisent
                import time
                time.sleep(3)
                
                # Corriger les permissions pour dev-server
                if self.fix_dev_permissions(project_name):
                    print(f"✅ [DOCKER_SERVICE] Permissions automatiquement corrigées pour {project_name}")
                else:
                    print(f"⚠️ [DOCKER_SERVICE] Impossible de corriger automatiquement les permissions pour {project_name}")
            
            return success, result.stderr if result.returncode != 0 else None
        except subprocess.TimeoutExpired:
            return False, "Timeout lors du démarrage des conteneurs"
        except Exception as e:
            return False, str(e)
        finally:
            os.chdir(original_cwd)
    
    def stop_containers(self, container_path, timeout=60):
        """Arrête les conteneurs d'un projet depuis containers/"""
        original_cwd = os.getcwd()
        try:
            os.chdir(container_path)
            result = subprocess.run([
                'docker-compose', 'stop'
            ], capture_output=True, text=True, timeout=timeout)
            
            return result.returncode == 0, result.stderr if result.returncode != 0 else None
        except subprocess.TimeoutExpired:
            return False, "Timeout lors de l'arrêt des conteneurs"
        except Exception as e:
            return False, str(e)
        finally:
            os.chdir(original_cwd)
    
    def remove_containers(self, container_path, timeout=60):
        """Supprime complètement les conteneurs d'un projet depuis containers/"""
        original_cwd = os.getcwd()
        try:
            os.chdir(container_path)
            # Arrêter et supprimer
            result = subprocess.run([
                'docker-compose', 'down', '-v'
            ], capture_output=True, text=True, timeout=timeout)
            
            return result.returncode == 0, result.stderr if result.returncode != 0 else None
        except subprocess.TimeoutExpired:
            return False, "Timeout lors de la suppression des conteneurs"
        except Exception as e:
            return False, str(e)
        finally:
            os.chdir(original_cwd)
    
    def get_container_status(self, project_name):
        """Vérifie le statut des conteneurs d'un projet"""
        try:
            mysql_container = f"{project_name}_mysql_1"
            wp_container = f"{project_name}_wordpress_1"
            
            # Vérifier si les conteneurs sont en cours d'exécution
            result = subprocess.run([
                'docker', 'ps', '--format', '{{.Names}}'
            ], capture_output=True, text=True)
            
            running_containers = result.stdout.strip().split('\n')
            
            if mysql_container in running_containers and wp_container in running_containers:
                return 'active'
            else:
                return 'inactive'
        except Exception:
            return 'inactive'
    
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
        """Vérifie si MySQL est prêt dans un conteneur"""
        success, stdout, stderr = self.execute_command_in_container(
            project_name, 
            'mysql', 
            ['mysql', '-u', 'wordpress', '-pwordpress', '-e', 'SELECT 1'],
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
                
                if self.check_mysql_ready(project_name, timeout=3):
                    print(f"✅ MySQL prêt après {elapsed:.1f}s ({total_attempts} tentatives)")
                    return True
                
                time.sleep(interval)
        
        print(f"❌ MySQL non disponible après {max_wait_time}s d'attente")
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
        os.makedirs(wp_content_dir, exist_ok=True)
        os.makedirs(os.path.join(wp_content_dir, 'themes'), exist_ok=True)
        os.makedirs(os.path.join(wp_content_dir, 'plugins'), exist_ok=True)
        os.makedirs(os.path.join(wp_content_dir, 'uploads'), exist_ok=True)
        
        print("✅ [DOCKER_SERVICE] Structure de projet avec architecture séparée créée")
        return True
        
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
                'sudo', 'chown', '-R', 'www-data:www-data', wp_content_path
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
                    'sudo', 'chown', 'www-data:www-data', wp_config_path
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
                    'sudo', 'chown', 'dev-server:dev-server', wp_config_path
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
                    'sudo', 'chown', '-R', 'dev-server:dev-server', wp_content_path
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
    
    def register_hostname(self, project_name, hostname, port):
        """Enregistre un hostname dans le DNS local et reverse proxy"""
        try:
            # Appeler le script d'intégration Python
            result = subprocess.run([
                'python3', 'integrate_hostname_automation.py', 
                'add', project_name, hostname, str(port)
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print(f"✅ [DOCKER_SERVICE] Hostname {hostname} enregistré")
                return True
            else:
                print(f"⚠️ [DOCKER_SERVICE] Erreur lors de l'enregistrement hostname: {result.stderr}")
                return False
        except Exception as e:
            print(f"⚠️ [DOCKER_SERVICE] Erreur hostname: {e}")
            return False
    
    def unregister_hostname(self, project_name, hostname):
        """Désenregistre un hostname du DNS local et reverse proxy"""
        try:
            # Appeler le script d'intégration Python
            result = subprocess.run([
                'python3', 'integrate_hostname_automation.py', 
                'remove', project_name, hostname
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print(f"✅ [DOCKER_SERVICE] Hostname {hostname} désenregistré")
                return True
            else:
                print(f"⚠️ [DOCKER_SERVICE] Erreur lors du désenregistrement hostname: {result.stderr}")
                return False
        except Exception as e:
            print(f"⚠️ [DOCKER_SERVICE] Erreur hostname: {e}")
            return False
    
    def sync_all_hostnames(self):
        """Synchronise tous les hostnames avec le DNS local et reverse proxy"""
        try:
            result = subprocess.run([
                'python3', 'integrate_hostname_automation.py', 
                'sync'
            ], capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                print("✅ [DOCKER_SERVICE] Synchronisation hostnames terminée")
                return True
            else:
                print(f"⚠️ [DOCKER_SERVICE] Erreur lors de la synchronisation: {result.stderr}")
                return False
        except Exception as e:
            print(f"⚠️ [DOCKER_SERVICE] Erreur synchronisation: {e}")
            return False 