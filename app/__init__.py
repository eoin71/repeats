import logging
import os
from flask import Flask
from dotenv import load_dotenv
from app.database import init_db


def create_app():
    """Flask app factory."""
    load_dotenv()
    _configure_logging()

    app = Flask(__name__, instance_relative_config=True)

    # Configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tasks.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Ensure instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Initialize database
    init_db(app)

    # Register routes
    from app import routes
    app.register_blueprint(routes.bp)

    _log_config()

    return app


def _configure_logging():
    """Send app logs to the console (stderr), where docker/gunicorn collect them.

    The process id distinguishes gunicorn workers. Level comes from LOG_LEVEL
    (default INFO).
    """
    level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '%(asctime)s [pid %(process)d] %(levelname)s %(name)s: %(message)s'
        ))
        root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))
    # Keep third-party request logging quiet
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def _log_config():
    """Log which integrations are configured (names only, never values)."""
    logger = logging.getLogger('app')
    settings = [
        'INTERVALS_ICU_API_KEY', 'STRAVA_CLIENT_ID', 'STRAVA_CLIENT_SECRET', 'STRAVA_REFRESH_TOKEN',
    ]
    status = ', '.join(f"{name}={'set' if os.environ.get(name) else 'MISSING'}" for name in settings)
    logger.info('Starting repeats. Config: %s', status)
