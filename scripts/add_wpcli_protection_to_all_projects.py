#!/usr/bin/env python3
"""
Script pour ajouter la protection WP-CLI à tous les projets WordPress existants
"""

import os
import re
from pathlib import Path

def get_project_port(project_name):
    """Récupère le port d'un projet depuis le fichier .port"""
    try:
        container_path = Path(f'/home/dev-server/Sites/wp-launcher/containers/{project_name}')
        port_file = container_path / '.port'
        
        if port_file.exists():
            with open(port_file, 'r') as f:
                return f.read().strip()
        return None
    except Exception as e:
        print(f"⚠️ Erreur lecture port pour {project_name}: {e}")
        return None

def add_wpcli_protection(wp_config_path, project_name):
    """Ajoute la protection WP-CLI à un wp-config.php"""
    try:
        with open(wp_config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Vérifier si la protection existe déjà
        if 'Protection WP-CLI' in content or "defined('WP_CLI')" in content:
            return 'already_exists'
        
        # Récupérer le port du projet
        port = get_project_port(project_name)
        if not port:
            port = '8080'  # Port par défaut
        
        # Trouver la position après la définition de ABSPATH
        abspath_pattern = r"if \(!defined\('ABSPATH'\)\) \{[\s\S]*?\}"
        
        match = re.search(abspath_pattern, content)
        if not match:
            return 'no_abspath_found'
        
        # Insérer la protection après ABSPATH
        insert_pos = match.end()
        
        wpcli_protection = f"""

// Protection WP-CLI : définir les variables SERVER manquantes
if (defined('WP_CLI') && WP_CLI) {{
    $_SERVER['SERVER_NAME'] = '192.168.1.21';
    $_SERVER['SERVER_PORT'] = '{port}';
    $_SERVER['HTTP_HOST'] = '192.168.1.21:{port}';
    $_SERVER['REQUEST_URI'] = '/';
    $_SERVER['REQUEST_METHOD'] = 'GET';
}}
"""
        
        # Insérer la protection
        new_content = content[:insert_pos] + wpcli_protection + content[insert_pos:]
        
        # Sauvegarder
        with open(wp_config_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return 'added'
        
    except Exception as e:
        return f'error: {str(e)}'

def main():
    base_path = Path('/home/dev-server/Sites/wp-launcher/projets')
    
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║   Ajout Protection WP-CLI à tous les projets WordPress        ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    if not base_path.exists():
        print(f"❌ Dossier projets non trouvé: {base_path}")
        return
    
    stats = {
        'added': 0,
        'already_exists': 0,
        'no_config': 0,
        'errors': 0,
        'total': 0
    }
    
    # Parcourir tous les projets
    for project_dir in sorted(base_path.iterdir()):
        if not project_dir.is_dir():
            continue
        
        stats['total'] += 1
        project_name = project_dir.name
        wp_config_path = project_dir / 'wp-config.php'
        
        # Vérifier si wp-config.php existe
        if not wp_config_path.exists():
            print(f"⏭️  {project_name:<30} - Pas de wp-config.php")
            stats['no_config'] += 1
            continue
        
        # Ajouter la protection
        result = add_wpcli_protection(wp_config_path, project_name)
        
        if result == 'added':
            print(f"✅ {project_name:<30} - Protection ajoutée")
            stats['added'] += 1
        elif result == 'already_exists':
            print(f"ℹ️  {project_name:<30} - Protection déjà présente")
            stats['already_exists'] += 1
        elif result == 'no_abspath_found':
            print(f"⚠️  {project_name:<30} - Structure ABSPATH non trouvée")
            stats['errors'] += 1
        else:
            print(f"❌ {project_name:<30} - {result}")
            stats['errors'] += 1
    
    # Afficher le résumé
    print()
    print("━" * 64)
    print("📊 RÉSUMÉ")
    print("━" * 64)
    print(f"Total de projets:        {stats['total']}")
    print(f"Protection ajoutée:      {stats['added']}")
    print(f"Déjà protégés:           {stats['already_exists']}")
    print(f"Sans wp-config.php:      {stats['no_config']}")
    print(f"Erreurs:                 {stats['errors']}")
    print("━" * 64)
    
    if stats['added'] > 0:
        print()
        print("✅ Protection WP-CLI ajoutée avec succès !")
        print("💡 Les commandes WP-CLI ne provoqueront plus d'erreurs SERVER_NAME")

if __name__ == '__main__':
    main()

