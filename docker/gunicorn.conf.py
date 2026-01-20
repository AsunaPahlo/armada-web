# Gunicorn configuration for Armada
# Flask-SocketIO with gevent WebSocket support

import os

# Server socket
bind = f"0.0.0.0:{os.environ.get('ARMADA_PORT', '5000')}"

# Worker configuration
# IMPORTANT: Use only 1 worker for WebSocket support without Redis
# For multiple workers, you'd need to add Redis as a message queue
workers = 1
worker_class = "geventwebsocket.gunicorn.workers.GeventWebSocketWorker"

# Timeout (increase for long-running WebSocket connections)
timeout = 120
keepalive = 5

# Logging
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')

# Process naming
proc_name = "armada"

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# Hook to start background tasks after worker fork
def post_fork(server, worker):
    """Start background tasks after worker is forked."""
    from wsgi import app, socketio
    from app.routes.websocket import start_background_updates, start_lumina_updates

    start_background_updates(socketio, app, interval=30)
    start_lumina_updates(app)
    print(f"[Armada] Worker {worker.pid}: Background tasks started")
