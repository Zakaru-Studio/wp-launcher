#!/usr/bin/env python3
"""
Configuration centralisée pour la gestion des ports
"""

class PortsConfig:
    """Configuration pour l'allocation et la gestion des ports"""
    
    # Plage de ports disponibles pour les projets
    RANGE_START = 8080
    RANGE_END = 9000
    
    # Port par défaut de l'application
    APP_PORT = 5000
    
    # Fichiers de sauvegarde des ports par service
    PORT_FILES = {
        'wordpress': '.port',
        'phpmyadmin': '.pma_port',
        'mailpit': '.mailpit_port',
        'smtp': '.smtp_port',
        'nextjs': '.nextjs_port',
        'mongodb': '.mongodb_port',
        'mongo_express': '.mongo_express_port'
    }
    
    # Ports par défaut pour certains services
    DEFAULT_PORTS = {
        'wordpress': 8080,
        'phpmyadmin': 8081,
        'mailpit': 8082,
        'smtp': 1025,
        'nextjs': 3000,
        'mongodb': 27017,
        'mongo_express': 8083
    }
    
    # Services qui nécessitent des ports séquentiels
    SEQUENTIAL_SERVICES = ['wordpress', 'phpmyadmin', 'mailpit', 'nextjs']
    
    # Timeouts pour la vérification des ports (en secondes)
    PORT_CHECK_TIMEOUT = 1
    DOCKER_TIMEOUT = 5
    SYSTEM_TIMEOUT = 10
    
    @classmethod
    def get_port_range(cls):
        """Retourne la plage de ports sous forme de tuple"""
        return (cls.RANGE_START, cls.RANGE_END)
    
    @classmethod
    def get_port_file_path(cls, container_path, service):
        """Retourne le chemin complet vers le fichier de port d'un service"""
        import os
        if service in cls.PORT_FILES:
            return os.path.join(container_path, cls.PORT_FILES[service])
        return None
    
    @classmethod
    def is_valid_port(cls, port):
        """Vérifie si un port est dans la plage valide"""
        return cls.RANGE_START <= port <= cls.RANGE_END
    
    @classmethod
    def get_next_port(cls, current_port, increment=1):
        """Retourne le port suivant dans la plage valide"""
        next_port = current_port + increment
        return next_port if cls.is_valid_port(next_port) else None