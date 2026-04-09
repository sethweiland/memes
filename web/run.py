#!/usr/bin/env python3
"""
Entry point for the meme pipeline web app.

Usage:
    python web/run.py
"""

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path and we run from there
_ROOT = str(Path(__file__).resolve().parent.parent)
os.chdir(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
load_dotenv()

from web import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", "5050"))
    print(f"Starting meme pipeline UI at http://localhost:{port}")
    app.run(debug=True, port=port, use_reloader=False)
