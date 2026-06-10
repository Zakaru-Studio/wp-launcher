#!/usr/bin/env python3
"""
Service de gestion des ports - Version simplifiée utilisant utils/port_utils.py
"""

from app.utils.port_utils import get_used_ports, find_free_port_for_project, get_comprehensive_used_ports, is_port_in_use
from app.config.ports_config import PortsConfig
from app.config.docker_config import DockerConfig
from app.utils.logger import wp_logger

class PortService:
    """Service pour la gestion des ports des projets - Interface simplifiée"""
    
    def __init__(self, projects_folder=None, containers_folder=None):
        self.projects_folder = projects_folder or DockerConfig.PROJECTS_FOLDER
        self.containers_folder = containers_folder or DockerConfig.CONTAINERS_FOLDER
        self.port_range_start, self.port_range_end = PortsConfig.get_port_range()
    
    def find_free_port(self, start_port=None):
        """Trouve un port libre pour un nouveau projet"""
        if start_port is None:
            start_port = self.port_range_start
        
        return find_free_port_for_project(start_port)
    
    def allocate_ports_for_project(self, enable_nextjs=False, extra_used_ports=None):
        """Alloue tous les ports nécessaires pour un projet

        extra_used_ports : ports supplémentaires à considérer comme
        occupés (ex: ports d'instances dev arrêtées, invisibles pour
        get_used_ports() qui ne voit que les conteneurs actifs).
        """
        wp_logger.log_system_info(f"Allocation de ports pour nouveau projet",
                                 enable_nextjs=enable_nextjs,
                                 port_range=f"{self.port_range_start}-{self.port_range_end}")

        ports = {}
        used_ports = set(get_used_ports())
        if extra_used_ports:
            used_ports.update(int(p) for p in extra_used_ports)

        def next_free(candidate):
            """Premier port libre >= candidate.

            En plus de la liste agrégée (Docker + fichiers .port +
            extra_used_ports), chaque candidat subit un test socket
            réel : get_used_ports() ne voit pas les processus hôtes
            (ex: un service local sur 8080), ce qui produisait des
            "address already in use" au démarrage du conteneur.
            """
            while candidate <= self.port_range_end:
                if candidate not in used_ports and not is_port_in_use(candidate):
                    used_ports.add(candidate)  # réservé pour cette allocation
                    return candidate
                candidate += 1
            error_msg = f"Aucun port libre trouvé entre {self.port_range_start} et {self.port_range_end}"
            wp_logger.log_system_info(f"Erreur allocation ports: {error_msg}",
                                    used_ports_count=len(used_ports),
                                    port_range=f"{self.port_range_start}-{self.port_range_end}")
            raise Exception(error_msg)

        # Allocation séquentielle pour éviter les conflits
        current_port = self.port_range_start

        ports['wordpress'] = next_free(current_port)
        ports['phpmyadmin'] = next_free(ports['wordpress'] + 1)
        ports['mailpit'] = next_free(ports['phpmyadmin'] + 1)
        ports['smtp'] = next_free(ports['mailpit'] + 1)

        # Port Next.js si nécessaire
        if enable_nextjs:
            ports['nextjs'] = next_free(ports['smtp'] + 1)

        wp_logger.log_system_info(f"Ports alloués avec succès",
                                 ports=ports,
                                 enable_nextjs=enable_nextjs,
                                 total_ports=len(ports))

        return ports
    
    def is_port_available(self, port):
        """Vérifie si un port est disponible"""
        used_ports = get_used_ports()
        return port not in used_ports
    
    def get_port_usage_info(self):
        """Retourne des informations sur l'utilisation des ports"""
        used_ports = get_comprehensive_used_ports()
        
        return {
            'used_ports': sorted(used_ports),
            'available_range': f"{self.port_range_start}-{self.port_range_end}",
            'next_available': self.find_free_port(),
            'total_used': len(used_ports)
        } 