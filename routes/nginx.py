#!/usr/bin/env python3
"""
Routes pour la gestion de l'exposition des sites via Traefik
"""
from flask import Blueprint, request, jsonify, current_app
from models.project import Project

nginx_bp = Blueprint('nginx', __name__)

@nginx_bp.route('/expose_site', methods=['POST'])
def expose_site():
    """Expose un site via Traefik"""
    try:
        data = request.get_json()
        project_name = data.get('project_name')
        hostname = data.get('hostname')
        
        if not project_name or not hostname:
            return jsonify({
                'success': False, 
                'message': 'Nom du projet et hostname requis'
            })
        
        # Vérifier que le projet existe
        project = Project(project_name)
        if not project.exists:
            return jsonify({
                'success': False, 
                'message': 'Projet non trouvé'
            })
        
        # Récupérer le port du projet
        port = project.port
        if not port:
            return jsonify({
                'success': False, 
                'message': 'Port du projet non trouvé'
            })
        
        # Vérifier que le projet est démarré
        docker_service = current_app.extensions.get('docker')
        if docker_service:
            container_status = docker_service.get_container_status(project_name)
            if container_status != 'active':
                return jsonify({
                    'success': False, 
                    'message': 'Le projet doit être démarré pour être exposé'
                })
        
        # Exposer le site
        traefik_service = current_app.extensions.get('traefik')
        if traefik_service:
            result = traefik_service.expose_site(project_name, hostname, port)
            
            if result['success']:
                print(f"Site {project_name} exposé sur {hostname}")
            else:
                print(f"Erreur exposition site {project_name}: {result['message']}")
            
            return jsonify(result)
        else:
            return jsonify({
                'success': False,
                'message': 'Service Traefik non disponible'
            })
        
    except Exception as e:
        print(f"Erreur lors de l'exposition du site: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Erreur: {str(e)}'
        })


@nginx_bp.route('/unexpose_site', methods=['POST'])
def unexpose_site():
    """Retire l'exposition d'un site"""
    try:
        data = request.get_json()
        project_name = data.get('project_name')
        force_mode = data.get('force', False)
        
        if not project_name:
            return jsonify({
                'success': False, 
                'message': 'Nom du projet requis'
            })
        
        # Retirer l'exposition
        traefik_service = current_app.extensions.get('traefik')
        if traefik_service:
            if force_mode:
                result = traefik_service.force_unexpose_site(project_name)
            else:
                result = traefik_service.unexpose_site(project_name)
            
            if result['success']:
                print(f"Site {project_name} retiré d'internet")
            else:
                print(f"Erreur retrait site {project_name}: {result['message']}")
            
            return jsonify(result)
        else:
            return jsonify({
                'success': False,
                'message': 'Service Traefik non disponible'
            })
        
    except Exception as e:
        print(f"Erreur lors du retrait du site: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Erreur: {str(e)}'
        })


@nginx_bp.route('/get_exposed_sites')
def get_exposed_sites():
    """Récupère la liste des sites exposés"""
    try:
        traefik_service = current_app.extensions.get('traefik')
        if traefik_service:
            exposed_sites = traefik_service.get_exposed_sites()
            return jsonify({
                'success': True,
                'sites': exposed_sites
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Service Traefik non disponible'
            })
        
    except Exception as e:
        print(f"Erreur récupération sites exposés: {str(e)}")
        return jsonify({
            'success': False, 
            'message': f'Erreur: {str(e)}'
        })


@nginx_bp.route('/traefik_status')
def traefik_status():
    """Récupère le statut de Traefik"""
    try:
        traefik_service = current_app.extensions.get('traefik')
        if traefik_service:
            result = traefik_service.get_traefik_status()
            return jsonify(result)
        else:
            return jsonify({
                'success': False,
                'message': 'Service Traefik non disponible'
            })
        
    except Exception as e:
        print(f"Erreur récupération statut Traefik: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


@nginx_bp.route('/start_traefik', methods=['POST'])
def start_traefik():
    """Démarre Traefik"""
    try:
        traefik_service = current_app.extensions.get('traefik')
        if traefik_service:
            result = traefik_service.start_traefik()
            return jsonify(result)
        else:
            return jsonify({
                'success': False,
                'message': 'Service Traefik non disponible'
            })
        
    except Exception as e:
        print(f"Erreur démarrage Traefik: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


@nginx_bp.route('/traefik_help')
def traefik_help():
    """Aide pour Traefik"""
    help_content = {
        'title': 'Aide Traefik',
        'sections': [
            {
                'title': 'Installation',
                'content': [
                    'Traefik est installé via Docker Compose',
                    'Répertoire: traefik/',
                    'Commande: cd traefik && ./install.sh'
                ]
            },
            {
                'title': 'Configuration',
                'content': [
                    'Dashboard: http://localhost:8080',
                    'Dashboard sécurisé: https://traefik.dev.akdigital.fr',
                    'Réseau: traefik-network',
                    'Certificats SSL automatiques via Let\'s Encrypt'
                ]
            },
            {
                'title': 'Utilisation',
                'content': [
                    'Les projets sont automatiquement connectés au réseau Traefik',
                    'Les labels Traefik sont ajoutés lors de l\'exposition',
                    'SSL automatique pour tous les sites exposés'
                ]
            },
            {
                'title': 'Dépannage',
                'content': [
                    'Vérifiez que Traefik est en cours d\'exécution',
                    'Vérifiez que le réseau traefik-network existe',
                    'Vérifiez les logs: docker-compose logs traefik'
                ]
            }
        ]
    }
    
    return jsonify({
        'success': True,
        'help': help_content
    }) 