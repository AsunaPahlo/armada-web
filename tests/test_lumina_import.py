"""Tests for Lumina exploration import (starting points) and voyage duration accuracy."""


# Minimal CSV mimicking xivapi SubmarineExploration.csv: header row, then rows.
# Row 0 is map 1's starting point (Location empty, StartingPoint=True).
CSV_CONTENT = """#,Destination,Location,ExpReward,SurveyDurationmin,X,Y,Z,Map,Stars,RankReq,CeruleumTankReq,SurveyDistance,StartingPoint
0,,,0,0,483,927,0,1,0,0,0,0,True
1,the Ivory Shoals (A),A,10610,180,640,880,100,1,1,1,1,10,False
31,,,0,0,483,927,0,2,0,0,0,0,True
"""


def test_import_keeps_row_zero_starting_point(app, db, monkeypatch):
    from app.services.lumina_service import LuminaDataService
    from app.models.lumina import SubmarineExploration

    svc = LuminaDataService()
    monkeypatch.setattr(svc, "fetch_csv", lambda url, table: CSV_CONTENT)
    monkeypatch.setattr(svc, "needs_update", lambda table: True)

    count = svc.update_submarine_explorations(force=True)
    assert count == 3  # row 0 must be imported too

    row0 = db.session.get(SubmarineExploration, 0)
    assert row0 is not None
    assert row0.starting_point is True
    assert row0.map_id == 1
    assert (row0.x, row0.y, row0.z) == (483, 927, 0)


def test_get_starting_point_map1_resolves(app, db, monkeypatch):
    from app.services.lumina_service import LuminaDataService
    from app.services.game_data_cache import get_starting_point, invalidate

    svc = LuminaDataService()
    monkeypatch.setattr(svc, "fetch_csv", lambda url, table: CSV_CONTENT)
    monkeypatch.setattr(svc, "needs_update", lambda table: True)
    svc.update_submarine_explorations(force=True)

    invalidate()
    start = get_starting_point(1)
    assert start is not None
    assert (start.x, start.y, start.z) == (483, 927, 0)


def _seed_jorz_game_data(db):
    """Seed the map-1 start point, JORZ sectors, S+S+U+C+ parts and rank 125.

    Values copied from the live SubmarineExploration/SubmarinePart/SubmarineRank
    sheets so the duration math runs against real game numbers.
    """
    from app.models.lumina import SubmarineExploration, SubmarinePart, SubmarineRank
    from app.services.game_data_cache import invalidate

    sectors = [
        # (id, loc, map, rank_req, cer, surveymin, survdist, x, y, z, start)
        (0, '', 1, 0, 0, 0, 0, 483, 927, 0, True),
        (10, 'J', 1, 20, 3, 480, 12, 900, 600, 600, False),
        (15, 'O', 1, 30, 6, 660, 14, 630, 490, 500, False),
        (18, 'R', 1, 37, 6, 780, 15, 150, 540, 600, False),
        (26, 'Z', 1, 50, 6, 1020, 17, 430, 100, 1000, False),
    ]
    for (sid, loc, m, rr, cer, smin, sdist, x, y, z, start) in sectors:
        db.session.add(SubmarineExploration(
            id=sid, destination=loc, location=loc, map_id=m, rank_req=rr,
            ceruleum_tank_req=cer, stars=1, exp_reward=0,
            survey_duration_min=smin, survey_distance=sdist,
            x=x, y=y, z=z, starting_point=start))
    parts = [  # (row_id, rank, speed, repair_materials)
        (22, 50, 30, 6), (23, 50, 25, 6), (24, 50, 70, 6), (25, 50, 25, 6),
    ]
    for (pid, rank, speed, repair) in parts:
        db.session.add(SubmarinePart(
            id=pid, slot=0, rank=rank, class_type='', components=1,
            repair_materials=repair, surveillance=0, retrieval=0,
            speed=speed, range=0, favor=0))
    db.session.add(SubmarineRank(id=125, speed_bonus=80))
    db.session.commit()
    invalidate()


def test_jorz_duration_matches_submarine_builder(app, db):
    """With the map-1 start point present, JORZ @ S+S+U+C+ lvl 125 must land on
    SubmarineBuilder's 33h26m (was 31.1h when the first travel leg was dropped)."""
    from app.services.voyage_duration_calculator import calculate_voyage_duration

    _seed_jorz_game_data(db)
    pts = [10, 15, 18, 26]
    raw = calculate_voyage_duration(pts, [23, 24, 22, 25], 125, snap=False)
    assert raw is not None
    assert 33.0 <= raw <= 34.0  # 33h26m actual
    snapped = calculate_voyage_duration(pts, [23, 24, 22, 25], 125)
    assert snapped == 36.0  # bucket behavior unchanged when snapping


def test_consumption_uses_real_duration_not_clamp(app, db):
    """JORZ fuel is exactly 21/voyage; tanks_per_day must reflect the ~33.4h
    real duration (~15/day), not the old 48h clamp (10.5/day)."""
    from app.services.config_parser import ConfigParser

    _seed_jorz_game_data(db)
    pts = [10, 15, 18, 26]
    # S+S+U+C+ as AutoRetainer item IDs (rows 23,24,22,25)
    item_ids = [24358, 24359, 24357, 24352]
    tanks, kits = ConfigParser()._calculate_consumption(item_ids, pts, 125)
    assert 14.5 <= tanks <= 15.5  # 21 * 24 / ~33.4h
    assert kits > 0
