#!/usr/bin/env python3
"""
Script pour corriger les 5 projets avec structure wp-config.php non standard
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for app imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config.docker_config import DockerConfig

PROJECTS_TO_FIX = ['aratice', 'clpac', 'express-shrink', 'ludovic-magat', 'memoiresdoceans']

def get_project_port(project_name):
    """Récupère le port d'un projet"""
    try:
        container_path = Path(f'/home/dev-server/Sites/wp-launcher/containers/{project_name}')
        port_file = container_path / '.port'
        
        if port_file.exists():
            with open(port_file, 'r') as f:
                return f.read().strip()
        return '8080'
    except:
        return '8080'

def fix_wp_config(project_name):
    """Corrige un wp-config.php avec structure WordPress standard"""
    wp_config_path = Path(f'/home/dev-server/Sites/wp-launcher/projets/{project_name}/wp-config.php')
    
    if not wp_config_path.exists():
        return 'no_config'
    
    try:
        with open(wp_config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Vérifier si déjà protégé
        if 'Protection WP-CLI' in content or "defined('WP_CLI')" in content:
            return 'already_protected'
        
        port = get_project_port(project_name)
        
        # Chercher la ligne "require_once ABSPATH . 'wp-settings.php';"
        if "require_once ABSPATH . 'wp-settings.php';" in content or \
           "require_once( ABSPATH . 'wp-settings.php' );" in content:
            
            local_ip = DockerConfig.LOCAL_IP
            wpcli_protection = f"""
// Protection WP-CLI : définir les variables SERVER manquantes
if (defined('WP_CLI') && WP_CLI) {{
    $_SERVER['SERVER_NAME'] = '{local_ip}';
    $_SERVER['SERVER_PORT'] = '{port}';
    $_SERVER['HTTP_HOST'] = '{local_ip}:{port}';
    $_SERVER['REQUEST_URI'] = '/';
    $_SERVER['REQUEST_METHOD'] = 'GET';
}}

"""
            
            # Insérer avant require_once wp-settings.php
            content = content.replace(
                "require_once ABSPATH . 'wp-settings.php';",
                wpcli_protection + "require_once ABSPATH . 'wp-settings.php';"
            )
            content = content.replace(
                "require_once( ABSPATH . 'wp-settings.php' );",
                wpcli_protection + "require_once( ABSPATH . 'wp-settings.php' );"
            )
            
            with open(wp_config_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return 'fixed'
        else:
            return 'no_wp_settings_found'
            
    except Exception as e:
        return f'error: {str(e)}'

def main():
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║   Correction Protection WP-CLI - Projets non standard          ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    stats = {'fixed': 0, 'already_protected': 0, 'errors': 0}
    
    for project_name in PROJECTS_TO_FIX:
        result = fix_wp_config(project_name)
        
        if result == 'fixed':
            print(f"✅ {project_name:<30} - Protection ajoutée")
            stats['fixed'] += 1
        elif result == 'already_protected':
            print(f"ℹ️  {project_name:<30} - Déjà protégé")
            stats['already_protected'] += 1
        else:
            print(f"❌ {project_name:<30} - {result}")
            stats['errors'] += 1
    
    print()
    print("━" * 64)
    print(f"Corrigés:        {stats['fixed']}")
    print(f"Déjà protégés:   {stats['already_protected']}")
    print(f"Erreurs:         {stats['errors']}")
    print("━" * 64)

if __name__ == '__main__':
    main()

