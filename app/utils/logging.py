"""
Centralized logging configuration for Armada.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging():
    """Configure application-wide logging."""
    # Create formatters
    console_formatter = logging.Formatter('[%(name)s] %(message)s')
    file_formatter = logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add stdout handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Add file handler (rotating, max 5MB, keep 3 backups)
    log_dir = Path(__file__).parent.parent.parent / 'data'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'armada.log'

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Suppress noisy loggers
    logging.getLogger('engineio').setLevel(logging.WARNING)
    logging.getLogger('socketio').setLevel(logging.WARNING)
    logging.getLogger('gevent').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.

    Usage:
        from app.utils.logging import get_logger
        logger = get_logger(__name__)
        logger.info("Something happened")
    """
    return logging.getLogger(name)
