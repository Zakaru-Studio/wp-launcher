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
    
    def __init__(self, template_path='docker-template'):
        self.template_path = template_path
    
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
    
    def configure_compose_file(self, project_path, project_name, ports, enable_nextjs=False):
        """Configure le fichier docker-compose.yml avec les bons paramètres"""
        compose_file = os.path.join(project_path, 'docker-compose.yml')
        
        if not os.path.exists(compose_file):
            raise Exception("Fichier docker-compose.yml manquant")
        
        with open(compose_file, 'r') as f:
            content = f.read()
        
        # Remplacer les placeholders
        content = content.replace('PROJECT_NAME', project_name)
        content = content.replace('PROJECT_PORT', str(ports['wordpress']))
        content = content.replace('PROJECT_PMA_PORT', str(ports['phpmyadmin']))
        content = content.replace('PROJECT_MAILPIT_PORT', str(ports['mailpit']))
        content = content.replace('PROJECT_SMTP_PORT', str(ports['smtp']))
        
        if enable_nextjs and 'nextjs' in ports:
            content = content.replace('PROJECT_NEXTJS_PORT', str(ports['nextjs']))
        
        with open(compose_file, 'w') as f:
            f.write(content)
    
    def configure_wp_config(self, project_path, ports):
        """Configure le fichier wp-config.php avec les bons paramètres"""
        wp_config_file = os.path.join(project_path, 'wordpress', 'wp-config.php')
        
        if not os.path.exists(wp_config_file):
            # Le fichier wp-config.php sera créé par WordPress automatiquement
            return
        
        with open(wp_config_file, 'r') as f:
            content = f.read()
        
        # Remplacer les placeholders
        content = content.replace('PROJECT_PORT', str(ports['wordpress']))
        
        with open(wp_config_file, 'w') as f:
            f.write(content)
    
    def start_containers(self, project_path, timeout=120):
        """Démarre les conteneurs d'un projet"""
        original_cwd = os.getcwd()
        try:
            os.chdir(project_path)
            result = subprocess.run([
                'docker-compose', 'up', '-d'
            ], capture_output=True, text=True, timeout=timeout)
            
            return result.returncode == 0, result.stderr if result.returncode != 0 else None
        except subprocess.TimeoutExpired:
            return False, "Timeout lors du démarrage des conteneurs"
        except Exception as e:
            return False, str(e)
        finally:
            os.chdir(original_cwd)
    
    def stop_containers(self, project_path, timeout=60):
        """Arrête les conteneurs d'un projet"""
        original_cwd = os.getcwd()
        try:
            os.chdir(project_path)
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
    
    def remove_containers(self, project_path, timeout=60):
        """Supprime complètement les conteneurs d'un projet"""
        original_cwd = os.getcwd()
        try:
            os.chdir(project_path)
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
    
    def execute_command_in_container(self, project_name, service_name, command, timeout=30):
        """Exécute une commande dans un conteneur"""
        try:
            container_name = f"{project_name}_{service_name}_1"
            
            # Construire la commande docker exec
            docker_cmd = ['docker', 'exec', container_name] + command
            
            result = subprocess.run(
                docker_cmd, 
                capture_output=True, 
                text=True, 
                timeout=timeout
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