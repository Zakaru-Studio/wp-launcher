"""
User Service for managing users and authentication
"""
import sqlite3
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from app.models.user import User


class UserService:
    """Service for user management"""
    
    def __init__(self, db_path='data/users.db'):
        # Utiliser un chemin absolu si le chemin est relatif
        if not os.path.isabs(db_path):
            # Obtenir le répertoire racine du projet
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, db_path)
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize the users database"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                role TEXT DEFAULT 'developer',
                first_name TEXT,
                last_name TEXT,
                avatar_url TEXT,
                ssh_public_key TEXT,
                github_username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create oauth_tokens table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                provider TEXT,
                access_token TEXT,
                refresh_token TEXT,
                expires_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        
        # Create indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_username ON users(username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_github ON users(github_username)')
        
        conn.commit()
        conn.close()
    
    def create_user(self, username, email, password=None, role='developer', **kwargs):
        """Create a new user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        user = User(
            username=username,
            email=email,
            role=role,
            first_name=kwargs.get('first_name'),
            last_name=kwargs.get('last_name'),
            avatar_url=kwargs.get('avatar_url'),
            ssh_public_key=kwargs.get('ssh_public_key'),
            github_username=kwargs.get('github_username')
        )
        
        if password:
            user.set_password(password)
        
        try:
            cursor.execute('''
                INSERT INTO users (username, email, password_hash, role, first_name, last_name, 
                                   avatar_url, ssh_public_key, github_username, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user.username, user.email, user.password_hash, user.role, user.first_name,
                  user.last_name, user.avatar_url, user.ssh_public_key, user.github_username,
                  datetime.now()))
            
            user.id = cursor.lastrowid
            conn.commit()
            return user
        except sqlite3.IntegrityError as e:
            raise Exception(f"User already exists: {str(e)}")
        finally:
            conn.close()
    
    def create_or_update_from_oauth(self, provider, oauth_data):
        """Create or update user from OAuth data"""
        github_username = oauth_data.get('username')
        email = oauth_data.get('email')
        
        # Check if user exists by GitHub username
        user = self.get_user_by_github_username(github_username)
        
        if user:
            # Update existing user
            self.update_user(
                user.username,
                first_name=oauth_data.get('name', '').split()[0] if oauth_data.get('name') else None,
                last_name=' '.join(oauth_data.get('name', '').split()[1:]) if oauth_data.get('name') and len(oauth_data.get('name', '').split()) > 1 else None,
                avatar_url=oauth_data.get('avatar_url'),
                ssh_public_key=oauth_data.get('ssh_keys')[0] if oauth_data.get('ssh_keys') else user.ssh_public_key
            )
            return user
        else:
            # Create new user
            name_parts = oauth_data.get('name', '').split() if oauth_data.get('name') else []
            return self.create_user(
                username=github_username,
                email=email,
                password=None,  # OAuth users don't have password
                role='developer',
                first_name=name_parts[0] if name_parts else None,
                last_name=' '.join(name_parts[1:]) if len(name_parts) > 1 else None,
                avatar_url=oauth_data.get('avatar_url'),
                ssh_public_key=oauth_data.get('ssh_keys')[0] if oauth_data.get('ssh_keys') else None,
                github_username=github_username
            )
    
    def authenticate(self, username, password):
        """Authenticate user with username and password"""
        user = self.get_user_by_username(username)
        if user and user.check_password(password):
            return user
        return None
    
    def get_user_by_id(self, user_id):
        """Get user by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_user(row)
        return None
    
    def get_user_by_username(self, username):
        """Get user by username"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_user(row)
        return None
    
    def get_user_by_github_username(self, github_username):
        """Get user by GitHub username"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE github_username = ?', (github_username,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_user(row)
        return None
    
    def list_users(self):
        """List all users"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users ORDER BY created_at DESC')
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_user(row) for row in rows]
    
    def update_user(self, username, **kwargs):
        """Update user information"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Build update query dynamically
        update_fields = []
        values = []
        
        allowed_fields = ['email', 'role', 'first_name', 'last_name', 'avatar_url', 'ssh_public_key']
        for field in allowed_fields:
            if field in kwargs:
                update_fields.append(f"{field} = ?")
                values.append(kwargs[field])
        
        if not update_fields:
            conn.close()
            return
        
        values.append(username)
        query = f"UPDATE users SET {', '.join(update_fields)} WHERE username = ?"
        
        cursor.execute(query, values)
        conn.commit()
        conn.close()
    
    def delete_user(self, username):
        """Delete a user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM users WHERE username = ?', (username,))
        conn.commit()
        conn.close()
    
    def upload_avatar(self, username, file):
        """Save avatar file for user"""
        if not file:
            return None
        
        # Create avatars directory
        avatars_dir = 'data/avatars'
        os.makedirs(avatars_dir, exist_ok=True)
        
        # Secure filename and save
        filename = secure_filename(f"{username}{os.path.splitext(file.filename)[1]}")
        filepath = os.path.join(avatars_dir, filename)
        file.save(filepath)
        
        # Update user avatar_url
        avatar_url = f"/static/avatars/{filename}"
        self.update_user(username, avatar_url=avatar_url)
        
        return avatar_url
    
    def save_oauth_token(self, user_id, provider, access_token, refresh_token=None, expires_at=None):
        """Save OAuth token for user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO oauth_tokens (user_id, provider, access_token, refresh_token, expires_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, provider, access_token, refresh_token, expires_at))
        
        conn.commit()
        conn.close()
    
    def get_oauth_token(self, user_id, provider):
        """Get OAuth token for user"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT access_token, refresh_token, expires_at 
            FROM oauth_tokens 
            WHERE user_id = ? AND provider = ?
        ''', (user_id, provider))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'access_token': row[0],
                'refresh_token': row[1],
                'expires_at': row[2]
            }
        return None
    
    def _row_to_user(self, row):
        """Convert database row to User object"""
        return User(
            id=row[0],
            username=row[1],
            email=row[2],
            password_hash=row[3],
            role=row[4],
            first_name=row[5],
            last_name=row[6],
            avatar_url=row[7],
            ssh_public_key=row[8],
            github_username=row[9],
            created_at=row[10]
        )

