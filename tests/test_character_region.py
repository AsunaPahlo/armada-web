"""Tests for per-account character-by-region counts."""


def _mkchar(world, name="C"):
    from app.services.config_parser import CharacterInfo
    return CharacterInfo(cid=0, name=name, world=world, fc_id=1, gil=0,
                         ceruleum=0, repair_kits=0, num_sub_slots=0)


def _account(nickname, worlds):
    from app.services.config_parser import AccountData
    acct = AccountData(nickname=nickname, config_path="plugin")
    acct.characters = [_mkchar(w) for w in worlds]
    return acct


def test_character_region_counts_basic(app, db, monkeypatch):
    from app.services.fleet_manager import FleetManager
    # Gilgamesh + Cactuar are NA (Aether); Lich is EU (Light).
    acctA = _account("avalon1", ["Gilgamesh", "Gilgamesh", "Cactuar", "Lich"])
    acctB = _account("shuzelin1", ["Lich"])
    fm = FleetManager()
    monkeypatch.setattr(fm, "get_data", lambda: [acctB, acctA])  # unsorted on purpose

    result = fm.get_character_region_counts()

    assert result["grand_total"] == 5
    assert result["totals"]["NA"] == 3
    assert result["totals"]["EU"] == 2
    assert [a["nickname"] for a in result["accounts"]] == ["avalon1", "shuzelin1"]

    a = result["accounts"][0]
    assert a["total"] == 4
    assert a["region_totals"] == {"NA": 3, "EU": 1}
    assert list(a["regions"]["NA"].items()) == [("Gilgamesh", 2), ("Cactuar", 1)]
    assert a["regions"]["EU"] == {"Lich": 1}


def test_character_region_counts_unknown_world(app, db, monkeypatch):
    from app.services.fleet_manager import FleetManager
    fm = FleetManager()
    monkeypatch.setattr(fm, "get_data", lambda: [_account("x", ["Nowhere"])])
    result = fm.get_character_region_counts()
    assert result["totals"].get("Unknown") == 1
    assert result["accounts"][0]["regions"]["Unknown"] == {"Nowhere": 1}


def test_character_region_counts_empty(app, db, monkeypatch):
    from app.services.fleet_manager import FleetManager
    fm = FleetManager()
    monkeypatch.setattr(fm, "get_data", lambda: [])
    assert fm.get_character_region_counts() == {"totals": {}, "grand_total": 0, "accounts": []}


def test_character_region_counts_skips_empty_account(app, db, monkeypatch):
    from app.services.fleet_manager import FleetManager
    fm = FleetManager()
    monkeypatch.setattr(fm, "get_data", lambda: [_account("empty", []), _account("real", ["Gilgamesh"])])
    result = fm.get_character_region_counts()
    assert [a["nickname"] for a in result["accounts"]] == ["real"]


def _login(client, app):
    from app.models.user import User
    from app import db as _db
    with app.app_context():
        if not User.query.filter_by(username="tester").first():
            u = User(username="tester", role="admin")
            u.set_password("testpass")
            _db.session.add(u)
            _db.session.commit()
    client.post("/auth/login", data={"username": "tester", "password": "testpass"},
                follow_redirects=True)


def test_stats_page_shows_characters_by_region(client, app, db):
    _login(client, app)
    resp = client.get("/stats/")
    assert resp.status_code == 200
    assert b"Characters by Region" in resp.data
