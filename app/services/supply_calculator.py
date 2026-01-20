"""
Supply Calculator Service

Calculates submarine supply consumption using Lumina game data.
Based on formulas from SubmarineTracker.

Key formulas:
- Damage per part per sector = (335 + Sector.RankReq - Part.Rank) * 7
- Fuel per voyage = sum of CeruleumTankReq for all sectors
- Repair materials = sum of RepairMaterials for all 4 parts (on full repair)
- Max durability = 30,000 HP
"""
import math
from typing import Optional
from dataclasses import dataclass

from app.models.lumina import SubmarinePart, SubmarineExploration, SubmarineRank


# Constants from SubmarineTracker
BASE_DAMAGE_MODIFIER = 335
DAMAGE_MULTIPLIER = 7
MAX_DURABILITY = 30000

# Fixed voyage time (12 hours in seconds)
FIXED_VOYAGE_TIME = 43200


@dataclass
class VoyageSupplyCost:
    """Supply cost for a single voyage."""
    ceruleum_tanks: int = 0
    repair_damage: int = 0  # Total damage dealt to parts
    repair_materials_on_full: int = 0  # Repair kits needed if fully repairing
    voyage_duration_hours: float = 0.0


@dataclass
class DailySupplyCost:
    """Daily supply consumption rates."""
    ceruleum_per_day: float = 0.0
    repair_kits_per_day: float = 0.0
    voyages_per_day: float = 0.0


@dataclass
class SupplyForecast:
    """Forecast of supply consumption."""
    days_until_ceruleum_empty: float = 999.0
    days_until_kits_empty: float = 999.0
    days_until_restock: float = 999.0
    limiting_resource: str = "none"  # "ceruleum", "kits", or "none"


class SupplyCalculator:
    """
    Calculate submarine supply consumption using Lumina data.
    """

    def get_part(self, part_id: int) -> Optional[SubmarinePart]:
        """Get submarine part from database."""
        return SubmarinePart.query.get(part_id)

    def get_sector(self, sector_id: int) -> Optional[SubmarineExploration]:
        """Get exploration sector from database."""
        return SubmarineExploration.query.get(sector_id)

    def get_sector_by_location(self, location: str) -> Optional[SubmarineExploration]:
        """Get sector by location letter (e.g., 'O', 'J', 'Z')."""
        return SubmarineExploration.query.filter_by(location=location).first()

    def get_rank_bonus(self, rank: int) -> Optional[SubmarineRank]:
        """Get rank bonuses for a given rank level."""
        return SubmarineRank.query.get(rank)

    def calculate_part_damage(self, part_rank: int, sector_rank_req: int) -> int:
        """
        Calculate damage to a single part for one sector.

        Formula: (335 + Sector.RankReq - Part.Rank) * 7
        """
        return (BASE_DAMAGE_MODIFIER + sector_rank_req - part_rank) * DAMAGE_MULTIPLIER

    def calculate_voyage_damage(self, part_ids: list[int], sector_ids: list[int]) -> dict:
        """
        Calculate total voyage damage to each part.

        Args:
            part_ids: List of 4 part IDs [hull, stern, bow, bridge]
            sector_ids: List of sector IDs in the route

        Returns:
            Dict with per-part damage and total
        """
        parts = [self.get_part(pid) for pid in part_ids if pid]
        sectors = [self.get_sector(sid) for sid in sector_ids if sid]

        if not parts or not sectors:
            return {'per_part': [], 'max_damage': 0, 'total_damage': 0}

        per_part_damage = []
        for part in parts:
            if not part:
                per_part_damage.append(0)
                continue

            damage = 0
            for sector in sectors:
                if sector:
                    damage += self.calculate_part_damage(part.rank, sector.rank_req)
            per_part_damage.append(damage)

        return {
            'per_part': per_part_damage,
            'max_damage': max(per_part_damage) if per_part_damage else 0,
            'total_damage': sum(per_part_damage)
        }

    def calculate_voyages_until_repair(self, part_ids: list[int], sector_ids: list[int]) -> int:
        """
        Calculate how many voyages until repair is needed (when any part would exceed max HP).

        Formula: ceil(30,000 / max_part_damage)
        """
        damage_info = self.calculate_voyage_damage(part_ids, sector_ids)
        max_damage = damage_info['max_damage']

        if max_damage <= 0:
            return 999

        return math.ceil(MAX_DURABILITY / max_damage)

    def calculate_fuel_cost(self, sector_ids: list[int]) -> int:
        """
        Calculate total ceruleum tank cost for a voyage.

        Formula: sum of CeruleumTankReq for all sectors
        """
        total = 0
        for sector_id in sector_ids:
            sector = self.get_sector(sector_id)
            if sector:
                total += sector.ceruleum_tank_req
        return total

    def calculate_repair_materials(self, part_ids: list[int]) -> int:
        """
        Calculate total repair materials for a full repair.

        Formula: sum of RepairMaterials for all 4 parts
        """
        total = 0
        for part_id in part_ids:
            part = self.get_part(part_id)
            if part:
                total += part.repair_materials
        return total

    def calculate_voyage_duration(
        self,
        sector_ids: list[int],
        total_speed: int
    ) -> float:
        """
        Calculate voyage duration in hours.

        This is a simplified calculation - full calculation requires
        distance between sectors.
        """
        # Basic: 12 hours fixed + survey time
        total_survey_mins = 0
        for sector_id in sector_ids:
            sector = self.get_sector(sector_id)
            if sector:
                total_survey_mins += sector.survey_duration_min

        # Speed affects survey time: floor(survey_min * 7000 / (speed * 100) * 60)
        speed = max(total_speed, 1)
        adjusted_survey_seconds = sum(
            math.floor(sector.survey_duration_min * 7000 / (speed * 100) * 60)
            for sector in [self.get_sector(sid) for sid in sector_ids]
            if sector
        )

        total_seconds = FIXED_VOYAGE_TIME + adjusted_survey_seconds
        return total_seconds / 3600

    def calculate_voyage_supply_cost(
        self,
        part_ids: list[int],
        sector_ids: list[int],
        total_speed: int = 100
    ) -> VoyageSupplyCost:
        """
        Calculate complete supply cost for a single voyage.
        """
        damage_info = self.calculate_voyage_damage(part_ids, sector_ids)
        voyages_until_repair = self.calculate_voyages_until_repair(part_ids, sector_ids)

        # Repair kits needed per voyage = total_repair_materials / voyages_until_repair
        total_repair_materials = self.calculate_repair_materials(part_ids)
        repair_per_voyage = total_repair_materials / voyages_until_repair if voyages_until_repair > 0 else 0

        return VoyageSupplyCost(
            ceruleum_tanks=self.calculate_fuel_cost(sector_ids),
            repair_damage=damage_info['max_damage'],
            repair_materials_on_full=total_repair_materials,
            voyage_duration_hours=self.calculate_voyage_duration(sector_ids, total_speed)
        )

    def calculate_daily_supply_cost(
        self,
        part_ids: list[int],
        sector_ids: list[int],
        total_speed: int = 100
    ) -> DailySupplyCost:
        """
        Calculate daily supply consumption rate.
        """
        voyage_cost = self.calculate_voyage_supply_cost(part_ids, sector_ids, total_speed)

        if voyage_cost.voyage_duration_hours <= 0:
            return DailySupplyCost()

        voyages_per_day = 24.0 / voyage_cost.voyage_duration_hours

        # Repair kits per day = (repair_materials / voyages_until_repair) * voyages_per_day
        voyages_until_repair = self.calculate_voyages_until_repair(part_ids, sector_ids)
        kits_per_voyage = voyage_cost.repair_materials_on_full / voyages_until_repair if voyages_until_repair > 0 else 0

        return DailySupplyCost(
            ceruleum_per_day=voyage_cost.ceruleum_tanks * voyages_per_day,
            repair_kits_per_day=kits_per_voyage * voyages_per_day,
            voyages_per_day=voyages_per_day
        )

    def calculate_supply_forecast(
        self,
        current_ceruleum: int,
        current_repair_kits: int,
        total_ceruleum_per_day: float,
        total_kits_per_day: float
    ) -> SupplyForecast:
        """
        Calculate forecast for when supplies will run out.
        """
        forecast = SupplyForecast()

        if total_ceruleum_per_day > 0:
            forecast.days_until_ceruleum_empty = current_ceruleum / total_ceruleum_per_day
        else:
            forecast.days_until_ceruleum_empty = 999.0

        if total_kits_per_day > 0:
            forecast.days_until_kits_empty = current_repair_kits / total_kits_per_day
        else:
            forecast.days_until_kits_empty = 999.0

        forecast.days_until_restock = min(
            forecast.days_until_ceruleum_empty,
            forecast.days_until_kits_empty
        )

        if forecast.days_until_ceruleum_empty <= forecast.days_until_kits_empty:
            forecast.limiting_resource = "ceruleum"
        else:
            forecast.limiting_resource = "kits"

        if forecast.days_until_restock >= 999:
            forecast.limiting_resource = "none"

        return forecast


# Singleton instance
supply_calculator = SupplyCalculator()


def get_part_stats(part_id: int) -> dict:
    """
    Get part statistics from Lumina data.

    Returns dict with surveillance, retrieval, speed, range, favor, repair_materials
    """
    part = SubmarinePart.query.get(part_id)
    if not part:
        return {}

    return {
        'id': part.id,
        'slot': part.slot,
        'rank': part.rank,
        'class_type': part.class_type,
        'surveillance': part.surveillance,
        'retrieval': part.retrieval,
        'speed': part.speed,
        'range': part.range,
        'favor': part.favor,
        'repair_materials': part.repair_materials,
        'components': part.components
    }


def get_sector_info(sector_id: int) -> dict:
    """
    Get sector information from Lumina data.
    """
    sector = SubmarineExploration.query.get(sector_id)
    if not sector:
        return {}

    return {
        'id': sector.id,
        'destination': sector.destination,
        'location': sector.location,
        'map_id': sector.map_id,
        'rank_req': sector.rank_req,
        'ceruleum_tank_req': sector.ceruleum_tank_req,
        'exp_reward': sector.exp_reward,
        'survey_duration_min': sector.survey_duration_min,
        'stars': sector.stars
    }


def calculate_build_stats(part_ids: list[int], rank: int = 1) -> dict:
    """
    Calculate total stats for a submarine build.

    Args:
        part_ids: List of 4 part IDs
        rank: Submarine rank level

    Returns:
        Dict with total stats
    """
    totals = {
        'surveillance': 0,
        'retrieval': 0,
        'speed': 0,
        'range': 0,
        'favor': 0,
        'repair_materials': 0,
        'components': 0
    }

    # Add part stats
    for part_id in part_ids:
        part = SubmarinePart.query.get(part_id)
        if part:
            totals['surveillance'] += part.surveillance
            totals['retrieval'] += part.retrieval
            totals['speed'] += part.speed
            totals['range'] += part.range
            totals['favor'] += part.favor
            totals['repair_materials'] += part.repair_materials
            totals['components'] += part.components

    # Add rank bonuses
    rank_bonus = SubmarineRank.query.get(rank)
    if rank_bonus:
        totals['surveillance'] += rank_bonus.surveillance_bonus
        totals['retrieval'] += rank_bonus.retrieval_bonus
        totals['speed'] += rank_bonus.speed_bonus
        totals['range'] += rank_bonus.range_bonus
        totals['favor'] += rank_bonus.favor_bonus

    return totals
