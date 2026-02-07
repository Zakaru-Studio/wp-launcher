"""
ProjectMetadata model for unified database management
"""
from datetime import datetime


class ProjectMetadata:
    """Model for project metadata stored in unified database"""
    
    def __init__(self, id=None, name=None, project_type=None, 
                 port=None, pma_port=None, mailpit_port=None, smtp_port=None,
                 nextjs_port=None, api_port=None, mysql_port=None,
                 mongodb_port=None, mongo_express_port=None,
                 hostname=None, wordpress_type=None, php_version=None,
                 created_at=None, updated_at=None, status='active'):
        self.id = id  # ID numérique auto-incrémenté
        self.name = name  # Nom du projet (unique, nettoyé)
        self.project_type = project_type  # wordpress, nextjs, etc.
        self.port = port  # Port WordPress ou principal
        self.pma_port = pma_port  # Port phpMyAdmin
        self.mailpit_port = mailpit_port  # Port Mailpit
        self.smtp_port = smtp_port  # Port SMTP
        self.nextjs_port = nextjs_port  # Port Next.js
        self.api_port = api_port  # Port API Express
        self.mysql_port = mysql_port  # Port MySQL externe
        self.mongodb_port = mongodb_port  # Port MongoDB
        self.mongo_express_port = mongo_express_port  # Port Mongo Express
        self.hostname = hostname  # Hostname du projet
        self.wordpress_type = wordpress_type  # showcase ou woocommerce
        self.php_version = php_version  # Version PHP
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()
        self.status = status  # active, stopped, deleted
    
    def to_dict(self):
        """Convert metadata to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'project_type': self.project_type,
            'port': self.port,
            'pma_port': self.pma_port,
            'mailpit_port': self.mailpit_port,
            'smtp_port': self.smtp_port,
            'nextjs_port': self.nextjs_port,
            'api_port': self.api_port,
            'mysql_port': self.mysql_port,
            'mongodb_port': self.mongodb_port,
            'mongo_express_port': self.mongo_express_port,
            'hostname': self.hostname,
            'wordpress_type': self.wordpress_type,
            'php_version': self.php_version,
            'created_at': self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            'updated_at': self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at,
            'status': self.status
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create ProjectMetadata from dictionary"""
        return cls(
            id=data.get('id'),
            name=data.get('name'),
            project_type=data.get('project_type'),
            port=data.get('port'),
            pma_port=data.get('pma_port'),
            mailpit_port=data.get('mailpit_port'),
            smtp_port=data.get('smtp_port'),
            nextjs_port=data.get('nextjs_port'),
            api_port=data.get('api_port'),
            mysql_port=data.get('mysql_port'),
            mongodb_port=data.get('mongodb_port'),
            mongo_express_port=data.get('mongo_express_port'),
            hostname=data.get('hostname'),
            wordpress_type=data.get('wordpress_type'),
            php_version=data.get('php_version'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            status=data.get('status', 'active')
        )






