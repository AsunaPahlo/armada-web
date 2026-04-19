"""Per-FC daily snapshot of FC credits balance."""
from datetime import datetime
from app import db


class FCCreditsSnapshot(db.Model):
    """One row per FC per day. Latest value seen during the day wins."""
    __tablename__ = 'fc_credits_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    fc_id = db.Column(db.String(64), nullable=False, index=True)
    snapshot_date = db.Column(db.Date, nullable=False, index=True)
    credits = db.Column(db.BigInteger, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('fc_id', 'snapshot_date', name='uq_fc_credits_fc_date'),
    )

    def __repr__(self):
        return f'<FCCreditsSnapshot fc={self.fc_id} date={self.snapshot_date} credits={self.credits}>'
