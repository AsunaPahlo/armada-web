"""
Unlock Service - Manages submarine sector unlock data and flowchart generation.
"""
from typing import Optional

from app.data.unlock_tree import (
    UNLOCK_TREE, MAP_NAMES,
    get_sectors_by_map, get_map_sector_count,
    get_starting_sectors, get_sector_children
)
from app.services import get_fleet_manager


class UnlockService:
    """Service for submarine sector unlock data and flowchart visualization."""

    # Map starting sector IDs for each map
    MAP_START_SECTORS = {
        1: 1,    # Map 1: sectors 1-30
        2: 32,   # Map 2: sectors 32-51
        3: 53,   # Map 3: sectors 53-72
        4: 74,   # Map 4: sectors 74-93
        5: 95,   # Map 5: sectors 95-114
        6: 116,  # Map 6: sectors 116-135
        7: 137,  # Map 7: sectors 137-143
    }

    def _get_sector_letter(self, sector_id: int, map_id: int) -> str:
        """Convert sector ID to letter label (A, B, C... Z, AA, AB, etc.)"""
        start = self.MAP_START_SECTORS.get(map_id, 1)
        index = sector_id - start  # 0-based index within map

        if index < 26:
            return chr(ord('A') + index)
        else:
            # For sectors beyond Z, use AA, AB, AC, etc.
            first = chr(ord('A') + (index // 26) - 1)
            second = chr(ord('A') + (index % 26))
            return first + second

    def get_unlock_tree(self) -> dict:
        """Get the complete unlock tree data."""
        return UNLOCK_TREE

    def get_map_names(self) -> dict:
        """Get map ID to name mapping."""
        return MAP_NAMES

    def get_fc_unlock_status(self, fc_id: str) -> set[int]:
        """
        Get the set of unlocked sector IDs for a specific FC.

        Args:
            fc_id: FC ID string, or "all" for aggregate across all FCs

        Returns:
            Set of unlocked sector IDs
        """
        fleet = get_fleet_manager()
        accounts = fleet.get_data()

        unlocked = set()

        for account in accounts:
            for char in account.characters:
                # Filter by FC if specified
                char_fc_id = str(char.fc_id) if char.fc_id else 'unknown'
                if fc_id != 'all' and char_fc_id != fc_id:
                    continue

                # Get unlocked sectors from character data
                if hasattr(char, 'unlocked_sectors') and char.unlocked_sectors:
                    unlocked.update(char.unlocked_sectors)

        return unlocked

    def build_flowchart_data(self, map_id: int, unlocked: set[int]) -> dict:
        """
        Build vis.js network data for a specific map.

        Args:
            map_id: The map ID (1-7)
            unlocked: Set of unlocked sector IDs

        Returns:
            Dictionary with 'nodes' and 'edges' for vis.js
        """
        sectors = get_sectors_by_map(map_id)
        nodes = []
        edges = []

        for sector_id, data in sectors.items():
            is_unlocked = sector_id in unlocked
            prereq = data["prereq"]
            can_unlock = prereq is None or prereq in unlocked or prereq < 0

            # Determine node color/style based on status
            if is_unlocked:
                if data["unlocks_sub"]:
                    # Unlocked + unlocks submarine
                    color = {"background": "#68d391", "border": "#38a169", "highlight": {"background": "#9ae6b4", "border": "#48bb78"}}
                    shape = "ellipse"
                elif data["unlocks_map"]:
                    # Unlocked + unlocks new map
                    color = {"background": "#63b3ed", "border": "#3182ce", "highlight": {"background": "#90cdf4", "border": "#4299e1"}}
                    shape = "circle"
                else:
                    # Regular unlocked sector
                    color = {"background": "#68d391", "border": "#38a169", "highlight": {"background": "#9ae6b4", "border": "#48bb78"}}
                    shape = "box"
            else:
                # Check if prereq is unlocked (can be unlocked next)
                if can_unlock:
                    if data["unlocks_sub"]:
                        color = {"background": "#ffd700", "border": "#b8860b", "highlight": {"background": "#ffe566", "border": "#daa520"}}
                        shape = "ellipse"
                    elif data["unlocks_map"]:
                        color = {"background": "#ffd700", "border": "#b8860b", "highlight": {"background": "#ffe566", "border": "#daa520"}}
                        shape = "circle"
                    else:
                        color = {"background": "#f6e05e", "border": "#d69e2e", "highlight": {"background": "#faf089", "border": "#ecc94b"}}
                        shape = "box"
                else:
                    if data["unlocks_sub"]:
                        color = {"background": "#4a5568", "border": "#2d3748", "highlight": {"background": "#718096", "border": "#4a5568"}}
                        shape = "ellipse"
                    elif data["unlocks_map"]:
                        color = {"background": "#4a5568", "border": "#2d3748", "highlight": {"background": "#718096", "border": "#4a5568"}}
                        shape = "circle"
                    else:
                        color = {"background": "#4a5568", "border": "#2d3748", "highlight": {"background": "#718096", "border": "#4a5568"}}
                        shape = "box"

            # Build node label - use letter from data
            sector_name = data['name']
            label = data['letter']

            title = f"{label}: {sector_name}"
            if data["unlocks_sub"]:
                title += "\n+1 Submarine Slot"
            if data["unlocks_map"]:
                title += f"\nUnlocks {MAP_NAMES.get(data['unlocks_map'], 'Unknown Map')}"

            node = {
                "id": sector_id,
                "label": label,
                "title": title,
                "shape": shape,
                "color": color,
                "font": {"color": "#ffffff" if is_unlocked or can_unlock else "#a0aec0"},
                "borderWidth": 2,
                "size": 25 if data["unlocks_sub"] or data["unlocks_map"] else 20,
            }

            # Add custom data for filtering/interaction
            node["unlocked"] = is_unlocked
            node["unlocksSubmarine"] = data["unlocks_sub"]
            node["unlocksMap"] = data["unlocks_map"]
            node["sectorName"] = data["name"]

            nodes.append(node)

            # Create edge from prerequisite if it exists and is in same map
            if data["prereq"] is not None and data["prereq"] > 0:
                prereq_data = UNLOCK_TREE.get(data["prereq"])
                if prereq_data and prereq_data["map_id"] == map_id:
                    # Edge within same map
                    edge_color = "#68d391" if is_unlocked else "#4a5568"
                    edges.append({
                        "from": data["prereq"],
                        "to": sector_id,
                        "arrows": "to",
                        "color": {"color": edge_color, "highlight": "#63b3ed"},
                        "width": 2
                    })

        return {"nodes": nodes, "edges": edges}

    def get_map_summary(self, fc_id: str = None) -> dict:
        """
        Get unlock progress summary for all maps.

        Args:
            fc_id: FC ID to filter by, or None/all for aggregate

        Returns:
            Dictionary with map progress data
        """
        if fc_id is None:
            fc_id = "all"

        unlocked = self.get_fc_unlock_status(fc_id)

        summaries = {}
        for map_id in range(1, 8):
            map_sectors = get_sectors_by_map(map_id)
            total = len(map_sectors)
            unlocked_count = sum(1 for s_id in map_sectors if s_id in unlocked)

            # Check if map is accessible (has at least one unlocked sector or entry point unlocked)
            entry_points = get_starting_sectors(map_id)
            is_accessible = any(s_id in unlocked for s_id in entry_points) if entry_points else False

            # For first map, always accessible
            if map_id == 1:
                is_accessible = True

            summaries[map_id] = {
                "map_id": map_id,
                "name": MAP_NAMES.get(map_id, f"Map {map_id}"),
                "total": total,
                "unlocked": unlocked_count,
                "percent": round((unlocked_count / total) * 100, 1) if total > 0 else 0,
                "accessible": is_accessible,
                "complete": unlocked_count == total
            }

        return summaries

    def get_fc_list(self) -> list[dict]:
        """Get list of FCs with basic info for the selector."""
        fleet = get_fleet_manager()
        data = fleet.get_dashboard_data()

        fcs = []
        for fc in data.get("fc_summaries", []):
            fcs.append({
                "fc_id": fc.get("fc_id"),
                "fc_name": fc.get("fc_name"),
                "world": fc.get("world")
            })

        # Sort by name
        fcs.sort(key=lambda x: x.get("fc_name", ""))
        return fcs


# Singleton instance
unlock_service = UnlockService()
