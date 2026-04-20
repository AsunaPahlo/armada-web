"""FC Credits tracking page routes."""
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required

from app import db
from app.decorators import writable_required
from app.models.fc_config import FCConfig, get_credits_excluded_fc_ids
from app.services.fc_credits_tracker import FCCreditsTracker

credits_bp = Blueprint('credits', __name__)

ALLOWED_DAYS = {0, 7, 14, 30, 90, 365}


@credits_bp.route('/')
@login_required
def index():
    """Render the FC credits page skeleton."""
    return render_template('credits.html')


@credits_bp.route('/data')
@login_required
def data():
    """Return the FC credits report as JSON for the chart + cards."""
    days = request.args.get('days', 30, type=int)
    if days is None or days not in ALLOWED_DAYS:
        days = 30

    tz_offset = request.args.get('tz', 0, type=int)
    tz_offset = max(-720, min(840, tz_offset))

    excluded = get_credits_excluded_fc_ids()
    report = FCCreditsTracker.get_report(
        days=days, exclude_fc_ids=excluded, tz_offset_minutes=tz_offset
    )
    return jsonify(report)


@credits_bp.route('/toggle', methods=['POST'])
@login_required
@writable_required
def toggle():
    """Toggle excluded_from_credits for a given fc_id.

    Body: {"fc_id": "...", "excluded": true|false}
    """
    payload = request.get_json(silent=True) or {}
    fc_id = payload.get('fc_id')
    excluded = payload.get('excluded')
    if not fc_id or not isinstance(excluded, bool):
        return jsonify({"error": "fc_id (string) and excluded (bool) required"}), 400

    fc_id = str(fc_id)
    cfg = FCConfig.query.filter_by(fc_id=fc_id).first()
    if not cfg:
        cfg = FCConfig(fc_id=fc_id)
        db.session.add(cfg)
    cfg.excluded_from_credits = excluded
    db.session.commit()
    return jsonify({"status": "ok"})
