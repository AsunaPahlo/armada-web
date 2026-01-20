#!/usr/bin/env python
"""
Armada - FFXIV Submarine Fleet Dashboard
Main entry point
"""
# Gevent monkey patching must happen before any other imports
from gevent import monkey
monkey.patch_all()

import os
import sys

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, socketio
from app.routes.websocket import start_background_updates, start_lumina_updates


def main():
    """Run the Armada application."""
    # Create Flask app
    app = create_app()

    # Get configuration
    host = os.environ.get('ARMADA_HOST', '0.0.0.0')
    port = int(os.environ.get('ARMADA_PORT', 5000))
    debug = os.environ.get('ARMADA_DEBUG', 'false').lower() == 'true'

    print(f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   🚢 Armada - FFXIV Submarine Fleet Dashboard             ║
    ║                                                           ║
    ║   Starting server at: http://{host}:{port}                ║
    ║   Default login: admin / armada                           ║
    ║                                                           ║
    ║   Press Ctrl+C to stop                                    ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)

    # Start background updates for WebSocket
    # Only start in main process (not Flask reloader's parent process)
    # WERKZEUG_RUN_MAIN is 'true' in the reloader child, or not set if no reloader
    if not debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        start_background_updates(socketio, app, interval=30)
        start_lumina_updates(app)
    else:
        print("    [Reloader parent process - skipping background threads]")

    # Run with SocketIO
    socketio.run(
        app,
        host=host,
        port=port,
        debug=debug,
        use_reloader=debug,
        log_output=True,
        allow_unsafe_werkzeug=True
    )


if __name__ == '__main__':
    main()
