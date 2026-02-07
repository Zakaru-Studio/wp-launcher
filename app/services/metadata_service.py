"""
MetadataService - Unified service for managing all project metadata
"""
import sqlite3
import os
import json
from datetime import datetime
from app.models.project_metadata import ProjectMetadata
from app.utils.logger import wp_logger


class MetadataService:
    """Centralized service for managing project metadata in unified database"""
    
    def __init__(self, db_path='data/projects.db'):
        # Utiliser un chemin absolu si le chemin est relatif
        if not os.path.isabs(db_path) and db_path != ':memory:':
            # Obtenir le répertoire racine du projet
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, db_path)
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize the unified database with all tables"""
        # Don't try to create directory for in-memory database
        if self.db_path != ':memory:':
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table projects
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                project_type TEXT NOT NULL,
                port INTEGER UNIQUE,
                pma_port INTEGER,
                mailpit_port INTEGER,
                smtp_port INTEGER,
                nextjs_port INTEGER,
                api_port INTEGER,
                mysql_port INTEGER,
                mongodb_port INTEGER,
                mongo_express_port INTEGER,
                hostname TEXT,
                wordpress_type TEXT,
                php_version TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active'
            )
        ''')
        
        # Indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_project_name ON projects(name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_project_status ON projects(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_project_port ON projects(port)')
        
        conn.commit()
        conn.close()
        
        wp_logger.log_system_info("MetadataService initialized", db_path=self.db_path)
    
    def get_project_by_name(self, name):
        """Retrieve a project by its name"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM projects WHERE name = ?', (name,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_metadata(row)
        return None
    
    def get_project_by_id(self, project_id):
        """Retrieve a project by its ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_metadata(row)
        return None
    
    def get_all_projects(self, status='active'):
        """List all projects with optional status filter"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if status:
            cursor.execute('SELECT * FROM projects WHERE status = ? ORDER BY name', (status,))
        else:
            cursor.execute('SELECT * FROM projects ORDER BY name')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_metadata(row) for row in rows]
    
    def save_project(self, project_metadata):
        """Save or update project metadata"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("BEGIN TRANSACTION")
            
            project_metadata.updated_at = datetime.now()
            
            if project_metadata.id:
                # Update existing project
                cursor.execute('''
                    UPDATE projects SET
                        name = ?, project_type = ?, port = ?, pma_port = ?,
                        mailpit_port = ?, smtp_port = ?, nextjs_port = ?,
                        api_port = ?, mysql_port = ?, mongodb_port = ?,
                        mongo_express_port = ?, hostname = ?, wordpress_type = ?,
                        php_version = ?, updated_at = ?, status = ?
                    WHERE id = ?
                ''', (
                    project_metadata.name, project_metadata.project_type,
                    project_metadata.port, project_metadata.pma_port,
                    project_metadata.mailpit_port, project_metadata.smtp_port,
                    project_metadata.nextjs_port, project_metadata.api_port,
                    project_metadata.mysql_port, project_metadata.mongodb_port,
                    project_metadata.mongo_express_port, project_metadata.hostname,
                    project_metadata.wordpress_type, project_metadata.php_version,
                    project_metadata.updated_at, project_metadata.status,
                    project_metadata.id
                ))
            else:
                # Insert new project
                cursor.execute('''
                    INSERT INTO projects (
                        name, project_type, port, pma_port, mailpit_port, smtp_port,
                        nextjs_port, api_port, mysql_port, mongodb_port,
                        mongo_express_port, hostname, wordpress_type, php_version,
                        created_at, updated_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    project_metadata.name, project_metadata.project_type,
                    project_metadata.port, project_metadata.pma_port,
                    project_metadata.mailpit_port, project_metadata.smtp_port,
                    project_metadata.nextjs_port, project_metadata.api_port,
                    project_metadata.mysql_port, project_metadata.mongodb_port,
                    project_metadata.mongo_express_port, project_metadata.hostname,
                    project_metadata.wordpress_type, project_metadata.php_version,
                    project_metadata.created_at, project_metadata.updated_at,
                    project_metadata.status
                ))
                project_metadata.id = cursor.lastrowid
            
            # Sync to filesystem for Docker compatibility
            self.sync_to_filesystem(project_metadata.id)
            
            cursor.execute("COMMIT")
            
            wp_logger.log_system_info(
                f"Project saved: {project_metadata.name}",
                project_id=project_metadata.id
            )
            
            return project_metadata
            
        except Exception as e:
            cursor.execute("ROLLBACK")
            wp_logger.log_system_info(f"Error saving project: {str(e)}")
            raise e
        finally:
            conn.close()
    
    def delete_project(self, project_id):
        """Delete a project (soft delete)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('UPDATE projects SET status = ?, updated_at = ? WHERE id = ?',
                      ('deleted', datetime.now(), project_id))
        conn.commit()
        conn.close()
        
        wp_logger.log_system_info(f"Project deleted (soft)", project_id=project_id)
    
    def sync_to_filesystem(self, project_id):
        """Generate .port files for Docker compatibility"""
        project = self.get_project_by_id(project_id)
        if not project:
            return
        
        container_path = os.path.join('containers', project.name)
        if not os.path.exists(container_path):
            return  # Container folder doesn't exist yet
        
        # Write port files
        port_mapping = {
            '.port': project.port,
            '.pma_port': project.pma_port,
            '.mailpit_port': project.mailpit_port,
            '.smtp_port': project.smtp_port,
            '.nextjs_port': project.nextjs_port,
            '.api_port': project.api_port,
            '.mysql_port': project.mysql_port,
            '.mongodb_port': project.mongodb_port,
            '.mongo_express_port': project.mongo_express_port
        }
        
        for filename, port_value in port_mapping.items():
            if port_value is not None:
                filepath = os.path.join(container_path, filename)
                try:
                    with open(filepath, 'w') as f:
                        f.write(str(port_value))
                except Exception as e:
                    wp_logger.log_system_info(
                        f"Warning: Could not write {filename}: {str(e)}"
                    )
        
        # Write hostname if exists
        if project.hostname:
            hostname_file = os.path.join(container_path, '.hostname')
            try:
                with open(hostname_file, 'w') as f:
                    f.write(project.hostname)
            except Exception:
                pass
        
        wp_logger.log_system_info(
            f"Synced metadata to filesystem",
            project_name=project.name,
            container_path=container_path
        )
    
    def _row_to_metadata(self, row):
        """Convert database row to ProjectMetadata object"""
        return ProjectMetadata(
            id=row[0],
            name=row[1],
            project_type=row[2],
            port=row[3],
            pma_port=row[4],
            mailpit_port=row[5],
            smtp_port=row[6],
            nextjs_port=row[7],
            api_port=row[8],
            mysql_port=row[9],
            mongodb_port=row[10],
            mongo_express_port=row[11],
            hostname=row[12],
            wordpress_type=row[13],
            php_version=row[14],
            created_at=row[15],
            updated_at=row[16],
            status=row[17]
        )

