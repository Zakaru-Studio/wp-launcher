#!/usr/bin/env python3
"""
WordPress Launcher - Version modulaire
Application Flask principale utilisant une architecture modulaire
"""
import os
import sys

# Ajouter le répertoire courant au path Python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.app_config import create_app, create_socketio, init_services
from routes.main import main_bp
from routes.projects import projects_bp
from routes.database import database_bp
from routes.nginx import nginx_bp

# Créer l'application Flask et SocketIO
app = create_app()
socketio = create_socketio(app)

# Initialiser les services (sans Traefik - accès local uniquement)
services = init_services(socketio)

# Stocker les services dans les extensions de l'app pour un accès global
# On exclut le service Traefik car l'exposition publique est désactivée
filtered_services = {k: v for k, v in services.items() if k != 'traefik'}
app.extensions.update(filtered_services)
app.extensions['socketio'] = socketio

# Enregistrer les blueprints (modules de routes)
app.register_blueprint(main_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(database_bp)
app.register_blueprint(nginx_bp)

# Routes SocketIO pour les mises à jour en temps réel
@socketio.on('connect')
def handle_connect():
    """Gestion de la connexion WebSocket"""
    print('🔌 Client connecté via WebSocket')

@socketio.on('disconnect')
def handle_disconnect():
    """Gestion de la déconnexion WebSocket"""
    print('🔌 Client déconnecté du WebSocket')

@socketio.on('join_project')
def handle_join_project(data):
    """Rejoindre une room pour un projet spécifique"""
    project_name = data.get('project_name')
    if project_name:
        from flask_socketio import join_room
        join_room(project_name)
        print(f'📡 Client rejoint la room du projet: {project_name}')

@socketio.on('leave_project')
def handle_leave_project(data):
    """Quitter une room de projet"""
    project_name = data.get('project_name')
    if project_name:
        from flask_socketio import leave_room
        leave_room(project_name)
        print(f'📡 Client quitte la room du projet: {project_name}')

if __name__ == '__main__':
    print("🚀 Démarrage de WordPress Launcher (version modulaire)...")
    print("📁 Architecture modulaire chargée:")
    print("   • Config: config/app_config.py")
    print("   • Routes: routes/")
    print("   • Utils: utils/")
    print("   • Services: services/")
    print("   • Models: models/")
    
    # Démarrer l'application avec SocketIO
    socketio.run(
        app, 
        debug=True, 
        host='0.0.0.0', 
        port=5000, 
        allow_unsafe_werkzeug=True
    )