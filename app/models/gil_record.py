"""Gil tracking model for per-character gil snapshots over time."""
from datetime import datetime
from app import db


class GilRecord(db.Model):
    """Daily gil snapshot for a character. One record per character per day."""

    __tablename__ = 'gil_records'

    id = db.Column(db.Integer, primary_key=True)

    # Source tracking
    api_key_id = db.Column(db.Integer, db.ForeignKey('api_keys.id'), nullable=False, index=True)
    client_nickname = db.Column(db.String(100), nullable=False)

    # Character identification
    character_name = db.Column(db.String(100), nullable=False, index=True)
    world = db.Column(db.String(50), nullable=False)
    cid = db.Column(db.String(30), nullable=False, index=True)

    # Gil amounts (last known value for the day)
    gil_player = db.Column(db.BigInteger, nullable=False, default=0)
    gil_retainer = db.Column(db.BigInteger, nullable=False, default=0)

    # Date of the record (one per character per day)
    record_date = db.Column(db.Date, nullable=False, index=True)

    # Original CashFlow timestamp (for reference)
    timestamp = db.Column(db.DateTime, nullable=False)

    # When the server last updated this record
    received_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Deduplicate on character + date (one record per character per day)
    __table_args__ = (
        db.UniqueConstraint('cid', 'record_date', name='unique_gil_record'),
        db.Index('ix_gil_cid_date', 'cid', 'record_date'),
        db.Index('ix_gil_api_key', 'api_key_id'),
    )

    def __repr__(self):
        return f'<GilRecord {self.character_name} {self.gil_player + self.gil_retainer:,} @ {self.record_date}>'
