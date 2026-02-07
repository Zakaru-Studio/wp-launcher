"""
DevInstance model for development instances
"""
from datetime import datetime


class DevInstance:
    """Development instance model"""
    
    def __init__(self, id=None, name=None, slug=None, parent_project=None, owner_username=None, 
                 port=None, db_name=None, created_at=None, status='stopped', ports=None):
        self.id = id
        self.name = name                    # ex: "test-dev-pancin" (nom complet pour Docker/DB)
        self.slug = slug or owner_username  # ex: "pancin" (nom simple pour dossier)
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

