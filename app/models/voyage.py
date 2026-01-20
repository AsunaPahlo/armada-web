"""
Voyage tracking models for per-voyage statistics
"""
from datetime import datetime
from app import db


class Voyage(db.Model):
    """Individual voyage record for tracking submarine voyages."""

    __tablename__ = 'voyages'

    id = db.Column(db.Integer, primary_key=True)

    # Account/Character identification
    account_name = db.Column(db.String(100), nullable=False, index=True)
    character_name = db.Column(db.String(100), nullable=False, index=True)
    character_cid = db.Column(db.String(30), nullable=False, index=True)  # Stored as string (FFXIV IDs exceed SQLite int)
    fc_id = db.Column(db.String(30), nullable=True, index=True)  # Stored as string
    fc_name = db.Column(db.String(100), nullable=True)
    world = db.Column(db.String(50), nullable=False)

    # Submarine info
    submarine_name = db.Column(db.String(100), nullable=False, index=True)
    submarine_level = db.Column(db.Integer, nullable=True)
    submarine_build = db.Column(db.String(20), nullable=True)  # e.g., "S+S+U+C+"

    # Voyage details
    route_name = db.Column(db.String(50), nullable=True)  # e.g., "OJ", "JORZ"
    route_points = db.Column(db.String(100), nullable=True)  # JSON array of point IDs
    duration_hours = db.Column(db.Float, nullable=True)  # Calculated voyage duration in hours

    # Timestamps
    departure_time = db.Column(db.DateTime, nullable=True)
    return_time = db.Column(db.DateTime, nullable=False, index=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Status tracking
    was_collected = db.Column(db.Boolean, default=False)
    collected_at = db.Column(db.DateTime, nullable=True, index=True)

    # Unique constraint to prevent duplicate voyage entries
    # Composite indexes for common query patterns (fc + date, submarine + date)
    __table_args__ = (
        db.UniqueConstraint('character_cid', 'submarine_name', 'return_time',
                            name='unique_voyage'),
        db.Index('ix_voyage_fc_return', 'fc_id', 'return_time'),
        db.Index('ix_voyage_submarine_return', 'submarine_name', 'return_time'),
    )

    def __repr__(self):
        return f'<Voyage {self.submarine_name} @ {self.return_time}>'


class VoyageStats(db.Model):
    """Aggregated daily statistics per FC/character."""

    __tablename__ = 'voyage_stats'

    id = db.Column(db.Integer, primary_key=True)

    # Identification
    account_name = db.Column(db.String(100), nullable=False, index=True)
    fc_id = db.Column(db.String(30), nullable=True, index=True)  # Stored as string
    fc_name = db.Column(db.String(100), nullable=True)

    # Date for aggregation
    stat_date = db.Column(db.Date, nullable=False, index=True)

    # Counts
    voyages_sent = db.Column(db.Integer, default=0)
    voyages_collected = db.Column(db.Integer, default=0)
    submarines_active = db.Column(db.Integer, default=0)

    # Calculated values
    estimated_gil = db.Column(db.BigInteger, default=0)
    ceruleum_used = db.Column(db.Float, default=0.0)
    repair_kits_used = db.Column(db.Float, default=0.0)

    # Snapshot of inventory at end of day
    ceruleum_remaining = db.Column(db.Integer, nullable=True)
    repair_kits_remaining = db.Column(db.Integer, nullable=True)

    # Unique constraint
    __table_args__ = (
        db.UniqueConstraint('account_name', 'fc_id', 'stat_date',
                            name='unique_daily_stat'),
    )

    def __repr__(self):
        return f'<VoyageStats {self.fc_name} @ {self.stat_date}>'
