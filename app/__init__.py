#!/usr/bin/env python3
"""
WordPress Launcher - Package principal
Application Flask avec architecture modulaire
"""
import os
import sys

# Ajouter le répertoire parent au path Python pour permettre les imports depuis app/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, g, session
from flask_socketio import SocketIO, join_room, leave_room, emit

def create_app():
    """Factory pour créer et configurer l'application Flask"""
    from dotenv import load_dotenv
    load_dotenv()
    
    from app.config.app_config import create_app as _create_app, init_services
    from app.config.app_config import APP_VERSION
    
    # Créer l'application Flask
    app = _create_app()
    
    # Before request handler global pour charger l'utilisateur sur toutes les routes
    @app.before_request
    def load_user():
        """Charger l'utilisateur connecté avant chaque requête"""
        g.current_user = None
        
        # Si système auth activé, charger l'utilisateur
        if hasattr(app, 'extensions') and 'user_service' in app.extensions:
            if 'user_id' in session:
                user_service = app.extensions['user_service']
                g.current_user = user_service.get_user_by_id(session['user_id'])
    
    # Context processor pour rendre les variables globales disponibles dans tous les templates
    @app.context_processor
    def inject_globals():
        """Injecte des variables globales dans tous les templates"""
        return {
            'app_version': APP_VERSION
        }
    
    return app

def create_socketio_instance(app):
    """Créer et configurer l'instance SocketIO"""
    from app.config.app_config import create_socketio
    return create_socketio(app)

def init_app_services(app, socketio):
    """Initialiser tous les services et blueprints"""
    from app.config.app_config import init_services
    
    # Initialiser les services (sans Traefik - accès local uniquement)
    services = init_services(socketio)
    
    # Stocker les services dans les extensions de l'app pour un accès global
    # On exclut le service Traefik car l'exposition publique est désactivée
    filtered_services = {k: v for k, v in services.items() if k != 'traefik'}
    app.extensions.update(filtered_services)
    app.extensions['socketio'] = socketio
    
    # Instancier les nouveaux services
    from app.services.permission_service import PermissionService
    from app.services.project_service import ProjectService
    from app.services.wpcli_service import WPCLIService
    from app.services.clone_service import CloneService
    from app.services.git_service import GitService
    from app.services.snapshot_service import SnapshotService
    
    permission_service = PermissionService()
    wpcli_service = WPCLIService(timeout=60)
    git_service = GitService()
    project_service = ProjectService(
        docker_service=services.get('docker'),
        permission_service=permission_service,
        database_service=services.get('database')
    )
    clone_service = CloneService(
        docker_service=services.get('docker'),
        database_service=services.get('database'),
        wpcli_service=wpcli_service
    )
    # Récupérer socketio depuis les extensions
    socketio = app.extensions.get('socketio')
    snapshot_service = SnapshotService(socketio=socketio)
    
    # Ajouter les nouveaux services aux extensions Flask
    app.extensions['permission_service'] = permission_service
    app.extensions['project_service'] = project_service
    app.extensions['wpcli_service'] = wpcli_service
    app.extensions['clone_service'] = clone_service
    app.extensions['git_service'] = git_service
    app.extensions['snapshot_service'] = snapshot_service
    
    # Enregistrer les blueprints (modules de routes)
    from app.routes.main import main_bp
    from app.routes.projects import projects_bp
    from app.routes.project_lifecycle import project_lifecycle_bp
    from app.routes.project_nextjs import project_nextjs_bp
    from app.routes.project_maintenance import project_maintenance_bp
    from app.routes.project_wpcli import project_wpcli_bp
    from app.routes.project_clone import project_clone_bp
    from app.routes.project_snapshots import project_snapshots_bp
    from app.routes.database import database_bp
    from app.routes.config import config_bp
    from app.routes.logs import logs_bp
    from app.routes.monitoring import monitoring_bp
    from app.routes.system import system_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(project_lifecycle_bp)
    app.register_blueprint(project_nextjs_bp)
    app.register_blueprint(project_maintenance_bp)
    app.register_blueprint(project_wpcli_bp)
    app.register_blueprint(project_clone_bp)
    app.register_blueprint(project_snapshots_bp)
    
    # WP Debug
    from app.routes.project_wpdebug import project_wpdebug_bp
    app.register_blueprint(project_wpdebug_bp)
    app.register_blueprint(database_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(system_bp)
    
    # ==================== MULTI-DEV SYSTEM ====================
    # Système multi-dev avec mode compatibilité (fonctionne même sans auth)
    try:
        from app.services.user_service import UserService
        from app.services.oauth_service import GitHubOAuthService
        from app.services.dev_instance_service import DevInstanceService
        
        user_service = UserService()
        oauth_service = GitHubOAuthService(
            client_id=os.environ.get('GITHUB_CLIENT_ID', ''),
            client_secret=os.environ.get('GITHUB_CLIENT_SECRET', '')
        )
        dev_instance_service = DevInstanceService()
        
        app.extensions['user_service'] = user_service
        app.extensions['oauth_service'] = oauth_service
        app.extensions['dev_instance_service'] = dev_instance_service
        
        # Blueprints multi-dev
        from app.routes.auth import auth_bp
        from app.routes.dev_instances import dev_instances_bp
        from app.routes.admin import admin_bp
        
        app.register_blueprint(auth_bp)
        app.register_blueprint(dev_instances_bp)
        app.register_blueprint(admin_bp)
        
        # Config session
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')
        app.config['SESSION_COOKIE_NAME'] = 'wp_launcher_session'
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        app.config['PERMANENT_SESSION_LIFETIME'] = 2592000  # 30 jours
        
        print("✅ Système multi-dev activé")
        
    except ImportError as e:
        print(f"⚠️  Système multi-dev non disponible: {e}")
        print("⚠️  Mode compatibilité activé (branche main)")
    except Exception as e:
        print(f"⚠️  Erreur lors de l'initialisation multi-dev: {e}")
        print("⚠️  L'application continue sans authentification")

def register_socketio_handlers(socketio):
    """Enregistrer les handlers SocketIO"""
    
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
            join_room(project_name)
            print(f'📡 Client rejoint la room du projet: {project_name}')
    
    @socketio.on('leave_project')
    def handle_leave_project(data):
        """Quitter une room de projet"""
        project_name = data.get('project_name')
        if project_name:
            leave_room(project_name)
            print(f'📡 Client quitte la room du projet: {project_name}')
    
    # Gestionnaires d'événements pour les tâches synchronisées
    @socketio.on('task_created')
    def handle_task_created(data):
        """Relayer la création de tâche aux autres clients"""
        print(f'📡 Relai création tâche: {data.get("taskName")} {data.get("projectName", "")}')
        emit('task_created', data, broadcast=True, include_self=False)
    
    @socketio.on('task_updated')
    def handle_task_updated(data):
        """Relayer la mise à jour de tâche aux autres clients"""
        print(f'📡 Relai mise à jour tâche: {data.get("taskId")}')
        emit('task_updated', data, broadcast=True, include_self=False)
    
    @socketio.on('task_completed')
    def handle_task_completed(data):
        """Relayer la completion de tâche aux autres clients"""
        print(f'📡 Relai completion tâche: {data.get("taskId")} - {"Succès" if data.get("success") else "Erreur"}')
        emit('task_completed', data, broadcast=True, include_self=False)
        
        # Si c'est une tâche de projet, émettre aussi le changement de statut
        if data.get('taskType') in ['start_project', 'stop_project'] and data.get('projectName'):
            project_status = 'running' if data.get('taskType') == 'start_project' and data.get('success') else 'stopped'
            emit('project_status_changed', {
                'projectName': data.get('projectName'),
                'status': project_status
            }, broadcast=True)

