# app/__init__.py
import os

from dotenv import load_dotenv
from flask import Flask

from .database import db

load_dotenv()


def create_app():
    # Get the project root (one level above the 'app' folder)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    app = Flask(
        __name__,
        # Tell Flask exactly where templates and static are
        template_folder=os.path.join(project_root, "templates"),
        static_folder=os.path.join(project_root, "static"),
    )

    # Config
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    if not app.config["SECRET_KEY"]:
        raise ValueError(
            "No SECRET_KEY set for Flask application. Check your .env file."
        )

    # --- UPDATED: Point database to the persistent instance folder ---
    instance_path = os.path.join(project_root, "instance")
    os.makedirs(
        instance_path, exist_ok=True
    )  # Safely create the folder if it's missing
    db_path = os.path.join(instance_path, "products.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    # -----------------------------------------------------------------

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Initialize database
    db.init_app(app)

    # Create tables
    with app.app_context():
        from . import models

        db.create_all()

    # Register routes
    from .routes import bp as main_bp

    app.register_blueprint(main_bp)

    # Start price checker
    from .scheduler import start_scheduler

    start_scheduler(app)

    return app
