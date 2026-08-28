"""Alert-settings persistence regression: unbuilt-subs was never saved by either handler."""


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


def test_save_settings_json_persists_unbuilt_subs(client, app, db):
    _login(client, app)
    resp = client.post('/alerts/save-settings', json={
        'alerts_enabled': True,
        'unbuilt_subs_enabled': True,
        'unbuilt_subs_cooldown_minutes': 555,
    })
    assert resp.status_code == 200
    from app.models.alert import AlertSettings
    s = AlertSettings.get_settings()
    assert s.unbuilt_subs_enabled is True
    assert s.unbuilt_subs_cooldown_minutes == 555


def test_save_settings_form_persists_unbuilt_subs(client, app, db):
    _login(client, app)
    resp = client.post('/alerts/save', data={
        'alerts_enabled': 'on',
        'unbuilt_subs_enabled': 'on',
        'unbuilt_subs_cooldown_minutes': '333',
    }, follow_redirects=True)
    assert resp.status_code == 200
    from app.models.alert import AlertSettings
    s = AlertSettings.get_settings()
    assert s.unbuilt_subs_enabled is True
    assert s.unbuilt_subs_cooldown_minutes == 333
