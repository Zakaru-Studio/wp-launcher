#!/usr/bin/env python3
"""
Utilitaires pour la gestion des ports - Module canonique consolidé.

Ce module est la source de vérité pour toute la logique liée aux ports :
- Détection des ports utilisés (sockets, Docker, fichiers projet)
- Recherche de ports libres
- Résolution automatique des conflits de ports (classe PortConflictResolver)

Note: l'ancien module `port_conflict_resolver` est conservé comme shim
rétro-compatible qui ré-exporte depuis ici.
"""
import os
import re
import subprocess
import socket
from typing import Dict, List, Set

from app.config.app_config import PROJECTS_FOLDER, CONTAINERS_FOLDER
from app.config.docker_config import DockerConfig


# ---------------------------------------------------------------------------
# Helpers de bas niveau
# ---------------------------------------------------------------------------

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
    """Récupère tous les ports utilisés de manière exhaustive - UNIQUEMENT les containers actifs"""
    used_ports = set()

    # 1. Ports utilisés par Docker (containers actifs uniquement)
    try:
        result = subprocess.run(['docker', 'ps', '--format', '{{.Ports}}'],
                               capture_output=True, text=True, timeout=10)
        for line in result.stdout.strip().split('\n'):
            if line:
                port_matches = re.findall(r'0\.0\.0\.0:(\d+)->', line)
                used_ports.update(int(port) for port in port_matches)
    except Exception as e:
        print(f"⚠️ Erreur Docker ps: {e}")

    # 2. Ports système en écoute (double vérification)
    try:
        result = subprocess.run(['ss', '-tuln'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.strip().split('\n'):
            if 'LISTEN' in line:
                # Extraire le port de la colonne "Local Address:Port"
                # Format: "0.0.0.0:8000" ou "[::]:8000"
                port_match = re.search(r'(?:0\.0\.0\.0|\[::\]):(\d+)', line)
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
                if 'LISTEN' in line:
                    # Extraire le port de la colonne "Local Address:Port"
                    port_match = re.search(r'(?:0\.0\.0\.0|\[::\]):(\d+)', line)
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
    """Récupère la liste des ports utilisés de manière exhaustive

    Agrège : ports exposés par les containers Docker actifs + ports persistés
    dans les fichiers `.port*` des projets (containers/ et projets/).
    Retourne une liste d'entiers.
    """
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

    # Ports des projets existants dans containers/
    containers_folder = 'containers'
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

    # Ports des projets existants dans projets/ (fallback pour compatibilité)
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


# ---------------------------------------------------------------------------
# Résolution automatique des conflits de ports
# ---------------------------------------------------------------------------

class PortConflictResolver:
    """Résout automatiquement les conflits de ports entre conteneurs"""

    def __init__(self, containers_folder='containers'):
        self.containers_folder = containers_folder

    def get_active_docker_ports(self) -> Set[int]:
        """Récupère les ports utilisés par les conteneurs Docker actifs"""
        used_ports = set()

        try:
            result = subprocess.run(['docker', 'ps', '--format', '{{.Ports}}'],
                                  capture_output=True, text=True, check=True)
            for line in result.stdout.strip().split('\n'):
                if line and line != '<none>':
                    port_matches = re.findall(r'0\.0\.0\.0:(\d+)->', line)
                    used_ports.update(int(port) for port in port_matches)

        except Exception as e:
            print(f"Erreur lors de la récupération des ports Docker: {e}")

        return used_ports

    def get_project_ports(self) -> Dict[str, Dict[str, int]]:
        """Récupère les ports de tous les projets"""
        project_ports = {}

        if not os.path.exists(self.containers_folder):
            return project_ports

        for project_name in os.listdir(self.containers_folder):
            project_path = os.path.join(self.containers_folder, project_name)
            if not os.path.isdir(project_path):
                continue

            ports = {}
            port_files = {
                '.port': 'wordpress',
                '.pma_port': 'phpmyadmin',
                '.mailpit_port': 'mailpit',
                '.smtp_port': 'smtp',
                '.nextjs_port': 'nextjs'
            }

            for port_file, service_name in port_files.items():
                port_file_path = os.path.join(project_path, port_file)
                if os.path.exists(port_file_path):
                    try:
                        with open(port_file_path, 'r') as f:
                            port = int(f.read().strip())
                            ports[service_name] = port
                    except (ValueError, IOError):
                        pass

            if ports:
                project_ports[project_name] = ports

        return project_ports

    def find_conflicts(self) -> List[Dict]:
        """Identifie les conflits de ports"""
        docker_ports = self.get_active_docker_ports()
        project_ports = self.get_project_ports()

        conflicts = []
        port_usage = {}

        # Analyser l'utilisation des ports
        for project_name, ports in project_ports.items():
            for service_name, port in ports.items():
                if port in port_usage:
                    port_usage[port].append((project_name, service_name))
                else:
                    port_usage[port] = [(project_name, service_name)]

        # Détecter les conflits
        for port, users in port_usage.items():
            if len(users) > 1:
                conflicts.append({
                    'port': port,
                    'type': 'project_conflict',
                    'users': users
                })
            elif port in docker_ports:
                conflicts.append({
                    'port': port,
                    'type': 'docker_conflict',
                    'users': users
                })

        return conflicts

    def find_free_ports(self, count: int = 1, start: int = 8080) -> List[int]:
        """Trouve des ports libres consécutifs"""
        docker_ports = self.get_active_docker_ports()
        project_ports = self.get_project_ports()

        all_used_ports = set(docker_ports)
        for project_ports_dict in project_ports.values():
            all_used_ports.update(project_ports_dict.values())

        free_ports = []
        port = start

        while len(free_ports) < count and port <= 9000:
            if port not in all_used_ports:
                free_ports.append(port)
                all_used_ports.add(port)  # Éviter les doublons
            port += 1

        return free_ports

    def resolve_project_conflicts(self, project_name: str) -> Dict:
        """Résout les conflits pour un projet spécifique"""
        conflicts = self.find_conflicts()
        project_conflicts = []

        for conflict in conflicts:
            for user in conflict['users']:
                if user[0] == project_name:
                    project_conflicts.append(conflict)
                    break

        if not project_conflicts:
            return {
                'success': True,
                'message': f'Aucun conflit détecté pour {project_name}',
                'changes': []
            }

        project_path = os.path.join(self.containers_folder, project_name)
        if not os.path.exists(project_path):
            return {
                'success': False,
                'message': f'Projet {project_name} non trouvé'
            }

        changes = []

        # Résoudre chaque conflit
        for conflict in project_conflicts:
            old_port = conflict['port']

            # Trouver le service en conflit pour ce projet
            project_service = None
            for user in conflict['users']:
                if user[0] == project_name:
                    project_service = user[1]
                    break

            if not project_service:
                continue

            # Trouver un nouveau port libre
            new_ports = self.find_free_ports(1, old_port + 1)
            if not new_ports:
                continue

            new_port = new_ports[0]

            # Mettre à jour le fichier de port
            port_files = {
                'wordpress': '.port',
                'phpmyadmin': '.pma_port',
                'mailpit': '.mailpit_port',
                'smtp': '.smtp_port',
                'nextjs': '.nextjs_port'
            }

            if project_service in port_files:
                port_file_path = os.path.join(project_path, port_files[project_service])
                with open(port_file_path, 'w') as f:
                    f.write(str(new_port))

                changes.append({
                    'service': project_service,
                    'old_port': old_port,
                    'new_port': new_port,
                    'conflict_type': conflict['type']
                })

        if changes:
            # Mettre à jour le docker-compose.yml
            self._update_docker_compose(project_name, changes)

        return {
            'success': True,
            'message': f'Conflits résolus pour {project_name}',
            'changes': changes
        }

    def _update_docker_compose(self, project_name: str, changes: List[Dict]):
        """Met à jour le fichier docker-compose.yml avec les nouveaux ports"""
        compose_file = os.path.join(self.containers_folder, project_name, 'docker-compose.yml')

        if not os.path.exists(compose_file):
            return

        with open(compose_file, 'r') as f:
            content = f.read()

        # Créer une sauvegarde
        backup_file = f"{compose_file}.backup"
        with open(backup_file, 'w') as f:
            f.write(content)

        # Appliquer les changements
        for change in changes:
            old_port = change['old_port']
            new_port = change['new_port']
            service = change['service']

            # Patterns de remplacement selon le service
            if service == 'wordpress':
                content = re.sub(
                    rf'"0\.0\.0\.0:{old_port}:80"',
                    f'"0.0.0.0:{new_port}:80"',
                    content
                )
            elif service == 'phpmyadmin':
                content = re.sub(
                    rf'"0\.0\.0\.0:{old_port}:80"',
                    f'"0.0.0.0:{new_port}:80"',
                    content
                )
                content = re.sub(
                    rf'PMA_ABSOLUTE_URI: http://192\.168\.1\.21:{old_port}/',
                    f'PMA_ABSOLUTE_URI: http://{DockerConfig.LOCAL_IP}:{new_port}/',
                    content
                )
            elif service == 'mailpit':
                content = re.sub(
                    rf'"0\.0\.0\.0:{old_port}:8025"',
                    f'"0.0.0.0:{new_port}:8025"',
                    content
                )
            elif service == 'smtp':
                content = re.sub(
                    rf'"0\.0\.0\.0:{old_port}:1025"',
                    f'"0.0.0.0:{new_port}:1025"',
                    content
                )
            elif service == 'nextjs':
                content = re.sub(
                    rf'"0\.0\.0\.0:{old_port}:3000"',
                    f'"0.0.0.0:{new_port}:3000"',
                    content
                )

        # Sauvegarder le fichier modifié
        with open(compose_file, 'w') as f:
            f.write(content)

        print(f"✅ docker-compose.yml mis à jour pour {project_name}")

    def get_diagnostic_report(self) -> Dict:
        """Génère un rapport de diagnostic complet"""
        docker_ports = self.get_active_docker_ports()
        project_ports = self.get_project_ports()
        conflicts = self.find_conflicts()

        return {
            'docker_ports': sorted(docker_ports),
            'project_ports': project_ports,
            'conflicts': conflicts,
            'total_conflicts': len(conflicts),
            'next_free_port': self.find_free_ports(1)[0] if self.find_free_ports(1) else None
        }
