#!/usr/bin/env python3
"""
Script pour gérer automatiquement l'attribution des ports WordPress
"""

import os
import subprocess
import json
import re

def get_used_ports():
    """Récupère la liste des ports utilisés par Docker"""
    try:
        result = subprocess.run(['docker', 'ps', '--format', '{{.Ports}}'], 
                               capture_output=True, text=True)
        ports = []
        for line in result.stdout.strip().split('\n'):
            if line:
                # Extraire les ports de la forme "0.0.0.0:8080->80/tcp"
                port_matches = re.findall(r'0\.0\.0\.0:(\d+)->', line)
                ports.extend([int(port) for port in port_matches])
        return sorted(list(set(ports)))
    except Exception as e:
        print(f"Erreur lors de la récupération des ports: {e}")
        return []

def get_project_ports():
    """Récupère les ports attribués aux projets WP Launcher"""
    projects_ports = {}
    projects_dir = 'projets'
    
    if not os.path.exists(projects_dir):
        return projects_ports
    
    for project_name in os.listdir(projects_dir):
        project_path = os.path.join(projects_dir, project_name)
        if os.path.isdir(project_path):
            # Lire le port depuis le fichier .port
            port_file = os.path.join(project_path, '.port')
            if os.path.exists(port_file):
                try:
                    with open(port_file, 'r') as f:
                        port = int(f.read().strip())
                        projects_ports[project_name] = port
                except (ValueError, IOError):
                    pass
            else:
                # Essayer de lire depuis docker-compose.yml
                compose_file = os.path.join(project_path, 'docker-compose.yml')
                if os.path.exists(compose_file):
                    try:
                        with open(compose_file, 'r') as f:
                            content = f.read()
                            # Chercher la ligne "8080:80"
                            port_match = re.search(r'"(\d+):80"', content)
                            if port_match:
                                port = int(port_match.group(1))
                                projects_ports[project_name] = port
                                # Sauvegarder pour la prochaine fois
                                with open(port_file, 'w') as pf:
                                    pf.write(str(port))
                    except (IOError, ValueError):
                        pass
    
    return projects_ports

def find_free_port(start_port=8080):
    """Trouve un port libre à partir du port de départ"""
    used_ports = get_used_ports()
    project_ports = get_project_ports()
    all_used_ports = set(used_ports + list(project_ports.values()))
    
    port = start_port
    while port in all_used_ports:
        port += 1
        if port > 9000:  # Limite de sécurité
            raise Exception("Aucun port libre trouvé entre 8080 et 9000")
    
    return port

def assign_port_to_project(project_name):
    """Attribue un port à un projet"""
    project_ports = get_project_ports()
    
    # Si le projet a déjà un port, le retourner
    if project_name in project_ports:
        return project_ports[project_name]
    
    # Sinon, trouver un port libre
    port = find_free_port()
    
    # Sauvegarder le port
    project_path = os.path.join('projets', project_name)
    if os.path.exists(project_path):
        port_file = os.path.join(project_path, '.port')
        with open(port_file, 'w') as f:
            f.write(str(port))
    
    return port

def update_docker_compose_port(project_name, port):
    """Met à jour le port dans docker-compose.yml"""
    project_path = os.path.join('projets', project_name)
    compose_file = os.path.join(project_path, 'docker-compose.yml')
    
    if not os.path.exists(compose_file):
        return False
    
    try:
        with open(compose_file, 'r') as f:
            content = f.read()
        
        # Remplacer la ligne du port
        content = re.sub(r'"(\d+):80"', f'"{port}:80"', content)
        
        with open(compose_file, 'w') as f:
            f.write(content)
        
        return True
    except Exception as e:
        print(f"Erreur lors de la mise à jour du port: {e}")
        return False

def list_projects_with_ports():
    """Liste tous les projets avec leurs ports"""
    project_ports = get_project_ports()
    used_ports = get_used_ports()
    
    print("🔍 Projets et leurs ports:")
    print("=" * 40)
    
    for project, port in project_ports.items():
        status = "🟢 LIBRE" if port not in used_ports else "🔴 UTILISÉ"
        print(f"  {project}: {port} ({status})")
    
    print("\n🔍 Ports utilisés sur le système:")
    print("=" * 40)
    for port in used_ports:
        print(f"  Port {port}")

def check_port_conflicts():
    """Vérifie et résout les conflits de ports"""
    project_ports = get_project_ports()
    used_ports = get_used_ports()
    conflicts = []
    
    for project, port in project_ports.items():
        if port in used_ports:
            conflicts.append((project, port))
    
    if conflicts:
        print("⚠️ Conflits de ports détectés:")
        for project, port in conflicts:
            print(f"  {project}: port {port} déjà utilisé")
        
        print("\n🔧 Résolution des conflits...")
        for project, old_port in conflicts:
            new_port = find_free_port(old_port + 1)
            print(f"  {project}: {old_port} → {new_port}")
            
            # Mettre à jour le docker-compose.yml
            if update_docker_compose_port(project, new_port):
                # Mettre à jour le fichier .port
                port_file = os.path.join('projets', project, '.port')
                with open(port_file, 'w') as f:
                    f.write(str(new_port))
                print(f"  ✅ {project} mis à jour")
            else:
                print(f"  ❌ Échec mise à jour {project}")
    else:
        print("✅ Aucun conflit de port détecté")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python3 manage_ports.py [command]")
        print("Commands:")
        print("  list     - Lister les projets et leurs ports")
        print("  check    - Vérifier les conflits de ports")
        print("  assign <project> - Attribuer un port à un projet")
        print("  free     - Trouver le prochain port libre")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "list":
        list_projects_with_ports()
    elif command == "check":
        check_port_conflicts()
    elif command == "assign" and len(sys.argv) > 2:
        project_name = sys.argv[2]
        port = assign_port_to_project(project_name)
        print(f"Port {port} attribué au projet {project_name}")
    elif command == "free":
        port = find_free_port()
        print(f"Prochain port libre: {port}")
    else:
        print("Commande inconnue")
        sys.exit(1) 