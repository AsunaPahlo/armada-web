"""
Submarine Sector Unlock Tree Data

This module contains the complete unlock dependency tree for all submarine
exploration sectors across all 7 maps. Data sourced from AutoRetainer's Unlocks.cs.

Each sector entry contains:
- prereq: The sector ID required to unlock this sector (None for starting sectors)
- unlocks_sub: True if unlocking this sector grants a new submarine slot
- unlocks_map: The map ID this sector unlocks (0 if none)
- map_id: Which map this sector belongs to
- letter: The sector letter designation (A, B, C, etc.)
- name: The sector name from game data
"""

# Map names for display
MAP_NAMES = {
    1: "The Deep-sea Site",
    2: "The Sea of Ash",
    3: "The Sea of Jade",
    4: "The Sirensong Sea",
    5: "The Lilac Sea",
    6: "South Indigo Deep",
    7: "The Northern Empty",
}

# Complete unlock tree for all sectors
# Based on AutoRetainer's Unlocks.cs
# prereq of None = starting sector, prereq of -1 = unknown
UNLOCK_TREE = {
    # ============================================
    # Map 1: The Deep-sea Site (sectors 1-30)
    # ============================================
    1: {"prereq": None, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "A", "name": "The Ivory Shoals"},
    2: {"prereq": None, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "B", "name": "Deep-sea Site 1"},
    3: {"prereq": 1, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "C", "name": "Deep-sea Site 2"},
    4: {"prereq": 2, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "D", "name": "The Lightless Basin"},
    5: {"prereq": 2, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "E", "name": "Deep-sea Site 3"},
    6: {"prereq": 3, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "F", "name": "The Southern Rimilala Trench"},
    7: {"prereq": 4, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "G", "name": "The Umbrella Narrow"},
    8: {"prereq": 7, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "H", "name": "Offender's Rot"},
    9: {"prereq": 5, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "I", "name": "Neolith Island"},
    10: {"prereq": 5, "unlocks_sub": True, "unlocks_map": 0, "map_id": 1, "letter": "J", "name": "Unidentified Derelict"},
    11: {"prereq": 9, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "K", "name": "The Cobalt Shoals"},
    12: {"prereq": 8, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "L", "name": "The Mystic Basin"},
    13: {"prereq": 8, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "M", "name": "Deep-sea Site 4"},
    14: {"prereq": 10, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "N", "name": "The Central Rimilala Trench"},
    15: {"prereq": 14, "unlocks_sub": True, "unlocks_map": 0, "map_id": 1, "letter": "O", "name": "The Wreckage Of Discovery I"},
    16: {"prereq": 11, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "P", "name": "Komura"},
    17: {"prereq": 16, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "Q", "name": "Kanayama"},
    18: {"prereq": 12, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "R", "name": "Concealed Bay"},
    19: {"prereq": 15, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "S", "name": "Deep-sea Site 5"},
    20: {"prereq": 19, "unlocks_sub": True, "unlocks_map": 0, "map_id": 1, "letter": "T", "name": "Purgatory"},
    21: {"prereq": 19, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "U", "name": "Deep-sea Site 6"},
    22: {"prereq": 21, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "V", "name": "The Rimilala Shelf"},
    23: {"prereq": 14, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "W", "name": "Deep-sea Site 7"},
    24: {"prereq": 23, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "X", "name": "Glittersand Basin"},
    25: {"prereq": 20, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "Y", "name": "Flickering Dip"},
    26: {"prereq": 25, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "Z", "name": "The Wreckage Of The Headway"},
    27: {"prereq": 26, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "AA", "name": "The Upwell"},
    28: {"prereq": 27, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "AB", "name": "The Rimilala Trench Bottom"},
    29: {"prereq": 27, "unlocks_sub": False, "unlocks_map": 0, "map_id": 1, "letter": "AC", "name": "Stone Temple"},
    30: {"prereq": 28, "unlocks_sub": False, "unlocks_map": 2, "map_id": 1, "letter": "AD", "name": "Sunken Vault"},

    # ============================================
    # Map 2: The Sea of Ash (sectors 32-51)
    # ============================================
    32: {"prereq": 30, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "A", "name": "South Isle Of Zozonan"},
    33: {"prereq": 32, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "B", "name": "Wreckage Of The Windwalker"},
    34: {"prereq": 33, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "C", "name": "North Isle Of Zozonan"},
    35: {"prereq": 34, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "D", "name": "Sea Of Ash 1"},
    36: {"prereq": 35, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "E", "name": "The Southern Charnel Trench"},
    37: {"prereq": 34, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "F", "name": "Sea Of Ash 2"},
    38: {"prereq": 37, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "G", "name": "Sea Of Ash 3"},
    39: {"prereq": 38, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "H", "name": "Ascetic's Demise"},
    40: {"prereq": 38, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "I", "name": "The Central Charnel Trench"},
    41: {"prereq": 40, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "J", "name": "The Catacombs Of The Father"},
    42: {"prereq": 39, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "K", "name": "Sea Of Ash 4"},
    43: {"prereq": 42, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "L", "name": "The Midden Pit"},
    44: {"prereq": 40, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "M", "name": "The Lone Glove"},
    45: {"prereq": 41, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "N", "name": "Coldtoe Isle"},
    46: {"prereq": 45, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "O", "name": "Smuggler's Knot"},
    47: {"prereq": 43, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "P", "name": "The Open Robe"},
    48: {"prereq": 36, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "Q", "name": "Nald'thal's Pipe"},
    49: {"prereq": 47, "unlocks_sub": False, "unlocks_map": 3, "map_id": 2, "letter": "R", "name": "The Slipped Anchor"},
    50: {"prereq": 45, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "S", "name": "Glutton's Belly"},
    51: {"prereq": 42, "unlocks_sub": False, "unlocks_map": 0, "map_id": 2, "letter": "T", "name": "The Blue Hole"},

    # ============================================
    # Map 3: The Sea of Jade (sectors 53-72)
    # ============================================
    53: {"prereq": 49, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "A", "name": "The Isle Of Sacrament"},
    54: {"prereq": 53, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "B", "name": "The Kraken's Tomb"},
    55: {"prereq": 53, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "C", "name": "Sea Of Jade 1"},
    56: {"prereq": 55, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "D", "name": "Rogo-Tumu-Here's Haunt"},
    57: {"prereq": 55, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "E", "name": "The Stone Barbs"},
    58: {"prereq": 56, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "F", "name": "Rogo-Tumu-Here's Repose"},
    59: {"prereq": 57, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "G", "name": "Tangaroa's Prow"},
    60: {"prereq": 57, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "H", "name": "Sea Of Jade 2"},
    61: {"prereq": 59, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "I", "name": "The Blind Sound"},
    62: {"prereq": 59, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "J", "name": "Sea Of Jade 3"},
    63: {"prereq": 61, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "K", "name": "Moergynn's Forge"},
    64: {"prereq": 61, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "L", "name": "Tangaroa's Beacon"},
    65: {"prereq": 62, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "M", "name": "Sea Of Jade 4"},
    66: {"prereq": 65, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "N", "name": "The Forest Of Kelp"},
    67: {"prereq": 64, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "O", "name": "Sea Of Jade 5"},
    68: {"prereq": 66, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "P", "name": "Bladefall Chasm"},
    69: {"prereq": 64, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "Q", "name": "Stormport"},
    70: {"prereq": 65, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "R", "name": "Wyrm's Rest"},
    71: {"prereq": 69, "unlocks_sub": False, "unlocks_map": 0, "map_id": 3, "letter": "S", "name": "Sea Of Jade 6"},
    72: {"prereq": 70, "unlocks_sub": False, "unlocks_map": 4, "map_id": 3, "letter": "T", "name": "The Devil's Crypt"},

    # ============================================
    # Map 4: The Sirensong Sea (sectors 74-93)
    # ============================================
    74: {"prereq": 72, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "A", "name": "Mastbound's Bounty"},
    75: {"prereq": 74, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "B", "name": "Sirensong Sea 1"},
    76: {"prereq": 74, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "C", "name": "Sirensong Sea 2"},
    77: {"prereq": 76, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "D", "name": "Anthemoessa"},
    78: {"prereq": 75, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "E", "name": "Magos Trench"},
    79: {"prereq": 75, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "F", "name": "Thrall's Unrest"},
    80: {"prereq": 76, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "G", "name": "Crow's Drop"},
    81: {"prereq": 77, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "H", "name": "Sirensong Sea 3"},
    82: {"prereq": 81, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "I", "name": "The Anthemoessa Undertow"},
    83: {"prereq": 79, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "J", "name": "Sirensong Sea 4"},
    84: {"prereq": 83, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "K", "name": "Seafoam Tide"},
    85: {"prereq": 83, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "L", "name": "The Beak"},
    86: {"prereq": 81, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "M", "name": "Seafarer's End"},
    87: {"prereq": 82, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "N", "name": "Drifter's Decay"},
    88: {"prereq": 84, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "O", "name": "Lugat's Landing"},
    89: {"prereq": 85, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "P", "name": "The Frozen Spring"},
    90: {"prereq": 87, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "Q", "name": "Sirensong Sea 5"},
    91: {"prereq": 88, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "R", "name": "Tidewind Isle"},
    92: {"prereq": 88, "unlocks_sub": False, "unlocks_map": 0, "map_id": 4, "letter": "S", "name": "Bloodbreak"},
    93: {"prereq": 89, "unlocks_sub": False, "unlocks_map": 5, "map_id": 4, "letter": "T", "name": "The Crystal Font"},

    # ============================================
    # Map 5: The Lilac Sea (sectors 95-114)
    # ============================================
    95: {"prereq": 93, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "A", "name": "Weeping Trellis"},
    96: {"prereq": 95, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "B", "name": "The Forsaken Isle"},
    97: {"prereq": 95, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "C", "name": "Fortune's Ford"},
    98: {"prereq": 96, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "D", "name": "The Lilac Sea 1"},
    99: {"prereq": 97, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "E", "name": "Runner's Reach"},
    100: {"prereq": 96, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "F", "name": "Bellflower Flood"},
    101: {"prereq": 97, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "G", "name": "The Lilac Sea 2"},
    102: {"prereq": 101, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "H", "name": "The Lilac Sea 3"},
    103: {"prereq": 98, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "I", "name": "Northwest Bellflower"},
    104: {"prereq": 100, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "J", "name": "Corolla Isle"},
    105: {"prereq": 101, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "K", "name": "Southeast Bellflower"},
    106: {"prereq": 104, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "L", "name": "The Floral Reef"},
    107: {"prereq": 105, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "M", "name": "Wingsreach"},
    108: {"prereq": 106, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "N", "name": "The Floating Standard"},
    109: {"prereq": 107, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "O", "name": "The Fluttering Bay"},
    110: {"prereq": 103, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "P", "name": "The Lilac Sea 4"},
    111: {"prereq": 106, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "Q", "name": "Proudkeel"},
    112: {"prereq": 109, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "R", "name": "East Dodie's Abyss"},
    113: {"prereq": 108, "unlocks_sub": False, "unlocks_map": 0, "map_id": 5, "letter": "S", "name": "The Lilac Sea 5"},
    114: {"prereq": 111, "unlocks_sub": False, "unlocks_map": 6, "map_id": 5, "letter": "T", "name": "West Dodie's Abyss"},

    # ============================================
    # Map 6: South Indigo Deep (sectors 116-135)
    # ============================================
    116: {"prereq": 114, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "A", "name": "The Indigo Shallows"},
    117: {"prereq": 116, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "B", "name": "Voyagers' Reprieve"},
    118: {"prereq": 116, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "C", "name": "North Delphinium Seashelf"},
    119: {"prereq": 117, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "D", "name": "Rainbringer Rift"},
    120: {"prereq": 118, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "E", "name": "South Indigo Deep 1"},
    121: {"prereq": 117, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "F", "name": "The Central Blue"},
    122: {"prereq": 118, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "G", "name": "South Indigo Deep 2"},
    123: {"prereq": 122, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "H", "name": "The Talon"},
    124: {"prereq": 121, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "I", "name": "Southern Central Blue"},
    125: {"prereq": 122, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "J", "name": "South Indigo Deep 3"},
    126: {"prereq": 123, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "K", "name": "The Talonspoint Depths"},
    127: {"prereq": 124, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "L", "name": "Saltfarer's Eye"},
    128: {"prereq": 124, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "M", "name": "Startail Shallows"},
    129: {"prereq": 128, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "N", "name": "Moonshadow Isle"},
    130: {"prereq": 127, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "O", "name": "Emerald Drop"},
    131: {"prereq": 129, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "P", "name": "South Indigo Deep 4"},
    132: {"prereq": 127, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "Q", "name": "South Delphinium Seashelf"},
    133: {"prereq": 129, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "R", "name": "Startail Shelf"},
    134: {"prereq": 132, "unlocks_sub": False, "unlocks_map": 0, "map_id": 6, "letter": "S", "name": "Cradle of the Winds"},
    135: {"prereq": 133, "unlocks_sub": False, "unlocks_map": 7, "map_id": 6, "letter": "T", "name": "Startail Trench"},

    # ============================================
    # Map 7: The Northern Empty (sectors 137-143)
    # ============================================
    137: {"prereq": 135, "unlocks_sub": False, "unlocks_map": 0, "map_id": 7, "letter": "A", "name": "Eastern Blackblood Wells"},
    138: {"prereq": 137, "unlocks_sub": False, "unlocks_map": 0, "map_id": 7, "letter": "B", "name": "Sea Wolf Cove"},
    139: {"prereq": 137, "unlocks_sub": False, "unlocks_map": 0, "map_id": 7, "letter": "C", "name": "Southernmost Hanthbyrt"},
    140: {"prereq": 139, "unlocks_sub": False, "unlocks_map": 0, "map_id": 7, "letter": "D", "name": "Oeyaseik"},
    141: {"prereq": 138, "unlocks_sub": False, "unlocks_map": 0, "map_id": 7, "letter": "E", "name": "Northeast Hanthbyrt"},
    142: {"prereq": 140, "unlocks_sub": False, "unlocks_map": 0, "map_id": 7, "letter": "F", "name": "Vyrstrant"},
    143: {"prereq": -1, "unlocks_sub": False, "unlocks_map": 0, "map_id": 7, "letter": "G", "name": "The Sunken Jawbone"},  # Unknown prereq
}


def get_sectors_by_map(map_id: int) -> dict:
    """Get all sectors for a specific map."""
    return {
        sector_id: data
        for sector_id, data in UNLOCK_TREE.items()
        if data["map_id"] == map_id
    }


def get_map_sector_count(map_id: int) -> int:
    """Get the number of sectors in a map."""
    return len(get_sectors_by_map(map_id))


def get_starting_sectors(map_id: int) -> list[int]:
    """Get sectors that have no prerequisites within a map (entry points)."""
    map_sectors = get_sectors_by_map(map_id)
    # A starting sector either has no prereq, or its prereq is in a different map
    return [
        sector_id
        for sector_id, data in map_sectors.items()
        if data["prereq"] is None or (
            data["prereq"] not in map_sectors and
            data["prereq"] > 0  # Exclude unknown prereqs (-1)
        )
    ]


def get_sector_children(sector_id: int) -> list[int]:
    """Get all sectors that require this sector as a prerequisite."""
    return [
        s_id
        for s_id, data in UNLOCK_TREE.items()
        if data["prereq"] == sector_id
    ]


def get_unlock_chain(sector_id: int) -> list[int]:
    """Get the full chain of prerequisites leading to a sector."""
    chain = []
    current = sector_id
    while current is not None and current > 0:
        sector = UNLOCK_TREE.get(current)
        if sector is None:
            break
        prereq = sector.get("prereq")
        if prereq is not None and prereq > 0:
            chain.insert(0, prereq)
        current = prereq
    return chain
