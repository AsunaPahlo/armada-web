"""
Armada services
"""
from app.services.config_parser import ConfigParser
from app.services.fleet_manager import FleetManager
from app.services.stats_tracker import StatsTracker

__all__ = ['ConfigParser', 'FleetManager', 'StatsTracker', 'get_fleet_manager']

# Single shared FleetManager instance
_shared_fleet_manager: FleetManager = None


def get_fleet_manager(app=None) -> FleetManager:
    """
    Get the shared FleetManager instance.

    Args:
        app: Flask app (required on first call to get config path)

    Returns:
        The shared FleetManager instance
    """
    global _shared_fleet_manager
    if _shared_fleet_manager is None:
        if app is None:
            from flask import current_app
            app = current_app
        _shared_fleet_manager = FleetManager(app.config['ACCOUNTS_CONFIG_PATH'])
    return _shared_fleet_manager
