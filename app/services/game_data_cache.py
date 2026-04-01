"""
In-memory cache for static Lumina game data tables.

These tables (SubmarinePart, SubmarineExploration, RouteStats) are only updated
every 6 hours by the Lumina update job, so we cache them in memory to avoid
thousands of individual DB queries per fleet data parse.
"""
import threading

from app.utils.logging import get_logger

logger = get_logger('GameDataCache')

_lock = threading.Lock()

# Cached data
_submarine_parts: dict | None = None       # row_id -> SubmarinePart
_explorations: dict | None = None           # sector_id -> SubmarineExploration
_exploration_starting: dict | None = None   # map_id -> SubmarineExploration (starting points)
_route_stats: dict | None = None            # route_name -> list[RouteStats]


def get_submarine_part(row_id: int):
    """Get a SubmarinePart by row ID from cache."""
    _ensure_parts_loaded()
    return _submarine_parts.get(row_id)


def get_exploration(sector_id: int):
    """Get a SubmarineExploration by sector ID from cache."""
    _ensure_explorations_loaded()
    return _explorations.get(sector_id)


def get_starting_point(map_id: int):
    """Get the starting point SubmarineExploration for a map from cache."""
    _ensure_explorations_loaded()
    return _exploration_starting.get(map_id)


def get_route_stats_for(route_name: str) -> list:
    """Get all RouteStats entries for a route name from cache."""
    _ensure_route_stats_loaded()
    return _route_stats.get(route_name, [])


def get_all_route_names() -> set:
    """Get set of all known route names from cache."""
    _ensure_route_stats_loaded()
    return set(_route_stats.keys())


def invalidate():
    """Clear all cached data, forcing reload on next access."""
    global _submarine_parts, _explorations, _exploration_starting, _route_stats
    with _lock:
        _submarine_parts = None
        _explorations = None
        _exploration_starting = None
        _route_stats = None
        logger.info("Game data cache invalidated")


def _ensure_parts_loaded():
    global _submarine_parts
    if _submarine_parts is not None:
        return
    with _lock:
        if _submarine_parts is not None:
            return
        from app.models.lumina import SubmarinePart
        parts = SubmarinePart.query.all()
        _submarine_parts = {p.id: p for p in parts}
        logger.info(f"Cached {len(_submarine_parts)} submarine parts")


def _ensure_explorations_loaded():
    global _explorations, _exploration_starting
    if _explorations is not None:
        return
    with _lock:
        if _explorations is not None:
            return
        from app.models.lumina import SubmarineExploration
        sectors = SubmarineExploration.query.all()
        _explorations = {s.id: s for s in sectors}
        _exploration_starting = {}
        for s in sectors:
            if s.starting_point:
                _exploration_starting[s.map_id] = s
        logger.info(f"Cached {len(_explorations)} exploration sectors")


def _ensure_route_stats_loaded():
    global _route_stats
    if _route_stats is not None:
        return
    with _lock:
        if _route_stats is not None:
            return
        from app.models.lumina import RouteStats
        all_routes = RouteStats.query.all()
        _route_stats = {}
        for r in all_routes:
            _route_stats.setdefault(r.route_name, []).append(r)
        logger.info(f"Cached route stats for {len(_route_stats)} routes")
