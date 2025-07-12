#!/usr/bin/env python3
"""
Configuration centralisée pour WordPress Launcher
"""
import os
from flask import Flask
from flask_socketio import SocketIO

# Configuration des constantes
UPLOAD_FOLDER = 'uploads'
PROJECTS_FOLDER = 'projets'
CONTAINERS_FOLDER = 'containers'
ALLOWED_EXTENSIONS = {'zip', 'sql', 'gz'}

def create_app():
    """Créer et configurer l'application Flask"""
    # Spécifier le répertoire racine pour les templates et static
    import os
    root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    app = Flask(__name__, 
                template_folder=os.path.join(root_path, 'templates'),
                static_folder=os.path.join(root_path, 'static'))
    app.secret_key = 'wp-launcher-secret-key-2024'
    
    # Configuration Flask
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024  # 5GB max
    
    # Créer les dossiers nécessaires
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(PROJECTS_FOLDER, exist_ok=True)
    
    return app

def create_socketio(app):
    """Créer et configurer SocketIO"""
    return SocketIO(app, cors_allowed_origins="*")

def init_services(socketio):
    """Initialiser tous les services"""
    from services.docker_service import DockerService
    from services.port_service import PortService
    from services.database_service import DatabaseService
    from services.fast_import_service import FastImportService
    from services.traefik_service import TraefikService
    
    # Initialisation des services
    docker_service = DockerService()
    port_service = PortService()
    database_service = DatabaseService(socketio)
    fast_import_service = FastImportService(socketio)
    traefik_service = TraefikService(
        base_domain='akdigital.fr', 
        projects_folder=PROJECTS_FOLDER, 
        containers_folder=CONTAINERS_FOLDER
    )
    
    return {
        'docker': docker_service,
        'port': port_service,
        'database': database_service,
        'fast_import': fast_import_service,
        'traefik': traefik_service
    } 