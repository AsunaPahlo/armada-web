"""
Armada - FFXIV Submarine Fleet Dashboard
Flask application factory
"""
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_socketio import SocketIO
from sqlalchemy.exc import SQLAlchemyError

from app.utils.logging import setup_logging, get_logger

__version__ = '1.0.0.9'

# Set up logging before anything else
setup_logging()
logger = get_logger('Startup')

db = SQLAlchemy()
login_manager = LoginManager()
socketio = SocketIO()
scheduler = None  # APScheduler instance, initialized in create_app


def create_app(config_name=None):
    """Application factory for creating Flask app instance."""
    app = Flask(__name__)

    # Load configuration
    app.config.from_object('app.config.Config')

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode='gevent',
        ping_timeout=60,
        ping_interval=25
    )

    # Configure login manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    # Make version available to all templates
    @app.context_processor
    def inject_version():
        return {'app_version': __version__}

    # Register blueprints
    from app.routes.dashboard import dashboard_bp
    from app.routes.api import api_bp
    from app.routes.auth import auth_bp
    from app.routes.stats import stats_bp
    from app.routes.alerts import alerts_bp
    from app.routes.tags import tags_bp
    from app.routes.users import users_bp
    from app.routes.api_keys import api_keys_bp
    from app.routes.fc_config import fc_config_bp
    from app.routes.export import export_bp
    from app.routes.unlocks import unlocks_bp
    from app.routes.mobile import mobile_bp
    from app.routes.settings import settings_bp
    from app.routes.api_v1 import api_v1_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(stats_bp, url_prefix='/stats')
    app.register_blueprint(alerts_bp, url_prefix='/alerts')
    app.register_blueprint(tags_bp, url_prefix='/tags')
    app.register_blueprint(users_bp, url_prefix='/users')
    app.register_blueprint(api_keys_bp, url_prefix='/api-keys')
    app.register_blueprint(fc_config_bp, url_prefix='/settings/fc-config')
    app.register_blueprint(export_bp, url_prefix='/export')
    app.register_blueprint(unlocks_bp, url_prefix='/unlocks')
    app.register_blueprint(mobile_bp, url_prefix='/m')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(api_v1_bp, url_prefix='/api/v1')

    # Create database tables
    with app.app_context():
        # Import models to ensure tables are created
        from app.models import tag  # noqa: F401
        from app.models import api_key  # noqa: F401
        from app.models import voyage_loot  # noqa: F401
        from app.models import fc_config  # noqa: F401
        from app.models import fc_housing  # noqa: F401
        from app.models import daily_stats  # noqa: F401
        db.create_all()

        # Auto-populate DailyStats from historical data if empty
        from app.models.daily_stats import DailyStats
        if DailyStats.query.count() == 0:
            try:
                logger.info("DailyStats table empty, rebuilding from historical data...")
                DailyStats.rebuild_from_raw_data()
            except SQLAlchemyError as e:
                db.session.rollback()
                logger.warning(f"Could not rebuild DailyStats: {e}")

        # Load Lumina game data on startup
        from app.services.lumina_service import lumina_service
        lumina_service.ensure_data_loaded()

        # Load route stats from community spreadsheet
        from app.services.route_stats_service import route_stats_service
        route_stats_service.ensure_data_loaded()

    # Register WebSocket handlers
    from app.routes import websocket
    websocket.register_handlers(socketio)

    # Initialize background scheduler for nightly tasks
    _init_scheduler(app)

    return app


def _init_scheduler(app):
    """Initialize APScheduler for background tasks like DailyStats rebuild."""
    global scheduler
    sched_logger = get_logger('Scheduler')

    # Only start scheduler once (avoid duplicates in multi-worker setups)
    if scheduler is not None:
        return

    # Don't start scheduler in reloader subprocess
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.interval import IntervalTrigger
            from datetime import datetime, date

            scheduler = BackgroundScheduler()

            # Track last rebuild date to ensure once-per-day
            last_rebuild_date = {'value': None}

            def smart_rebuild_check():
                """Check if it's safe to rebuild DailyStats (1-7 AM window, no subs returning in next hour)."""
                with app.app_context():
                    try:
                        # Skip if already rebuilt today
                        today = date.today()
                        if last_rebuild_date['value'] == today:
                            return

                        # Only run during 1 AM - 7 AM window (local server time)
                        current_hour = datetime.now().hour
                        if current_hour < 1 or current_hour >= 7:
                            return

                        # Check soonest submarine return time
                        from app.services import get_fleet_manager
                        from datetime import timedelta

                        fleet = get_fleet_manager()
                        fleet_data = fleet.get_dashboard_data()

                        # Find the soonest return time across all submarines
                        now = datetime.utcnow()
                        one_hour_from_now = now + timedelta(hours=1)
                        soonest_return = None

                        for fc in fleet_data.get('fc_summaries', []):
                            for sub in fc.get('submarines', []):
                                return_time = sub.get('return_time')
                                if return_time:
                                    # Parse if string
                                    if isinstance(return_time, str):
                                        try:
                                            return_time = datetime.fromisoformat(return_time.replace('Z', '+00:00'))
                                            return_time = return_time.replace(tzinfo=None)
                                        except (ValueError, AttributeError):
                                            continue

                                    # Only consider future returns
                                    if return_time > now:
                                        if soonest_return is None or return_time < soonest_return:
                                            soonest_return = return_time

                        # If no subs returning in next hour, rebuild
                        if soonest_return is None or soonest_return > one_hour_from_now:
                            sched_logger.info(f"Safe window detected (next return: {soonest_return or 'none'}). Starting DailyStats rebuild...")
                            from app.models.daily_stats import DailyStats
                            count = DailyStats.rebuild_from_raw_data()
                            last_rebuild_date['value'] = today
                            sched_logger.info(f"DailyStats rebuild complete. {count} records.")
                        else:
                            mins_until = int((soonest_return - now).total_seconds() / 60)
                            sched_logger.debug(f"Sub returning in {mins_until} mins, skipping rebuild check.")

                    except Exception as e:
                        sched_logger.exception(f"Smart rebuild check failed: {e}")

            # Check every 30 minutes for a safe rebuild window
            scheduler.add_job(
                smart_rebuild_check,
                IntervalTrigger(minutes=30),
                id='smart_daily_stats_rebuild',
                name='Smart DailyStats Rebuild Check',
                replace_existing=True
            )

            scheduler.start()
            sched_logger.info("Background scheduler started. DailyStats rebuild will run once daily between 1-7 AM when no subs are returning for 1 hour.")

        except ImportError:
            sched_logger.warning("APScheduler not installed. Background tasks disabled. Install with: pip install apscheduler")
        except Exception as e:
            sched_logger.exception(f"Failed to start scheduler: {e}")
