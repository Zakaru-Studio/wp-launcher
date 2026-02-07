#!/usr/bin/env python3
"""
Configuration centralisée pour Docker et gestion des projets
"""
import os

class DockerConfig:
    """Configuration pour les services Docker et structure des projets"""
    
    # Chemin racine de l'application (remonter de app/config/ vers la racine)
    ROOT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Chemins des dossiers principaux (absolus)
    TEMPLATE_PATH = os.path.join(ROOT_PATH, 'docker-template')
    PROJECTS_FOLDER = os.path.join(ROOT_PATH, 'projets')
    CONTAINERS_FOLDER = os.path.join(ROOT_PATH, 'containers')
    UPLOADS_FOLDER = os.path.join(ROOT_PATH, 'uploads')
    
    # Utilisateurs et permissions
    WWW_USER = 'www-data:www-data'
    DEV_USER = 'dev-server:dev-server'
    
    # Permissions par défaut
    DIRECTORY_PERMISSIONS = 0o755
    FILE_PERMISSIONS = 0o644
    CONFIG_FILE_PERMISSIONS = 0o600
    UPLOADS_PERMISSIONS = 0o775
    UPLOADS_FILE_PERMISSIONS = 0o664
    
    # Timeouts Docker (en secondes)
    START_TIMEOUT = 120
    STOP_TIMEOUT = 60
    COMMAND_TIMEOUT = 30
    
    # Configuration réseau locale (charge depuis .env ou utilise valeur par défaut)
    LOCAL_IP = os.getenv('APP_HOST', '192.168.1.21')
    APP_PORT = os.getenv('APP_PORT', '5000')
    
    # Noms des services Docker standards
    SERVICES = {
        'mysql': 'mysql',
        'wordpress': 'wordpress', 
        'phpmyadmin': 'phpmyadmin',
        'mailpit': 'mailpit',
        'nextjs': 'nextjs',
        'mongodb': 'mongodb',
        'mongo_express': 'mongo-express'
    }
    
    # Templates docker-compose
    COMPOSE_TEMPLATES = {
        'wordpress_only': 'docker-compose-no-nextjs.yml',
        'wordpress_nextjs': 'docker-compose.yml',
        'nextjs_mongo': 'docker-compose-nextjs-mongo.yml',
        'nextjs_mysql': 'docker-compose-nextjs-mysql.yml'
    }
    
    @classmethod
    def get_project_path(cls, project_name):
        """Retourne le chemin vers les fichiers éditables d'un projet"""
        return os.path.join(cls.PROJECTS_FOLDER, project_name)
    
    @classmethod
    def get_container_path(cls, project_name):
        """Retourne le chemin vers la configuration Docker d'un projet"""
        return os.path.join(cls.CONTAINERS_FOLDER, project_name)
    
    @classmethod
    def get_project_url(cls, port, path=''):
        """Génère une URL locale pour un projet"""
        base_url = f"http://{cls.LOCAL_IP}:{port}"
        return f"{base_url}/{path}" if path else base_url
    
    @classmethod
    def ensure_directories(cls):
        """Crée les dossiers nécessaires s'ils n'existent pas"""
        directories = [
            cls.PROJECTS_FOLDER,
            cls.CONTAINERS_FOLDER,
            cls.UPLOADS_FOLDER
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)