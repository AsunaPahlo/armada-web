"""Tests for the workshop-disabled warning + alert."""
from datetime import datetime


def test_parse_workshop_enabled_flag():
    from app.services.config_parser import ConfigParser
    data = {"characters": [
        {"cid": "1", "name": "A", "world": "Gilgamesh", "fc_id": "5",
         "submarines": [{"name": "S1", "return_time": 0}], "workshop_enabled": False},
    ]}
    acct = ConfigParser().parse_plugin_data(data)
    assert acct.characters[0].workshop_enabled is False


def test_parse_workshop_enabled_defaults_true_when_missing():
    from app.services.config_parser import ConfigParser
    data = {"characters": [
        {"cid": "1", "name": "A", "world": "Gilgamesh", "fc_id": "5",
         "submarines": [{"name": "S1", "return_time": 0}]},
    ]}
    acct = ConfigParser().parse_plugin_data(data)
    assert acct.characters[0].workshop_enabled is True


def _account_with_workshop(workshop_enabled):
    from app.services.config_parser import CharacterInfo, SubmarineInfo, AccountData, FCInfo
    sub = SubmarineInfo(name="S1", return_time=datetime.utcfromtimestamp(0),
                        hours_remaining=0.0, status='ready')
    char = CharacterInfo(cid=1, name="A", world="Gilgamesh", fc_id=5, gil=0,
                         ceruleum=0, repair_kits=0, num_sub_slots=1,
                         workshop_enabled=workshop_enabled)
    char.submarines = [sub]
    acct = AccountData(nickname="acct", config_path="plugin")
    acct.characters = [char]
    acct.fc_data = {5: FCInfo(fc_id=5, name="Test FC", gil=0, fc_points=0, holder_chara=0)}
    return acct


def test_fc_summary_flags_workshop_disabled(app, db, monkeypatch):
    from app.services.fleet_manager import FleetManager
    fm = FleetManager()
    monkeypatch.setattr(fm, "get_data", lambda: [_account_with_workshop(False)])
    fc = fm.get_dashboard_data()['fc_summaries'][0]
    assert fc['workshop_disabled'] is True


def test_fc_summary_not_flagged_when_workshop_enabled(app, db, monkeypatch):
    from app.services.fleet_manager import FleetManager
    fm = FleetManager()
    monkeypatch.setattr(fm, "get_data", lambda: [_account_with_workshop(True)])
    fc = fm.get_dashboard_data()['fc_summaries'][0]
    assert fc['workshop_disabled'] is False


def test_alert_settings_has_workshop_disabled_columns(app, db):
    from app.models.alert import AlertSettings
    s = AlertSettings.get_settings()
    assert s.workshop_disabled_enabled is False
    assert s.workshop_disabled_cooldown_minutes == 1440


def test_check_workshop_disabled_fires_for_flagged_fc(app, db):
    from app.services.alert_service import AlertService
    from app.models.alert import AlertSettings
    settings = AlertSettings.get_settings()
    dashboard_data = {'fc_summaries': [
        {'fc_id': '5', 'fc_name': 'Test FC', 'workshop_disabled': True},
        {'fc_id': '6', 'fc_name': 'OK FC', 'workshop_disabled': False},
    ]}
    alerts = AlertService()._check_workshop_disabled(dashboard_data, settings)
    assert len(alerts) == 1
    assert alerts[0]['alert_type'] == 'workshop_disabled'
    assert alerts[0]['target_id'] == '5'
    assert 'Test FC' in alerts[0]['message']


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


def test_save_settings_persists_workshop_disabled(client, app, db):
    _login(client, app)
    resp = client.post('/alerts/save-settings', json={
        'alerts_enabled': True,
        'workshop_disabled_enabled': True,
        'workshop_disabled_cooldown_minutes': 720,
    })
    assert resp.status_code == 200
    from app.models.alert import AlertSettings
    s = AlertSettings.get_settings()
    assert s.workshop_disabled_enabled is True
    assert s.workshop_disabled_cooldown_minutes == 720
