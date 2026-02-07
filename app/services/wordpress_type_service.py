#!/usr/bin/env python3
"""
Service pour la gestion du type de WordPress (vitrine vs WooCommerce)
Gère la détection, les limites de ressources et la configuration
"""

import os
from pathlib import Path
from typing import Dict, Optional


class WordPressTypeService:
    """Service de gestion du type WordPress et des limites de ressources associées"""
    
    # Types WordPress supportés
    TYPE_SHOWCASE = 'showcase'
    TYPE_WOOCOMMERCE = 'woocommerce'
    
    def __init__(self, projects_folder='projets', containers_folder='containers'):
        self.projects_folder = projects_folder
        self.containers_folder = containers_folder
    
    def detect_woocommerce(self, project_name: str) -> bool:
        """
        Détecte si WooCommerce est installé dans un projet
        
        Args:
            project_name: Nom du projet
            
        Returns:
            True si WooCommerce est détecté, False sinon
        """
        woocommerce_path = Path(self.projects_folder) / project_name / 'wp-content' / 'plugins' / 'woocommerce'
        
        # Vérifier si le dossier woocommerce existe et contient des fichiers
        if woocommerce_path.exists() and woocommerce_path.is_dir():
            # Vérifier qu'il contient au moins le fichier principal
            main_file = woocommerce_path / 'woocommerce.php'
            return main_file.exists()
        
        return False
    
    def get_wordpress_type(self, project_name: str) -> str:
        """
        Récupère le type WordPress d'un projet
        
        Args:
            project_name: Nom du projet
            
        Returns:
            'showcase' ou 'woocommerce'
        """
        # Vérifier si le fichier .wp_type existe
        wp_type_file = Path(self.containers_folder) / project_name / '.wp_type'
        
        if wp_type_file.exists():
            try:
                with open(wp_type_file, 'r') as f:
                    wp_type = f.read().strip()
                    if wp_type in [self.TYPE_SHOWCASE, self.TYPE_WOOCOMMERCE]:
                        return wp_type
            except Exception as e:
                print(f"⚠️ Erreur lecture .wp_type pour {project_name}: {e}")
        
        # Si le fichier n'existe pas, détecter automatiquement
        if self.detect_woocommerce(project_name):
            return self.TYPE_WOOCOMMERCE
        
        return self.TYPE_SHOWCASE
    
    def save_wordpress_type(self, project_name: str, wp_type: str) -> bool:
        """
        Sauvegarde le type WordPress d'un projet
        
        Args:
            project_name: Nom du projet
            wp_type: 'showcase' ou 'woocommerce'
            
        Returns:
            True si succès, False sinon
        """
        if wp_type not in [self.TYPE_SHOWCASE, self.TYPE_WOOCOMMERCE]:
            print(f"❌ Type WordPress invalide: {wp_type}")
            return False
        
        container_path = Path(self.containers_folder) / project_name
        
        # Créer le dossier containers si nécessaire
        if not container_path.exists():
            try:
                container_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"❌ Erreur création dossier container pour {project_name}: {e}")
                return False
        
        wp_type_file = container_path / '.wp_type'
        
        try:
            with open(wp_type_file, 'w') as f:
                f.write(wp_type)
            print(f"✅ Type WordPress sauvegardé pour {project_name}: {wp_type}")
            return True
        except Exception as e:
            print(f"❌ Erreur sauvegarde .wp_type pour {project_name}: {e}")
            return False
    
    def get_memory_limits(self, wp_type: str) -> Dict[str, str]:
        """
        Retourne les limites de ressources selon le type WordPress
        
        Args:
            wp_type: 'showcase' ou 'woocommerce'
            
        Returns:
            Dictionnaire avec les limites de mémoire et CPU
        """
        if wp_type == self.TYPE_WOOCOMMERCE:
            return {
                'wordpress_memory': '512m',
                'mysql_memory': '512m',
                'wordpress_cpu': '2.0',
                'mysql_cpu': '2.0'
            }
        else:  # showcase par défaut
            return {
                'wordpress_memory': '256m',
                'mysql_memory': '256m',
                'wordpress_cpu': '1.0',
                'mysql_cpu': '1.0'
            }
    
    def get_wordpress_type_label(self, wp_type: str) -> str:
        """
        Retourne le label français du type WordPress
        
        Args:
            wp_type: 'showcase' ou 'woocommerce'
            
        Returns:
            Label en français
        """
        if wp_type == self.TYPE_WOOCOMMERCE:
            return "WordPress WooCommerce (512Mo / 2 CPU)"
        else:
            return "WordPress Vitrine (256Mo / 1 CPU)"
    
    def get_all_types(self) -> Dict[str, Dict[str, str]]:
        """
        Retourne tous les types WordPress disponibles avec leurs informations
        
        Returns:
            Dictionnaire avec les types et leurs métadonnées
        """
        return {
            self.TYPE_SHOWCASE: {
                'label': 'WordPress Vitrine',
                'memory': '256Mo RAM',
                'cpu': '1 CPU',
                'icon': 'fas fa-globe'
            },
            self.TYPE_WOOCOMMERCE: {
                'label': 'WordPress WooCommerce',
                'memory': '512Mo RAM',
                'cpu': '2 CPU',
                'icon': 'fas fa-shopping-cart'
            }
        }

