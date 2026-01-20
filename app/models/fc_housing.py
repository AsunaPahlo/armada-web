"""
FC Housing data model for storing FC house addresses.
"""
from datetime import datetime
from app import db


class FCHousing(db.Model):
    """FC house address information."""
    __tablename__ = 'fc_housing'

    id = db.Column(db.Integer, primary_key=True)
    fc_id = db.Column(db.String(30), nullable=False, unique=True, index=True)

    # House location
    world = db.Column(db.String(50), nullable=False)
    district = db.Column(db.String(50), nullable=False)
    ward = db.Column(db.Integer, nullable=False)
    plot = db.Column(db.Integer, nullable=False)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<FCHousing {self.fc_id} - {self.address}>'

    @property
    def address(self) -> str:
        """Return formatted house address."""
        return f"{self.district} Ward {self.ward} Plot {self.plot}"

    def to_dict(self):
        return {
            'fc_id': self.fc_id,
            'world': self.world,
            'district': self.district,
            'ward': self.ward,
            'plot': self.plot,
            'address': self.address,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


def get_fc_housing(fc_id: str) -> FCHousing | None:
    """
    Get housing data for an FC.

    Args:
        fc_id: The FC identifier

    Returns:
        FCHousing object or None if not found
    """
    return FCHousing.query.filter_by(fc_id=str(fc_id)).first()


def get_all_fc_housing() -> dict:
    """
    Get all FC housing data as a dict.

    Returns:
        Dict mapping fc_id -> FCHousing object
    """
    housing = FCHousing.query.all()
    return {h.fc_id: h for h in housing}


def update_fc_housing(fc_id: str, world: str, district: str,
                      ward: int, plot: int) -> FCHousing:
    """
    Update or create housing data for an FC.

    Args:
        fc_id: The FC identifier
        world: World name where the house is located
        district: Housing district name (Mist, Lavender Beds, etc.)
        ward: Ward number
        plot: Plot number

    Returns:
        Updated FCHousing object
    """
    fc_id = str(fc_id)
    housing = FCHousing.query.filter_by(fc_id=fc_id).first()

    if not housing:
        housing = FCHousing(fc_id=fc_id)
        db.session.add(housing)

    housing.world = world
    housing.district = district
    housing.ward = ward
    housing.plot = plot
    housing.updated_at = datetime.utcnow()

    db.session.commit()
    return housing
