# Contributing to WP Launcher

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

1. Fork and clone the repository
2. Run `./install.sh` to set up the environment
3. Start the app: `source venv/bin/activate && python3 run.py`

## Project Structure

- `app/` - Main Python package (Flask)
  - `config/` - Configuration classes
  - `routes/` - Flask route handlers
  - `services/` - Business logic
  - `models/` - Data models
  - `utils/` - Utilities
  - `static/` - CSS, JS, images
  - `templates/` - Jinja2 HTML templates
- `docker-template/` - Docker Compose templates for new projects
- `scripts/` - Maintenance scripts

## Making Changes

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make your changes
3. Test locally by creating/starting/stopping a WordPress project
4. Commit with a clear message
5. Open a Pull Request

## Code Style

- Python: Follow PEP 8
- JavaScript: Use `const`/`let`, template literals, async/await
- Keep functions focused and concise

## Reporting Issues

Open an issue on GitHub with:
- Steps to reproduce
- Expected vs actual behavior
- OS and Docker version

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
