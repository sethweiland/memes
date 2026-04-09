"""
Flask web app for the meme generation pipeline.

Usage:
    python web/run.py
"""

import os
import sys
from pathlib import Path

from flask import Flask, redirect, url_for

# Ensure project root is on sys.path so `from src.config import ...` works
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )
    app.secret_key = os.urandom(24)

    # Register blueprints
    from .blueprints.generate import bp as generate_bp
    from .blueprints.gallery import bp as gallery_bp
    from .blueprints.templates_review import bp as templates_bp
    from .blueprints.discovery import bp as discovery_bp

    app.register_blueprint(generate_bp, url_prefix="/generate")
    app.register_blueprint(gallery_bp, url_prefix="/gallery")
    app.register_blueprint(templates_bp, url_prefix="/templates")
    app.register_blueprint(discovery_bp, url_prefix="/discovery")

    @app.route("/")
    def index():
        return redirect(url_for("generate.start"))

    return app
