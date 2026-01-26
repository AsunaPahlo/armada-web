"""
WebSocket handlers for real-time updates
"""
import base64
import gzip
import json
from flask import current_app, request
from flask_socketio import SocketIO, emit, join_room, leave_room, Namespace
from flask_login import current_user
import threading
import time
from datetime import datetime

from app.services import get_fleet_manager
from app.utils.logging import get_logger

logger = get_logger('WebSocket')
plugin_logger = get_logger('Plugin')
lumina_logger = get_logger('Lumina')


def decompress_data(compressed_base64: str) -> list:
    """Decompress base64-encoded gzip data."""
    compressed_bytes = base64.b64decode(compressed_base64)
    decompressed_bytes = gzip.decompress(compressed_bytes)
    return json.loads(decompressed_bytes.decode('utf-8'))

_update_thread: threading.Thread = None
_lumina_thread: threading.Thread = None
_running = False

# Lumina update interval (6 hours in seconds)
LUMINA_UPDATE_INTERVAL = 6 * 60 * 60

# Plugin data storage (in-memory, keyed by plugin_id)
_plugin_data = {}
_plugin_connections = {}  # sid -> plugin_id mapping


def get_ws_fleet_manager(app):
    """Get the shared fleet manager instance."""
    with app.app_context():
        return get_fleet_manager(app)


def register_handlers(socketio: SocketIO):
    """Register all WebSocket event handlers."""

    # Register plugin namespace
    socketio.on_namespace(PluginNamespace('/plugin'))

    @socketio.on('connect')
    def handle_connect():
        """Handle client connection."""
        if not current_user.is_authenticated:
            return False  # Reject unauthenticated connections

        join_room('dashboard')
        emit('connected', {'status': 'connected'})

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        leave_room('dashboard')

    @socketio.on('request_update')
    def handle_update_request():
        """Handle manual update request from client."""
        if not current_user.is_authenticated:
            return

        app = current_app._get_current_object()
        fleet = get_ws_fleet_manager(app)

        with app.app_context():
            data = fleet.get_dashboard_data()
            emit('dashboard_update', data)

    @socketio.on('join_fc')
    def handle_join_fc(data):
        """Join FC-specific room for targeted updates."""
        if not current_user.is_authenticated:
            return

        fc_id = data.get('fc_id')
        if fc_id:
            join_room(f'fc_{fc_id}')

    @socketio.on('leave_fc')
    def handle_leave_fc(data):
        """Leave FC-specific room."""
        fc_id = data.get('fc_id')
        if fc_id:
            leave_room(f'fc_{fc_id}')


class PluginNamespace(Namespace):
    """WebSocket namespace for Dalamud plugin connections."""

    def _validate_api_key(self, api_key: str) -> bool:
        """Validate the provided API key against database."""
        if not api_key:
            return False
        from app.models.api_key import APIKey
        return APIKey.validate_key(api_key) is not None

    def on_connect(self):
        """Handle plugin connection."""
        plugin_logger.info(f"Connection attempt from {request.sid}")
        # Connection is allowed, but authentication happens on 'authenticate' event

    def on_disconnect(self):
        """Handle plugin disconnection."""
        sid = request.sid
        if sid in _plugin_connections:
            plugin_id = _plugin_connections.pop(sid)
            plugin_logger.info(f"Disconnected: {plugin_id}")
            # Note: We intentionally don't clear plugin data on disconnect
            # so that the data persists across restarts and reconnections

            # Notify dashboard clients of plugin disconnection
            from app import socketio as main_socketio
            main_socketio.emit('plugin_disconnected', {
                'plugin_id': plugin_id
            }, room='dashboard', namespace='/')
        else:
            plugin_logger.info(f"Disconnected: {sid} (unauthenticated)")

    def on_authenticate(self, data):
        """
        Authenticate plugin with API key.

        Expected data:
        {
            "api_key": "your-api-key",
            "plugin_id": "unique-plugin-identifier",
            "plugin_version": "1.0.0"
        }
        """
        api_key = data.get('api_key', '')
        # Support both 'nickname' and 'plugin_id' for backwards compatibility
        plugin_id = data.get('nickname') or data.get('plugin_id', 'unknown')
        plugin_version = data.get('plugin_version', 'unknown')

        if not self._validate_api_key(api_key):
            plugin_logger.info(f"Authentication failed for {plugin_id}")
            emit('auth_response', {
                'success': False,
                'error': 'Invalid API key'
            })
            return

        # Store connection mapping
        _plugin_connections[request.sid] = plugin_id

        plugin_logger.info(f"Authenticated: {plugin_id} v{plugin_version}")
        emit('auth_response', {
            'success': True,
            'message': f'Welcome {plugin_id}'
        })

        # Notify dashboard clients of new plugin connection
        from app import socketio as main_socketio
        main_socketio.emit('plugin_connected', {
            'plugin_id': plugin_id
        }, room='dashboard', namespace='/')

    def on_fleet_data(self, data):
        """
        Receive fleet data from plugin.

        Expected data (uncompressed):
        {
            "api_key": "your-api-key",
            "timestamp": "2026-01-14T12:00:00Z",
            "accounts": [...]
        }

        Expected data (compressed):
        {
            "api_key": "your-api-key",
            "timestamp": "2026-01-14T12:00:00Z",
            "compressed": true,
            "data": "base64-encoded-gzip-data"
        }
        """
        # Validate API key
        api_key = data.get('api_key', '')
        if not self._validate_api_key(api_key):
            emit('data_response', {
                'success': False,
                'error': 'Invalid API key'
            })
            return

        plugin_id = _plugin_connections.get(request.sid, 'unknown')
        timestamp = data.get('timestamp', datetime.utcnow().isoformat() + 'Z')

        # Handle compressed or uncompressed data
        if data.get('compressed', False):
            try:
                compressed_data = data.get('data', '')
                accounts = decompress_data(compressed_data)
                plugin_logger.info(f"Decompressed data from {plugin_id}")
            except Exception as e:
                plugin_logger.info(f"Failed to decompress data: {e}")
                emit('data_response', {
                    'success': False,
                    'error': f'Decompression failed: {str(e)}'
                })
                return
        else:
            accounts = data.get('accounts', [])

        # Store plugin data in raw format
        received_at = datetime.utcnow().isoformat() + 'Z'
        _plugin_data[plugin_id] = {
            'timestamp': timestamp,
            'received_at': received_at,
            'accounts': accounts
        }

        plugin_logger.info(f"Received fleet data from {plugin_id}: {len(accounts)} accounts")

        # Update FleetManager with plugin data (including metadata for persistence)
        try:
            app = current_app._get_current_object()
            fleet = get_ws_fleet_manager(app)
            fleet.set_plugin_data(plugin_id, accounts, timestamp=timestamp, received_at=received_at)
            plugin_logger.info(f"Updated FleetManager with data from {plugin_id}")
        except Exception as e:
            plugin_logger.warning(f"Error updating FleetManager: {e}")

        # Acknowledge receipt
        emit('data_response', {
            'success': True,
            'message': f'Received {len(accounts)} accounts',
            'timestamp': timestamp
        })

        # Broadcast update to dashboard clients with full refresh
        from app import socketio as main_socketio

        # Send notification
        main_socketio.emit('plugin_data_update', {
            'plugin_id': plugin_id,
            'timestamp': timestamp,
            'account_count': len(accounts)
        }, room='dashboard', namespace='/')

        # Also trigger a full dashboard refresh
        try:
            app = current_app._get_current_object()
            fleet = get_ws_fleet_manager(app)
            with app.app_context():
                data = fleet.get_dashboard_data()
                main_socketio.emit('dashboard_update', data, room='dashboard', namespace='/')
                plugin_logger.info(f"Broadcast dashboard update to clients")
        except Exception as e:
            plugin_logger.warning(f"Error broadcasting dashboard update: {e}")

    def on_ping(self):
        """Respond to keepalive ping."""
        emit('pong', {'timestamp': datetime.utcnow().isoformat() + 'Z'})

    def on_voyage_loot(self, data):
        """
        Receive voyage loot data from plugin.

        Expected data:
        {
            "api_key": "your-api-key",
            "character_name": "Character Name",
            "fc_id": "12345678",
            "fc_tag": "FC",
            "submarine_name": "Submarine 1",
            "sectors": [10, 15, 26],
            "items": [
                {
                    "sector_id": 10,
                    "item_id_primary": 12345,
                    "item_name_primary": "Deep-sea Coral",
                    "count_primary": 5,
                    "hq_primary": false,
                    "vendor_price_primary": 156,
                    "item_id_additional": 0,
                    "item_name_additional": "",
                    "count_additional": 0,
                    "hq_additional": false,
                    "vendor_price_additional": 0
                }
            ],
            "total_gil_value": 780,
            "captured_at": "2026-01-16T12:00:00Z"
        }
        """
        # Validate API key
        api_key = data.get('api_key', '')
        if not self._validate_api_key(api_key):
            emit('loot_response', {
                'success': False,
                'error': 'Invalid API key'
            })
            return

        plugin_id = _plugin_connections.get(request.sid, 'unknown')
        submarine_name = data.get('submarine_name', 'unknown')

        plugin_logger.info(f"Received voyage loot from {plugin_id}: {submarine_name}")

        # Record loot using loot tracker service
        try:
            from app.services.loot_tracker import loot_tracker
            result = loot_tracker.record_loot(plugin_id, data)

            emit('loot_response', result)

            # Notify dashboard clients of new loot
            if result.get('success'):
                from app import socketio as main_socketio
                main_socketio.emit('loot_recorded', {
                    'plugin_id': plugin_id,
                    'submarine_name': submarine_name,
                    'total_gil_value': data.get('total_gil_value', 0),
                    'item_count': len(data.get('items', []))
                }, room='dashboard', namespace='/')

        except Exception as e:
            plugin_logger.warning(f"Error recording loot: {e}")
            emit('loot_response', {
                'success': False,
                'error': str(e)
            })


def get_plugin_data(plugin_id: str = None) -> dict:
    """
    Get stored plugin data.

    Args:
        plugin_id: Specific plugin to get data from, or None for all

    Returns:
        Plugin data dict
    """
    if plugin_id:
        return _plugin_data.get(plugin_id, {})
    return _plugin_data


def get_connected_plugins() -> list:
    """Get list of connected plugin IDs."""
    return list(set(_plugin_connections.values()))


def clear_plugin_data(plugin_id: str = None):
    """
    Clear plugin data from websocket storage.

    Args:
        plugin_id: Specific plugin to clear, or None for all
    """
    global _plugin_data
    if plugin_id:
        _plugin_data.pop(plugin_id, None)
    else:
        _plugin_data.clear()


def get_plugin_status(app=None) -> list:
    """
    Get status information for all known plugins.

    Returns:
        List of plugin status dicts with connection state and last update time
    """
    connected_plugins = set(_plugin_connections.values())
    known_plugins = set(_plugin_data.keys())

    # Also check FleetManager for persisted plugin data and metadata
    fleet_metadata = {}
    fleet_account_counts = {}
    if app:
        try:
            fleet = get_ws_fleet_manager(app)
            known_plugins.update(fleet._plugin_data_raw.keys())
            fleet_metadata = fleet.get_plugin_metadata()
            # Get account counts from persisted data
            for pid, accounts in fleet._plugin_data_raw.items():
                fleet_account_counts[pid] = len(accounts)
        except Exception:
            pass

    status_list = []

    for plugin_id in known_plugins:
        ws_data = _plugin_data.get(plugin_id, {})
        fm_metadata = fleet_metadata.get(plugin_id, {})

        # Use websocket data if available, otherwise fall back to FleetManager metadata
        last_timestamp = ws_data.get('timestamp') or fm_metadata.get('timestamp')
        last_received = ws_data.get('received_at') or fm_metadata.get('received_at')
        account_count = len(ws_data.get('accounts', [])) or fleet_account_counts.get(plugin_id, 0)

        status_list.append({
            'plugin_id': plugin_id,
            'connected': plugin_id in connected_plugins,
            'last_data_timestamp': last_timestamp,
            'last_received_at': last_received,
            'account_count': account_count
        })

    # Also include connected plugins that haven't sent data yet
    for plugin_id in connected_plugins:
        if plugin_id not in known_plugins:
            status_list.append({
                'plugin_id': plugin_id,
                'connected': True,
                'last_data_timestamp': None,
                'last_received_at': None,
                'account_count': 0
            })

    return status_list


def start_background_updates(socketio: SocketIO, app, interval: int = 30):
    """
    Start background thread for pushing updates to all connected clients.

    Args:
        socketio: SocketIO instance
        app: Flask app instance
        interval: Seconds between updates
    """
    global _update_thread, _running

    if _running:
        return

    _running = True

    def update_loop():
        fleet = get_ws_fleet_manager(app)

        while _running:
            try:
                with app.app_context():
                    data = fleet.get_dashboard_data()
                    socketio.emit('dashboard_update', data, room='dashboard')

                    # Also emit to FC-specific rooms
                    for fc in data.get('fc_summaries', []):
                        fc_id = fc.get('fc_id')
                        if fc_id:
                            socketio.emit('fc_update', fc, room=f'fc_{fc_id}')

                    # Check alert conditions
                    from app.services.alert_service import alert_service
                    alert_service.check_alerts(data)

            except Exception as e:
                logger.info(f"Update error: {e}")

            time.sleep(interval)

    _update_thread = threading.Thread(target=update_loop, daemon=True)
    _update_thread.start()


def stop_background_updates():
    """Stop background update thread."""
    global _running
    _running = False


def start_lumina_updates(app):
    """
    Start background thread for updating Lumina game data every 6 hours.

    Args:
        app: Flask app instance
    """
    global _lumina_thread, _running

    if _lumina_thread is not None and _lumina_thread.is_alive():
        return

    def lumina_update_loop():
        from app.services.lumina_service import lumina_service
        from app.services.route_stats_service import route_stats_service
        from app.services.stats_tracker import stats_tracker

        # Link any unlinked loot on startup
        try:
            with app.app_context():
                linked = stats_tracker.link_all_unlinked_loot()
                if linked > 0:
                    logger.info(f"Linked {linked} unlinked loot records on startup")
        except Exception as e:
            logger.warning(f"Error linking loot on startup: {e}")

        while _running:
            try:
                # Sleep first (data is loaded on startup)
                time.sleep(LUMINA_UPDATE_INTERVAL)

                if not _running:
                    break

                with app.app_context():
                    # Update Lumina game data
                    lumina_logger.info(" Checking for game data updates...")
                    results = lumina_service.update_all()
                    total = sum(results.values())
                    if total > 0:
                        lumina_logger.info(f"Updated {total} rows from GitHub")
                    else:
                        lumina_logger.info(" No updates needed")

                    # Update route stats from community spreadsheet
                    lumina_logger.info(" Checking for route data updates...")
                    route_count = route_stats_service.update_route_stats()
                    if route_count > 0:
                        lumina_logger.info(f"Updated {route_count} routes")
                    else:
                        lumina_logger.info(" No updates needed")

                    # Aggregate daily voyage stats
                    logger.info(" Aggregating daily stats...")
                    from app.services.stats_tracker import stats_tracker
                    stats_tracker.aggregate_daily_stats()

            except Exception as e:
                lumina_logger.info(f"Update error: {e}")

    _lumina_thread = threading.Thread(target=lumina_update_loop, daemon=True)
    _lumina_thread.start()
    lumina_logger.info(" Background update thread started (6 hour interval)")
