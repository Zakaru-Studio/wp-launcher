#!/usr/bin/env python3
"""
Routes propres aux projets Payload CMS (commandes npm) et logs de conteneurs.
"""

import os

from flask import Blueprint, current_app, jsonify, request, session

from app.config.docker_config import DockerConfig
from app.middleware.auth_middleware import login_required
from app.services import payload_service
from app.utils.project_utils import get_project_type

project_payload_bp = Blueprint('project_payload', __name__)

#: Services dont on peut lire les logs, par type de projet.
_LOG_SERVICES = {
    'payload': ('payload', 'postgres', 'adminer', 'mailpit'),
    'wordpress': ('wordpress', 'mysql', 'phpmyadmin', 'mailpit'),
    'nextjs': ('client', 'api', 'mysql', 'mongodb', 'mailpit'),
}

_MAX_LOG_LINES = 2000


#: Blueprints qui supposent WordPress (wp-cli, wp-config, wp-content) :
#: leurs routes refusent un projet Payload au lieu d'échouer au milieu.
_WORDPRESS_ONLY_BLUEPRINTS = ('project_wpcli', 'project_wpdebug', 'project_clone',
                              'project_snapshots')


@project_payload_bp.before_app_request
def _refuse_wordpress_features_for_payload():
    if request.blueprint not in _WORDPRESS_ONLY_BLUEPRINTS or not request.view_args:
        return None
    # Hors session, laisser login_required rediriger : ne rien révéler du
    # projet à un visiteur non connecté.
    if 'user_id' not in session:
        return None
    project_name = request.view_args.get('project_name') or request.view_args.get('source_name')
    if project_name and _project_type(project_name) == 'payload':
        return jsonify({'success': False,
                        'message': 'Fonction non supportée pour les projets Payload'}), 400
    return None


def _project_type(project_name):
    path = os.path.join(DockerConfig.PROJECTS_FOLDER, project_name)
    if not os.path.isdir(path):
        return None
    return get_project_type(path)


@project_payload_bp.route('/payload/<project_name>/cmd/<command>', methods=['POST'])
@login_required
def payload_command(project_name, command):
    """Lance une commande npm de la liste blanche dans le conteneur de l'app."""
    project_type = _project_type(project_name)
    if project_type is None:
        return jsonify({'success': False, 'message': 'Projet non trouvé'}), 404
    if project_type != 'payload':
        return jsonify({'success': False, 'message': "Ce projet n'est pas un projet Payload"}), 400
    if command not in payload_service.ALLOWED_COMMANDS:
        return jsonify({'success': False, 'message': f'Commande non autorisée: {command}'}), 400

    success, output = payload_service.run_command(project_name, command)
    return jsonify({
        'success': success,
        'message': f'{command} terminé' if success else f'{command} a échoué',
        'output': output[-20000:],
    })


@project_payload_bp.route('/api/projects/<project_name>/logs', methods=['GET'])
@login_required
def container_logs(project_name):
    """Dernières lignes des logs d'un conteneur du projet.

    ``?service=`` (défaut : le service principal du type de projet) et
    ``?tail=`` (défaut 500, plafonné).
    """
    project_type = _project_type(project_name)
    if project_type is None:
        return jsonify({'success': False, 'message': 'Projet non trouvé'}), 404

    services = _LOG_SERVICES.get(project_type, ())
    service = request.args.get('service') or (services[0] if services else '')
    if service not in services:
        return jsonify({'success': False, 'message': f'Service inconnu: {service}'}), 400

    try:
        tail = max(1, min(int(request.args.get('tail', 500)), _MAX_LOG_LINES))
    except ValueError:
        tail = 500

    docker_service = current_app.extensions.get('docker')
    if not docker_service:
        return jsonify({'success': False, 'message': 'Service Docker non disponible'}), 503

    return jsonify({
        'success': True,
        'service': service,
        'services': list(services),
        'logs': docker_service.get_container_logs(project_name, service, tail),
    })
