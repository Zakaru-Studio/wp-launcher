#!/usr/bin/env python3
"""
Service WP-CLI pour exécuter des commandes WordPress en ligne de commande
"""

import subprocess
import json
import os
from typing import Dict, List, Optional, Tuple
from app.config.docker_config import DockerConfig


class WPCLIService:
    """Service pour exécuter des commandes WP-CLI dans les conteneurs WordPress"""
    
    # Commandes autorisées (whitelist pour la sécurité)
    ALLOWED_COMMANDS = [
        'plugin', 'theme', 'user', 'post', 'page', 'comment',
        'cache', 'db', 'search-replace', 'maintenance-mode',
        'option', 'transient', 'cron', 'media', 'core',
        'rewrite', 'role', 'cap', 'menu', 'widget',
        'site', 'network', 'super-admin', 'term', 'taxonomy'
    ]
    
    # Commandes interdites (sécurité)
    FORBIDDEN_PATTERNS = [
        'eval', 'shell', 'exec', 'system', 'passthru',
        'rm -rf', 'dd if=', '$(', '`', ';', '&&', '||'
    ]
    
    # Templates de commandes courantes
    COMMAND_TEMPLATES = {
        'plugin_list': 'plugin list --format=json',
        'plugin_install': 'plugin install {plugin} --activate',
        'plugin_activate': 'plugin activate {plugin}',
        'plugin_deactivate': 'plugin deactivate {plugin}',
        'plugin_update': 'plugin update {plugin}',
        'plugin_delete': 'plugin delete {plugin}',
        
        'theme_list': 'theme list --format=json',
        'theme_activate': 'theme activate {theme}',
        'theme_install': 'theme install {theme}',
        
        'user_list': 'user list --format=json',
        'user_create': 'user create {username} {email} --role={role}',
        'user_delete': 'user delete {id} --yes',
        'user_update_role': 'user set-role {id} {role}',
        
        'post_list': 'post list --format=json --posts_per_page=20',
        'post_create': 'post create --post_title="{title}" --post_status=publish',
        'post_delete': 'post delete {id} --force',
        
        'cache_flush': 'cache flush',
        'transient_delete_all': 'transient delete --all',
        
        'maintenance_on': 'maintenance-mode activate',
        'maintenance_off': 'maintenance-mode deactivate',
        
        'search_replace': 'search-replace "{old}" "{new}" --all-tables',
        'search_replace_dry': 'search-replace "{old}" "{new}" --all-tables --dry-run',
        
        'db_export': 'db export {file}',
        'db_optimize': 'db optimize',
        'db_repair': 'db repair',
        
        'core_version': 'core version',
        'core_update': 'core update',
        'core_verify_checksums': 'core verify-checksums',
        
        'rewrite_flush': 'rewrite flush',
        'rewrite_list': 'rewrite list --format=json',
        
        'option_get': 'option get {option}',
        'option_update': 'option update {option} {value}',
        'option_delete': 'option delete {option}',
    }
    
    def __init__(self, timeout=60):
        """
        Initialise le service WP-CLI
        
        Args:
            timeout: Timeout en secondes pour l'exécution des commandes (défaut: 60s)
        """
        self.timeout = timeout
    
    def get_container_name(self, project_name: str) -> str:
        """
        Détermine le nom du conteneur WordPress en fonction du type de projet
        
        Args:
            project_name: Nom du projet ou de l'instance dev
            
        Returns:
            Nom du conteneur Docker WordPress
        """
        # Si c'est une instance dev (format: parent_dev_slug)
        if '_dev_' in project_name:
            return f"{project_name}_wordpress"
        # Sinon c'est un projet normal
        return f"{project_name}_wordpress_1"
    
    def execute_command(self, project_name: str, command: str, args: List[str] = None) -> Dict:
        """
        Exécute une commande WP-CLI dans le conteneur WordPress du projet
        
        Args:
            project_name: Nom du projet
            command: Commande WP-CLI (ex: 'plugin list')
            args: Arguments supplémentaires optionnels
            
        Returns:
            Dict avec {success, output, error, exit_code}
        """
        try:
            # Déterminer le nom du conteneur
            container_name = self.get_container_name(project_name)
            
            # Vérifier que le conteneur existe et tourne
            check_result = subprocess.run(
                ['docker', 'ps', '--filter', f'name={container_name}', '--format', '{{.Names}}'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if container_name not in check_result.stdout:
                is_dev_instance = '_dev_' in project_name
                error_msg = f"Le conteneur {container_name} n'est pas démarré"
                if is_dev_instance:
                    error_msg += f". L'instance dev '{project_name}' doit être démarrée avant d'exécuter des commandes WP-CLI."
                return {
                    'success': False,
                    'output': '',
                    'error': error_msg,
                    'exit_code': 1,
                    'container_not_running': True
                }
            
            # Validation de la commande
            validation_result = self._validate_command(command)
            if not validation_result['valid']:
                return {
                    'success': False,
                    'output': '',
                    'error': validation_result['reason'],
                    'exit_code': -1
                }
            
            # Ajouter --format=json automatiquement pour les commandes list
            if ' list' in command and '--format=' not in command:
                command += ' --format=json'
            
            # Construction de la commande complète
            full_command = command
            if args:
                full_command += ' ' + ' '.join(args)
            
            # Nom du conteneur WordPress (gère les projets normaux et les instances dev)
            container_name = self.get_container_name(project_name)
            
            # Commande Docker exec
            docker_command = [
                'docker', 'exec',
                '-u', 'www-data',  # Exécuter en tant que www-data
                container_name,
                'wp', '--path=/var/www/html'
            ] + full_command.split()
            
            print(f"🔧 [WP-CLI] Exécution: {' '.join(docker_command)}")
            
            # Exécution avec timeout
            result = subprocess.run(
                docker_command,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            success = result.returncode == 0
            output = result.stdout.strip()
            error = result.stderr.strip()
            
            # Parser la sortie si c'est du JSON
            parsed_output = self._parse_output(output)
            
            print(f"{'✅' if success else '❌'} [WP-CLI] Code retour: {result.returncode}")
            
            return {
                'success': success,
                'output': output,
                'parsed_output': parsed_output,
                'error': error,
                'exit_code': result.returncode,
                'command': full_command
            }
            
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'output': '',
                'error': f'Timeout: La commande a dépassé {self.timeout}s',
                'exit_code': -2
            }
        except Exception as e:
            print(f"❌ [WP-CLI] Erreur: {e}")
            return {
                'success': False,
                'output': '',
                'error': f'Erreur: {str(e)}',
                'exit_code': -1
            }
    
    def _validate_command(self, command: str) -> Dict:
        """
        Valide une commande WP-CLI pour la sécurité
        
        Args:
            command: Commande à valider
            
        Returns:
            Dict avec {valid: bool, reason: str}
        """
        # Vérifier les patterns interdits
        for forbidden in self.FORBIDDEN_PATTERNS:
            if forbidden in command.lower():
                return {
                    'valid': False,
                    'reason': f'Commande interdite: contient "{forbidden}"'
                }
        
        # Extraire la commande principale
        main_command = command.split()[0] if command.split() else ''
        
        # Vérifier que la commande principale est autorisée
        if main_command not in self.ALLOWED_COMMANDS:
            return {
                'valid': False,
                'reason': f'Commande non autorisée: "{main_command}". Commandes autorisées: {", ".join(self.ALLOWED_COMMANDS)}'
            }
        
        return {'valid': True, 'reason': ''}
    
    def _parse_output(self, output: str) -> Optional[any]:
        """
        Parse la sortie de la commande si c'est du JSON
        
        Args:
            output: Sortie de la commande
            
        Returns:
            Données parsées si JSON, None sinon
        """
        if not output:
            return None
        
        try:
            # Tenter de parser en JSON
            return json.loads(output)
        except json.JSONDecodeError:
            # Pas du JSON, retourner None
            return None
    
    def get_plugin_list(self, project_name: str) -> Dict:
        """
        Récupère la liste des plugins installés
        
        Args:
            project_name: Nom du projet
            
        Returns:
            Dict avec la liste des plugins
        """
        result = self.execute_command(project_name, 'plugin list --format=json')
        if result['success'] and result['parsed_output']:
            return {
                'success': True,
                'plugins': result['parsed_output']
            }
        return {
            'success': False,
            'error': result['error'],
            'plugins': []
        }
    
    def get_theme_list(self, project_name: str) -> Dict:
        """
        Récupère la liste des thèmes installés
        
        Args:
            project_name: Nom du projet
            
        Returns:
            Dict avec la liste des thèmes
        """
        result = self.execute_command(project_name, 'theme list --format=json')
        if result['success'] and result['parsed_output']:
            return {
                'success': True,
                'themes': result['parsed_output']
            }
        return {
            'success': False,
            'error': result['error'],
            'themes': []
        }
    
    def get_user_list(self, project_name: str) -> Dict:
        """
        Récupère la liste des utilisateurs
        
        Args:
            project_name: Nom du projet
            
        Returns:
            Dict avec la liste des utilisateurs
        """
        result = self.execute_command(project_name, 'user list --format=json')
        if result['success'] and result['parsed_output']:
            return {
                'success': True,
                'users': result['parsed_output']
            }
        return {
            'success': False,
            'error': result['error'],
            'users': []
        }
    
    def install_plugin(self, project_name: str, plugin_slug: str, activate: bool = True) -> Dict:
        """
        Installe un plugin
        
        Args:
            project_name: Nom du projet
            plugin_slug: Slug du plugin (ex: 'contact-form-7')
            activate: Activer après installation
            
        Returns:
            Dict avec le résultat
        """
        command = f'plugin install {plugin_slug}'
        if activate:
            command += ' --activate'
        
        return self.execute_command(project_name, command)
    
    def activate_plugin(self, project_name: str, plugin_slug: str) -> Dict:
        """Active un plugin"""
        return self.execute_command(project_name, f'plugin activate {plugin_slug}')
    
    def deactivate_plugin(self, project_name: str, plugin_slug: str) -> Dict:
        """Désactive un plugin"""
        return self.execute_command(project_name, f'plugin deactivate {plugin_slug}')
    
    def delete_plugin(self, project_name: str, plugin_slug: str) -> Dict:
        """Supprime un plugin"""
        return self.execute_command(project_name, f'plugin delete {plugin_slug}')
    
    def create_user(self, project_name: str, username: str, email: str, role: str = 'subscriber') -> Dict:
        """
        Crée un utilisateur WordPress
        
        Args:
            project_name: Nom du projet
            username: Nom d'utilisateur
            email: Email
            role: Rôle (administrator, editor, author, contributor, subscriber)
            
        Returns:
            Dict avec le résultat
        """
        command = f'user create {username} {email} --role={role}'
        return self.execute_command(project_name, command)
    
    def search_replace(self, project_name: str, old: str, new: str, dry_run: bool = False) -> Dict:
        """
        Effectue un search-replace dans la base de données
        
        Args:
            project_name: Nom du projet
            old: Ancienne valeur
            new: Nouvelle valeur
            dry_run: Mode test sans modifications
            
        Returns:
            Dict avec le résultat
        """
        command = f'search-replace "{old}" "{new}" --all-tables'
        if dry_run:
            command += ' --dry-run'
        
        return self.execute_command(project_name, command)
    
    def flush_cache(self, project_name: str) -> Dict:
        """Vide le cache WordPress"""
        return self.execute_command(project_name, 'cache flush')
    
    def maintenance_mode(self, project_name: str, activate: bool) -> Dict:
        """
        Active/désactive le mode maintenance
        
        Args:
            project_name: Nom du projet
            activate: True pour activer, False pour désactiver
            
        Returns:
            Dict avec le résultat
        """
        action = 'activate' if activate else 'deactivate'
        return self.execute_command(project_name, f'maintenance-mode {action}')
    
    def get_core_version(self, project_name: str) -> Dict:
        """Récupère la version de WordPress"""
        return self.execute_command(project_name, 'core version')
    
    def flush_rewrite_rules(self, project_name: str) -> Dict:
        """Régénère les règles de réécriture"""
        return self.execute_command(project_name, 'rewrite flush')
    
    def get_command_templates(self) -> Dict:
        """
        Retourne les templates de commandes disponibles
        
        Returns:
            Dict avec les templates
        """
        return {
            'success': True,
            'templates': self.COMMAND_TEMPLATES
        }
    
    def get_allowed_commands(self) -> List[str]:
        """
        Retourne la liste des commandes autorisées
        
        Returns:
            Liste des commandes autorisées
        """
        return self.ALLOWED_COMMANDS

