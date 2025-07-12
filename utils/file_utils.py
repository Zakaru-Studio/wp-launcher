#!/usr/bin/env python3
"""
Utilitaires pour la gestion des fichiers
"""
import os
import zipfile
from config.app_config import ALLOWED_EXTENSIONS


def allowed_file(filename):
    """Vérifie si le fichier a une extension autorisée"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_zip(zip_path, extract_to):
    """Extrait un fichier ZIP vers le dossier de destination"""
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)


def get_file_size(file_obj):
    """Récupère la taille d'un fichier"""
    current_pos = file_obj.tell()
    file_obj.seek(0, 2)  # Aller à la fin du fichier
    size = file_obj.tell()
    file_obj.seek(current_pos)  # Retourner à la position initiale
    return size


def is_sql_file(filename):
    """Vérifie si le fichier est un fichier SQL"""
    return filename.lower().endswith(('.sql', '.sql.gz'))


def is_zip_file(filename):
    """Vérifie si le fichier est un fichier ZIP"""
    return filename.lower().endswith('.zip')


def get_file_size_mb(file_path):
    """Retourne la taille d'un fichier en MB"""
    try:
        size_bytes = os.path.getsize(file_path)
        return size_bytes / (1024 * 1024)
    except OSError:
        return 0 