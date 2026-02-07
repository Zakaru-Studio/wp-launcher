#!/usr/bin/env python3
"""
WordPress Launcher - Point d'entrée principal
Application Flask utilisant une architecture modulaire
"""
import os
import sys

# Ajouter le répertoire courant au path Python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Charger les variables d'environnement depuis .env
from dotenv import load_dotenv
load_dotenv()

# Importer les fonctions de factory depuis le package app
from app import create_app, create_socketio_instance, init_app_services, register_socketio_handlers

# Créer l'application Flask et SocketIO
app = create_app()
socketio = create_socketio_instance(app)

# Initialiser les services et blueprints
init_app_services(app, socketio)

# Enregistrer les handlers SocketIO
register_socketio_handlers(socketio)

if __name__ == '__main__':
    print("🚀 Démarrage de WordPress Launcher (version modulaire)...")
    print("📁 Architecture modulaire chargée:")
    print("   • Package principal: app/")
    print("   • Config: app/config/")
    print("   • Routes: app/routes/")
    print("   • Services: app/services/")
    print("   • Models: app/models/")
    print("   • Utils: app/utils/")
    print("   • Static: app/static/")
    print("   • Templates: app/templates/")
    
    # Démarrer l'application avec SocketIO
    socketio.run(
        app, 
        debug=False,  # Désactivé pour éviter les problèmes de socket
        host='0.0.0.0', 
        port=5000, 
        allow_unsafe_werkzeug=True,
        use_reloader=False  # Désactiver le reloader pour éviter les conflits
    )

