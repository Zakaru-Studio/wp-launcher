# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

WP Launcher is a modular Flask application for managing WordPress projects with Docker. It creates and manages WordPress instances with optional Next.js frontends, using a separated architecture with `projets/` (editable files) and `containers/` (Docker configurations).

## Development Commands

### Starting the Application
```bash
./start.sh                    # Full setup with venv creation and dependency installation
python app.py                 # Direct start (requires venv activated)
```

### Project Management
```bash
./show_sites.sh              # List all active WordPress sites
./cleanup.sh                 # Clean up temporary files and stopped containers
./delete_project_robust.sh   # Safely delete a project
```

### Database Operations
```bash
./fast_import_db.sh          # Fast database import utility
./optimize_mysql.sh          # Optimize MySQL performance
```

### Development Utilities
```bash
./debug_start.sh            # Start with debug logging
./watch_logs.sh             # Monitor application logs
./fix_permissions.sh        # Fix file permissions
```

## Architecture

### Core Structure
- **app.py**: Main Flask application entry point with SocketIO
- **config/app_config.py**: Centralized configuration and service initialization
- **routes/**: Blueprint-based route handlers (main, projects, database, nginx)
- **services/**: Business logic services (docker, database, port management, traefik)
- **utils/**: Utility functions and helpers
- **models/**: Data models (Project class with dual-path architecture)

### Key Services
- **DockerService**: Manages Docker containers and docker-compose configurations
- **PortService**: Handles port allocation and conflict resolution
- **DatabaseService**: MySQL database operations with SocketIO updates
- **FastImportService**: Optimized database import functionality
- **TraefikService**: Reverse proxy configuration (disabled for local-only access)

### Project Architecture
Projects use a separated architecture:
- **projets/[name]/**: Editable WordPress files (wp-content, wp-config.php)
- **containers/[name]/**: Docker configuration files (docker-compose.yml, port files)

### Port Management
The application automatically assigns ports for services:
- WordPress: 8080+ (stored in `.port`)
- phpMyAdmin: Auto-assigned (stored in `.pma_port`)
- Mailpit: Auto-assigned (stored in `.mailpit_port`)
- SMTP: Auto-assigned (stored in `.smtp_port`)
- Next.js: Auto-assigned (stored in `.nextjs_port`)

## Key Features

### WordPress Project Creation
- Supports archive imports (WP Migrate Pro, WP Umbrella)
- Automatic wp-content extraction and database import
- Next.js frontend integration option
- MySQL/MongoDB database options

### Real-time Updates
- SocketIO integration for live project status updates
- WebSocket rooms for project-specific updates

### Development Environment
- Python virtual environment management
- Flask with debug mode
- Modular blueprint architecture
- Comprehensive logging system

## Environment Setup

The application requires:
- Python 3.x with venv
- Docker and Docker Compose
- MySQL/MariaDB
- 5GB+ disk space for uploads

Configuration is stored in `config/app_config.py` with environment-specific settings.