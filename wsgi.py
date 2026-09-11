#!/usr/bin/env python3
"""
WSGI entry point for production deployment.

Usage:
    gunicorn -b 0.0.0.0:8080 wsgi:app
"""

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from dotenv import load_dotenv
load_dotenv()

from web import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
