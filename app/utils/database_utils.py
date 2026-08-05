#!/usr/bin/env python3
"""Small database-adjacent helpers.

This module used to carry a second, parallel implementation of "talk to a
project's MySQL": ``create_clean_wordpress_database``, ``smart_mysql_check``,
``intelligent_mysql_wait``, ``execute_mysql_command``, ``check_database_exists``,
``get_database_size``, ``backup_database`` and two ``update_wordpress_urls``
variants. All of them hard-coded ``-u wordpress -pwordpress`` and
``<project>_mysql_1``, all of them predated per-project credential
randomisation, and none of them was reachable — the only two still imported
anywhere (``create_clean_wordpress_database``, ``intelligent_mysql_wait``)
were imported by :mod:`app.routes.project_lifecycle` and never called.

They are gone. Anything that needs to reach a database goes through
:func:`app.utils.db_target.db_target`, which resolves the container and the
credentials rather than assuming them. URL rewriting in particular must use
``wp search-replace`` (see :mod:`app.services.db_push`) — the raw SQL
``REPLACE()`` statements that lived here silently corrupted serialised PHP.
"""
import secrets
import string


def generate_wordpress_security_keys():
    """Génère les clés de sécurité WordPress"""
    def generate_key():
        chars = string.ascii_letters + string.digits + '!@#$%^&*(-_=+)'
        return ''.join(secrets.choice(chars) for _ in range(64))

    return {
        'AUTH_KEY': generate_key(),
        'SECURE_AUTH_KEY': generate_key(),
        'LOGGED_IN_KEY': generate_key(),
        'NONCE_KEY': generate_key(),
        'AUTH_SALT': generate_key(),
        'SECURE_AUTH_SALT': generate_key(),
        'LOGGED_IN_SALT': generate_key(),
        'NONCE_SALT': generate_key()
    }


def detect_file_encoding(file_path):
    """Détecte l'encodage d'un fichier et retourne son contenu"""
    encodings_to_try = ['utf-8', 'latin-1', 'windows-1252', 'iso-8859-1']

    for encoding in encodings_to_try:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
                print(f"✅ Encodage détecté: {encoding}")
                return encoding, content
        except UnicodeDecodeError:
            print(f"⚠️ Échec avec encodage {encoding}")
            continue

    print("❌ Impossible de décoder le fichier avec les encodages supportés")
    return None, None
