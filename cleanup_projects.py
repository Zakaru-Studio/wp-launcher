#!/usr/bin/env python3
"""
Script de nettoyage automatique des projets corrompus
Peut être exécuté manuellement ou par un cron job
"""

import os
import subprocess
import shutil
import json

PROJECTS_FOLDER = 'projets'

def clean_corrupted_projects():
    """Nettoie tous les projets corrompus ou invalides"""
    print("🧹 Script de nettoyage automatique des projets")
    print("=" * 50)
    
    if not os.path.exists(PROJECTS_FOLDER):
        print(f"❌ Dossier {PROJECTS_FOLDER} non trouvé")
        return
    
    projects_to_cleanup = []
    valid_projects = []
    
    # Scanner tous les projets
    for project in os.listdir(PROJECTS_FOLDER):
        project_path = os.path.join(PROJECTS_FOLDER, project)
        
        if not os.path.isdir(project_path):
            continue
            
        print(f"\n🔍 Vérification du projet: {project}")
        
        # Test d'accès
        try:
            os.listdir(project_path)
        except PermissionError:
            print(f"  ⚠️ Dossier inaccessible")
            projects_to_cleanup.append((project, project_path, "permission"))
            continue
        
        # Vérifier docker-compose.yml
        docker_compose_file = os.path.join(project_path, 'docker-compose.yml')
        if not os.path.exists(docker_compose_file):
            print(f"  ⚠️ Pas de docker-compose.yml")
            projects_to_cleanup.append((project, project_path, "no_compose"))
            continue
        
        # Vérifier le contenu du docker-compose.yml
        try:
            with open(docker_compose_file, 'r') as f:
                compose_content = f.read()
            if not compose_content.strip() or project not in compose_content:
                print(f"  ⚠️ docker-compose.yml invalide")
                projects_to_cleanup.append((project, project_path, "invalid_compose"))
                continue
        except Exception as e:
            print(f"  ⚠️ Erreur lecture docker-compose.yml: {e}")
            projects_to_cleanup.append((project, project_path, "compose_error"))
            continue
        
        # Vérifier si les conteneurs existent
        mysql_container = f"{project}_mysql_1"
        wp_container = f"{project}_wordpress_1"
        
        try:
            result = subprocess.run([
                'docker', 'ps', '-a', '--format', '{{.Names}}'
            ], capture_output=True, text=True)
            
            containers = result.stdout.strip().split('\n')
            has_mysql = any(mysql_container in container for container in containers)
            has_wp = any(wp_container in container for container in containers)
            
            if not has_mysql and not has_wp:
                print(f"  ⚠️ Aucun conteneur trouvé")
                projects_to_cleanup.append((project, project_path, "no_containers"))
                continue
        except Exception:
            pass
        
        print(f"  ✅ Projet valide")
        valid_projects.append(project)
    
    # Rapport
    print(f"\n📊 Résumé:")
    print(f"  ✅ Projets valides: {len(valid_projects)}")
    print(f"  🗑️ Projets à nettoyer: {len(projects_to_cleanup)}")
    
    if valid_projects:
        print(f"\n✅ Projets valides:")
        for project in valid_projects:
            print(f"  - {project}")
    
    if projects_to_cleanup:
        print(f"\n🗑️ Projets à nettoyer:")
        for project, path, reason in projects_to_cleanup:
            print(f"  - {project} (raison: {reason})")
        
        # Demander confirmation en mode interactif
        import sys
        if sys.stdin.isatty():
            response = input(f"\n❓ Voulez-vous supprimer ces {len(projects_to_cleanup)} projets corrompus ? (y/N): ")
            if response.lower() != 'y':
                print("❌ Nettoyage annulé")
                return
        
        # Nettoyer les projets corrompus
        for project, project_path, reason in projects_to_cleanup:
            print(f"\n🗑️ Suppression de {project} ({reason})...")
            
            try:
                # Tenter d'arrêter les conteneurs Docker
                try:
                    os.chdir(project_path)
                    subprocess.run(['docker-compose', 'down', '-v', '--remove-orphans'], 
                                 capture_output=True, text=True, timeout=30)
                    os.chdir('..')
                except Exception:
                    pass
                
                # Supprimer tous les conteneurs liés
                try:
                    result = subprocess.run([
                        'docker', 'ps', '-a', '--format', '{{.Names}}'
                    ], capture_output=True, text=True)
                    
                    for container in result.stdout.strip().split('\n'):
                        if container and project in container:
                            subprocess.run(['docker', 'stop', container], capture_output=True, text=True)
                            subprocess.run(['docker', 'rm', '-f', container], capture_output=True, text=True)
                except Exception:
                    pass
                
                # Supprimer les images liées
                try:
                    result = subprocess.run([
                        'docker', 'images', '--format', '{{.Repository}}:{{.Tag}}'
                    ], capture_output=True, text=True)
                    
                    for image in result.stdout.strip().split('\n'):
                        if image and project in image:
                            subprocess.run(['docker', 'rmi', '-f', image], capture_output=True, text=True)
                except Exception:
                    pass
                
                # Supprimer les volumes liés
                try:
                    result = subprocess.run([
                        'docker', 'volume', 'ls', '--format', '{{.Name}}'
                    ], capture_output=True, text=True)
                    
                    for volume in result.stdout.strip().split('\n'):
                        if volume and project in volume:
                            subprocess.run(['docker', 'volume', 'rm', '-f', volume], capture_output=True, text=True)
                except Exception:
                    pass
                
                # Supprimer le dossier avec sudo
                result = subprocess.run(['sudo', 'rm', '-rf', project_path], 
                                      capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    print(f"  ✅ {project} supprimé")
                else:
                    print(f"  ⚠️ Erreur suppression {project}: {result.stderr}")
                    
            except Exception as e:
                print(f"  ❌ Erreur lors de la suppression de {project}: {e}")
    
    print(f"\n🎯 Nettoyage terminé")

if __name__ == "__main__":
    clean_corrupted_projects() 