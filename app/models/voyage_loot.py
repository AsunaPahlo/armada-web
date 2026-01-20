"""
Voyage loot tracking models for per-voyage loot and gil value tracking
"""
from datetime import datetime
from app import db


class VoyageLoot(db.Model):
    """Record of loot captured from a single submarine voyage."""

    __tablename__ = 'voyage_loot'

    id = db.Column(db.Integer, primary_key=True)

    # Link to voyage record (optional - may not always match)
    voyage_id = db.Column(db.Integer, db.ForeignKey('voyages.id'), nullable=True, index=True)

    # Account/Character identification
    account_name = db.Column(db.String(100), nullable=False, index=True)
    character_name = db.Column(db.String(100), nullable=False, index=True)
    fc_id = db.Column(db.String(30), nullable=True, index=True)
    fc_tag = db.Column(db.String(10), nullable=True)

    # Submarine info
    submarine_name = db.Column(db.String(100), nullable=False, index=True)

    # Route info
    route_sectors = db.Column(db.String(100), nullable=True)  # JSON array of sector IDs
    route_name = db.Column(db.String(50), nullable=True)

    # Aggregated values
    total_items = db.Column(db.Integer, default=0)
    total_gil_value = db.Column(db.BigInteger, default=0)

    # Timestamps
    captured_at = db.Column(db.DateTime, nullable=False, index=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to items
    items = db.relationship('VoyageLootItem', backref='voyage_loot', lazy='dynamic',
                           cascade='all, delete-orphan')

    # Unique constraint to prevent duplicate submissions
    # Composite indexes for common query patterns (fc + date, submarine + date)
    __table_args__ = (
        db.UniqueConstraint('fc_id', 'submarine_name', 'captured_at',
                            name='unique_voyage_loot'),
        db.Index('ix_voyage_loot_fc_captured', 'fc_id', 'captured_at'),
        db.Index('ix_voyage_loot_submarine_captured', 'submarine_name', 'captured_at'),
    )

    def __repr__(self):
        return f'<VoyageLoot {self.submarine_name} @ {self.captured_at}>'


class VoyageLootItem(db.Model):
    """Individual item from a voyage sector."""

    __tablename__ = 'voyage_loot_items'

    id = db.Column(db.Integer, primary_key=True)

    # Link to parent loot record
    voyage_loot_id = db.Column(db.Integer, db.ForeignKey('voyage_loot.id'), nullable=False, index=True)

    # Sector identification
    sector_id = db.Column(db.Integer, nullable=False)

    # Primary item
    item_id_primary = db.Column(db.Integer, nullable=True)
    item_name_primary = db.Column(db.String(100), nullable=True)
    count_primary = db.Column(db.Integer, default=0)
    hq_primary = db.Column(db.Boolean, default=False)
    vendor_price_primary = db.Column(db.Integer, default=0)

    # Additional item
    item_id_additional = db.Column(db.Integer, nullable=True)
    item_name_additional = db.Column(db.String(100), nullable=True)
    count_additional = db.Column(db.Integer, default=0)
    hq_additional = db.Column(db.Boolean, default=False)
    vendor_price_additional = db.Column(db.Integer, default=0)

    @property
    def primary_value(self) -> int:
        """Calculate vendor value for primary item."""
        return self.vendor_price_primary * self.count_primary

    @property
    def additional_value(self) -> int:
        """Calculate vendor value for additional item."""
        return self.vendor_price_additional * self.count_additional

    @property
    def total_value(self) -> int:
        """Calculate total vendor value for this sector."""
        return self.primary_value + self.additional_value

    def __repr__(self):
        return f'<VoyageLootItem sector={self.sector_id}>'
