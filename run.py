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
    from app.utils import security_config

    port = int(os.getenv('APP_PORT', '5000'))
    # Loopback par défaut : ce chemin utilise le serveur de développement
    # Werkzeug, qui n'a rien à faire face à Internet. La production passe
    # par scripts/start.sh (gunicorn + eventlet).
    host = os.getenv('WPL_BIND') or (
        '0.0.0.0' if security_config.is_local_mode() else '127.0.0.1'
    )

    print(f"🚀 Starting WP Launcher on {host}:{port}...")
    if host != '127.0.0.1':
        print("⚠️  Serveur de développement exposé au-delà de la loopback — "
              "utilisez scripts/start.sh (gunicorn) pour un déploiement réel.")

    socketio.run(
        app,
        debug=False,
        host=host,
        port=port,
        allow_unsafe_werkzeug=True,
        use_reloader=False
    )

