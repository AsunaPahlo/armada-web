"""
In-memory cache for static Lumina game data tables.

These tables (SubmarinePart, SubmarineExploration, RouteStats) are only updated
every 6 hours by the Lumina update job, so we cache them in memory to avoid
thousands of individual DB queries per fleet data parse.

Important: We snapshot ORM objects into plain SimpleNamespace objects so that
the cached data is not tied to any SQLAlchemy session. SQLAlchemy 2.0 expires
object attributes when the session closes, which would cause DetachedInstanceError
if we cached the ORM objects directly.
"""
import threading
from types import SimpleNamespace

from app.utils.logging import get_logger

logger = get_logger('GameDataCache')

_lock = threading.Lock()

# Cached data (all values are plain SimpleNamespace objects, not ORM instances)
_submarine_parts: dict | None = None       # row_id -> SimpleNamespace
_explorations: dict | None = None           # sector_id -> SimpleNamespace
_exploration_starting: dict | None = None   # map_id -> SimpleNamespace (starting points)
_route_stats: dict | None = None            # route_name -> list[SimpleNamespace]


def _snapshot(obj, attrs: list[str]) -> SimpleNamespace:
    """Convert an ORM object to a plain SimpleNamespace with the given attributes."""
    return SimpleNamespace(**{a: getattr(obj, a) for a in attrs})


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


_PART_ATTRS = [
    'id', 'slot', 'rank', 'class_type', 'components', 'repair_materials',
    'surveillance', 'retrieval', 'speed', 'range', 'favor',
]

_EXPLORATION_ATTRS = [
    'id', 'destination', 'location', 'map_id',
    'rank_req', 'ceruleum_tank_req', 'stars',
    'exp_reward', 'survey_duration_min', 'survey_distance',
    'x', 'y', 'z', 'starting_point',
]

_ROUTE_STATS_ATTRS = [
    'id', 'route_name', 'duration_hours', 'gil_per_sub_day', 'avg_exp', 'fc_points',
]


def _ensure_parts_loaded():
    global _submarine_parts
    if _submarine_parts is not None:
        return
    with _lock:
        if _submarine_parts is not None:
            return
        from app.models.lumina import SubmarinePart
        parts = SubmarinePart.query.all()
        _submarine_parts = {p.id: _snapshot(p, _PART_ATTRS) for p in parts}
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
        snapped = [_snapshot(s, _EXPLORATION_ATTRS) for s in sectors]
        _explorations = {s.id: s for s in snapped}
        _exploration_starting = {}
        for s in snapped:
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
            _route_stats.setdefault(r.route_name, []).append(
                _snapshot(r, _ROUTE_STATS_ATTRS)
            )
        logger.info(f"Cached route stats for {len(_route_stats)} routes")
