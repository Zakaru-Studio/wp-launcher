#!/usr/bin/env python3
"""
Routes pour la gestion de la configuration WP Debug
"""

import os
import re
from flask import Blueprint, request, jsonify
from app.models.project import Project
from app.config.docker_config import DockerConfig
from app.utils.logger import wp_logger

project_wpdebug_bp = Blueprint('project_wpdebug', __name__)

PROJECTS_FOLDER = 'projets'
CONTAINERS_FOLDER = 'containers'


def is_dev_instance(project_name):
    """Vérifie si le nom correspond à une instance dev"""
    return '_dev_' in project_name


def get_wp_config_path(project_name: str) -> str:
    """
    Retourne le chemin vers le wp-config.php d'un projet ou d'une instance
    
    Args:
        project_name: Nom du projet ou de l'instance (ex: 'test' ou 'test_dev_pancin')
        
    Returns:
        str: Chemin complet vers wp-config.php
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    if is_dev_instance(project_name):
        # Instance dev: format test_dev_pancin -> projets/test/.dev-instances/pancin/wp-config.php
        parts = project_name.split('_dev_')
        if len(parts) == 2:
            parent_project = parts[0]
            instance_slug = parts[1]
            
            # Charger le service dev_instance pour obtenir l'owner
            from app.services.dev_instance_service import DevInstanceService
            dev_instance_service = DevInstanceService()
            instance = dev_instance_service.get_instance_by_name(project_name)
            
            if instance:
                wp_config_path = os.path.join(
                    root_dir, PROJECTS_FOLDER, parent_project, 
                    '.dev-instances', instance.owner_username, instance_slug,
                    'wp-config.php'
                )
                return wp_config_path
    
    # Projet normal
    return os.path.join(root_dir, PROJECTS_FOLDER, project_name, 'wp-config.php')


def parse_wp_config_constant(content: str, constant: str) -> bool:
    """
    Parse une constante dans wp-config.php
    
    Returns:
        bool: True si la constante est définie à true, False sinon
    """
    # Chercher la définition de la constante
    pattern = rf"define\s*\(\s*['\"]?{constant}['\"]?\s*,\s*(\w+)\s*\)"
    match = re.search(pattern, content, re.IGNORECASE)
    
    if match:
        value = match.group(1).lower()
        return value == 'true'
    
    return False


def set_wp_config_constant(content: str, constant: str, value: bool) -> str:
    """
    Modifie ou ajoute une constante dans wp-config.php
    
    Args:
        content: Contenu du fichier wp-config.php
        constant: Nom de la constante (ex: WP_DEBUG)
        value: Valeur (True/False)
        
    Returns:
        str: Nouveau contenu du fichier
    """
    value_str = 'true' if value else 'false'
    
    # Pattern pour trouver la définition existante
    pattern = rf"define\s*\(\s*['\"]?{constant}['\"]?\s*,\s*\w+\s*\)\s*;"
    
    # Vérifier si la constante existe déjà
    if re.search(pattern, content, re.IGNORECASE):
        # Remplacer la valeur existante
        new_define = f"define( '{constant}', {value_str} );"
        content = re.sub(pattern, new_define, content, flags=re.IGNORECASE)
    else:
        # Ajouter la constante après la première occurrence de define
        # Chercher un bon endroit pour insérer (après DB_COLLATE ou après le premier define)
        insert_pattern = r"(define\s*\([^)]+\)\s*;)"
        match = re.search(insert_pattern, content)
        
        if match:
            insert_pos = match.end()
            new_line = f"\ndefine( '{constant}', {value_str} );"
            content = content[:insert_pos] + new_line + content[insert_pos:]
        else:
            # Si aucun define trouvé, ajouter au début après <?php
            php_tag_pos = content.find('<?php')
            if php_tag_pos >= 0:
                insert_pos = content.find('\n', php_tag_pos) + 1
                new_line = f"define( '{constant}', {value_str} );\n"
                content = content[:insert_pos] + new_line + content[insert_pos:]
    
    return content


@project_wpdebug_bp.route('/wp-debug/get/<project_name>', methods=['GET'])
def get_wp_debug_config(project_name):
    """
    Récupère la configuration WP Debug actuelle
    """
    try:
        # Vérifier que le projet ou l'instance existe
        if not is_dev_instance(project_name):
            project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
            if not project.exists:
                return jsonify({
                    'success': False,
                    'message': 'Projet non trouvé'
                })
        
        # Chemin vers wp-config.php (gère les projets et les instances)
        wp_config_path = get_wp_config_path(project_name)
        
        if not os.path.exists(wp_config_path):
            return jsonify({
                'success': False,
                'message': 'Fichier wp-config.php non trouvé'
            })
        
        # Lire le fichier
        with open(wp_config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parser les constantes
        config = {
            'WP_DEBUG': parse_wp_config_constant(content, 'WP_DEBUG'),
            'WP_DEBUG_LOG': parse_wp_config_constant(content, 'WP_DEBUG_LOG'),
            'WP_DEBUG_DISPLAY': parse_wp_config_constant(content, 'WP_DEBUG_DISPLAY'),
            'SCRIPT_DEBUG': parse_wp_config_constant(content, 'SCRIPT_DEBUG'),
            'SAVEQUERIES': parse_wp_config_constant(content, 'SAVEQUERIES')
        }
        
        print(f"✅ [WP_DEBUG] Configuration chargée pour {project_name}: {config}")
        
        return jsonify({
            'success': True,
            'config': config
        })
        
    except Exception as e:
        print(f"❌ [WP_DEBUG] Erreur get: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


@project_wpdebug_bp.route('/wp-debug/set/<project_name>', methods=['POST'])
def set_wp_debug_config(project_name):
    """
    Modifie une constante WP Debug
    
    Body JSON:
        constant: str - Nom de la constante
        value: bool - Valeur (true/false)
    """
    try:
        # Vérifier que le projet ou l'instance existe
        if not is_dev_instance(project_name):
            project = Project(project_name, PROJECTS_FOLDER, CONTAINERS_FOLDER)
            if not project.exists:
                return jsonify({
                    'success': False,
                    'message': 'Projet non trouvé'
                })
        
        # Récupérer les données
        data = request.get_json()
        constant = data.get('constant')
        value = data.get('value', False)
        
        # Valider la constante
        allowed_constants = ['WP_DEBUG', 'WP_DEBUG_LOG', 'WP_DEBUG_DISPLAY', 'SCRIPT_DEBUG', 'SAVEQUERIES']
        if constant not in allowed_constants:
            return jsonify({
                'success': False,
                'message': f'Constante non autorisée: {constant}'
            })
        
        # Chemin vers wp-config.php (gère les projets et les instances)
        wp_config_path = get_wp_config_path(project_name)
        
        if not os.path.exists(wp_config_path):
            return jsonify({
                'success': False,
                'message': 'Fichier wp-config.php non trouvé'
            })
        
        # Lire le fichier
        with open(wp_config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Modifier la constante
        new_content = set_wp_config_constant(content, constant, value)
        
        # Sauvegarder le fichier
        with open(wp_config_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"✅ [WP_DEBUG] {constant} = {value} pour {project_name}")
        
        # Relire la configuration complète
        config = {
            'WP_DEBUG': parse_wp_config_constant(new_content, 'WP_DEBUG'),
            'WP_DEBUG_LOG': parse_wp_config_constant(new_content, 'WP_DEBUG_LOG'),
            'WP_DEBUG_DISPLAY': parse_wp_config_constant(new_content, 'WP_DEBUG_DISPLAY'),
            'SCRIPT_DEBUG': parse_wp_config_constant(new_content, 'SCRIPT_DEBUG'),
            'SAVEQUERIES': parse_wp_config_constant(new_content, 'SAVEQUERIES')
        }
        
        wp_logger.logger.info(f"WP Debug modifié: {project_name} - {constant} = {value}")
        
        return jsonify({
            'success': True,
            'message': f'{constant} modifié avec succès',
            'config': config
        })
        
    except Exception as e:
        print(f"❌ [WP_DEBUG] Erreur set: {e}")
        import traceback
        traceback.print_exc()
        wp_logger.logger.error(f"Erreur modification WP Debug: {e}")
        return jsonify({
            'success': False,
            'message': f'Erreur: {str(e)}'
        })


