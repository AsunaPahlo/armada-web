"""
Application settings model for storing configurable values like material costs.
"""
from app import db


class AppSettings(db.Model):
    """
    Key-value store for application-wide settings.
    Used for things like marketboard prices that apply to all users.
    """

    __tablename__ = 'app_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.String(500), nullable=True)
    description = db.Column(db.String(255), nullable=True)

    # Default settings with their descriptions
    DEFAULTS = {
        'ceruleum_price_per_stack': ('5000', 'Price per stack of 999 Ceruleum Tanks on marketboard'),
        'repair_kit_price_per_stack': ('10000', 'Price per stack of 999 Repair Kits on marketboard'),
        'ceruleum_stack_size': ('999', 'Number of tanks per stack'),
        'repair_kit_stack_size': ('999', 'Number of kits per stack'),
        'rebuild_window_start': ('1', 'Start hour for DailyStats rebuild window (0-23)'),
        'rebuild_window_end': ('7', 'End hour for DailyStats rebuild window (0-23)'),
        'target_submarine_level': ('90', 'Target level for submarine leveling estimates'),
    }

    @classmethod
    def get(cls, key: str, default=None):
        """
        Get a setting value by key.

        Args:
            key: Setting key
            default: Default value if not found (or use DEFAULTS)

        Returns:
            Setting value as string, or default
        """
        setting = cls.query.filter_by(key=key).first()
        if setting:
            return setting.value

        # Check built-in defaults
        if key in cls.DEFAULTS:
            return cls.DEFAULTS[key][0]

        return default

    @classmethod
    def get_int(cls, key: str, default: int = 0) -> int:
        """Get a setting value as integer."""
        value = cls.get(key)
        try:
            return int(value) if value else default
        except (ValueError, TypeError):
            return default

    @classmethod
    def get_float(cls, key: str, default: float = 0.0) -> float:
        """Get a setting value as float."""
        value = cls.get(key)
        try:
            return float(value) if value else default
        except (ValueError, TypeError):
            return default

    @classmethod
    def set(cls, key: str, value, description: str = None):
        """
        Set a setting value.

        Args:
            key: Setting key
            value: Value to store (will be converted to string)
            description: Optional description
        """
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = str(value)
            if description:
                setting.description = description
        else:
            desc = description
            if not desc and key in cls.DEFAULTS:
                desc = cls.DEFAULTS[key][1]
            setting = cls(key=key, value=str(value), description=desc)
            db.session.add(setting)

        db.session.commit()
        return setting

    @classmethod
    def get_all(cls) -> dict:
        """
        Get all settings as a dictionary.
        Includes defaults for any missing keys.
        """
        result = {}

        # Start with defaults
        for key, (default_value, description) in cls.DEFAULTS.items():
            result[key] = {
                'value': default_value,
                'description': description
            }

        # Override with database values
        for setting in cls.query.all():
            result[setting.key] = {
                'value': setting.value,
                'description': setting.description or result.get(setting.key, {}).get('description', '')
            }

        return result

    @classmethod
    def get_material_costs(cls) -> dict:
        """
        Get material cost settings specifically.

        Returns:
            Dict with ceruleum_price_per_unit and repair_kit_price_per_unit
        """
        ceruleum_price = cls.get_int('ceruleum_price_per_stack', 5000)
        ceruleum_stack = cls.get_int('ceruleum_stack_size', 999)
        kit_price = cls.get_int('repair_kit_price_per_stack', 10000)
        kit_stack = cls.get_int('repair_kit_stack_size', 999)

        return {
            'ceruleum_price_per_stack': ceruleum_price,
            'ceruleum_stack_size': ceruleum_stack,
            'ceruleum_price_per_unit': ceruleum_price / ceruleum_stack if ceruleum_stack > 0 else 0,
            'repair_kit_price_per_stack': kit_price,
            'repair_kit_stack_size': kit_stack,
            'repair_kit_price_per_unit': kit_price / kit_stack if kit_stack > 0 else 0,
        }

    def __repr__(self):
        return f'<AppSettings {self.key}={self.value}>'
