#!/usr/bin/env python3
"""
Service de gestion des ports
"""

import os
import re
import subprocess

class PortService:
    """Service pour la gestion des ports des projets"""
    
    def __init__(self, projects_folder='projets'):
        self.projects_folder = projects_folder
        self.port_range_start = 8080
        self.port_range_end = 9000
    
    def find_free_port(self, start_port=None):
        """Trouve un port libre pour un nouveau projet"""
        if start_port is None:
            start_port = self.port_range_start
        
        used_ports = self._get_used_ports()
        
        # Trouver un port libre
        port = start_port
        while port in used_ports:
            port += 1
            if port > self.port_range_end:
                raise Exception(f"Aucun port libre trouvé entre {self.port_range_start} et {self.port_range_end}")
        
        return port
    
    def _get_used_ports(self):
        """Récupère tous les ports utilisés"""
        used_ports = set()
        
        # Récupérer les ports utilisés par Docker
        try:
            result = subprocess.run(['docker', 'ps', '--format', '{{.Ports}}'], 
                                   capture_output=True, text=True)
            for line in result.stdout.strip().split('\n'):
                if line:
                    port_matches = re.findall(r'0\.0\.0\.0:(\d+)->', line)
                    used_ports.update(int(port) for port in port_matches)
        except Exception:
            pass
        
        # Récupérer les ports des projets existants
        used_ports.update(self._get_project_ports())
        
        return used_ports
    
    def _get_project_ports(self):
        """Récupère les ports des projets existants"""
        used_ports = set()
        
        if not os.path.exists(self.projects_folder):
            return used_ports
        
        for project in os.listdir(self.projects_folder):
            project_path = os.path.join(self.projects_folder, project)
            if os.path.isdir(project_path):
                # Récupérer tous les fichiers de ports
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
        
        return used_ports
    
    def allocate_ports_for_project(self, enable_nextjs=False):
        """Alloue tous les ports nécessaires pour un projet"""
        ports = {}
        
        # Port WordPress
        ports['wordpress'] = self.find_free_port()
        
        # Port phpMyAdmin
        ports['phpmyadmin'] = self.find_free_port(ports['wordpress'] + 1)
        
        # Port Mailpit
        ports['mailpit'] = self.find_free_port(ports['phpmyadmin'] + 1)
        
        # Port SMTP
        ports['smtp'] = self.find_free_port(ports['mailpit'] + 1)
        
        # Port Next.js si nécessaire
        if enable_nextjs:
            ports['nextjs'] = self.find_free_port(ports['smtp'] + 1)
        
        return ports
    
    def is_port_available(self, port):
        """Vérifie si un port est disponible"""
        used_ports = self._get_used_ports()
        return port not in used_ports
    
    def get_port_usage_info(self):
        """Retourne des informations sur l'utilisation des ports"""
        used_ports = self._get_used_ports()
        docker_ports = self._get_docker_ports()
        project_ports = self._get_project_ports()
        
        return {
            'used_ports': sorted(used_ports),
            'docker_ports': sorted(docker_ports),
            'project_ports': sorted(project_ports),
            'available_range': f"{self.port_range_start}-{self.port_range_end}",
            'next_available': self.find_free_port()
        }
    
    def _get_docker_ports(self):
        """Récupère les ports utilisés par Docker"""
        used_ports = set()
        
        try:
            result = subprocess.run(['docker', 'ps', '--format', '{{.Ports}}'], 
                                   capture_output=True, text=True)
            for line in result.stdout.strip().split('\n'):
                if line:
                    port_matches = re.findall(r'0\.0\.0\.0:(\d+)->', line)
                    used_ports.update(int(port) for port in port_matches)
        except Exception:
            pass
        
        return used_ports 