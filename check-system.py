#!/usr/bin/env python3
"""
Script de diagnostic du système WordPress Launcher
Vérifie l'état des ports, permissions, Docker et Traefik
"""

import os
import sys
import subprocess
import json
from pathlib import Path

# Ajouter le répertoire courant au path Python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.port_utils import get_comprehensive_used_ports, find_free_port_for_project
from config.app_config import PROJECTS_FOLDER, CONTAINERS_FOLDER

def print_header(title):
    """Affiche un header formaté"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def print_success(message):
    """Affiche un message de succès"""
    print(f"✅ {message}")

def print_error(message):
    """Affiche un message d'erreur"""
    print(f"❌ {message}")

def print_warning(message):
    """Affiche un message d'avertissement"""
    print(f"⚠️  {message}")

def print_info(message):
    """Affiche un message d'information"""
    print(f"ℹ️  {message}")

def check_docker():
    """Vérifie l'état de Docker"""
    print_header("VÉRIFICATION DOCKER")
    
    try:
        # Vérifier si Docker est en cours d'exécution
        result = subprocess.run(['docker', 'ps'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print_success("Docker est en cours d'exécution")
            
            # Compter les conteneurs
            lines = result.stdout.strip().split('\n')
            container_count = len(lines) - 1 if len(lines) > 1 else 0
            print_info(f"Conteneurs actifs: {container_count}")
            
            return True
        else:
            print_error("Docker n'est pas accessible")
            return False
            
    except Exception as e:
        print_error(f"Erreur Docker: {e}")
        return False

def check_traefik():
    """Vérifie l'état de Traefik"""
    print_header("VÉRIFICATION TRAEFIK")
    
    try:
        result = subprocess.run(['docker', 'ps', '--filter', 'name=traefik', '--format', '{{.Names}}\t{{.Status}}'], 
                               capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0 and 'traefik' in result.stdout:
            print_success("Traefik est en cours d'exécution")
            print_info("SSL automatique activé")
            
            # Vérifier les ports Traefik
            traefik_result = subprocess.run(['docker', 'port', 'traefik'], capture_output=True, text=True)
            if traefik_result.returncode == 0:
                print_info("Ports Traefik:")
                for line in traefik_result.stdout.strip().split('\n'):
                    if line:
                        print(f"    {line}")
            
            return True
        else:
            print_warning("Traefik n'est pas en cours d'exécution")
            print_info("Les nouveaux sites ne seront pas automatiquement exposés en HTTPS")
            return False
            
    except Exception as e:
        print_error(f"Erreur lors de la vérification Traefik: {e}")
        return False

def check_ports():
    """Vérifie l'état des ports"""
    print_header("VÉRIFICATION PORTS")
    
    try:
        used_ports = get_comprehensive_used_ports()
        print_success(f"Détection des ports réussie")
        print_info(f"Ports utilisés ({len(used_ports)}): {sorted(used_ports)}")
        
        # Trouver les prochains ports libres
        try:
            next_free = find_free_port_for_project()
            print_success(f"Prochain port libre: {next_free}")
        except Exception as e:
            print_error(f"Impossible de trouver un port libre: {e}")
            
        return True
        
    except Exception as e:
        print_error(f"Erreur lors de la vérification des ports: {e}")
        return False

def check_projects():
    """Vérifie l'état des projets"""
    print_header("VÉRIFICATION PROJETS")
    
    projects_count = 0
    containers_count = 0
    
    # Vérifier le dossier projets
    if os.path.exists(PROJECTS_FOLDER):
        projects = [d for d in os.listdir(PROJECTS_FOLDER) if os.path.isdir(os.path.join(PROJECTS_FOLDER, d))]
        projects_count = len(projects)
        print_success(f"Dossier projets trouvé: {PROJECTS_FOLDER}")
        print_info(f"Projets détectés: {projects_count}")
        
        for project in projects:
            print(f"    📁 {project}")
    else:
        print_warning(f"Dossier projets non trouvé: {PROJECTS_FOLDER}")
    
    # Vérifier le dossier containers
    if os.path.exists(CONTAINERS_FOLDER):
        containers = [d for d in os.listdir(CONTAINERS_FOLDER) if os.path.isdir(os.path.join(CONTAINERS_FOLDER, d))]
        containers_count = len(containers)
        print_success(f"Dossier containers trouvé: {CONTAINERS_FOLDER}")
        print_info(f"Configurations Docker: {containers_count}")
        
        for container in containers:
            print(f"    🐳 {container}")
    else:
        print_warning(f"Dossier containers non trouvé: {CONTAINERS_FOLDER}")
    
    return projects_count, containers_count

def check_permissions():
    """Vérifie les permissions"""
    print_header("VÉRIFICATION PERMISSIONS")
    
    # Vérifier les groupes de l'utilisateur
    try:
        import grp
        import pwd
        
        current_user = pwd.getpwuid(os.getuid()).pw_name
        user_groups = [grp.getgrgid(gid).gr_name for gid in os.getgroups()]
        
        print_info(f"Utilisateur actuel: {current_user}")
        print_info(f"Groupes: {', '.join(user_groups)}")
        
        if 'www-data' in user_groups:
            print_success("Utilisateur dans le groupe www-data")
        else:
            print_warning("Utilisateur PAS dans le groupe www-data")
            print_info("Exécutez: sudo usermod -a -G www-data $USER")
        
        if 'docker' in user_groups:
            print_success("Utilisateur dans le groupe docker")
        else:
            print_warning("Utilisateur PAS dans le groupe docker")
            
    except Exception as e:
        print_error(f"Erreur lors de la vérification des permissions: {e}")
        return False
    
    # Tester l'écriture dans projets
    if os.path.exists(PROJECTS_FOLDER):
        test_file = os.path.join(PROJECTS_FOLDER, '.test_write')
        try:
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            print_success("Écriture dans le dossier projets: OK")
        except Exception as e:
            print_error(f"Impossible d'écrire dans {PROJECTS_FOLDER}: {e}")
            
    return True

def check_ssl_certificates():
    """Vérifie les certificats SSL"""
    print_header("VÉRIFICATION CERTIFICATS SSL")
    
    cert_paths = [
        '/etc/letsencrypt/live/dev.akdigital.fr/fullchain.pem',
        './traefik/fullchain.pem'
    ]
    
    cert_found = False
    for cert_path in cert_paths:
        if os.path.exists(cert_path):
            print_success(f"Certificat trouvé: {cert_path}")
            cert_found = True
            
            # Vérifier les permissions
            try:
                stat_info = os.stat(cert_path)
                print_info(f"Permissions: {oct(stat_info.st_mode)[-3:]}")
            except Exception as e:
                print_warning(f"Impossible de vérifier les permissions: {e}")
        else:
            print_warning(f"Certificat non trouvé: {cert_path}")
    
    if cert_found:
        print_success("Certificats SSL configurés")
    else:
        print_error("Aucun certificat SSL trouvé")
        
    return cert_found

def generate_summary(docker_ok, traefik_ok, ports_ok, projects_count, containers_count, permissions_ok, ssl_ok):
    """Génère un résumé du diagnostic"""
    print_header("RÉSUMÉ DU DIAGNOSTIC")
    
    total_checks = 6
    passed_checks = sum([docker_ok, traefik_ok, ports_ok, permissions_ok, ssl_ok, projects_count > 0])
    
    print(f"Score de santé: {passed_checks}/{total_checks}")
    print()
    
    if docker_ok and traefik_ok and ports_ok and ssl_ok:
        print_success("🎉 Système entièrement opérationnel !")
        print_info("Vous pouvez créer des sites avec SSL automatique")
    elif docker_ok and ports_ok:
        print_warning("⚡ Système partiellement opérationnel")
        print_info("Vous pouvez créer des sites (sans SSL automatique)")
    else:
        print_error("🔧 Système nécessite une maintenance")
        print_info("Corrigez les erreurs ci-dessus avant de continuer")
    
    print(f"\nProjets: {projects_count} | Configurations: {containers_count}")

def main():
    """Fonction principale"""
    print("🔍 DIAGNOSTIC DU SYSTÈME WORDPRESS LAUNCHER")
    print("Version: 2.0 - Système robuste avec SSL automatique")
    
    # Exécuter les vérifications
    docker_ok = check_docker()
    traefik_ok = check_traefik()
    ports_ok = check_ports()
    projects_count, containers_count = check_projects()
    permissions_ok = check_permissions()
    ssl_ok = check_ssl_certificates()
    
    # Générer le résumé
    generate_summary(docker_ok, traefik_ok, ports_ok, projects_count, containers_count, permissions_ok, ssl_ok)
    
    print(f"\n{'='*60}")
    print("Diagnostic terminé")
    print(f"{'='*60}")

if __name__ == "__main__":
    main() 