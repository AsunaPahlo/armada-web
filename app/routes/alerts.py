"""
Alert configuration routes.
"""
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

from app import db
from app.models.alert import AlertHistory, AlertSettings
from app.services.alert_service import alert_service

alerts_bp = Blueprint('alerts', __name__)


@alerts_bp.route('/')
@login_required
def settings():
    """Alert settings page."""
    alert_settings = AlertSettings.get_settings()

    # Get recent alert history
    recent_alerts = AlertHistory.query.order_by(
        AlertHistory.created_at.desc()
    ).limit(50).all()

    return render_template(
        'alerts/settings.html',
        settings=alert_settings,
        recent_alerts=recent_alerts
    )


@alerts_bp.route('/save', methods=['POST'])
@login_required
def save_settings():
    """Save alert settings (form-based, with redirect)."""
    settings = AlertSettings.get_settings()

    # Master enable
    settings.alerts_enabled = request.form.get('alerts_enabled') == 'on'

    # Low supply settings
    settings.low_supply_enabled = request.form.get('low_supply_enabled') == 'on'
    settings.low_supply_threshold_days = float(request.form.get('low_supply_threshold_days', 7))
    settings.low_supply_cooldown_minutes = int(request.form.get('low_supply_cooldown_minutes', 60))

    # Idle sub settings
    settings.idle_sub_enabled = request.form.get('idle_sub_enabled') == 'on'
    settings.idle_sub_threshold_hours = float(request.form.get('idle_sub_threshold_hours', 2))
    settings.idle_sub_cooldown_minutes = int(request.form.get('idle_sub_cooldown_minutes', 30))

    # Not farming settings
    settings.not_farming_enabled = request.form.get('not_farming_enabled') == 'on'
    settings.not_farming_level_threshold = int(request.form.get('not_farming_level_threshold', 90))
    settings.not_farming_cooldown_minutes = int(request.form.get('not_farming_cooldown_minutes', 60))

    # Email settings
    settings.email_enabled = request.form.get('email_enabled') == 'on'
    settings.smtp_host = request.form.get('smtp_host', '').strip() or None
    settings.smtp_port = int(request.form.get('smtp_port', 587))
    settings.smtp_use_auth = request.form.get('smtp_use_auth') == 'on'
    settings.smtp_username = request.form.get('smtp_username', '').strip() or None
    # Only update password if provided (don't clear existing)
    new_password = request.form.get('smtp_password', '').strip()
    if new_password:
        settings.smtp_password = new_password
    settings.smtp_use_tls = request.form.get('smtp_use_tls') == 'on'
    settings.smtp_from_address = request.form.get('smtp_from_address', '').strip() or None
    settings.smtp_to_addresses = request.form.get('smtp_to_addresses', '').strip() or None

    # Pushover settings
    settings.pushover_enabled = request.form.get('pushover_enabled') == 'on'
    settings.pushover_user_key = request.form.get('pushover_user_key', '').strip() or None
    new_pushover_token = request.form.get('pushover_api_token', '').strip()
    if new_pushover_token:
        settings.pushover_api_token = new_pushover_token
    settings.pushover_priority = int(request.form.get('pushover_priority', 0))

    # Discord settings
    settings.discord_enabled = request.form.get('discord_enabled') == 'on'
    settings.discord_webhook_url = request.form.get('discord_webhook_url', '').strip() or None

    # Browser toast settings
    settings.browser_toast_enabled = request.form.get('browser_toast_enabled') == 'on'

    db.session.commit()
    flash('Alert settings saved successfully.', 'success')
    return redirect(url_for('alerts.settings'))


@alerts_bp.route('/save-settings', methods=['POST'])
@login_required
def save_settings_json():
    """Save alert settings (JSON-based, for AJAX)."""
    settings = AlertSettings.get_settings()
    data = request.get_json() or {}

    # Master enable
    settings.alerts_enabled = data.get('alerts_enabled', False)

    # Low supply settings
    settings.low_supply_enabled = data.get('low_supply_enabled', False)
    settings.low_supply_threshold_days = float(data.get('low_supply_threshold_days', 7))
    settings.low_supply_cooldown_minutes = int(data.get('low_supply_cooldown_minutes', 60))

    # Idle sub settings
    settings.idle_sub_enabled = data.get('idle_sub_enabled', False)
    settings.idle_sub_threshold_hours = float(data.get('idle_sub_threshold_hours', 2))
    settings.idle_sub_cooldown_minutes = int(data.get('idle_sub_cooldown_minutes', 30))

    # Not farming settings
    settings.not_farming_enabled = data.get('not_farming_enabled', False)
    settings.not_farming_level_threshold = int(data.get('not_farming_level_threshold', 90))
    settings.not_farming_cooldown_minutes = int(data.get('not_farming_cooldown_minutes', 60))

    # Email settings
    settings.email_enabled = data.get('email_enabled', False)
    settings.smtp_host = (data.get('smtp_host') or '').strip() or None
    settings.smtp_port = int(data.get('smtp_port', 587))
    settings.smtp_use_auth = data.get('smtp_use_auth', False)
    settings.smtp_username = (data.get('smtp_username') or '').strip() or None
    new_password = (data.get('smtp_password') or '').strip()
    if new_password:
        settings.smtp_password = new_password
    settings.smtp_use_tls = data.get('smtp_use_tls', False)
    settings.smtp_from_address = (data.get('smtp_from_address') or '').strip() or None
    settings.smtp_to_addresses = (data.get('smtp_to_addresses') or '').strip() or None

    # Pushover settings
    settings.pushover_enabled = data.get('pushover_enabled', False)
    settings.pushover_user_key = (data.get('pushover_user_key') or '').strip() or None
    new_pushover_token = (data.get('pushover_api_token') or '').strip()
    if new_pushover_token:
        settings.pushover_api_token = new_pushover_token
    settings.pushover_priority = int(data.get('pushover_priority', 0))

    # Discord settings
    settings.discord_enabled = data.get('discord_enabled', False)
    settings.discord_webhook_url = (data.get('discord_webhook_url') or '').strip() or None

    db.session.commit()
    return jsonify({'success': True})


@alerts_bp.route('/test/<channel>', methods=['POST'])
@login_required
def test_notification(channel: str):
    """Test a notification channel."""
    result = alert_service.test_notification(channel)
    return jsonify(result)


@alerts_bp.route('/history')
@login_required
def history():
    """Get alert history as JSON."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    alerts = AlertHistory.query.order_by(
        AlertHistory.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'alerts': [{
            'id': a.id,
            'type': a.alert_type,
            'target_name': a.target_name,
            'message': a.message,
            'severity': a.severity,
            'sent_email': a.sent_email,
            'sent_pushover': a.sent_pushover,
            'sent_discord': a.sent_discord,
            'sent_browser': a.sent_browser,
            'created_at': a.created_at.isoformat() + 'Z'
        } for a in alerts.items],
        'total': alerts.total,
        'page': alerts.page,
        'pages': alerts.pages
    })


@alerts_bp.route('/clear-history', methods=['POST'])
@login_required
def clear_history():
    """Clear alert history."""
    AlertHistory.query.delete()
    db.session.commit()

    # Return JSON for AJAX requests
    if request.is_json or request.headers.get('Accept') == 'application/json':
        return jsonify({'success': True})

    flash('Alert history cleared.', 'success')
    return redirect(url_for('alerts.settings'))


@alerts_bp.route('/unacknowledged')
@login_required
def unacknowledged():
    """Get unacknowledged alerts for the navbar bell icon."""
    alerts = AlertHistory.query.filter_by(acknowledged=False).order_by(
        AlertHistory.created_at.desc()
    ).limit(10).all()

    unack_count = AlertHistory.query.filter_by(acknowledged=False).count()

    return jsonify({
        'count': unack_count,
        'alerts': [{
            'id': a.id,
            'type': a.alert_type,
            'target_name': a.target_name,
            'message': a.message,
            'severity': a.severity,
            'created_at': a.created_at.isoformat() + 'Z'
        } for a in alerts]
    })


@alerts_bp.route('/acknowledge', methods=['POST'])
@login_required
def acknowledge():
    """Mark alerts as acknowledged."""
    data = request.get_json() or {}
    alert_ids = data.get('ids', [])

    if alert_ids:
        # Acknowledge specific alerts
        AlertHistory.query.filter(AlertHistory.id.in_(alert_ids)).update(
            {'acknowledged': True, 'acknowledged_at': datetime.utcnow()},
            synchronize_session=False
        )
    else:
        # Acknowledge all
        AlertHistory.query.filter_by(acknowledged=False).update(
            {'acknowledged': True, 'acknowledged_at': datetime.utcnow()},
            synchronize_session=False
        )

    db.session.commit()
    return jsonify({'success': True})


@alerts_bp.route('/delete/<int:alert_id>', methods=['POST'])
@login_required
def delete_alert(alert_id: int):
    """Delete a specific alert."""
    alert = AlertHistory.query.get(alert_id)
    if alert:
        db.session.delete(alert)
        db.session.commit()
    return jsonify({'success': True})
