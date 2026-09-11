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
    from .blueprints.dashboard import bp as dashboard_bp
    from .blueprints.spend import bp as spend_bp
    from .blueprints.generate import bp as generate_bp
    from .blueprints.gallery import bp as gallery_bp
    from .blueprints.templates_review import bp as templates_bp
    from .blueprints.discovery import bp as discovery_bp
    from .blueprints.video import bp as video_bp
    from .blueprints.daily_candidates import bp as daily_candidates_bp
    from .blueprints.x_activity import bp as x_activity_bp

    app.register_blueprint(dashboard_bp, url_prefix="/")
    app.register_blueprint(spend_bp, url_prefix="/spend")
    app.register_blueprint(generate_bp, url_prefix="/generate")
    app.register_blueprint(video_bp, url_prefix="/video")
    app.register_blueprint(gallery_bp, url_prefix="/gallery")
    app.register_blueprint(templates_bp, url_prefix="/templates")
    app.register_blueprint(discovery_bp, url_prefix="/discovery")
    app.register_blueprint(daily_candidates_bp)
    app.register_blueprint(x_activity_bp)

    return app
