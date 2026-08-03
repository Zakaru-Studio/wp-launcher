#!/usr/bin/env python3
"""
Configuration centralisée pour les bases de données MySQL
"""

class DatabaseConfig:
    """Configuration pour les connexions et opérations MySQL"""
    
    # Identifiants HÉRITÉS, partagés par tous les projets créés avant la
    # randomisation par projet. Ils ne valent plus que comme repli : tout
    # nouveau code doit passer par app.utils.project_credentials, qui lit
    # l'environnement du conteneur puis le docker-compose.
    # Alias explicites pour qu'un seul grep trouve tous les consommateurs.
    from app.utils.security_config import (
        LEGACY_MYSQL_DATABASE as _LEGACY_DB,
        LEGACY_MYSQL_PASSWORD as _LEGACY_PW,
        LEGACY_MYSQL_ROOT_PASSWORD as _LEGACY_ROOT_PW,
        LEGACY_MYSQL_USER as _LEGACY_USER,
    )

    DEFAULT_USER = _LEGACY_USER
    DEFAULT_PASSWORD = _LEGACY_PW
    DEFAULT_DB = _LEGACY_DB
    ROOT_PASSWORD = _LEGACY_ROOT_PW
    
    # Configuration du charset
    CHARSET = 'utf8mb4'
    COLLATION = 'utf8mb4_unicode_ci'
    
    # Encodages supportés pour la détection de fichiers
    SUPPORTED_ENCODINGS = ['utf-8', 'latin-1', 'windows-1252', 'iso-8859-1']
    
    # Timeouts (en secondes)
    CONNECTION_TIMEOUT = 2
    WAIT_TIMEOUT = 60
    IMPORT_TIMEOUT = 1800  # 30 minutes
    
    # Paramètres d'optimisation MySQL
    MYSQL_SETTINGS = {
        'innodb_buffer_pool_size': '1G',
        'key_buffer_size': '256M',
        'sort_buffer_size': '64M',
        'read_buffer_size': '64M',
        'myisam_sort_buffer_size': '8M',
        'thread_cache_size': '8',
        'query_cache_size': '16M',
        'tmp_table_size': '256M',
        'max_heap_table_size': '256M',
        'slow_query_log': '1',
        'long_query_time': '1',
        'innodb_flush_log_at_trx_commit': '0',
        'innodb_log_buffer_size': '64M'
    }
    
    @classmethod
    def get_connection_string(cls, host='localhost', port=3306, database=None):
        """Génère une chaîne de connexion MySQL"""
        database = database or cls.DEFAULT_DB
        return f"mysql://{cls.DEFAULT_USER}:{cls.DEFAULT_PASSWORD}@{host}:{port}/{database}"
    
    @classmethod
    def get_root_connection_string(cls, host='localhost', port=3306, database=None):
        """Génère une chaîne de connexion MySQL en tant que root"""
        database = database or cls.DEFAULT_DB
        return f"mysql://root:{cls.ROOT_PASSWORD}@{host}:{port}/{database}"