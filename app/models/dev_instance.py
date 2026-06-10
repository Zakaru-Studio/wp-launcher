"""
DevInstance model for development instances
"""
from datetime import datetime


class DevInstance:
    """Development instance model"""
    
    def __init__(self, id=None, name=None, slug=None, parent_project=None, owner_username=None,
                 port=None, db_name=None, created_at=None, status='stopped', ports=None):
        if not slug and owner_username:
            # Le dossier de l'instance est créé avec le username NETTOYÉ ;
            # le fallback doit appliquer le même nettoyage, sinon les
            # usernames avec majuscules/points pointent vers un dossier
            # qui n'existe pas.
            from app.utils.slug_utils import clean_username_for_slug
            slug = clean_username_for_slug(owner_username)
        self.id = id
        self.name = name                    # ex: "test_dev_pancin" (nom complet pour Docker/DB)
        self.slug = slug                    # ex: "pancin" (nom simple pour dossier)
        self.parent_project = parent_project # ex: "test"
        self.owner_username = owner_username
        self.port = port  # Port principal WordPress
        self.ports = ports or {'wordpress': port}  # Tous les ports alloués
        self.db_name = db_name
        self.created_at = created_at or datetime.now()
        self.status = status  # 'running', 'stopped', 'creating'
    
    def to_dict(self):
        """Convert instance to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'parent_project': self.parent_project,
            'owner_username': self.owner_username,
            'port': self.port,
            'ports': self.ports,  # Inclure tous les ports
            'db_name': self.db_name,
            'created_at': self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            'status': self.status
        }

