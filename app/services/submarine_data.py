"""
Submarine constants and data mappings

Static fallback data for when Lumina database isn't available.
Includes Item ID mappings, part lookups, and world-to-region mapping.
"""
from typing import Optional


# =============================================================================
# ITEM ID TO LUMINA ROW ID MAPPING
# =============================================================================
# AutoRetainer stores game Item IDs (21794, etc.)
# Lumina SubmarinePart.csv uses row IDs (1-40)
# This mapping bridges the two systems.
#
# Item ID structure: Each class has 4 items in order: Bow, Bridge, Hull, Stern
# Row ID structure: Each class has 4 rows in order: Bow(slot2), Bridge(slot3), Hull(slot0), Stern(slot1)

ITEM_ID_TO_ROW_ID = {
    # Shark-class (Item 21792-21795 -> Rows 9-12, Class 1, Rank 25)
    21792: 9,   # Shark-class Bow
    21793: 10,  # Shark-class Bridge
    21794: 11,  # Shark-class Pressure Hull
    21795: 12,  # Shark-class Stern

    # Unkiu-class (Item 21796-21799 -> Rows 5-8, Class 2, Rank 15)
    21796: 5,   # Unkiu-class Bow
    21797: 6,   # Unkiu-class Bridge
    21798: 7,   # Unkiu-class Pressure Hull
    21799: 8,   # Unkiu-class Stern

    # Whale-class (Item 22526-22529 -> Rows 1-4, Class 3, Rank 1)
    22526: 1,   # Whale-class Bow
    22527: 2,   # Whale-class Bridge
    22528: 3,   # Whale-class Pressure Hull
    22529: 4,   # Whale-class Stern

    # Coelacanth-class (Item 23903-23906 -> Rows 13-16, Class 4, Rank 35)
    23903: 13,  # Coelacanth-class Bow
    23904: 14,  # Coelacanth-class Bridge
    23905: 15,  # Coelacanth-class Pressure Hull
    23906: 16,  # Coelacanth-class Stern

    # Syldra-class (Item 24344-24347 -> Rows 17-20, Class 5, Rank 45)
    24344: 17,  # Syldra-class Bow
    24345: 18,  # Syldra-class Bridge
    24346: 19,  # Syldra-class Pressure Hull
    24347: 20,  # Syldra-class Stern

    # Modified Shark-class (Item 24348-24351 -> Rows 29-32, Class 6, Rank 50)
    24348: 29,  # Modified Shark-class Bow
    24349: 30,  # Modified Shark-class Bridge
    24350: 31,  # Modified Shark-class Pressure Hull
    24351: 32,  # Modified Shark-class Stern

    # Modified Unkiu-class (Item 24352-24355 -> Rows 25-28, Class 7, Rank 50)
    24352: 25,  # Modified Unkiu-class Bow
    24353: 26,  # Modified Unkiu-class Bridge
    24354: 27,  # Modified Unkiu-class Pressure Hull
    24355: 28,  # Modified Unkiu-class Stern

    # Modified Whale-class (Item 24356-24359 -> Rows 21-24, Class 8, Rank 50)
    24356: 21,  # Modified Whale-class Bow
    24357: 22,  # Modified Whale-class Bridge
    24358: 23,  # Modified Whale-class Pressure Hull
    24359: 24,  # Modified Whale-class Stern

    # Modified Coelacanth-class (Item 24360-24363 -> Rows 33-36, Class 9, Rank 50)
    24360: 33,  # Modified Coelacanth-class Bow
    24361: 34,  # Modified Coelacanth-class Bridge
    24362: 35,  # Modified Coelacanth-class Pressure Hull
    24363: 36,  # Modified Coelacanth-class Stern

    # Modified Syldra-class (Item 24364-24367 -> Rows 37-40, Class 10, Rank 50)
    24364: 37,  # Modified Syldra-class Bow
    24365: 38,  # Modified Syldra-class Bridge
    24366: 39,  # Modified Syldra-class Pressure Hull
    24367: 40,  # Modified Syldra-class Stern
}


def item_id_to_row_id(item_id: int) -> Optional[int]:
    """Convert AutoRetainer Item ID to Lumina SubmarinePart row ID."""
    return ITEM_ID_TO_ROW_ID.get(item_id)


def get_part_name_from_db(part_id: int) -> Optional[str]:
    """
    Get part name from Lumina database.
    Returns None if database not available or part not found.
    """
    try:
        from app.models.lumina import SubmarinePart
        from flask import current_app

        # Check if we're in app context
        if not current_app:
            return None

        part = SubmarinePart.query.get(part_id)
        if part:
            # Build name from class type and slot
            class_names = {
                1: "Shark-class",
                2: "Unkiu-class",
                3: "Whale-class",
                4: "Coelacanth-class",
                5: "Syldra-class",
                6: "Modified Shark-class",
                7: "Modified Unkiu-class",
                8: "Modified Whale-class",
                9: "Modified Coelacanth-class",
                10: "Modified Syldra-class",
            }
            slot_names = {0: "Pressure Hull", 1: "Stern", 2: "Bow", 3: "Bridge"}

            class_name = class_names.get(part.class_type, f"Class-{part.class_type}")
            slot_name = slot_names.get(part.slot, f"Part-{part.slot}")
            return f"{class_name} {slot_name}"
    except Exception:
        pass
    return None


def get_part_name(part_id: int) -> str:
    """Get part name, using database first, then fallback to static mapping."""
    # Try database first
    db_name = get_part_name_from_db(part_id)
    if db_name:
        return db_name
    # Fall back to static lookup
    return SUB_PARTS_LOOKUP.get(part_id, f"Unknown({part_id})")


# Part ID to full name mapping (static fallback)
SUB_PARTS_LOOKUP = {
    21792: "Shark-class Bow",
    21793: "Shark-class Bridge",
    21794: "Shark-class Pressure Hull",
    21795: "Shark-class Stern",
    21796: "Unkiu-class Bow",
    21797: "Unkiu-class Bridge",
    21798: "Unkiu-class Pressure Hull",
    21799: "Unkiu-class Stern",
    22526: "Whale-class Bow",
    22527: "Whale-class Bridge",
    22528: "Whale-class Pressure Hull",
    22529: "Whale-class Stern",
    23903: "Coelacanth-class Bow",
    23904: "Coelacanth-class Bridge",
    23905: "Coelacanth-class Pressure Hull",
    23906: "Coelacanth-class Stern",
    24344: "Syldra-class Bow",
    24345: "Syldra-class Bridge",
    24346: "Syldra-class Pressure Hull",
    24347: "Syldra-class Stern",
    24348: "Modified Shark-class Bow",
    24349: "Modified Shark-class Bridge",
    24350: "Modified Shark-class Pressure Hull",
    24351: "Modified Shark-class Stern",
    24352: "Modified Unkiu-class Bow",
    24353: "Modified Unkiu-class Bridge",
    24354: "Modified Unkiu-class Pressure Hull",
    24355: "Modified Unkiu-class Stern",
    24356: "Modified Whale-class Bow",
    24357: "Modified Whale-class Bridge",
    24358: "Modified Whale-class Pressure Hull",
    24359: "Modified Whale-class Stern",
    24360: "Modified Coelacanth-class Bow",
    24361: "Modified Coelacanth-class Bridge",
    24362: "Modified Coelacanth-class Pressure Hull",
    24363: "Modified Coelacanth-class Stern",
    24364: "Modified Syldra-class Bow",
    24365: "Modified Syldra-class Bridge",
    24366: "Modified Syldra-class Pressure Hull",
    24367: "Modified Syldra-class Stern"
}

# Class name to short code mapping
CLASS_SHORTCUTS = {
    "Shark-class": "S",
    "Unkiu-class": "U",
    "Whale-class": "W",
    "Coelacanth-class": "C",
    "Syldra-class": "Y",
    "Modified Shark-class": "S+",
    "Modified Unkiu-class": "U+",
    "Modified Whale-class": "W+",
    "Modified Coelacanth-class": "C+",
    "Modified Syldra-class": "Y+"
}


# =============================================================================
# SUBMARINE PART ICONS
# =============================================================================
# XIVAPI icon URLs for submarine parts
# Icon paths fetched from XIVAPI item endpoints

SUB_PARTS_ICONS = {
    # Shark-class
    21792: "https://xivapi.com/i/027000/027782.png",  # Shark-class Bow
    21793: "https://xivapi.com/i/027000/027802.png",  # Shark-class Bridge
    21794: "https://xivapi.com/i/027000/027842.png",  # Shark-class Pressure Hull
    21795: "https://xivapi.com/i/027000/027822.png",  # Shark-class Stern

    # Unkiu-class
    21796: "https://xivapi.com/i/027000/027781.png",  # Unkiu-class Bow
    21797: "https://xivapi.com/i/027000/027801.png",  # Unkiu-class Bridge
    21798: "https://xivapi.com/i/027000/027841.png",  # Unkiu-class Pressure Hull
    21799: "https://xivapi.com/i/027000/027821.png",  # Unkiu-class Stern

    # Whale-class
    22526: "https://xivapi.com/i/027000/027783.png",  # Whale-class Bow
    22527: "https://xivapi.com/i/027000/027803.png",  # Whale-class Bridge
    22528: "https://xivapi.com/i/027000/027843.png",  # Whale-class Pressure Hull
    22529: "https://xivapi.com/i/027000/027823.png",  # Whale-class Stern

    # Coelacanth-class
    23903: "https://xivapi.com/i/027000/027784.png",  # Coelacanth-class Bow
    23904: "https://xivapi.com/i/027000/027804.png",  # Coelacanth-class Bridge
    23905: "https://xivapi.com/i/027000/027844.png",  # Coelacanth-class Pressure Hull
    23906: "https://xivapi.com/i/027000/027824.png",  # Coelacanth-class Stern

    # Syldra-class
    24344: "https://xivapi.com/i/027000/027785.png",  # Syldra-class Bow
    24345: "https://xivapi.com/i/027000/027805.png",  # Syldra-class Bridge
    24346: "https://xivapi.com/i/027000/027845.png",  # Syldra-class Pressure Hull
    24347: "https://xivapi.com/i/027000/027825.png",  # Syldra-class Stern

    # Modified Shark-class
    24348: "https://xivapi.com/i/027000/027787.png",  # Modified Shark-class Bow
    24349: "https://xivapi.com/i/027000/027807.png",  # Modified Shark-class Bridge
    24350: "https://xivapi.com/i/027000/027847.png",  # Modified Shark-class Pressure Hull
    24351: "https://xivapi.com/i/027000/027827.png",  # Modified Shark-class Stern

    # Modified Unkiu-class
    24352: "https://xivapi.com/i/027000/027786.png",  # Modified Unkiu-class Bow
    24353: "https://xivapi.com/i/027000/027806.png",  # Modified Unkiu-class Bridge
    24354: "https://xivapi.com/i/027000/027846.png",  # Modified Unkiu-class Pressure Hull
    24355: "https://xivapi.com/i/027000/027826.png",  # Modified Unkiu-class Stern

    # Modified Whale-class
    24356: "https://xivapi.com/i/027000/027788.png",  # Modified Whale-class Bow
    24357: "https://xivapi.com/i/027000/027808.png",  # Modified Whale-class Bridge
    24358: "https://xivapi.com/i/027000/027848.png",  # Modified Whale-class Pressure Hull
    24359: "https://xivapi.com/i/027000/027828.png",  # Modified Whale-class Stern

    # Modified Coelacanth-class
    24360: "https://xivapi.com/i/027000/027789.png",  # Modified Coelacanth-class Bow
    24361: "https://xivapi.com/i/027000/027809.png",  # Modified Coelacanth-class Bridge
    24362: "https://xivapi.com/i/027000/027849.png",  # Modified Coelacanth-class Pressure Hull
    24363: "https://xivapi.com/i/027000/027829.png",  # Modified Coelacanth-class Stern

    # Modified Syldra-class
    24364: "https://xivapi.com/i/027000/027790.png",  # Modified Syldra-class Bow
    24365: "https://xivapi.com/i/027000/027810.png",  # Modified Syldra-class Bridge
    24366: "https://xivapi.com/i/027000/027850.png",  # Modified Syldra-class Pressure Hull
    24367: "https://xivapi.com/i/027000/027830.png",  # Modified Syldra-class Stern
}


def get_part_icon_url(item_id: int) -> str:
    """Get the XIVAPI icon URL for a submarine part."""
    return SUB_PARTS_ICONS.get(item_id, "")


def get_inventory_parts_with_details(inventory_parts: dict) -> list:
    """
    Convert inventory_parts dict to a list with full details.

    Args:
        inventory_parts: Dict of item_id -> count

    Returns:
        List of dicts with: item_id, name, icon_url, count, short_code
    """
    result = []
    for item_id, count in inventory_parts.items():
        item_id = int(item_id)
        name = SUB_PARTS_LOOKUP.get(item_id, f"Unknown({item_id})")
        icon_url = SUB_PARTS_ICONS.get(item_id, "")

        # Get short code from name
        short_code = "?"
        for prefix, code in CLASS_SHORTCUTS.items():
            if name.startswith(prefix):
                short_code = code
                break

        # Determine part type from name
        part_type = "Unknown"
        if "Bow" in name:
            part_type = "Bow"
        elif "Bridge" in name:
            part_type = "Bridge"
        elif "Hull" in name:
            part_type = "Hull"
        elif "Stern" in name:
            part_type = "Stern"

        result.append({
            'item_id': item_id,
            'name': name,
            'icon_url': icon_url,
            'count': count,
            'short_code': short_code,
            'part_type': part_type
        })

    # Sort by class (short_code) then by part type
    part_order = {'Hull': 0, 'Stern': 1, 'Bow': 2, 'Bridge': 3}
    result.sort(key=lambda x: (x['short_code'], part_order.get(x['part_type'], 99)))

    return result


def get_route_name_from_points(points: list) -> str:
    """
    Get route name from list of point IDs using Lumina database.

    Looks up each sector ID in SubmarineExploration table and concatenates
    the location letters (e.g., [10, 15, 26] -> "JOZ").

    Args:
        points: List of sector point IDs

    Returns:
        Route name like "OJ", "JORZ", etc. or empty string if lookup fails
    """
    if not points:
        return ""

    try:
        from flask import current_app, has_app_context
        if not has_app_context():
            return ""

        from app.models.lumina import SubmarineExploration

        letters = []
        for point_id in points:
            sector = SubmarineExploration.query.get(point_id)
            if sector and sector.location and sector.location not in ('', '—', '-'):
                letters.append(sector.location)

        return "".join(letters) if letters else ""
    except Exception:
        return ""


def get_points_from_route_name(route_name: str) -> list[int]:
    """
    Get route points (sector IDs) from route name letters.

    Reverse of get_route_name_from_points. Looks up each letter in
    SubmarineExploration table (e.g., "OJ" -> [15, 10]).

    Note: Assumes all sectors are on the same map. If a letter exists on
    multiple maps, returns the first match.

    Args:
        route_name: Route name like "OJ", "JORZ", etc.

    Returns:
        List of sector IDs, or empty list if lookup fails
    """
    if not route_name:
        return []

    try:
        from flask import has_app_context
        if not has_app_context():
            return []

        from app.models.lumina import SubmarineExploration

        points = []
        first_map_id = None

        for letter in route_name.upper():
            # Find sector with this location letter
            query = SubmarineExploration.query.filter(
                SubmarineExploration.location == letter,
                SubmarineExploration.starting_point == False
            )

            # Try to stay on the same map as the first sector
            if first_map_id is not None:
                sector = query.filter(SubmarineExploration.map_id == first_map_id).first()
                if not sector:
                    sector = query.first()
            else:
                sector = query.first()

            if sector:
                points.append(sector.id)
                if first_map_id is None:
                    first_map_id = sector.map_id

        return points
    except Exception:
        return []


# =============================================================================
# WORLD TO REGION MAPPING
# =============================================================================
# FFXIV Data Centers organized by region

WORLD_TO_REGION = {
    # NA - Aether
    'Adamantoise': 'NA', 'Cactuar': 'NA', 'Faerie': 'NA', 'Gilgamesh': 'NA',
    'Jenova': 'NA', 'Midgardsormr': 'NA', 'Sargatanas': 'NA', 'Siren': 'NA',
    # NA - Crystal
    'Balmung': 'NA', 'Brynhildr': 'NA', 'Coeurl': 'NA', 'Diabolos': 'NA',
    'Goblin': 'NA', 'Malboro': 'NA', 'Mateus': 'NA', 'Zalera': 'NA',
    # NA - Primal
    'Behemoth': 'NA', 'Excalibur': 'NA', 'Exodus': 'NA', 'Famfrit': 'NA',
    'Hyperion': 'NA', 'Lamia': 'NA', 'Leviathan': 'NA', 'Ultros': 'NA',
    # NA - Dynamis
    'Halicarnassus': 'NA', 'Maduin': 'NA', 'Marilith': 'NA', 'Seraph': 'NA',
    'Cuchulainn': 'NA', 'Golem': 'NA', 'Kraken': 'NA', 'Rafflesia': 'NA',

    # EU - Chaos
    'Cerberus': 'EU', 'Louisoix': 'EU', 'Moogle': 'EU', 'Omega': 'EU',
    'Phantom': 'EU', 'Ragnarok': 'EU', 'Sagittarius': 'EU', 'Spriggan': 'EU',
    # EU - Light
    'Alpha': 'EU', 'Lich': 'EU', 'Odin': 'EU', 'Phoenix': 'EU',
    'Raiden': 'EU', 'Shiva': 'EU', 'Twintania': 'EU', 'Zodiark': 'EU',

    # JP - Elemental
    'Aegis': 'JP', 'Atomos': 'JP', 'Carbuncle': 'JP', 'Garuda': 'JP',
    'Gungnir': 'JP', 'Kujata': 'JP', 'Tonberry': 'JP', 'Typhon': 'JP',
    # JP - Gaia
    'Alexander': 'JP', 'Bahamut': 'JP', 'Durandal': 'JP', 'Fenrir': 'JP',
    'Ifrit': 'JP', 'Ridill': 'JP', 'Tiamat': 'JP', 'Ultima': 'JP',
    # JP - Mana
    'Anima': 'JP', 'Asura': 'JP', 'Chocobo': 'JP', 'Hades': 'JP',
    'Ixion': 'JP', 'Masamune': 'JP', 'Pandaemonium': 'JP', 'Titan': 'JP',
    # JP - Meteor
    'Belias': 'JP', 'Mandragora': 'JP', 'Ramuh': 'JP', 'Shinryu': 'JP',
    'Unicorn': 'JP', 'Valefor': 'JP', 'Yojimbo': 'JP', 'Zeromus': 'JP',

    # OCE - Materia
    'Bismarck': 'OCE', 'Ravana': 'OCE', 'Sephirot': 'OCE', 'Sophia': 'OCE',
    'Zurvan': 'OCE',
}


def get_world_region(world: str) -> str:
    """Get the region for a world. Returns 'Unknown' if not found."""
    return WORLD_TO_REGION.get(world, 'Unknown')
