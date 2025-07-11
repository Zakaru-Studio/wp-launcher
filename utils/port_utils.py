#!/usr/bin/env python3
"""
Utilitaires pour la gestion des ports - Version robuste
"""
import os
import re
import subprocess
import socket
from config.app_config import PROJECTS_FOLDER, CONTAINERS_FOLDER


def is_port_in_use(port):
    """Vérifie si un port est utilisé en tentant de se connecter"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            return result == 0
    except Exception:
        return False


def get_comprehensive_used_ports():
    """Récupère tous les ports utilisés de manière exhaustive"""
    used_ports = set()
    
    # 1. Ports utilisés par Docker
    try:
        result = subprocess.run(['docker', 'ps', '--format', '{{.Ports}}'], 
                               capture_output=True, text=True, timeout=10)
        for line in result.stdout.strip().split('\n'):
            if line:
                port_matches = re.findall(r'0\.0\.0\.0:(\d+)->', line)
                used_ports.update(int(port) for port in port_matches)
    except Exception as e:
        print(f"⚠️ Erreur Docker ps: {e}")
    
    # 2. Ports des projets existants depuis containers/
    containers_folder = CONTAINERS_FOLDER if os.path.exists(CONTAINERS_FOLDER) else 'containers'
    if os.path.exists(containers_folder):
        for project in os.listdir(containers_folder):
            project_path = os.path.join(containers_folder, project)
            if os.path.isdir(project_path):
                # Lire les fichiers de ports
                port_files = ['.port', '.pma_port', '.mailpit_port', '.smtp_port', '.nextjs_port']
                for port_file in port_files:
                    port_file_path = os.path.join(project_path, port_file)
                    if os.path.exists(port_file_path):
                        try:
                            with open(port_file_path, 'r') as f:
                                port = int(f.read().strip())
                                used_ports.add(port)
                        except (ValueError, IOError):
                            pass
    
    # 3. Ports des projets depuis projets/ (fallback)
    if os.path.exists(PROJECTS_FOLDER):
        for project in os.listdir(PROJECTS_FOLDER):
            project_path = os.path.join(PROJECTS_FOLDER, project)
            if os.path.isdir(project_path):
                port_file = os.path.join(project_path, '.port')
                if os.path.exists(port_file):
                    try:
                        with open(port_file, 'r') as f:
                            port = int(f.read().strip())
                            used_ports.add(port)
                    except (ValueError, IOError):
                        pass
    
    # 4. Ports système via netstat (plus robuste)
    try:
        result = subprocess.run(['ss', '-tuln'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.strip().split('\n'):
            if ':' in line and 'LISTEN' in line:
                port_match = re.search(r':(\d+)\s+.*LISTEN', line)
                if port_match:
                    port = int(port_match.group(1))
                    if 8000 <= port <= 9000:  # Seulement dans notre plage
                        used_ports.add(port)
    except Exception as e:
        print(f"⚠️ Erreur ss: {e}")
        # Fallback avec netstat
        try:
            result = subprocess.run(['netstat', '-tuln'], capture_output=True, text=True, timeout=5)
            for line in result.stdout.strip().split('\n'):
                if ':' in line and 'LISTEN' in line:
                    port_match = re.search(r':(\d+)\s+', line)
                    if port_match:
                        port = int(port_match.group(1))
                        if 8000 <= port <= 9000:
                            used_ports.add(port)
        except Exception:
            pass
    
    return used_ports


def find_free_port_for_project(start_port=8080):
    """Trouve un port libre pour un nouveau projet - Version robuste"""
    used_ports = get_comprehensive_used_ports()
    
    print(f"🔍 Ports utilisés détectés: {sorted(used_ports)}")
    
    # Trouver un port libre
    port = start_port
    max_attempts = 50  # Éviter les boucles infinies
    attempts = 0
    
    while port <= 9000 and attempts < max_attempts:
        attempts += 1
        
        if port not in used_ports:
            # Double vérification avec test de connexion
            if not is_port_in_use(port):
                print(f"✅ Port libre trouvé: {port}")
                return port
            else:
                print(f"⚠️ Port {port} détecté comme utilisé par test de connexion")
                used_ports.add(port)
        
        port += 1
    
    raise Exception(f"Aucun port libre trouvé entre {start_port} et 9000 après {attempts} tentatives")


def get_used_ports():
    """Récupère la liste des ports utilisés"""
    used_ports = set()
    
    # Ports utilisés par Docker
    try:
        result = subprocess.run(['docker', 'ps', '--format', '{{.Ports}}'], 
                               capture_output=True, text=True)
        for line in result.stdout.strip().split('\n'):
            if line:
                port_matches = re.findall(r'0\.0\.0\.0:(\d+)->', line)
                used_ports.update(int(port) for port in port_matches)
    except Exception:
        pass
    
    # Ports des projets existants
    if os.path.exists(PROJECTS_FOLDER):
        for project in os.listdir(PROJECTS_FOLDER):
            project_path = os.path.join(PROJECTS_FOLDER, project)
            if os.path.isdir(project_path):
                port_file = os.path.join(project_path, '.port')
                if os.path.exists(port_file):
                    try:
                        with open(port_file, 'r') as f:
                            used_ports.add(int(f.read().strip()))
                    except (ValueError, IOError):
                        pass
    
    return list(used_ports)


def is_port_available(port):
    """Vérifie si un port est disponible"""
    used_ports = get_used_ports()
    return port not in used_ports


def save_project_port(project_path, port):
    """Sauvegarde le port d'un projet"""
    port_file = os.path.join(project_path, '.port')
    with open(port_file, 'w') as f:
        f.write(str(port))


def get_project_port(project_path):
    """Récupère le port d'un projet"""
    port_file = os.path.join(project_path, '.port')
    if os.path.exists(port_file):
        try:
            with open(port_file, 'r') as f:
                return int(f.read().strip())
        except (ValueError, IOError):
            return None
    return None 