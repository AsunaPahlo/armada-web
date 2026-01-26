"""
Alert system models for notification configuration and history tracking.
"""
from datetime import datetime
from app import db
from app.utils.crypto import encrypt_value, decrypt_value


class AlertSettings(db.Model):
    """Global alert configuration settings (singleton pattern - one row)."""

    __tablename__ = 'alert_settings'

    id = db.Column(db.Integer, primary_key=True)

    # Master enable
    alerts_enabled = db.Column(db.Boolean, default=False)

    # Low supply alert settings
    low_supply_enabled = db.Column(db.Boolean, default=True)
    low_supply_threshold_days = db.Column(db.Float, default=7.0)
    low_supply_cooldown_minutes = db.Column(db.Integer, default=60)

    # Idle submarine alert settings
    idle_sub_enabled = db.Column(db.Boolean, default=True)
    idle_sub_threshold_hours = db.Column(db.Float, default=2.0)
    idle_sub_cooldown_minutes = db.Column(db.Integer, default=30)

    # Not farming alert settings (submarines above level threshold not on money routes)
    not_farming_enabled = db.Column(db.Boolean, default=False)
    not_farming_level_threshold = db.Column(db.Integer, default=90)
    not_farming_cooldown_minutes = db.Column(db.Integer, default=60)

    # Email (SMTP) settings
    email_enabled = db.Column(db.Boolean, default=False)
    smtp_host = db.Column(db.String(255), nullable=True)
    smtp_port = db.Column(db.Integer, default=587)
    smtp_username = db.Column(db.String(255), nullable=True)
    _smtp_password = db.Column('smtp_password', db.String(500), nullable=True)
    smtp_use_tls = db.Column(db.Boolean, default=True)
    smtp_use_auth = db.Column(db.Boolean, default=True)
    smtp_from_address = db.Column(db.String(255), nullable=True)
    smtp_to_addresses = db.Column(db.Text, nullable=True)  # Comma-separated

    # Pushover settings
    pushover_enabled = db.Column(db.Boolean, default=False)
    _pushover_user_key = db.Column('pushover_user_key', db.String(500), nullable=True)
    _pushover_api_token = db.Column('pushover_api_token', db.String(500), nullable=True)
    pushover_priority = db.Column(db.Integer, default=0)  # -2 to 2

    # Discord webhook settings
    discord_enabled = db.Column(db.Boolean, default=False)
    _discord_webhook_url = db.Column('discord_webhook_url', db.String(1000), nullable=True)

    # Encrypted property accessors
    @property
    def smtp_password(self):
        return decrypt_value(self._smtp_password)

    @smtp_password.setter
    def smtp_password(self, value):
        self._smtp_password = encrypt_value(value) if value else None

    @property
    def pushover_user_key(self):
        return decrypt_value(self._pushover_user_key)

    @pushover_user_key.setter
    def pushover_user_key(self, value):
        self._pushover_user_key = encrypt_value(value) if value else None

    @property
    def pushover_api_token(self):
        return decrypt_value(self._pushover_api_token)

    @pushover_api_token.setter
    def pushover_api_token(self, value):
        self._pushover_api_token = encrypt_value(value) if value else None

    @property
    def discord_webhook_url(self):
        return decrypt_value(self._discord_webhook_url)

    @discord_webhook_url.setter
    def discord_webhook_url(self, value):
        self._discord_webhook_url = encrypt_value(value) if value else None

    # Browser toast settings
    browser_toast_enabled = db.Column(db.Boolean, default=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_settings(cls):
        """Get or create singleton settings row."""
        # Run migrations for new columns
        cls._migrate_columns()

        settings = cls.query.first()
        if settings is None:
            settings = cls()
            db.session.add(settings)
            db.session.commit()
        return settings

    @classmethod
    def _migrate_columns(cls):
        """Add any missing columns to the table (for existing databases)."""
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)

        if cls.__tablename__ not in inspector.get_table_names():
            return  # Table doesn't exist yet, will be created

        existing_columns = {col['name'] for col in inspector.get_columns(cls.__tablename__)}

        # Define new columns and their defaults
        migrations = [
            ('not_farming_enabled', 'BOOLEAN DEFAULT 0'),
            ('not_farming_level_threshold', 'INTEGER DEFAULT 90'),
            ('not_farming_cooldown_minutes', 'INTEGER DEFAULT 60'),
        ]

        for col_name, col_def in migrations:
            if col_name not in existing_columns:
                try:
                    db.session.execute(
                        text(f'ALTER TABLE {cls.__tablename__} ADD COLUMN {col_name} {col_def}')
                    )
                    db.session.commit()
                except Exception:
                    db.session.rollback()  # Column might already exist

    def __repr__(self):
        return f'<AlertSettings enabled={self.alerts_enabled}>'


class AlertHistory(db.Model):
    """Record of sent alerts for cooldown tracking and history."""

    __tablename__ = 'alert_history'

    id = db.Column(db.Integer, primary_key=True)

    # Alert type: 'low_supply' or 'idle_sub'
    alert_type = db.Column(db.String(30), nullable=False, index=True)

    # Target identifier (fc_id for low_supply, fc_id:sub_name for idle_sub)
    target_id = db.Column(db.String(100), nullable=False, index=True)
    target_name = db.Column(db.String(200), nullable=True)

    # Alert details
    message = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(20), default='warning')  # 'info', 'warning', 'critical'

    # Delivery status per channel
    sent_email = db.Column(db.Boolean, default=False)
    sent_pushover = db.Column(db.Boolean, default=False)
    sent_discord = db.Column(db.Boolean, default=False)
    sent_browser = db.Column(db.Boolean, default=False)

    # Acknowledgment tracking
    acknowledged = db.Column(db.Boolean, default=False, index=True)
    acknowledged_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Composite index for cooldown lookups
    __table_args__ = (
        db.Index('idx_alert_cooldown', 'alert_type', 'target_id', 'created_at'),
    )

    def __repr__(self):
        return f'<AlertHistory {self.alert_type} @ {self.created_at}>'
