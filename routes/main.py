#!/usr/bin/env python3
"""
Routes principales de l'application
"""
import platform
import subprocess
from flask import Blueprint, render_template, send_from_directory, jsonify

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Page d'accueil de l'application"""
    return render_template('index.html')


@main_bp.route('/debug')
def debug_interface():
    """Page de debug pour identifier les problèmes de redirection de ports"""
    return send_from_directory('.', 'debug_interface.html')


@main_bp.route('/favicon.png')
def favicon():
    """Favicon de l'application"""
    return send_from_directory('static', 'favicon.png')


@main_bp.route('/server_info')
def server_info():
    """Informations sur le serveur"""
    try:
        # Informations système
        info = {
            'os': platform.system(),
            'os_version': platform.release(),
            'python_version': platform.python_version(),
            'hostname': platform.node(),
            'architecture': platform.machine()
        }
        
        # Informations Docker
        try:
            docker_version = subprocess.run(['docker', '--version'], 
                                          capture_output=True, text=True)
            info['docker_version'] = docker_version.stdout.strip() if docker_version.returncode == 0 else 'Non disponible'
        except:
            info['docker_version'] = 'Non disponible'
        
        # Informations Docker Compose
        try:
            compose_version = subprocess.run(['docker-compose', '--version'], 
                                           capture_output=True, text=True)
            info['compose_version'] = compose_version.stdout.strip() if compose_version.returncode == 0 else 'Non disponible'
        except:
            info['compose_version'] = 'Non disponible'
        
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500 