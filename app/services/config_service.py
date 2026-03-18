#!/usr/bin/env python3
"""
Service de gestion des configurations PHP et MySQL par projet
"""

import os
import shutil
import subprocess
import configparser
from typing import Dict, Any, Optional
from app.config.docker_config import DockerConfig
from app.utils.logger import wp_logger

class ConfigService:
    """Service pour la gestion des configurations PHP et MySQL par projet"""
    
    def __init__(self):
        self.projects_folder = DockerConfig.PROJECTS_FOLDER
        self.containers_folder = DockerConfig.CONTAINERS_FOLDER
        self.template_path = DockerConfig.TEMPLATE_PATH
    
    def get_project_config_path(self, project_name: str) -> str:
        """Retourne le chemin vers le dossier config d'un projet"""
        return os.path.join(self.projects_folder, project_name, 'config')
    
    def ensure_project_config_directory(self, project_name: str) -> bool:
        """S'assure que le dossier config existe pour un projet"""
        try:
            config_path = self.get_project_config_path(project_name)
            os.makedirs(config_path, exist_ok=True)
            
            # Créer les fichiers de config par défaut s'ils n'existent pas
            php_config_file = os.path.join(config_path, 'php.ini')
            mysql_config_file = os.path.join(config_path, 'mysql.cnf')
            
            if not os.path.isfile(php_config_file):
                self._create_default_php_config(php_config_file)

            if not os.path.isfile(mysql_config_file):
                self._create_default_mysql_config(mysql_config_file)
            
            wp_logger.log_system_info(f"Dossier config créé/vérifié pour {project_name}", 
                                     config_path=config_path)
            return True
            
        except Exception as e:
            wp_logger.log_system_info(f"Erreur création dossier config pour {project_name}: {e}", 
                                     error=str(e))
            return False
    
    def _create_default_php_config(self, php_config_file: str) -> None:
        """Crée un fichier php.ini par défaut"""
        # Si c'est un dossier, le supprimer (correction d'erreur Docker)
        if os.path.exists(php_config_file) and os.path.isdir(php_config_file):
            wp_logger.log_system_info(f"Suppression du dossier incorrect: {php_config_file}")
            try:
                shutil.rmtree(php_config_file)
            except PermissionError:
                subprocess.run(['sudo', 'rm', '-rf', php_config_file], check=True)
        
        template_php = os.path.join(self.template_path, 'php-config', 'php.ini')
        if os.path.exists(template_php):
            shutil.copy2(template_php, php_config_file)
        else:
            # Créer un fichier PHP par défaut si le template n'existe pas
            default_php_content = """; Configuration PHP personnalisée pour ce projet
; Limites de mémoire
memory_limit = 512M
post_max_size = 128M
upload_max_filesize = 64M
max_file_uploads = 20

; Timeouts et limites d'exécution
max_execution_time = 300
max_input_time = 7200
max_input_vars = 10000

; Optimisations de performance
realpath_cache_size = 32M
realpath_cache_ttl = 3600
opcache.enable = 1
opcache.memory_consumption = 128

; Gestion des erreurs et logs
display_errors = On
log_errors = On
error_reporting = E_ALL & ~E_DEPRECATED & ~E_STRICT

; Sessions
session.gc_maxlifetime = 7200
session.cookie_lifetime = 7200
"""
            with open(php_config_file, 'w') as f:
                f.write(default_php_content)
    
    def _create_default_mysql_config(self, mysql_config_file: str) -> None:
        """Crée un fichier mysql.cnf par défaut"""
        # Si c'est un dossier, le supprimer (correction d'erreur Docker)
        if os.path.exists(mysql_config_file) and os.path.isdir(mysql_config_file):
            wp_logger.log_system_info(f"Suppression du dossier incorrect: {mysql_config_file}")
            try:
                shutil.rmtree(mysql_config_file)
            except PermissionError:
                subprocess.run(['sudo', 'rm', '-rf', mysql_config_file], check=True)
        
        template_mysql = os.path.join(self.template_path, 'mysql-config', 'mysql.cnf')
        if os.path.exists(template_mysql):
            shutil.copy2(template_mysql, mysql_config_file)
        else:
            # Créer un fichier MySQL par défaut si le template n'existe pas
            default_mysql_content = """[mysql]
default-character-set = utf8mb4

[mysqld]
# Configuration MySQL personnalisée pour ce projet
max_allowed_packet = 1G
innodb_buffer_pool_size = 512M
innodb_log_file_size = 256M
innodb_log_buffer_size = 32M

# Timeouts
interactive_timeout = 3600
wait_timeout = 3600
net_read_timeout = 120
net_write_timeout = 120

# Limites de connexions
max_connections = 200
max_user_connections = 100

# Charset
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
"""
            with open(mysql_config_file, 'w') as f:
                f.write(default_mysql_content)
    
    def get_php_config(self, project_name: str) -> Dict[str, Any]:
        """Récupère la configuration PHP d'un projet"""
        try:
            self.ensure_project_config_directory(project_name)
            php_config_file = os.path.join(self.get_project_config_path(project_name), 'php.ini')
            
            config = {}
            if os.path.exists(php_config_file):
                with open(php_config_file, 'r') as f:
                    content = f.read()
                
                # Parser le fichier INI manuellement pour préserver les commentaires
                config = self._parse_php_ini(content)
            
            # Ajouter la version PHP actuelle
            config['php_version'] = self.get_php_version(project_name)
            
            # Ajouter les constantes WordPress depuis wp-config.php
            wp_config = self._get_wordpress_debug_config(project_name)
            config.update(wp_config)
            
            wp_logger.log_system_info(f"Configuration PHP récupérée pour {project_name}", 
                                     config_keys=list(config.keys()))
            return config
            
        except Exception as e:
            wp_logger.log_system_info(f"Erreur récupération config PHP pour {project_name}: {e}", 
                                     error=str(e))
            return {}
    
    def get_mysql_config(self, project_name: str) -> Dict[str, Any]:
        """Récupère la configuration MySQL d'un projet"""
        try:
            self.ensure_project_config_directory(project_name)
            mysql_config_file = os.path.join(self.get_project_config_path(project_name), 'mysql.cnf')
            
            config = {}
            if os.path.exists(mysql_config_file):
                with open(mysql_config_file, 'r') as f:
                    content = f.read()
                
                # Parser le fichier CNF manuellement
                config = self._parse_mysql_cnf(content)
            
            wp_logger.log_system_info(f"Configuration MySQL récupérée pour {project_name}", 
                                     config_keys=list(config.keys()))
            return config
            
        except Exception as e:
            wp_logger.log_system_info(f"Erreur récupération config MySQL pour {project_name}: {e}", 
                                     error=str(e))
            return {}
    
    def update_php_config(self, project_name: str, config_data: Dict[str, Any]) -> bool:
        """Met à jour la configuration PHP d'un projet"""
        try:
            self.ensure_project_config_directory(project_name)
            php_config_file = os.path.join(self.get_project_config_path(project_name), 'php.ini')
            
            # Vérification robuste: si c'est un dossier, le supprimer
            if os.path.exists(php_config_file) and os.path.isdir(php_config_file):
                wp_logger.log_system_info(f"Correction: suppression du dossier {php_config_file}")
                shutil.rmtree(php_config_file)
            
            # Séparer les constantes WordPress des configs PHP
            wp_debug_keys = ['wp_debug', 'wp_debug_log', 'wp_debug_display']
            wp_config_data = {k: v for k, v in config_data.items() if k in wp_debug_keys}
            php_config_data = {k: v for k, v in config_data.items() if k not in wp_debug_keys}
            
            # Mettre à jour php.ini si nécessaire
            if php_config_data:
                # Lire le fichier existant pour préserver la structure
                existing_content = ""
                if os.path.exists(php_config_file):
                    with open(php_config_file, 'r') as f:
                        existing_content = f.read()
                
                # Mettre à jour le contenu
                updated_content = self._update_php_ini_content(existing_content, php_config_data)
                
                # Écrire le fichier mis à jour
                with open(php_config_file, 'w') as f:
                    f.write(updated_content)
            
            # Mettre à jour wp-config.php si nécessaire
            if wp_config_data:
                wp_success = self._update_wordpress_debug_config(project_name, wp_config_data)
                if not wp_success:
                    wp_logger.log_system_info(f"Avertissement: impossible de mettre à jour wp-config.php pour {project_name}")
            
            wp_logger.log_system_info(f"Configuration PHP mise à jour pour {project_name}", 
                                     config_file=php_config_file,
                                     updated_keys=list(config_data.keys()))
            return True
            
        except Exception as e:
            wp_logger.log_system_info(f"Erreur mise à jour config PHP pour {project_name}: {e}", 
                                     error=str(e))
            return False
    
    def update_mysql_config(self, project_name: str, config_data: Dict[str, Any]) -> bool:
        """Met à jour la configuration MySQL d'un projet"""
        try:
            self.ensure_project_config_directory(project_name)
            mysql_config_file = os.path.join(self.get_project_config_path(project_name), 'mysql.cnf')
            
            # Vérification robuste: si c'est un dossier, le supprimer
            if os.path.exists(mysql_config_file) and os.path.isdir(mysql_config_file):
                wp_logger.log_system_info(f"Correction: suppression du dossier {mysql_config_file}")
                shutil.rmtree(mysql_config_file)
            
            # Lire le fichier existant pour préserver la structure
            existing_content = ""
            if os.path.exists(mysql_config_file):
                with open(mysql_config_file, 'r') as f:
                    existing_content = f.read()
            
            # Mettre à jour le contenu
            updated_content = self._update_mysql_cnf_content(existing_content, config_data)
            
            # Écrire le fichier mis à jour
            with open(mysql_config_file, 'w') as f:
                f.write(updated_content)
            
            wp_logger.log_system_info(f"Configuration MySQL mise à jour pour {project_name}", 
                                     config_file=mysql_config_file,
                                     updated_keys=list(config_data.keys()))
            return True
            
        except Exception as e:
            wp_logger.log_system_info(f"Erreur mise à jour config MySQL pour {project_name}: {e}", 
                                     error=str(e))
            return False
    
    def _parse_php_ini(self, content: str) -> Dict[str, str]:
        """Parse un fichier PHP INI en préservant les valeurs importantes"""
        config = {}
        
        # Paramètres PHP importants à extraire
        important_params = [
            'memory_limit', 'post_max_size', 'upload_max_filesize', 'max_file_uploads',
            'max_execution_time', 'max_input_time', 'max_input_vars',
            'realpath_cache_size', 'realpath_cache_ttl', 'opcache.enable',
            'opcache.memory_consumption', 'display_errors', 'log_errors',
            'error_reporting', 'session.gc_maxlifetime', 'session.cookie_lifetime'
        ]
        
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith(';') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                if key in important_params:
                    config[key] = value
        
        return config
    
    def _parse_mysql_cnf(self, content: str) -> Dict[str, str]:
        """Parse un fichier MySQL CNF en préservant les valeurs importantes"""
        config = {}
        
        # Paramètres MySQL importants à extraire
        important_params = [
            'max_allowed_packet', 'innodb_buffer_pool_size', 'innodb_log_file_size',
            'innodb_log_buffer_size', 'interactive_timeout', 'wait_timeout',
            'net_read_timeout', 'net_write_timeout', 'max_connections',
            'max_user_connections', 'character-set-server', 'collation-server'
        ]
        
        current_section = None
        for line in content.split('\n'):
            line = line.strip()
            
            if line.startswith('[') and line.endswith(']'):
                current_section = line[1:-1]
                continue
            
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                if key in important_params:
                    config[key] = value
        
        return config
    
    def _update_php_ini_content(self, existing_content: str, config_data: Dict[str, Any]) -> str:
        """Met à jour le contenu d'un fichier PHP INI"""
        lines = existing_content.split('\n') if existing_content else []
        updated_lines = []
        updated_keys = set()
        
        for line in lines:
            original_line = line
            line_stripped = line.strip()
            
            if line_stripped and not line_stripped.startswith(';') and '=' in line_stripped:
                key, _ = line_stripped.split('=', 1)
                key = key.strip()
                
                if key in config_data:
                    # Remplacer la valeur
                    updated_lines.append(f"{key} = {config_data[key]}")
                    updated_keys.add(key)
                else:
                    updated_lines.append(original_line)
            else:
                updated_lines.append(original_line)
        
        # Ajouter les nouvelles clés qui n'existaient pas
        for key, value in config_data.items():
            if key not in updated_keys:
                updated_lines.append(f"{key} = {value}")
        
        return '\n'.join(updated_lines)
    
    def _update_mysql_cnf_content(self, existing_content: str, config_data: Dict[str, Any]) -> str:
        """Met à jour le contenu d'un fichier MySQL CNF"""
        lines = existing_content.split('\n') if existing_content else []
        updated_lines = []
        updated_keys = set()
        
        for line in lines:
            original_line = line
            line_stripped = line.strip()
            
            if line_stripped and not line_stripped.startswith('#') and '=' in line_stripped:
                key, _ = line_stripped.split('=', 1)
                key = key.strip()
                
                if key in config_data:
                    # Remplacer la valeur
                    updated_lines.append(f"{key} = {config_data[key]}")
                    updated_keys.add(key)
                else:
                    updated_lines.append(original_line)
            else:
                updated_lines.append(original_line)
        
        # Ajouter les nouvelles clés qui n'existaient pas (dans la section [mysqld])
        if updated_keys != set(config_data.keys()):
            # Trouver la section [mysqld] ou l'ajouter
            mysqld_found = False
            for i, line in enumerate(updated_lines):
                if line.strip() == '[mysqld]':
                    mysqld_found = True
                    break
            
            if not mysqld_found:
                updated_lines.extend(['', '[mysqld]'])
            
            # Ajouter les nouvelles clés
            for key, value in config_data.items():
                if key not in updated_keys:
                    updated_lines.append(f"{key} = {value}")
        
        return '\n'.join(updated_lines)
    
    def get_php_config_schema(self) -> Dict[str, Any]:
        """Retourne le schéma des configurations PHP disponibles"""
        return {
            'wp_debug': {
                'label': 'WP_DEBUG',
                'type': 'switch',
                'default': 'false',
                'description': 'Mode débogage WordPress'
            },
            'wp_debug_log': {
                'label': 'WP_DEBUG_LOG',
                'type': 'switch',
                'default': 'false',
                'description': 'Enregistrer les erreurs dans wp-content/debug.log'
            },
            'wp_debug_display': {
                'label': 'WP_DEBUG_DISPLAY',
                'type': 'switch',
                'default': 'false',
                'description': 'Afficher les erreurs WordPress à l\'écran'
            },
            'php_version': {
                'label': 'Version PHP',
                'type': 'select',
                'options': ['7.4', '8.0', '8.1', '8.2', '8.3', '8.4'],
                'default': '8.2',
                'description': 'Version PHP du conteneur (redémarrage requis)'
            },
            'memory_limit': {
                'label': 'Limite mémoire PHP',
                'type': 'text',
                'default': '512M',
                'description': 'Limite de mémoire pour les scripts PHP'
            },
            'post_max_size': {
                'label': 'Taille max POST',
                'type': 'text',
                'default': '128M',
                'description': 'Taille maximale des données POST'
            },
            'upload_max_filesize': {
                'label': 'Taille max upload',
                'type': 'text',
                'default': '64M',
                'description': 'Taille maximale des fichiers uploadés'
            },
            'max_execution_time': {
                'label': 'Temps d\'exécution max',
                'type': 'number',
                'default': '300',
                'description': 'Temps maximum d\'exécution en secondes'
            },
            'max_input_vars': {
                'label': 'Variables d\'entrée max',
                'type': 'number',
                'default': '10000',
                'description': 'Nombre maximum de variables d\'entrée'
            },
              'display_errors': {
                'label': 'Afficher les erreurs PHP',
                'type': 'switch',
                'default': 'On',
                'description': 'Afficher les erreurs PHP dans le navigateur'
            }
        }
    
    def get_php_version(self, project_name: str) -> str:
        """Récupère la version PHP actuelle d'un projet"""
        try:
            # Lire depuis le fichier .php_version dans containers/
            version_file = os.path.join(self.containers_folder, project_name, '.php_version')
            if os.path.exists(version_file):
                with open(version_file, 'r') as f:
                    return f.read().strip()
            return '8.2'  # Version par défaut
        except Exception as e:
            wp_logger.log_system_info(f"Erreur récupération version PHP pour {project_name}: {e}")
            return '8.2'
    
    def set_php_version(self, project_name: str, version: str) -> bool:
        """Définit la version PHP d'un projet"""
        try:
            version_file = os.path.join(self.containers_folder, project_name, '.php_version')
            os.makedirs(os.path.dirname(version_file), exist_ok=True)
            with open(version_file, 'w') as f:
                f.write(version)
            wp_logger.log_system_info(f"Version PHP définie pour {project_name}: {version}")
            return True
        except Exception as e:
            wp_logger.log_system_info(f"Erreur définition version PHP pour {project_name}: {e}")
            return False
    
    def _get_wordpress_debug_config(self, project_name: str) -> Dict[str, str]:
        """Récupère les constantes de débogage WordPress depuis wp-config.php"""
        try:
            wp_config_file = os.path.join(self.projects_folder, project_name, 'wp-config.php')
            
            if not os.path.exists(wp_config_file):
                return {
                    'wp_debug': 'false',
                    'wp_debug_log': 'false',
                    'wp_debug_display': 'false'
                }
            
            with open(wp_config_file, 'r') as f:
                content = f.read()
            
            config = {}
            
            # Chercher WP_DEBUG
            import re
            wp_debug_match = re.search(r"define\s*\(\s*['\"]WP_DEBUG['\"]\s*,\s*(true|false)\s*\)", content, re.IGNORECASE)
            config['wp_debug'] = wp_debug_match.group(1).lower() if wp_debug_match else 'false'
            
            # Chercher WP_DEBUG_LOG
            wp_debug_log_match = re.search(r"define\s*\(\s*['\"]WP_DEBUG_LOG['\"]\s*,\s*(true|false)\s*\)", content, re.IGNORECASE)
            config['wp_debug_log'] = wp_debug_log_match.group(1).lower() if wp_debug_log_match else 'false'
            
            # Chercher WP_DEBUG_DISPLAY
            wp_debug_display_match = re.search(r"define\s*\(\s*['\"]WP_DEBUG_DISPLAY['\"]\s*,\s*(true|false)\s*\)", content, re.IGNORECASE)
            config['wp_debug_display'] = wp_debug_display_match.group(1).lower() if wp_debug_display_match else 'false'
            
            return config
            
        except Exception as e:
            wp_logger.log_system_info(f"Erreur lecture config WordPress pour {project_name}: {e}")
            return {
                'wp_debug': 'false',
                'wp_debug_log': 'false',
                'wp_debug_display': 'false'
            }
    
    def _update_wordpress_debug_config(self, project_name: str, config_data: Dict[str, str]) -> bool:
        """Met à jour les constantes de débogage WordPress dans wp-config.php"""
        try:
            wp_config_file = os.path.join(self.projects_folder, project_name, 'wp-config.php')
            
            if not os.path.exists(wp_config_file):
                wp_logger.log_system_info(f"Fichier wp-config.php non trouvé pour {project_name}")
                return False
            
            with open(wp_config_file, 'r') as f:
                content = f.read()
            
            import re
            
            # Mettre à jour WP_DEBUG
            if 'wp_debug' in config_data:
                value = config_data['wp_debug']
                updated = False
                
                # Chercher le pattern avec if ( ! defined( 'WP_DEBUG' ) ) et définition sur plusieurs lignes
                pattern_conditional = r"(if\s*\(\s*!\s*defined\s*\(\s*['\"]WP_DEBUG['\"]\s*\)\s*\)\s*\{[^\}]*?define\s*\(\s*['\"]WP_DEBUG['\"]\s*,\s*)(true|false)(\s*\)\s*;[^\}]*?\})"
                if re.search(pattern_conditional, content, flags=re.IGNORECASE | re.DOTALL):
                    replacement = r"\g<1>" + value + r"\3"
                    content = re.sub(pattern_conditional, replacement, content, flags=re.IGNORECASE | re.DOTALL)
                    updated = True
                
                if not updated:
                    # Chercher le define simple (sans if)
                    pattern_simple = r"(^define\s*\(\s*['\"]WP_DEBUG['\"]\s*,\s*)(true|false)(\s*\)\s*;)"
                    if re.search(pattern_simple, content, flags=re.IGNORECASE | re.MULTILINE):
                        replacement = r"\g<1>" + value + r"\3"
                        content = re.sub(pattern_simple, replacement, content, flags=re.IGNORECASE | re.MULTILINE)
                        updated = True
                
                if not updated:
                    # Ajouter après le préfixe de table
                    insert_pattern = r"(\$table_prefix\s*=\s*['\"].*?['\"]\s*;[\s\n\r]*)"
                    insert_text = r"\1\n// Mode debug WordPress\ndefine('WP_DEBUG', " + value + ");\n"
                    content = re.sub(insert_pattern, insert_text, content, count=1)
            
            # Mettre à jour WP_DEBUG_LOG
            if 'wp_debug_log' in config_data:
                value = config_data['wp_debug_log']
                # Chercher avec ou sans indentation
                pattern = r"(^\s*define\s*\(\s*['\"]WP_DEBUG_LOG['\"]\s*,\s*)(true|false)(\s*\)\s*;)"
                if re.search(pattern, content, flags=re.IGNORECASE | re.MULTILINE):
                    replacement = r"\g<1>" + value + r"\3"
                    content = re.sub(pattern, replacement, content, flags=re.IGNORECASE | re.MULTILINE)
                else:
                    # Ajouter après le bloc WP_DEBUG (après le } s'il existe ou après le define)
                    # Chercher d'abord le pattern avec if/else
                    insert_pattern = r"(if\s*\(\s*!\s*defined\s*\(\s*['\"]WP_DEBUG['\"]\s*\)\s*\)\s*\{[^\}]*?\}[\s\n\r]*)"
                    if re.search(insert_pattern, content, flags=re.IGNORECASE | re.DOTALL):
                        insert_text = r"\1define('WP_DEBUG_LOG', " + value + ");\n"
                        content = re.sub(insert_pattern, insert_text, content, count=1, flags=re.IGNORECASE | re.DOTALL)
                    else:
                        # Sinon ajouter après le define simple
                        insert_pattern = r"(^\s*define\s*\(\s*['\"]WP_DEBUG['\"]\s*,\s*(?:true|false)\s*\)\s*;[\s\n\r]*)"
                        insert_text = r"\1define('WP_DEBUG_LOG', " + value + ");\n"
                        content = re.sub(insert_pattern, insert_text, content, count=1, flags=re.IGNORECASE | re.MULTILINE)
            
            # Mettre à jour WP_DEBUG_DISPLAY
            if 'wp_debug_display' in config_data:
                value = config_data['wp_debug_display']
                # Chercher avec ou sans indentation
                pattern = r"(^\s*define\s*\(\s*['\"]WP_DEBUG_DISPLAY['\"]\s*,\s*)(true|false)(\s*\)\s*;)"
                if re.search(pattern, content, flags=re.IGNORECASE | re.MULTILINE):
                    replacement = r"\g<1>" + value + r"\3"
                    content = re.sub(pattern, replacement, content, flags=re.IGNORECASE | re.MULTILINE)
                else:
                    # Ajouter après WP_DEBUG_LOG ou WP_DEBUG
                    insert_pattern = r"(^\s*define\s*\(\s*['\"]WP_DEBUG(?:_LOG)?['\"]\s*,\s*(?:true|false)\s*\)\s*;[\s\n\r]*)"
                    insert_text = r"\1define('WP_DEBUG_DISPLAY', " + value + ");\n"
                    # Trouver la dernière occurrence
                    matches = list(re.finditer(insert_pattern, content, flags=re.IGNORECASE | re.MULTILINE))
                    if matches:
                        last_match = matches[-1]
                        content = content[:last_match.end()] + f"define('WP_DEBUG_DISPLAY', {value});\n" + content[last_match.end():]
            
            # Écrire le fichier mis à jour
            # Utiliser un fichier temporaire car wp-config.php peut appartenir à www-data
            import tempfile
            import subprocess
            import shutil
            
            try:
                # Créer un fichier temporaire
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.php') as tmp_file:
                    tmp_file.write(content)
                    tmp_path = tmp_file.name
                
                # Copier le fichier avec les bonnes permissions
                shutil.copy2(tmp_path, wp_config_file)
                os.remove(tmp_path)
                
            except PermissionError:
                # Si on n'a pas les permissions, utiliser sudo
                wp_logger.log_system_info(f"Utilisation de sudo pour écrire {wp_config_file}")
                subprocess.run(['sudo', 'cp', tmp_path, wp_config_file], check=True)
                subprocess.run(['sudo', 'chown', 'www-data:www-data', wp_config_file], check=False)
                os.remove(tmp_path)
            
            wp_logger.log_system_info(f"Configuration WordPress mise à jour pour {project_name}")
            return True
            
        except Exception as e:
            wp_logger.log_system_info(f"Erreur mise à jour config WordPress pour {project_name}: {e}", 
                                     error=str(e))
            return False
    
    def get_mysql_config_schema(self) -> Dict[str, Any]:
        """Retourne le schéma des configurations MySQL disponibles"""
        return {
            'max_allowed_packet': {
                'label': 'Taille max paquet',
                'type': 'text',
                'default': '1G',
                'description': 'Taille maximale des paquets MySQL'
            },
            'innodb_buffer_pool_size': {
                'label': 'Taille buffer pool InnoDB',
                'type': 'text',
                'default': '512M',
                'description': 'Taille du buffer pool InnoDB'
            },
            'max_connections': {
                'label': 'Connexions max',
                'type': 'number',
                'default': '200',
                'description': 'Nombre maximum de connexions simultanées'
            },
            'interactive_timeout': {
                'label': 'Timeout interactif',
                'type': 'number',
                'default': '3600',
                'description': 'Timeout pour les connexions interactives (secondes)'
            },
            'wait_timeout': {
                'label': 'Timeout d\'attente',
                'type': 'number',
                'default': '3600',
                'description': 'Timeout d\'attente pour les connexions (secondes)'
            }
        }
