#!/usr/bin/env python
"""
Armada - FFXIV Submarine Fleet Dashboard
WSGI entry point for gunicorn
"""
# Gevent monkey patching must happen before any other imports
from gevent import monkey
monkey.patch_all()

import os

from app import create_app, socketio
from app.routes.websocket import start_background_updates, start_lumina_updates

# Create Flask app
app = create_app()

# Flag to ensure background tasks only start once
_background_started = False


def on_starting(server):
    """Gunicorn hook called when server starts."""
    pass


def post_fork(server, worker):
    """Gunicorn hook called after worker fork."""
    global _background_started
    if not _background_started:
        _background_started = True
        start_background_updates(socketio, app, interval=30)
        start_lumina_updates(app)
        print("[Armada] Background tasks started")


# For running directly (development)
if __name__ == "__main__":
    host = os.environ.get('ARMADA_HOST', '0.0.0.0')
    port = int(os.environ.get('ARMADA_PORT', 5000))

    # Start background tasks
    start_background_updates(socketio, app, interval=30)
    start_lumina_updates(app)

    socketio.run(app, host=host, port=port, debug=False)
