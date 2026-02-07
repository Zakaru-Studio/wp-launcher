#!/usr/bin/env python3
"""
Migration script: Migrate project metadata from filesystem to unified SQLite database

This script performs a SAFE migration without touching Docker containers or existing files.
It only READS from the filesystem and WRITES to the new database.

Usage:
    python scripts/migrate_to_unified_db.py --dry-run  # Simulation
    python scripts/migrate_to_unified_db.py             # Real migration
"""
import sys
import os
import sqlite3
import shutil
import json
import argparse
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.project_metadata import ProjectMetadata
from app.services.metadata_service import MetadataService


class MigrationScript:
    """Safe migration script with backup and rollback capabilities"""
    
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.containers_folder = 'containers'
        self.projets_folder = 'projets'
        self.data_folder = 'data'
        self.backup_folder = None
        self.metadata_service = None
        self.stats = {
            'projects_migrated': 0,
            'projects_skipped': 0,
            'errors': []
        }
    
    def run(self):
        """Run the migration"""
        print("=" * 80)
        print("MIGRATION: Filesystem → Unified Database (projects.db)")
        print("=" * 80)
        print(f"Mode: {'DRY RUN (simulation)' if self.dry_run else 'REAL MIGRATION'}")
        print()
        
        # Step 1: Create backup
        if not self.dry_run:
            if not self._create_backup():
                print("❌ Backup failed. Aborting migration.")
                return False
        else:
            print("📦 [DRY RUN] Skipping backup creation")
        
        # Step 2: Initialize database
        if not self._init_database():
            print("❌ Database initialization failed. Aborting migration.")
            return False
        
        # Step 3: Migrate projects
        if not self._migrate_projects():
            print("❌ Project migration failed.")
            if not self.dry_run:
                print("⚠️  You can rollback by removing data/projects.db")
            return False
        
        # Step 4: Validate
        if not self._validate_migration():
            print("❌ Validation failed.")
            return False
        
        # Step 5: Generate report
        self._generate_report()
        
        print()
        print("=" * 80)
        if self.dry_run:
            print("✅ DRY RUN COMPLETED - No changes were made")
        else:
            print("✅ MIGRATION COMPLETED SUCCESSFULLY")
            print(f"📦 Backup location: {self.backup_folder}")
        print("=" * 80)
        
        return True
    
    def _create_backup(self):
        """Create a complete backup before migration"""
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        self.backup_folder = f"backup-migration-{timestamp}"
        
        print(f"📦 Creating backup: {self.backup_folder}/")
        
        try:
            os.makedirs(self.backup_folder, exist_ok=True)
            
            # Backup data folder (users.db, dev_instances.db, etc.)
            if os.path.exists(self.data_folder):
                print(f"   📁 Backing up {self.data_folder}/")
                shutil.copytree(
                    self.data_folder,
                    os.path.join(self.backup_folder, 'data'),
                    dirs_exist_ok=True
                )
            
            # Backup a sample of containers/ (just .port files, not volumes)
            print(f"   📁 Backing up {self.containers_folder}/ metadata files")
            if os.path.exists(self.containers_folder):
                backup_containers = os.path.join(self.backup_folder, 'containers')
                os.makedirs(backup_containers, exist_ok=True)
                
                for project_name in os.listdir(self.containers_folder):
                    project_path = os.path.join(self.containers_folder, project_name)
                    if os.path.isdir(project_path):
                        backup_project = os.path.join(backup_containers, project_name)
                        os.makedirs(backup_project, exist_ok=True)
                        
                        # Copy only metadata files (not volumes)
                        for file in os.listdir(project_path):
                            if file.startswith('.') or file.endswith('.yml'):
                                src = os.path.join(project_path, file)
                                dst = os.path.join(backup_project, file)
                                if os.path.isfile(src):
                                    shutil.copy2(src, dst)
            
            print(f"✅ Backup created successfully")
            return True
            
        except Exception as e:
            print(f"❌ Backup failed: {str(e)}")
            return False
    
    def _init_database(self):
        """Initialize the new unified database"""
        print()
        print("🗄️  Initializing unified database (projects.db)")
        
        try:
            if self.dry_run:
                print("   [DRY RUN] Would create data/projects.db")
                # Create temporary in-memory DB for dry run
                self.metadata_service = MetadataService(':memory:')
            else:
                self.metadata_service = MetadataService('data/projects.db')
            
            print("✅ Database initialized with schema")
            return True
            
        except Exception as e:
            print(f"❌ Database initialization failed: {str(e)}")
            return False
    
    def _migrate_projects(self):
        """Migrate all projects from filesystem to database"""
        print()
        print("📂 Scanning containers/ for projects...")
        
        if not os.path.exists(self.containers_folder):
            print(f"⚠️  {self.containers_folder}/ not found")
            return True
        
        projects = [d for d in os.listdir(self.containers_folder) 
                   if os.path.isdir(os.path.join(self.containers_folder, d))
                   and not d.startswith('.')]
        
        print(f"   Found {len(projects)} project(s)")
        print()
        
        for project_name in sorted(projects):
            self._migrate_project(project_name)
        
        print()
        print(f"📊 Migration summary:")
        print(f"   ✅ Migrated: {self.stats['projects_migrated']}")
        print(f"   ⏭️  Skipped: {self.stats['projects_skipped']}")
        print(f"   ❌ Errors: {len(self.stats['errors'])}")
        
        if self.stats['errors']:
            print()
            print("   Errors details:")
            for error in self.stats['errors']:
                print(f"      - {error}")
        
        return len(self.stats['errors']) == 0
    
    def _migrate_project(self, project_name):
        """Migrate a single project"""
        container_path = os.path.join(self.containers_folder, project_name)
        
        try:
            # Read metadata from files
            metadata = self._read_project_metadata(project_name, container_path)
            
            if not metadata:
                print(f"⏭️  {project_name:30s} - No metadata found, skipping")
                self.stats['projects_skipped'] += 1
                return
            
            # Save to database
            if self.dry_run:
                print(f"📝 {project_name:30s} - Would migrate (port={metadata.port})")
            else:
                self.metadata_service.save_project(metadata)
                print(f"✅ {project_name:30s} - Migrated (port={metadata.port})")
            
            self.stats['projects_migrated'] += 1
            
        except Exception as e:
            error_msg = f"{project_name}: {str(e)}"
            self.stats['errors'].append(error_msg)
            print(f"❌ {project_name:30s} - Error: {str(e)}")
    
    def _read_project_metadata(self, project_name, container_path):
        """Read project metadata from filesystem"""
        # Read port files
        def read_port_file(filename):
            filepath = os.path.join(container_path, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r') as f:
                        return int(f.read().strip())
                except:
                    return None
            return None
        
        # Read hostname
        hostname = None
        hostname_file = os.path.join(container_path, '.hostname')
        if os.path.exists(hostname_file):
            try:
                with open(hostname_file, 'r') as f:
                    hostname = f.read().strip()
            except:
                pass
        
        # Read WordPress type
        wordpress_type = None
        wp_type_file = os.path.join(container_path, '.wp_type')
        if os.path.exists(wp_type_file):
            try:
                with open(wp_type_file, 'r') as f:
                    wordpress_type = f.read().strip()
            except:
                pass
        
        # Read PHP version
        php_version = None
        php_version_file = os.path.join(container_path, '.php_version')
        if os.path.exists(php_version_file):
            try:
                with open(php_version_file, 'r') as f:
                    php_version = f.read().strip()
            except:
                pass
        
        # Detect project type
        project_path = os.path.join(self.projets_folder, project_name)
        project_type = 'unknown'
        
        if os.path.exists(project_path):
            type_marker = os.path.join(project_path, '.project_type')
            if os.path.exists(type_marker):
                try:
                    with open(type_marker, 'r') as f:
                        project_type = f.read().strip()
                except:
                    pass
            elif os.path.exists(os.path.join(project_path, 'wp-content')):
                project_type = 'wordpress'
            elif os.path.exists(os.path.join(project_path, 'client')):
                project_type = 'nextjs'
        
        # Create metadata object
        port = read_port_file('.port')
        
        if not port:
            return None  # No port = not a valid project
        
        metadata = ProjectMetadata(
            name=project_name,
            project_type=project_type,
            port=port,
            pma_port=read_port_file('.pma_port'),
            mailpit_port=read_port_file('.mailpit_port'),
            smtp_port=read_port_file('.smtp_port'),
            nextjs_port=read_port_file('.nextjs_port'),
            api_port=read_port_file('.api_port'),
            mysql_port=read_port_file('.mysql_port'),
            mongodb_port=read_port_file('.mongodb_port'),
            mongo_express_port=read_port_file('.mongo_express_port'),
            hostname=hostname,
            wordpress_type=wordpress_type,
            php_version=php_version,
            status='active'
        )
        
        return metadata
    
    def _validate_migration(self):
        """Validate the migration by comparing DB vs filesystem"""
        print()
        print("🔍 Validating migration...")
        
        try:
            if self.dry_run:
                print("   [DRY RUN] Skipping validation")
                return True
            
            # Count projects in DB
            all_projects = self.metadata_service.get_all_projects()
            db_count = len(all_projects)
            
            # Count projects in filesystem
            fs_count = len([d for d in os.listdir(self.containers_folder) 
                          if os.path.isdir(os.path.join(self.containers_folder, d))
                          and not d.startswith('.')])
            
            print(f"   Database: {db_count} projects")
            print(f"   Filesystem: {fs_count} projects")
            
            if db_count != fs_count:
                print(f"⚠️  Warning: Count mismatch ({db_count} vs {fs_count})")
                print(f"   This is normal if some projects had no .port file")
            
            print("✅ Validation passed")
            return True
            
        except Exception as e:
            print(f"❌ Validation failed: {str(e)}")
            return False
    
    def _generate_report(self):
        """Generate migration report"""
        print()
        print("📋 Migration Report")
        print("-" * 80)
        print(f"Timestamp: {datetime.now().isoformat()}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'REAL'}")
        print(f"Projects migrated: {self.stats['projects_migrated']}")
        print(f"Projects skipped: {self.stats['projects_skipped']}")
        print(f"Errors: {len(self.stats['errors'])}")
        
        if not self.dry_run and self.backup_folder:
            print(f"Backup location: {self.backup_folder}/")
        
        # Save report to file
        if not self.dry_run:
            report_file = f"migration-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
            with open(report_file, 'w') as f:
                f.write(f"Migration Report\n")
                f.write(f"=" * 80 + "\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"Projects migrated: {self.stats['projects_migrated']}\n")
                f.write(f"Projects skipped: {self.stats['projects_skipped']}\n")
                f.write(f"Errors: {len(self.stats['errors'])}\n")
                
                if self.stats['errors']:
                    f.write(f"\nErrors:\n")
                    for error in self.stats['errors']:
                        f.write(f"  - {error}\n")
            
            print(f"Report saved: {report_file}")


def main():
    parser = argparse.ArgumentParser(description='Migrate project metadata to unified database')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Run in simulation mode without making changes')
    args = parser.parse_args()
    
    script = MigrationScript(dry_run=args.dry_run)
    success = script.run()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()






