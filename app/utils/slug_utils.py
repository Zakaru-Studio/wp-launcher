"""
Slug utilities for cleaning and validating identifiers
"""
import re


# Pattern pour les caractères autorisés dans les noms
ALLOWED_CHARS = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')


def clean_username_for_slug(username):
    """
    Nettoie un username pour créer un slug valide
    
    Examples:
        nicolas.tombal@akdigital.fr -> nicolas-tombal
        john.doe@example.com -> john-doe
        alice_wonder -> alice-wonder
    """
    # Extraire la partie avant @ si c'est un email
    if '@' in username:
        username = username.split('@')[0]
    
    # Remplacer les caractères non alphanumériques par des tirets
    slug = re.sub(r'[^a-zA-Z0-9-]', '-', username)
    
    # Éviter les tirets multiples
    slug = re.sub(r'-+', '-', slug)
    
    # Enlever les tirets au début et à la fin
    slug = slug.strip('-').lower()
    
    return slug


def validate_project_name(name):
    """
    Valide un nom de projet
    
    Rules:
        - Doit commencer par une lettre ou un chiffre
        - Ne peut contenir que a-z, A-Z, 0-9, _, -
        - Pas de caractères spéciaux (@, ., espace, etc.)
    
    Raises:
        ValueError: Si le nom est invalide
    
    Returns:
        bool: True si valide
    """
    if not name:
        raise ValueError("Le nom ne peut pas être vide")
    
    if not ALLOWED_CHARS.match(name):
        raise ValueError(
            "Nom invalide : seuls a-z, A-Z, 0-9, _, - sont autorisés. "
            "Le nom doit commencer par une lettre ou un chiffre."
        )
    
    return True


def validate_username(username):
    """
    Valide un nom d'utilisateur
    
    Rules:
        - Doit commencer par une lettre ou un chiffre
        - Ne peut contenir que a-z, A-Z, 0-9, _, -
        - Pas de caractères spéciaux (@, ., espace, etc.)
    
    Raises:
        ValueError: Si le username est invalide
    
    Returns:
        bool: True si valide
    """
    if not username:
        raise ValueError("Le nom d'utilisateur ne peut pas être vide")
    
    if not ALLOWED_CHARS.match(username):
        raise ValueError(
            "Nom d'utilisateur invalide : seuls a-z, A-Z, 0-9, _, - sont autorisés. "
            "Le nom doit commencer par une lettre ou un chiffre."
        )
    
    return True


def generate_instance_slug(parent_project, owner_username):
    """
    Génère un slug pour une instance dev
    
    Examples:
        test, nicolas.tombal@akdigital.fr -> test-dev-nicolas-tombal
        myproject, alice -> myproject-dev-alice
    
    Args:
        parent_project: Nom du projet parent
        owner_username: Username du propriétaire
    
    Returns:
        str: Slug pour l'instance
    """
    clean_user = clean_username_for_slug(owner_username)
    return f"{parent_project}-dev-{clean_user}"


def sanitize_container_name(name):
    """
    Nettoie un nom pour être compatible avec Docker
    
    Docker container names can only contain:
        - alphanumeric characters (a-z, A-Z, 0-9)
        - underscores (_)
        - periods (.)
        - hyphens (-)
    
    Examples:
        test-dev-nicolas.tombal@akdigital.fr -> test-dev-nicolas_tombal_akdigital_fr
    """
    # Remplacer @ et autres caractères spéciaux par des underscores
    clean_name = re.sub(r'[^a-zA-Z0-9._-]', '_', name)
    
    # Éviter les underscores multiples
    clean_name = re.sub(r'_+', '_', clean_name)
    
    return clean_name


def generate_db_name(project_name, suffix=''):
    """
    Génère un nom de base de données MySQL valide
    
    MySQL database names rules:
        - Only alphanumeric and underscores
        - No dots, hyphens, or special characters
        - Max 64 characters
    
    Examples:
        test, dev_alice -> test_dev_alice
        my-project, backup -> my_project_backup
    """
    # Remplacer les tirets par des underscores
    db_name = project_name.replace('-', '_')
    
    if suffix:
        # Nettoyer le suffix de tous les caractères spéciaux
        suffix = suffix.replace('-', '_').replace('.', '_').replace('@', '_')
        # Éviter les underscores multiples dans le suffix
        suffix = re.sub(r'_+', '_', suffix)
        db_name = f"{db_name}_{suffix}"
    
    # Nettoyer tout caractère non alphanumérique/underscore
    db_name = re.sub(r'[^a-zA-Z0-9_]', '_', db_name)
    
    # Éviter les underscores multiples
    db_name = re.sub(r'_+', '_', db_name)
    
    # Enlever les underscores au début et à la fin
    db_name = db_name.strip('_')
    
    # Limiter à 64 caractères (limite MySQL)
    if len(db_name) > 64:
        db_name = db_name[:64].rstrip('_')
    
    return db_name.lower()

