#!/usr/bin/env python3
"""
Utilitaires communs factorisant le code dupliqué
"""

import os
import subprocess
import time
from app.config.docker_config import DockerConfig

class DockerUtils:
    """Utilitaires pour les opérations Docker communes"""
    
    @staticmethod
    def get_container_name(project_name, service):
        """Génère le nom d'un conteneur selon la convention Docker Compose"""
        return f"{project_name}_{service}_1"
    
    @staticmethod
    def is_container_running(container_name):
        """Vérifie si un conteneur est en cours d'exécution"""
        try:
            result = subprocess.run([
                'docker', 'ps', '--format', '{{.Names}}'
            ], capture_output=True, text=True)
            
            running_containers = result.stdout.strip().split('\n')
            return container_name in running_containers
            
        except Exception:
            return False
    
    @staticmethod
    def execute_in_container(container_name, command, timeout=30, input_data=None):
        """Exécute une commande dans un conteneur Docker"""
        try:
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
            
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }
            
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'stdout': '',
                'stderr': 'Timeout lors de l\'exécution de la commande',
                'returncode': -1
            }
        except Exception as e:
            return {
                'success': False,
                'stdout': '',
                'stderr': str(e),
                'returncode': -1
            }

class FileUtils:
    """Utilitaires pour les opérations sur les fichiers"""
    
    @staticmethod
    def ensure_directory(path, permissions=None):
        """Crée un dossier s'il n'existe pas avec les bonnes permissions"""
        os.makedirs(path, exist_ok=True)
        
        if permissions:
            try:
                os.chmod(path, permissions)
            except Exception:
                pass  # Permissions non critiques
    
    @staticmethod
    def safe_read_file(file_path, encodings=None):
        """Lit un fichier en essayant plusieurs encodages"""
        if encodings is None:
            encodings = ['utf-8', 'latin-1', 'windows-1252', 'iso-8859-1']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    return f.read(), encoding
            except UnicodeDecodeError:
                continue
        
        raise Exception(f"Impossible de lire le fichier {file_path} avec les encodages: {encodings}")
    
    @staticmethod
    def write_port_file(container_path, service, port):
        """Écrit un port dans le fichier approprié"""
        # Mapping direct des services vers leurs fichiers de ports
        port_files = {
            'wordpress': '.port',
            'phpmyadmin': '.pma_port', 
            'mailpit': '.mailpit_port',
            'smtp': '.smtp_port',
            'nextjs': '.nextjs_port',
            'mongodb': '.mongodb_port',
            'mongo_express': '.mongo_express_port'
        }
        
        if service in port_files:
            FileUtils.ensure_directory(container_path)
            port_file_path = os.path.join(container_path, port_files[service])
            with open(port_file_path, 'w') as f:
                f.write(str(port))
            return True
        return False
    
    @staticmethod
    def read_port_file(container_path, service):
        """Lit un port depuis le fichier approprié"""
        # Mapping direct des services vers leurs fichiers de ports
        port_files = {
            'wordpress': '.port',
            'phpmyadmin': '.pma_port',
            'mailpit': '.mailpit_port', 
            'smtp': '.smtp_port',
            'nextjs': '.nextjs_port',
            'mongodb': '.mongodb_port',
            'mongo_express': '.mongo_express_port'
        }
        
        if service in port_files:
            port_file_path = os.path.join(container_path, port_files[service])
            if os.path.exists(port_file_path):
                try:
                    with open(port_file_path, 'r') as f:
                        return int(f.read().strip())
                except (ValueError, IOError):
                    pass
        return None

class PermissionUtils:
    """Utilitaires pour la gestion des permissions"""
    
    @staticmethod
    def apply_permissions(path, user, file_mode=None, dir_mode=None, recursive=False):
        """Applique des permissions de manière unifiée"""
        if not os.path.exists(path):
            return False
        
        try:
            # Changer le propriétaire
            chown_cmd = ['sudo', 'chown']
            if recursive:
                chown_cmd.append('-R')
            chown_cmd.extend([user, path])
            
            result = subprocess.run(chown_cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                print(f"❌ Erreur chown: {result.stderr}")
                return False
            
            # Appliquer les permissions sur les dossiers
            if dir_mode and os.path.isdir(path):
                if recursive:
                    subprocess.run([
                        'sudo', 'find', path, '-type', 'd', '-exec', 'chmod', str(oct(dir_mode)[2:]), '{}', ';'
                    ], capture_output=True, text=True, timeout=60)
                else:
                    subprocess.run(['sudo', 'chmod', str(oct(dir_mode)[2:]), path], 
                                 capture_output=True, text=True, timeout=30)
            
            # Appliquer les permissions sur les fichiers
            if file_mode and recursive:
                subprocess.run([
                    'sudo', 'find', path, '-type', 'f', '-exec', 'chmod', str(oct(file_mode)[2:]), '{}', ';'
                ], capture_output=True, text=True, timeout=60)
            elif file_mode and os.path.isfile(path):
                subprocess.run(['sudo', 'chmod', str(oct(file_mode)[2:]), path], 
                             capture_output=True, text=True, timeout=30)
            
            return True
            
        except Exception as e:
            print(f"❌ Erreur lors de l'application des permissions: {e}")
            return False
    
    @staticmethod
    def apply_wordpress_permissions(project_name, user_type='www'):
        """Applique les permissions WordPress selon le type d'utilisateur"""
        from app.config.docker_config import DockerConfig
        
        wp_content_path = os.path.join(DockerConfig.get_project_path(project_name), 'wp-content')
        wp_config_path = os.path.join(DockerConfig.get_project_path(project_name), 'wp-config.php')
        
        if user_type == 'www':
            user = DockerConfig.WWW_USER
            config_permissions = DockerConfig.CONFIG_FILE_PERMISSIONS
        else:  # dev
            user = DockerConfig.DEV_USER
            config_permissions = DockerConfig.FILE_PERMISSIONS
        
        success = True
        
        # Permissions wp-content
        if os.path.exists(wp_content_path):
            success &= PermissionUtils.apply_permissions(
                wp_content_path, user, 
                file_mode=DockerConfig.FILE_PERMISSIONS,
                dir_mode=DockerConfig.DIRECTORY_PERMISSIONS,
                recursive=True
            )
            
            # Permissions spéciales pour uploads
            uploads_path = os.path.join(wp_content_path, 'uploads')
            if os.path.exists(uploads_path):
                success &= PermissionUtils.apply_permissions(
                    uploads_path, user,
                    file_mode=DockerConfig.UPLOADS_FILE_PERMISSIONS,
                    dir_mode=DockerConfig.UPLOADS_PERMISSIONS,
                    recursive=True
                )
        
        # Permissions wp-config.php
        if os.path.exists(wp_config_path):
            success &= PermissionUtils.apply_permissions(
                wp_config_path, user,
                file_mode=config_permissions
            )
        
        return success

class URLUtils:
    """Utilitaires pour la gestion des URLs"""
    
    @staticmethod
    def generate_project_urls(project_name, ports):
        """Génère toutes les URLs d'un projet"""
        from app.config.docker_config import DockerConfig
        
        urls = {}
        
        url_mappings = {
            'wordpress': ('wordpress', ''),
            'wordpress_admin': ('wordpress', 'wp-admin'),
            'phpmyadmin': ('phpmyadmin', ''),
            'mailpit': ('mailpit', ''),
            'nextjs': ('nextjs', ''),
            'mongodb': ('mongodb', ''),
            'mongo_express': ('mongo_express', '')
        }
        
        for url_name, (service, path) in url_mappings.items():
            if service in ports:
                urls[url_name] = DockerConfig.get_project_url(ports[service], path)
        
        return urls

class LoggingUtils:
    """Utilitaires pour la gestion uniforme du logging"""
    
    @staticmethod
    def log_operation(operation, project_name, status, details=None):
        """Log une opération de manière standardisée"""
        status_emoji = "✅" if status == "success" else "❌" if status == "error" else "⏳"
        message = f"{status_emoji} [{operation.upper()}] {project_name}"
        
        if details:
            message += f" - {details}"
        
        print(message)
        
        # TODO: Intégrer avec le système de logging centralisé
        return message