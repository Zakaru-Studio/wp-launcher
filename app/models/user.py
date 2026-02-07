"""
User model for authentication and authorization
"""
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import hashlib


class User:
    """User model with OAuth support"""
    
    def __init__(self, id=None, username=None, email=None, password_hash=None, 
                 role='developer', first_name=None, last_name=None,
                 avatar_url=None, ssh_public_key=None, github_username=None,
                 created_at=None):
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.role = role  # 'admin' ou 'developer'
        self.first_name = first_name
        self.last_name = last_name
        self.avatar_url = avatar_url  # URL Gravatar, GitHub, ou /static/avatars/{username}.jpg
        self.ssh_public_key = ssh_public_key
        self.github_username = github_username
        self.created_at = created_at or datetime.now()
        
    def set_password(self, password):
        """Hash and set user password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify password against hash"""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def get_display_name(self):
        """Get user's display name (first + last or username)"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username
    
    def get_avatar_url(self):
        """Get user's avatar URL with fallback to Gravatar"""
        if self.avatar_url:
            return self.avatar_url
        # Fallback: Gravatar
        email_hash = hashlib.md5(self.email.lower().encode()).hexdigest()
        return f"https://www.gravatar.com/avatar/{email_hash}?d=identicon&s=200"
    
    def to_dict(self):
        """Convert user to dictionary"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'role': self.role,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'display_name': self.get_display_name(),
            'avatar_url': self.get_avatar_url(),
            'github_username': self.github_username,
            'created_at': self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at
        }






