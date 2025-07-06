#!/usr/bin/env python3
"""
Routes principales de l'application
"""

from flask import Blueprint, render_template

# Créer le blueprint principal
main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Page d'accueil avec le formulaire de création de projet"""
    return render_template('index.html') 