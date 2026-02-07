#!/usr/bin/env python3
"""
Script de migration pour détecter et configurer le type WordPress des projets existants
Détecte automatiquement si WooCommerce est installé et configure les limites de ressources
"""

import os
import sys
import re
from pathlib import Path

# Ajouter le dossier parent au PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.wordpress_type_service import WordPressTypeService


def detect_and_update_projects():
    """Détecte et met à jour les types WordPress de tous les projets existants"""
    
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║   Détection et configuration des types WordPress              ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()
    
    projects_folder = Path('projets')
    containers_folder = Path('containers')
    
    if not projects_folder.exists():
        print(f"❌ Dossier projets non trouvé: {projects_folder}")
        return
    
    wp_type_service = WordPressTypeService()
    
    stats = {
        'total': 0,
        'wordpress': 0,
        'woocommerce': 0,
        'nextjs': 0,
        'updated': 0,
        'errors': 0
    }
    
    # Parcourir tous les projets
    for project_dir in sorted(projects_folder.iterdir()):
        if not project_dir.is_dir():
            continue
        
        stats['total'] += 1
        project_name = project_dir.name
        
        # Vérifier si c'est un projet WordPress (a wp-content)
        wp_content = project_dir / 'wp-content'
        if not wp_content.exists():
            print(f"⏭️  {project_name:<30} - Projet Next.js (ignoré)")
            stats['nextjs'] += 1
            continue
        
        # Détecter WooCommerce
        has_woocommerce = wp_type_service.detect_woocommerce(project_name)
        
        if has_woocommerce:
            wp_type = 'woocommerce'
            icon = '🛒'
            stats['woocommerce'] += 1
        else:
            wp_type = 'showcase'
            icon = '🌐'
            stats['wordpress'] += 1
        
        # Sauvegarder le type
        try:
            wp_type_service.save_wordpress_type(project_name, wp_type)
            
            # Mettre à jour le docker-compose.yml
            container_path = containers_folder / project_name
            docker_compose_path = container_path / 'docker-compose.yml'
            
            if docker_compose_path.exists():
                update_docker_compose_limits(docker_compose_path, wp_type, wp_type_service)
                print(f"✅ {icon} {project_name:<28} - {wp_type.upper()} (détecté et configuré)")
                stats['updated'] += 1
            else:
                print(f"⚠️  {icon} {project_name:<28} - {wp_type.upper()} (type sauvegardé, docker-compose.yml non trouvé)")
                stats['updated'] += 1
                
        except Exception as e:
            print(f"❌ {project_name:<30} - Erreur: {str(e)}")
            stats['errors'] += 1
    
    # Afficher le résumé
    print()
    print("━" * 64)
    print("📊 RÉSUMÉ")
    print("━" * 64)
    print(f"Total de projets:           {stats['total']}")
    print(f"Projets WordPress:          {stats['wordpress'] + stats['woocommerce']}")
    print(f"  - Vitrines:               {stats['wordpress']}")
    print(f"  - WooCommerce:            {stats['woocommerce']}")
    print(f"Projets Next.js (ignorés):  {stats['nextjs']}")
    print(f"Configurés avec succès:     {stats['updated']}")
    print(f"Erreurs:                    {stats['errors']}")
    print("━" * 64)
    
    if stats['updated'] > 0:
        print()
        print("✅ Configuration terminée avec succès !")
        print()
        print("💡 Actions à effectuer manuellement :")
        print("   1. Redémarrer les projets pour appliquer les nouvelles limites")
        print("   2. Vérifier la configuration dans la modale de config PHP")
        print()
        print("   Pour redémarrer tous les projets actifs :")
        print("   → Utiliser l'interface web pour redémarrer chaque projet")


def update_docker_compose_limits(docker_compose_path: Path, wp_type: str, wp_type_service: WordPressTypeService) -> bool:
    """Met à jour les limites de ressources dans un fichier docker-compose.yml"""
    try:
        # Lire le fichier
        with open(docker_compose_path, 'r') as f:
            content = f.read()
        
        # Récupérer les nouvelles limites
        limits = wp_type_service.get_memory_limits(wp_type)
        
        # Remplacer les limites mémoire et CPU pour MySQL
        content = re.sub(
            r'(mysql:[\s\S]*?mem_limit:\s*)\d+[mMgG]',
            rf'\g<1>{limits["mysql_memory"]}',
            content
        )
        content = re.sub(
            r'(mysql:[\s\S]*?cpus:\s*["\'])\d+\.?\d*(["\'])',
            rf'\g<1>{limits["mysql_cpu"]}\g<2>',
            content
        )
        
        # Remplacer les limites mémoire et CPU pour WordPress
        content = re.sub(
            r'(wordpress:[\s\S]*?mem_limit:\s*)\d+[mMgG]',
            rf'\g<1>{limits["wordpress_memory"]}',
            content
        )
        content = re.sub(
            r'(wordpress:[\s\S]*?cpus:\s*["\'])\d+\.?\d*(["\'])',
            rf'\g<1>{limits["wordpress_cpu"]}\g<2>',
            content
        )
        
        # Sauvegarder
        with open(docker_compose_path, 'w') as f:
            f.write(content)
        
        return True
        
    except Exception as e:
        print(f"  ⚠️ Erreur mise à jour docker-compose.yml: {e}")
        return False


if __name__ == '__main__':
    detect_and_update_projects()






