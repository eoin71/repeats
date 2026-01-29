import os
from flask import Flask
from app.database import init_db


def create_app():
    """Flask app factory."""
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

    return app
