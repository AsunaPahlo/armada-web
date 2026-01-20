"""
Lumina game data models - stores FFXIV datamining CSV data
Updated from https://github.com/xivapi/ffxiv-datamining
"""
from datetime import datetime
from app import db


class DataVersion(db.Model):
    """Tracks version/update status of Lumina data tables."""

    __tablename__ = 'data_versions'

    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(50), nullable=False, unique=True, index=True)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    etag = db.Column(db.String(100), nullable=True)  # GitHub ETag for conditional requests
    row_count = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<DataVersion {self.table_name} @ {self.last_updated}>'


class SubmarinePart(db.Model):
    """Submarine part data from SubmarinePart.csv"""

    __tablename__ = 'submarine_parts'

    id = db.Column(db.Integer, primary_key=True)  # Row ID from CSV
    slot = db.Column(db.Integer, nullable=False)  # 0=Hull, 1=Stern, 2=Bow, 3=Bridge
    rank = db.Column(db.Integer, nullable=False)  # Part rank (affects damage calc)
    class_type = db.Column(db.Integer, nullable=False)  # Submarine class
    components = db.Column(db.Integer, default=0)  # Components to craft
    repair_materials = db.Column(db.Integer, default=0)  # Repair kits needed

    # Stats
    surveillance = db.Column(db.Integer, default=0)
    retrieval = db.Column(db.Integer, default=0)
    speed = db.Column(db.Integer, default=0)
    range = db.Column(db.Integer, default=0)
    favor = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<SubmarinePart {self.id} Slot:{self.slot} Rank:{self.rank}>'


class SubmarineExploration(db.Model):
    """Submarine exploration sector data from SubmarineExploration.csv"""

    __tablename__ = 'submarine_explorations'

    id = db.Column(db.Integer, primary_key=True)  # Row ID from CSV
    destination = db.Column(db.String(100), nullable=False)  # Sector name
    location = db.Column(db.String(10), nullable=False)  # Letter code (A, B, C, etc.)
    map_id = db.Column(db.Integer, nullable=False, index=True)  # Which map (1-7)

    # Requirements
    rank_req = db.Column(db.Integer, default=1)  # Minimum rank to unlock
    ceruleum_tank_req = db.Column(db.Integer, default=1)  # Fuel cost
    stars = db.Column(db.Integer, default=1)  # Difficulty stars

    # Rewards
    exp_reward = db.Column(db.Integer, default=0)  # Base experience

    # Survey info
    survey_duration_min = db.Column(db.Integer, default=0)  # Survey time in minutes
    survey_distance = db.Column(db.Integer, default=0)  # Distance value

    # Coordinates for distance calculation
    x = db.Column(db.Integer, default=0)
    y = db.Column(db.Integer, default=0)
    z = db.Column(db.Integer, default=0)

    # Starting point flag
    starting_point = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<SubmarineExploration {self.location} "{self.destination}">'


class SubmarineMap(db.Model):
    """Submarine map data from SubmarineMap.csv"""

    __tablename__ = 'submarine_maps'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f'<SubmarineMap {self.id} "{self.name}">'


class SubmarineRank(db.Model):
    """Submarine rank bonuses from SubmarineRank.csv"""

    __tablename__ = 'submarine_ranks'

    id = db.Column(db.Integer, primary_key=True)  # Rank level (1-125)
    capacity = db.Column(db.Integer, default=0)  # Unlocked capacity
    exp_to_next = db.Column(db.Integer, default=0)  # EXP needed for next rank

    # Rank bonuses
    surveillance_bonus = db.Column(db.Integer, default=0)
    retrieval_bonus = db.Column(db.Integer, default=0)
    speed_bonus = db.Column(db.Integer, default=0)
    range_bonus = db.Column(db.Integer, default=0)
    favor_bonus = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<SubmarineRank {self.id}>'


class RouteStats(db.Model):
    """
    Route gil/earnings data from community spreadsheet.
    Source: Fightclub submarine spreadsheet
    Note: Fuel/repair data should come from Lumina, this is just for gil estimates.
    """

    __tablename__ = 'route_stats'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    route_name = db.Column(db.String(20), nullable=False, unique=True, index=True)  # OJ, MOJ, JORZ, etc.
    gil_per_sub_day = db.Column(db.Integer, default=0)  # Gil per submarine per day
    avg_exp = db.Column(db.Integer, default=0)  # Average experience per voyage
    fc_points = db.Column(db.Integer, default=0)  # FC points per voyage

    def __repr__(self):
        return f'<RouteStats {self.route_name} {self.gil_per_sub_day}g/sub/day>'
