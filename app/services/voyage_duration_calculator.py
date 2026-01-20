"""
Voyage Duration Calculator

Calculates submarine voyage duration based on route, submarine parts, and level.
Formula derived from SubmarineTracker project.
"""
import math
import re
from typing import Optional

from app.models.lumina import SubmarinePart, SubmarineExploration, SubmarineRank


# Fixed voyage overhead: 12 hours in seconds
FIXED_VOYAGE_TIME_SECONDS = 43200

# Constants from the game's calculation
TRAVEL_TIME_CONSTANT = 3990
SURVEY_TIME_CONSTANT = 7000

# Standard voyage duration buckets (in hours)
# Voyages snap to 24, 36, 48, 60, 72 hour intervals
VOYAGE_DURATION_BUCKETS = [24, 36, 48, 60, 72, 84, 96]


def snap_duration_to_bucket(duration_hours: float) -> float:
    """
    Snap a calculated duration to the nearest standard voyage bucket.

    Voyages in FFXIV run on fixed duration intervals: 24, 36, 48, 60, 72 hours, etc.
    This function rounds the calculated duration to the nearest bucket.

    Args:
        duration_hours: Raw calculated duration in hours

    Returns:
        Duration snapped to nearest bucket (24, 36, 48, etc.)
    """
    if duration_hours <= 0:
        return 24.0  # Minimum voyage duration

    # Find the nearest bucket
    closest_bucket = VOYAGE_DURATION_BUCKETS[0]
    min_diff = abs(duration_hours - closest_bucket)

    for bucket in VOYAGE_DURATION_BUCKETS[1:]:
        diff = abs(duration_hours - bucket)
        if diff < min_diff:
            min_diff = diff
            closest_bucket = bucket
        elif diff > min_diff:
            # Since buckets are sorted, once diff increases we've passed the closest
            break

    return float(closest_bucket)


# Build string letter to base ID mapping (from SubmarineTracker)
# S = Shark, U = Unkiu, W = Whale, C = Coelacanth, Y = Syldra
# + suffix means generation 2 (add 20 to base)
BUILD_LETTER_TO_BASE = {
    'S': 0,   # Shark
    'U': 1,   # Unkiu
    'W': 2,   # Whale
    'C': 3,   # Coelacanth
    'Y': 4,   # Syldra
}

# Slot offsets to convert base ID to part row ID
# Hull row = base + 3, Stern = base + 4, Bow = base + 1, Bridge = base + 2
SLOT_OFFSETS = {
    'hull': 3,
    'stern': 4,
    'bow': 1,
    'bridge': 2,
}


def parse_build_string(build: str) -> Optional[list[int]]:
    """
    Parse a build string like "S+S+U+C+" into part row IDs.

    The build string format is 4 parts: Hull, Stern, Bow, Bridge
    Each part is a letter (S/U/W/C/Y) optionally followed by +

    Args:
        build: Build string like "S+S+U+C+", "SSUC", "SSUC++"

    Returns:
        List of 4 part row IDs [hull, stern, bow, bridge], or None if invalid
    """
    if not build:
        return None

    # Handle compressed format like "SSUC++" -> expand to "S+S+U+C+"
    # If 4 letters followed by ++, it means all parts are +
    match = re.match(r'^([SUWCY]{4})\+\+$', build.upper())
    if match:
        letters = match.group(1)
        build = '+'.join(letters) + '+'  # "SSUC" -> "S+S+U+C+"

    # Parse individual parts - each is a letter optionally followed by +
    parts = re.findall(r'([SUWCY])\+?', build.upper())
    if len(parts) != 4:
        return None

    # Determine if each part has + suffix
    plus_positions = []
    pos = 0
    for letter in parts:
        idx = build.upper().find(letter, pos)
        has_plus = idx + 1 < len(build) and build[idx + 1] == '+'
        plus_positions.append(has_plus)
        pos = idx + 1

    # Convert to part row IDs
    slot_names = ['hull', 'stern', 'bow', 'bridge']
    part_ids = []

    for i, (letter, has_plus) in enumerate(zip(parts, plus_positions)):
        base = BUILD_LETTER_TO_BASE.get(letter.upper())
        if base is None:
            return None

        # Add 20 for + variants (generation 2)
        if has_plus:
            base += 20

        # Add slot offset to get the actual part row ID
        part_id = base + SLOT_OFFSETS[slot_names[i]]
        part_ids.append(part_id)

    return part_ids


def _get_vector3_distance(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int) -> float:
    """Calculate 3D distance between two points."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)


def _get_travel_time(sector1: SubmarineExploration, sector2: SubmarineExploration, speed: int) -> int:
    """
    Calculate travel time between two sectors in seconds.

    Formula: Floor(Vector3Distance * 3990 / (Speed * 100) * 60)
    """
    if speed < 1:
        speed = 1

    distance = _get_vector3_distance(sector1.x, sector1.y, sector1.z, sector2.x, sector2.y, sector2.z)
    return int(math.floor(distance * TRAVEL_TIME_CONSTANT / (speed * 100) * 60))


def _get_survey_time(sector: SubmarineExploration, speed: int) -> int:
    """
    Calculate survey time at a sector in seconds.

    Formula: Floor(SurveyDurationMin * 7000 / (Speed * 100) * 60)
    """
    if speed < 1:
        speed = 1

    return int(math.floor(sector.survey_duration_min * SURVEY_TIME_CONSTANT / (speed * 100) * 60))


def calculate_submarine_speed(part_ids: list[int], level: int) -> Optional[int]:
    """
    Calculate total submarine speed from part row IDs and level.

    Speed = Sum of part speeds + Rank speed bonus

    Args:
        part_ids: List of 4 part ROW IDs [hull, stern, bow, bridge] (1-40, not item IDs)
        level: Submarine level (1-125)

    Returns:
        Total speed value, or None if parts not found
    """
    if not part_ids or len(part_ids) < 4:
        return None

    # Get speed from each part
    total_speed = 0
    for part_id in part_ids:
        part = SubmarinePart.query.get(part_id)
        if part:
            total_speed += part.speed
        else:
            # Part not found in database
            return None

    # Get rank bonus
    rank = SubmarineRank.query.get(level)
    if rank:
        total_speed += rank.speed_bonus

    return total_speed


def calculate_speed_from_build(build: str, level: int) -> Optional[int]:
    """
    Calculate total submarine speed from build string and level.

    Args:
        build: Build string like "S+S+U+C+"
        level: Submarine level (1-125)

    Returns:
        Total speed value, or None if build string is invalid
    """
    part_ids = parse_build_string(build)
    if not part_ids:
        return None

    return calculate_submarine_speed(part_ids, level)


def calculate_voyage_duration(route_points: list[int], part_ids: list[int], level: int) -> Optional[float]:
    """
    Calculate voyage duration in hours.

    Args:
        route_points: List of sector IDs in voyage order
        part_ids: List of 4 part item IDs [hull, stern, bow, bridge]
        level: Submarine level (1-125)

    Returns:
        Duration in hours, or None if calculation not possible
    """
    if not route_points or len(route_points) < 1:
        return None

    # Calculate speed
    speed = calculate_submarine_speed(part_ids, level)
    if not speed:
        return None

    # Get sector data for all points
    sectors = {}
    for point_id in route_points:
        sector = SubmarineExploration.query.get(point_id)
        if sector:
            sectors[point_id] = sector
        else:
            # Sector not found
            return None

    # Need to find the starting point for the first sector
    # The starting point depends on the map - get it from the first sector's map
    first_sector = sectors[route_points[0]]
    starting_sector = SubmarineExploration.query.filter_by(
        map_id=first_sector.map_id,
        starting_point=True
    ).first()

    if not starting_sector:
        # Fallback: use the first sector's coordinates as start
        starting_sector = first_sector

    # Calculate total duration
    total_seconds = FIXED_VOYAGE_TIME_SECONDS

    # Travel from starting point to first sector + survey first sector
    current_sector = starting_sector
    for point_id in route_points:
        next_sector = sectors[point_id]

        # Add travel time from current position to next sector
        total_seconds += _get_travel_time(current_sector, next_sector, speed)

        # Add survey time at the sector
        total_seconds += _get_survey_time(next_sector, speed)

        current_sector = next_sector

    # Convert to hours and snap to standard bucket
    raw_hours = total_seconds / 3600.0
    return snap_duration_to_bucket(raw_hours)


def calculate_voyage_duration_from_build(route_points: list[int], build: str, level: int) -> Optional[float]:
    """
    Calculate voyage duration from build string.

    Args:
        route_points: List of sector IDs in voyage order
        build: Build string like "S+S+U+C+"
        level: Submarine level (1-125)

    Returns:
        Duration in hours, or None if calculation not possible
    """
    part_ids = parse_build_string(build)
    if not part_ids:
        return None

    return calculate_voyage_duration(route_points, part_ids, level)


def calculate_voyage_duration_from_submarine(sub, level: int = None) -> Optional[float]:
    """
    Calculate voyage duration from a SubmarineInfo object.

    Args:
        sub: SubmarineInfo object with part_row_ids/build and route_points
        level: Optional level override (uses sub.level if not provided)

    Returns:
        Duration in hours (snapped to 24/36/48), or None if calculation not possible
    """
    route_points = getattr(sub, 'route_points', None)
    if not route_points:
        return None

    submarine_level = level if level is not None else getattr(sub, 'level', 1)

    # Prefer part_row_ids (direct row IDs 1-40 from plugin) if available
    part_row_ids = getattr(sub, 'part_row_ids', None)
    if part_row_ids and len(part_row_ids) == 4:
        return calculate_voyage_duration(
            route_points=route_points,
            part_ids=part_row_ids,
            level=submarine_level
        )

    # Fall back to parsing build string
    build = getattr(sub, 'build', None)
    if build:
        return calculate_voyage_duration_from_build(
            route_points=route_points,
            build=build,
            level=submarine_level
        )

    return None
