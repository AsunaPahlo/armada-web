"""Gil tracking page routes."""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required
from sqlalchemy import func, desc

from app import db
from app.models.gil_record import GilRecord

gil_bp = Blueprint('gil', __name__)


@gil_bp.route('/')
@login_required
def index():
    """Render the gil tracking page."""
    return render_template('gil.html')


@gil_bp.route('/api/data')
@login_required
def api_data():
    """Return gil data for charts and tables."""
    days = request.args.get('days', 30, type=int)

    # Timezone offset from JS getTimezoneOffset() (positive = west of UTC)
    tz_offset = request.args.get('tz', 0, type=int)
    tz_offset = max(-720, min(840, tz_offset))
    tz_delta = timedelta(minutes=-tz_offset)

    if days > 0:
        cutoff = datetime.utcnow() - timedelta(days=days)
    else:
        cutoff = None

    # Daily aggregated totals for the chart with forward-fill
    # Characters not scanned on a given day carry forward their last known value
    # (matches CashFlow plugin behavior to avoid dips on partial-scan days)
    records_query = db.session.query(
        GilRecord.timestamp,
        GilRecord.cid,
        (GilRecord.gil_player + GilRecord.gil_retainer).label('total'),
    )
    if cutoff:
        records_query = records_query.filter(GilRecord.record_date >= cutoff.date())

    records = records_query.order_by(GilRecord.timestamp).all()

    # Build per-date, per-character map using local date (adjusted by tz offset)
    dates_in_order = []
    date_char_map = {}  # date -> {cid: total}
    for row in records:
        d = (row.timestamp + tz_delta).date()
        if d not in date_char_map:
            date_char_map[d] = {}
            dates_in_order.append(d)
        date_char_map[d][row.cid] = int(row.total)

    # Seed forward-fill with last known values from before the cutoff
    # so the chart doesn't start low when characters weren't scanned in this window
    prev_values = {}  # cid -> last known total
    if cutoff:
        pre_cutoff_latest = (
            db.session.query(
                GilRecord.cid,
                func.max(GilRecord.record_date).label('max_date')
            )
            .filter(GilRecord.record_date < cutoff.date())
            .group_by(GilRecord.cid)
            .subquery()
        )
        pre_cutoff = (
            db.session.query(
                GilRecord.cid,
                (GilRecord.gil_player + GilRecord.gil_retainer).label('total'),
            )
            .join(pre_cutoff_latest, db.and_(
                GilRecord.cid == pre_cutoff_latest.c.cid,
                GilRecord.record_date == pre_cutoff_latest.c.max_date,
            ))
            .all()
        )
        for row in pre_cutoff:
            prev_values[row.cid] = int(row.total)

    # Forward-fill: for each date, carry forward unscanned characters
    chart_labels = []
    chart_totals = []
    chart_char_counts = []

    for d in dates_in_order:
        scanned = date_char_map[d]
        prev_values.update(scanned)
        daily_total = sum(prev_values.values())
        chart_labels.append(str(d))
        chart_totals.append(daily_total)
        chart_char_counts.append(len(prev_values))

    chart_data = {
        'labels': chart_labels,
        'totals': chart_totals,
        'character_counts': chart_char_counts,
    }

    # Per-character current snapshot (latest record per character)
    latest_date = (
        db.session.query(
            GilRecord.cid,
            func.max(GilRecord.record_date).label('max_date')
        )
        .group_by(GilRecord.cid)
        .subquery()
    )

    current_snapshot = (
        db.session.query(GilRecord)
        .join(latest_date, db.and_(
            GilRecord.cid == latest_date.c.cid,
            GilRecord.record_date == latest_date.c.max_date
        ))
        .order_by(desc(GilRecord.gil_player + GilRecord.gil_retainer))
        .all()
    )

    # Get previous day's snapshot for deltas
    second_latest_date = (
        db.session.query(
            GilRecord.cid,
            func.max(GilRecord.record_date).label('max_date')
        )
        .join(latest_date, db.and_(
            GilRecord.cid == latest_date.c.cid,
            GilRecord.record_date < latest_date.c.max_date
        ))
        .group_by(GilRecord.cid)
        .subquery()
    )

    previous_snapshot = (
        db.session.query(GilRecord)
        .join(second_latest_date, db.and_(
            GilRecord.cid == second_latest_date.c.cid,
            GilRecord.record_date == second_latest_date.c.max_date
        ))
        .all()
    )

    previous_by_cid = {r.cid: r for r in previous_snapshot}

    characters = []
    total_gil = 0
    for record in current_snapshot:
        current_total = record.gil_player + record.gil_retainer
        total_gil += current_total

        prev = previous_by_cid.get(record.cid)
        delta = current_total - (prev.gil_player + prev.gil_retainer) if prev else 0

        characters.append({
            'character_name': record.character_name,
            'world': record.world,
            'gil_player': record.gil_player,
            'gil_retainer': record.gil_retainer,
            'total': current_total,
            'delta': delta,
            'record_date': str((record.timestamp + tz_delta).date()) if record.timestamp else str(record.record_date),
            'last_updated': record.timestamp.isoformat() if record.timestamp else record.record_date.isoformat(),
            'client_nickname': record.client_nickname,
        })

    return jsonify({
        'chart': chart_data,
        'characters': characters,
        'total_gil': total_gil,
    })
