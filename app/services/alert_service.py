"""
Alert Service - monitors fleet conditions and dispatches notifications.

Checks for:
- Low supply alerts (days_until_restock below threshold)
- Idle submarine alerts (submarines ready for too long)

Dispatches to:
- Browser toast (via WebSocket)
- Email (SMTP)
- Pushover
- Discord webhooks
"""
import logging
import smtplib
import threading
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests

from app import db
from app.models.alert import AlertHistory, AlertSettings

logger = logging.getLogger(__name__)


class AlertService:
    """
    Monitors fleet data for alert conditions and dispatches notifications.
    Uses singleton pattern for consistent state tracking.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # Track when submarines became ready (in-memory cache)
        # Key: "fc_id:sub_name", Value: datetime when first seen ready
        self._ready_since: dict[str, datetime] = {}
        self._ready_lock = threading.Lock()

    def check_alerts(self, dashboard_data: dict):
        """
        Check all alert conditions against current dashboard data.
        Called from the background update loop. Batches multiple alerts
        into a single notification.

        Args:
            dashboard_data: Output from FleetManager.get_dashboard_data()
        """
        try:
            settings = AlertSettings.get_settings()

            if not settings.alerts_enabled:
                return

            # Collect all alerts to batch them
            pending_alerts = []

            # Check low supply alerts
            if settings.low_supply_enabled:
                pending_alerts.extend(self._check_low_supply(dashboard_data, settings))

            # Check idle submarine alerts
            if settings.idle_sub_enabled:
                pending_alerts.extend(self._check_idle_submarines(dashboard_data, settings))

            # Check not farming alerts (subs above level threshold not on money routes)
            if settings.not_farming_enabled:
                pending_alerts.extend(self._check_not_farming(dashboard_data, settings))

            # Dispatch batched alerts if any
            if pending_alerts:
                logger.info(f"[AlertService] Batching {len(pending_alerts)} alerts into single notification")
                self._dispatch_batched_alerts(pending_alerts, settings)

        except Exception as e:
            logger.error(f"[AlertService] Error checking alerts: {e}")

    def _check_low_supply(self, dashboard_data: dict, settings: AlertSettings) -> list[dict]:
        """Check for FCs with low supplies. Returns list of alert dicts."""
        alerts = []
        threshold = settings.low_supply_threshold_days
        cooldown_minutes = settings.low_supply_cooldown_minutes

        for fc in dashboard_data.get('fc_summaries', []):
            days = fc.get('days_until_restock')

            if days is not None and days < threshold:
                fc_id = str(fc.get('fc_id', ''))
                fc_name = fc.get('fc_name', 'Unknown FC')
                limiting = fc.get('limiting_resource', 'supplies')

                # Check cooldown
                if self._is_in_cooldown('low_supply', fc_id, cooldown_minutes):
                    continue

                # Determine severity
                if days < 3:
                    severity = 'critical'
                elif days < threshold / 2:
                    severity = 'warning'
                else:
                    severity = 'info'

                message = (
                    f"Low supplies in {fc_name}: {days:.1f} days remaining "
                    f"(limited by {limiting})"
                )

                alerts.append({
                    'alert_type': 'low_supply',
                    'target_id': fc_id,
                    'target_name': fc_name,
                    'message': message,
                    'severity': severity
                })

        return alerts

    def _check_idle_submarines(self, dashboard_data: dict, settings: AlertSettings) -> list[dict]:
        """Check for submarines that have been ready for too long. Returns list of alert dicts."""
        alerts = []
        threshold_hours = settings.idle_sub_threshold_hours
        cooldown_minutes = settings.idle_sub_cooldown_minutes
        now = datetime.utcnow()

        # Track which subs we've seen this cycle
        current_ready_subs = set()

        for fc in dashboard_data.get('fc_summaries', []):
            fc_id = str(fc.get('fc_id', ''))
            fc_name = fc.get('fc_name', 'Unknown FC')

            for sub in fc.get('submarines', []):
                if sub.get('status') != 'ready':
                    continue

                sub_name = sub.get('name', 'Unknown')
                target_id = f"{fc_id}:{sub_name}"
                current_ready_subs.add(target_id)

                # Track when this sub became ready
                with self._ready_lock:
                    if target_id not in self._ready_since:
                        self._ready_since[target_id] = now
                        continue  # Just started tracking, don't alert yet

                    ready_since = self._ready_since[target_id]

                # Calculate idle time
                idle_hours = (now - ready_since).total_seconds() / 3600

                if idle_hours >= threshold_hours:
                    # Check cooldown
                    if self._is_in_cooldown('idle_sub', target_id, cooldown_minutes):
                        continue

                    severity = 'critical' if idle_hours > threshold_hours * 2 else 'warning'

                    message = (
                        f"Idle submarine: {sub_name} in {fc_name} has been ready "
                        f"for {idle_hours:.1f} hours"
                    )

                    alerts.append({
                        'alert_type': 'idle_sub',
                        'target_id': target_id,
                        'target_name': f"{sub_name} ({fc_name})",
                        'message': message,
                        'severity': severity
                    })

        # Clean up submarines that are no longer ready
        with self._ready_lock:
            stale_keys = set(self._ready_since.keys()) - current_ready_subs
            for key in stale_keys:
                del self._ready_since[key]

        return alerts

    def _check_not_farming(self, dashboard_data: dict, settings: AlertSettings) -> list[dict]:
        """
        Check for submarines above level threshold that are not on money routes.
        Returns list of alert dicts.
        """
        alerts = []
        level_threshold = settings.not_farming_level_threshold
        cooldown_minutes = settings.not_farming_cooldown_minutes

        # Get known production routes from database
        try:
            from app.models.lumina import RouteStats
            known_routes = set(r.route_name for r in RouteStats.query.all())
        except Exception:
            # If we can't get routes, skip this check
            return alerts

        for fc in dashboard_data.get('fc_summaries', []):
            fc_id = str(fc.get('fc_id', ''))
            fc_name = fc.get('fc_name', 'Unknown FC')

            for sub in fc.get('submarines', []):
                sub_name = sub.get('name', 'Unknown')
                sub_level = sub.get('level', 0)
                sub_route = sub.get('route', '')

                # Skip if below level threshold
                if sub_level < level_threshold:
                    continue

                # Skip if on a known production route
                if sub_route and sub_route in known_routes:
                    continue

                # This sub is above threshold and NOT on a money route
                target_id = f"{fc_id}:{sub_name}"

                # Check cooldown
                if self._is_in_cooldown('not_farming', target_id, cooldown_minutes):
                    continue

                severity = 'warning'

                route_display = sub_route if sub_route else 'no route'
                message = (
                    f"Submarine not farming: {sub_name} (Lv{sub_level}) in {fc_name} "
                    f"is on {route_display} instead of a money route"
                )

                alerts.append({
                    'alert_type': 'not_farming',
                    'target_id': target_id,
                    'target_name': f"{sub_name} ({fc_name})",
                    'message': message,
                    'severity': severity
                })

        return alerts

    def _is_in_cooldown(self, alert_type: str, target_id: str, cooldown_minutes: int) -> bool:
        """Check if an alert is in cooldown period."""
        cutoff = datetime.utcnow() - timedelta(minutes=cooldown_minutes)

        recent = AlertHistory.query.filter(
            AlertHistory.alert_type == alert_type,
            AlertHistory.target_id == target_id,
            AlertHistory.created_at > cutoff
        ).first()

        return recent is not None

    def _dispatch_batched_alerts(self, alerts: list[dict], settings: AlertSettings):
        """
        Send multiple alerts as a single batched notification.
        Creates individual AlertHistory records but sends one combined notification per channel.
        """
        if not alerts:
            return

        # Determine highest severity for the batch
        severity_order = {'info': 0, 'warning': 1, 'critical': 2}
        highest_severity = max(alerts, key=lambda a: severity_order.get(a['severity'], 0))['severity']

        # Format combined message
        if len(alerts) == 1:
            combined_message = alerts[0]['message']
        else:
            combined_message = f"{len(alerts)} Fleet Alerts:\n\n"
            for i, alert in enumerate(alerts, 1):
                severity_label = alert['severity'].upper()
                combined_message += f"{i}. [{severity_label}] {alert['message']}\n"

        # Send to each channel once with combined message
        email_sent = False
        pushover_sent = False
        discord_sent = False

        logger.info(f"[AlertService] Sending ONE notification per channel for {len(alerts)} alerts")

        if settings.email_enabled:
            logger.debug(f"[AlertService] Sending batched email...")
            email_sent = self._send_email_batched(alerts, highest_severity, settings)

        if settings.pushover_enabled:
            logger.debug(f"[AlertService] Sending batched pushover...")
            pushover_sent = self._send_pushover(combined_message, highest_severity, settings)

        if settings.discord_enabled:
            logger.debug(f"[AlertService] Sending batched discord...")
            discord_sent, _ = self._send_discord_batched(alerts, highest_severity, settings)

        # Create AlertHistory records for each alert
        for alert in alerts:
            history = AlertHistory(
                alert_type=alert['alert_type'],
                target_id=alert['target_id'],
                target_name=alert['target_name'],
                message=alert['message'],
                severity=alert['severity'],
                sent_email=email_sent,
                sent_pushover=pushover_sent,
                sent_discord=discord_sent
            )
            db.session.add(history)

        db.session.commit()

        # Emit single WebSocket event with all alerts
        self._emit_batched_alert_websocket(alerts)

        logger.info(f"[AlertService] Dispatched {len(alerts)} batched alerts")

    def _send_email_batched(self, alerts: list[dict], severity: str, settings: AlertSettings) -> bool:
        """Send batched HTML email notification via SMTP."""
        try:
            if not settings.smtp_host or not settings.smtp_to_addresses:
                return False

            to_addresses = [a.strip() for a in settings.smtp_to_addresses.split(',')]

            msg = MIMEMultipart('alternative')

            if len(alerts) == 1:
                msg['Subject'] = f"[Armada {severity.upper()}] Fleet Alert"
            else:
                msg['Subject'] = f"[Armada {severity.upper()}] {len(alerts)} Fleet Alerts"

            msg['From'] = settings.smtp_from_address or settings.smtp_username
            msg['To'] = ', '.join(to_addresses)

            # Plain text fallback
            if len(alerts) == 1:
                plain_body = f"""Armada Fleet Alert

Severity: {alerts[0]['severity'].upper()}

{alerts[0]['message']}

---
This is an automated alert from Armada Fleet Dashboard.
"""
            else:
                plain_body = f"Armada Fleet Alerts\n\n{len(alerts)} alerts triggered:\n\n"
                for i, alert in enumerate(alerts, 1):
                    plain_body += f"{i}. [{alert['severity'].upper()}] {alert['message']}\n"
                plain_body += "\n---\nThis is an automated alert from Armada Fleet Dashboard."

            # HTML email template
            html_body = self._build_email_html(alerts, severity)

            # Attach both versions (plain text first, HTML second - email clients prefer last)
            msg.attach(MIMEText(plain_body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                if settings.smtp_use_auth and settings.smtp_username and settings.smtp_password:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.sendmail(
                    settings.smtp_from_address or settings.smtp_username,
                    to_addresses,
                    msg.as_string()
                )

            logger.debug(f"[AlertService] Batched email sent successfully")
            return True
        except Exception as e:
            logger.error(f"[AlertService] Email error: {e}")
            return False

    def _build_email_html(self, alerts: list[dict], highest_severity: str) -> str:
        """Build HTML email template for alerts."""
        severity_colors = {
            'critical': {'bg': '#dc3545', 'text': '#ffffff'},
            'warning': {'bg': '#ffc107', 'text': '#000000'},
            'info': {'bg': '#0dcaf0', 'text': '#000000'}
        }

        alert_icons = {
            'low_supply': '⛽',
            'idle_sub': '⏰',
            'not_farming': '💰',
            'test': '🔔'
        }

        # Build alert cards HTML
        alert_cards = ""
        for alert in alerts:
            sev = alert['severity']
            sev_color = severity_colors.get(sev, severity_colors['info'])
            icon = alert_icons.get(alert['alert_type'], '⚠️')

            alert_cards += f'''
            <tr>
                <td style="padding: 8px 0;">
                    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #2d2d2d; border-radius: 8px; border-left: 4px solid {sev_color['bg']};">
                        <tr>
                            <td style="padding: 16px;">
                                <table width="100%" cellpadding="0" cellspacing="0">
                                    <tr>
                                        <td style="font-size: 24px; width: 40px; vertical-align: top;">{icon}</td>
                                        <td style="vertical-align: top;">
                                            <table cellpadding="0" cellspacing="0">
                                                <tr>
                                                    <td>
                                                        <span style="display: inline-block; background-color: {sev_color['bg']}; color: {sev_color['text']}; font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 4px; text-transform: uppercase;">{sev}</span>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td style="padding-top: 8px;">
                                                        <span style="color: #ffffff; font-size: 14px; font-weight: 600;">{alert['target_name']}</span>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td style="padding-top: 4px;">
                                                        <span style="color: #b0b0b0; font-size: 13px;">{alert['message']}</span>
                                                    </td>
                                                </tr>
                                            </table>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            '''

        # Header text
        if len(alerts) == 1:
            header_text = "Fleet Alert"
            subheader_text = "An alert requires your attention"
        else:
            header_text = f"{len(alerts)} Fleet Alerts"
            subheader_text = "Multiple alerts require your attention"

        # Build complete HTML
        html = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #1a1a1a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #1a1a1a; padding: 20px 0;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%;">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #1e3a5f 0%, #0d1b2a 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center">
                                        <span style="font-size: 32px;">🌊</span>
                                    </td>
                                </tr>
                                <tr>
                                    <td align="center" style="padding-top: 10px;">
                                        <span style="color: #ffffff; font-size: 28px; font-weight: bold; letter-spacing: 1px;">ARMADA</span>
                                    </td>
                                </tr>
                                <tr>
                                    <td align="center" style="padding-top: 5px;">
                                        <span style="color: #64b5f6; font-size: 12px; text-transform: uppercase; letter-spacing: 2px;">Fleet Dashboard</span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Alert Header -->
                    <tr>
                        <td style="background-color: #242424; padding: 25px 30px; border-bottom: 1px solid #333;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td>
                                        <span style="color: #ffffff; font-size: 22px; font-weight: 600;">{header_text}</span>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding-top: 5px;">
                                        <span style="color: #888888; font-size: 14px;">{subheader_text}</span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Alert Cards -->
                    <tr>
                        <td style="background-color: #242424; padding: 20px 30px;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                {alert_cards}
                            </table>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #1e1e1e; padding: 20px 30px; border-radius: 0 0 12px 12px; text-align: center;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center">
                                        <span style="color: #666666; font-size: 12px;">This is an automated alert from Armada Fleet Dashboard</span>
                                    </td>
                                </tr>
                                <tr>
                                    <td align="center" style="padding-top: 10px;">
                                        <span style="color: #444444; font-size: 11px;">FFXIV Submarine Fleet Management</span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
'''
        return html

    def _send_discord_batched(self, alerts: list[dict], severity: str, settings: AlertSettings) -> tuple[bool, str]:
        """Send batched Discord webhook notification. Returns (success, error_message)."""
        try:
            if not settings.discord_webhook_url:
                return False, "No webhook URL configured"

            color_map = {'info': 3447003, 'warning': 16776960, 'critical': 15158332}
            color = color_map.get(severity, 3447003)

            timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')

            if len(alerts) == 1:
                title = f'Armada Fleet Alert ({severity.upper()})'
                description = alerts[0]['message']
            else:
                title = f'Armada Fleet Alerts ({len(alerts)} alerts)'
                description = ""
                for i, alert in enumerate(alerts, 1):
                    severity_emoji = {'critical': '🔴', 'warning': '🟡', 'info': '🔵'}.get(alert['severity'], '⚪')
                    description += f"{severity_emoji} {alert['message']}\n"

            payload = {
                'embeds': [{
                    'title': title,
                    'description': description,
                    'color': color,
                    'timestamp': timestamp,
                    'footer': {'text': 'Armada Fleet Dashboard'}
                }]
            }

            response = requests.post(
                settings.discord_webhook_url,
                json=payload,
                timeout=10
            )

            if response.status_code in (200, 204):
                logger.debug(f"[AlertService] Discord webhook sent successfully")
                return True, ""
            else:
                error_msg = f"Discord returned {response.status_code}: {response.text[:200]}"
                logger.warning(f"[AlertService] {error_msg}")
                return False, error_msg
        except requests.exceptions.Timeout:
            error_msg = "Request timed out"
            logger.error(f"[AlertService] Discord error: {error_msg}")
            return False, error_msg
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            logger.error(f"[AlertService] Discord error: {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[AlertService] Discord error: {error_msg}")
            return False, error_msg

    def _emit_batched_alert_websocket(self, alerts: list[dict]):
        """Emit batched alerts via WebSocket to update navbar bell icon."""
        try:
            from app import socketio

            # Emit each alert individually so the frontend can handle them
            for alert in alerts:
                socketio.emit('alert', {
                    'type': alert['alert_type'],
                    'target_id': alert['target_id'],
                    'target_name': alert['target_name'],
                    'message': alert['message'],
                    'severity': alert['severity'],
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                }, room='dashboard', namespace='/')

            logger.debug(f"[AlertService] WebSocket alerts emitted ({len(alerts)} alerts)")
        except Exception as e:
            logger.error(f"[AlertService] WebSocket alert error: {e}")

    def _dispatch_alert(self, alert_type: str, target_id: str, target_name: str,
                        message: str, severity: str, settings: AlertSettings):
        """Send alert through all enabled channels. (Legacy single-alert method)"""

        # Create history record
        history = AlertHistory(
            alert_type=alert_type,
            target_id=target_id,
            target_name=target_name,
            message=message,
            severity=severity
        )

        # Dispatch to each channel
        if settings.email_enabled:
            history.sent_email = self._send_email(message, severity, settings)

        if settings.pushover_enabled:
            history.sent_pushover = self._send_pushover(message, severity, settings)

        if settings.discord_enabled:
            history.sent_discord, _ = self._send_discord(message, severity, settings)

        # Always emit WebSocket event to update the navbar bell icon
        self._emit_alert_websocket(alert_type, target_id, target_name, message, severity)

        # Save history
        db.session.add(history)
        db.session.commit()

        logger.info(f"[AlertService] Dispatched {alert_type} alert: {message}")

    def _send_email(self, message: str, severity: str, settings: AlertSettings) -> bool:
        """Send email notification via SMTP. Used for test notifications."""
        try:
            if not settings.smtp_host or not settings.smtp_to_addresses:
                return False

            # Create a test alert structure for the HTML template
            test_alert = {
                'alert_type': 'test',
                'target_id': 'test',
                'target_name': 'Test Notification',
                'message': message,
                'severity': severity
            }

            to_addresses = [a.strip() for a in settings.smtp_to_addresses.split(',')]

            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[Armada {severity.upper()}] Fleet Alert"
            msg['From'] = settings.smtp_from_address or settings.smtp_username
            msg['To'] = ', '.join(to_addresses)

            # Plain text fallback
            plain_body = f"""Armada Fleet Alert

Severity: {severity.upper()}

{message}

---
This is an automated alert from Armada Fleet Dashboard.
"""

            # HTML version using the template
            html_body = self._build_email_html([test_alert], severity)

            msg.attach(MIMEText(plain_body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                if settings.smtp_use_auth and settings.smtp_username and settings.smtp_password:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.sendmail(
                    settings.smtp_from_address or settings.smtp_username,
                    to_addresses,
                    msg.as_string()
                )

            logger.debug(f"[AlertService] Email sent successfully")
            return True
        except Exception as e:
            logger.error(f"[AlertService] Email error: {e}")
            return False

    def _send_pushover(self, message: str, severity: str, settings: AlertSettings) -> bool:
        """Send Pushover notification."""
        try:
            if not settings.pushover_user_key or not settings.pushover_api_token:
                return False

            priority_map = {'info': -1, 'warning': 0, 'critical': 1}
            priority = priority_map.get(severity, settings.pushover_priority)

            response = requests.post(
                'https://api.pushover.net/1/messages.json',
                data={
                    'token': settings.pushover_api_token,
                    'user': settings.pushover_user_key,
                    'message': message,
                    'title': f'Armada Alert ({severity.upper()})',
                    'priority': priority,
                    'sound': 'bugle' if severity == 'critical' else 'pushover'
                },
                timeout=10
            )

            success = response.status_code == 200
            if success:
                logger.debug(f"[AlertService] Pushover sent successfully")
            else:
                logger.warning(f"[AlertService] Pushover returned {response.status_code}")
            return success
        except Exception as e:
            logger.error(f"[AlertService] Pushover error: {e}")
            return False

    def _send_discord(self, message: str, severity: str, settings: AlertSettings) -> tuple[bool, str]:
        """Send Discord webhook notification. Returns (success, error_message)."""
        try:
            if not settings.discord_webhook_url:
                return False, "No webhook URL configured"

            color_map = {'info': 3447003, 'warning': 16776960, 'critical': 15158332}
            color = color_map.get(severity, 3447003)

            # Discord requires ISO 8601 format with Z suffix
            timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')

            payload = {
                'embeds': [{
                    'title': f'Armada Fleet Alert ({severity.upper()})',
                    'description': message,
                    'color': color,
                    'timestamp': timestamp,
                    'footer': {'text': 'Armada Fleet Dashboard'}
                }]
            }

            response = requests.post(
                settings.discord_webhook_url,
                json=payload,
                timeout=10
            )

            if response.status_code in (200, 204):
                logger.debug(f"[AlertService] Discord webhook sent successfully")
                return True, ""
            else:
                error_msg = f"Discord returned {response.status_code}: {response.text[:200]}"
                logger.warning(f"[AlertService] {error_msg}")
                return False, error_msg
        except requests.exceptions.Timeout:
            error_msg = "Request timed out"
            logger.error(f"[AlertService] Discord error: {error_msg}")
            return False, error_msg
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            logger.error(f"[AlertService] Discord error: {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[AlertService] Discord error: {error_msg}")
            return False, error_msg

    def _emit_alert_websocket(self, alert_type: str, target_id: str,
                               target_name: str, message: str, severity: str):
        """Emit alert via WebSocket to update navbar bell icon."""
        try:
            from app import socketio

            socketio.emit('alert', {
                'type': alert_type,
                'target_id': target_id,
                'target_name': target_name,
                'message': message,
                'severity': severity,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }, room='dashboard', namespace='/')

            logger.debug(f"[AlertService] WebSocket alert emitted")
        except Exception as e:
            logger.error(f"[AlertService] WebSocket alert error: {e}")

    def test_notification(self, channel: str, settings: Optional[AlertSettings] = None) -> dict:
        """
        Send a test notification to a specific channel.

        Args:
            channel: 'email', 'pushover', or 'discord'
            settings: AlertSettings to use (fetches if None)

        Returns:
            Dict with 'success' bool and 'message' str
        """
        if settings is None:
            settings = AlertSettings.get_settings()

        test_message = "This is a test alert from Armada Fleet Dashboard."

        if channel == 'email':
            success = self._send_email(test_message, 'info', settings)
            error_msg = ""
        elif channel == 'pushover':
            success = self._send_pushover(test_message, 'info', settings)
            error_msg = ""
        elif channel == 'discord':
            success, error_msg = self._send_discord(test_message, 'info', settings)
        else:
            return {'success': False, 'message': f'Unknown channel: {channel}'}

        if success:
            return {'success': True, 'message': f'Test {channel} notification sent'}
        else:
            return {'success': False, 'message': f'Test {channel} failed: {error_msg}' if error_msg else f'Test {channel} failed'}


# Singleton instance
alert_service = AlertService()
