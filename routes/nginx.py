#!/usr/bin/env python3
"""
Routes pour la gestion de l'exposition des sites - DÉSACTIVÉ
L'exposition publique des sites a été supprimée pour privilégier l'accès local uniquement.
"""
from flask import Blueprint, jsonify

nginx_bp = Blueprint('nginx', __name__)

@nginx_bp.route('/expose_site', methods=['POST'])
def expose_site():
    """Exposition publique désactivée"""
    return jsonify({
        'success': False, 
        'message': 'Exposition publique désactivée - Utilisez l\'accès local uniquement (IP:port)'
    })

@nginx_bp.route('/unexpose_site', methods=['POST'])
def unexpose_site():
    """Exposition publique désactivée"""
    return jsonify({
        'success': False, 
        'message': 'Exposition publique désactivée'
    })

@nginx_bp.route('/get_exposed_sites')
def get_exposed_sites():
    """Retourne une liste vide car l'exposition est désactivée"""
    return jsonify({
        'success': True,
        'sites': {}
    })

@nginx_bp.route('/traefik_status')
def traefik_status():
    """Traefik désactivé"""
    return jsonify({
        'success': False,
        'message': 'Traefik désactivé - Accès local uniquement'
    })

@nginx_bp.route('/start_traefik', methods=['POST'])
def start_traefik():
    """Traefik désactivé"""
    return jsonify({
        'success': False,
        'message': 'Traefik désactivé - Accès local uniquement'
    })

@nginx_bp.route('/traefik_help')
def traefik_help():
    """Aide pour l'accès local"""
    help_content = {
        'title': 'Accès Local Uniquement',
        'sections': [
            {
                'title': 'Configuration',
                'content': [
                    'L\'exposition publique a été désactivée',
                    'Utilisez les URLs locales IP:port uniquement',
                    'Plus rapide et plus simple à gérer'
                ]
            },
            {
                'title': 'Accès aux projets',
                'content': [
                    'WordPress: http://192.168.1.21:PORT',
                    'phpMyAdmin: http://192.168.1.21:PMA_PORT',
                    'Mailpit: http://192.168.1.21:MAILPIT_PORT'
                ]
            }
        ]
    }
    
    return jsonify({
        'success': True,
        'help': help_content
    }) 