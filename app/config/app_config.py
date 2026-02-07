
#!/usr/bin/env python3
"""
Configuration centralisée pour WordPress Launcher
"""
import os
from flask import Flask
from flask_socketio import SocketIO
from app.config.docker_config import DockerConfig
from app.utils.version_utils import get_git_version

# Configuration des constantes (utilise DockerConfig pour la cohérence)
UPLOAD_FOLDER = DockerConfig.UPLOADS_FOLDER
PROJECTS_FOLDER = DockerConfig.PROJECTS_FOLDER
CONTAINERS_FOLDER = DockerConfig.CONTAINERS_FOLDER
ALLOWED_EXTENSIONS = {'zip', 'sql', 'gz'}

# Configuration de l'URL de l'application
APP_HOST = DockerConfig.LOCAL_IP
APP_PORT = DockerConfig.APP_PORT
APP_URL = f"http://{APP_HOST}:{APP_PORT}"

# Version de l'application depuis Git
APP_VERSION = get_git_version()

def create_app():
    """Créer et configurer l'application Flask"""
    # Spécifier le répertoire racine pour les templates et static
    # __file__ est dans app/config/, donc dirname(dirname(__file__)) = app/
    import os
    app_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    app = Flask(__name__, 
                template_folder=os.path.join(app_path, 'templates'),
                static_folder=os.path.join(app_path, 'static'))
    app.secret_key = os.getenv('SECRET_KEY', 'change-me-in-production')
    
    # Configuration Flask
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024  # 5GB max
    app.config['JSON_SORT_KEYS'] = False  # Préserver l'ordre des clés dans les réponses JSON
    
    # Créer les dossiers nécessaires
    DockerConfig.ensure_directories()
    
    return app

def create_socketio(app):
    """Créer et configurer SocketIO"""
    return SocketIO(app, cors_allowed_origins="*")

def init_services(socketio):
    """Initialiser tous les services"""
    from app.services.docker_service import DockerService
    from app.services.port_service import PortService
    from app.services.database_service import DatabaseService
    from app.services.fast_import_service import FastImportService
    from app.services.mysql_manager import MySQLManager
    from app.services.config_service import ConfigService
    from app.services.monitoring_service import MonitoringService
    
    # Initialisation des services
    docker_service = DockerService()
    port_service = PortService()
    database_service = DatabaseService(socketio)
    fast_import_service = FastImportService(socketio)
    mysql_manager = MySQLManager(socketio)
    config_service = ConfigService()
    monitoring_service = MonitoringService()
    
    return {
        'docker': docker_service,
        'port': port_service,
        'database_service': database_service,
        'fast_import_service': fast_import_service,
        'mysql_manager': mysql_manager,
        'config': config_service,
        'monitoring': monitoring_service
    } 