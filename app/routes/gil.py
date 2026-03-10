"""Gil tracking page routes."""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required
from sqlalchemy import func, desc

from app import db
from app.models.gil_record import GilRecord
from app.models.gil_config import get_gil_excluded_cids

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
    excluded_cids = get_gil_excluded_cids()

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
        included = {cid: total for cid, total in prev_values.items() if cid not in excluded_cids}
        daily_total = sum(included.values())
        chart_labels.append(str(d))
        chart_totals.append(daily_total)
        chart_char_counts.append(len(included))

    # Compute per-character first/last totals for stats (non-excluded only)
    char_first = {}  # cid -> first known total in window
    char_last = {}   # cid -> last known total in window
    for d in dates_in_order:
        scanned = date_char_map[d]
        for cid, total in scanned.items():
            if cid in excluded_cids:
                continue
            if cid not in char_first:
                char_first[cid] = total
            char_last[cid] = total

    # Also seed char_first from pre-cutoff for characters that weren't scanned in window
    for cid, total in prev_values.items():
        if cid in excluded_cids:
            continue
        if cid not in char_first:
            char_first[cid] = total
        if cid not in char_last:
            char_last[cid] = total

    # Net change and per-character deltas
    net_change = None
    avg_daily = None
    top_earner = None
    richest_char = None

    if len(chart_totals) >= 2:
        net_change = chart_totals[-1] - chart_totals[0]
        num_days = max(len(chart_totals) - 1, 1)
        avg_daily = net_change / num_days

    # Per-character period deltas and richest
    char_deltas = {}  # cid -> delta over period
    for cid in char_last:
        if cid in char_first:
            char_deltas[cid] = char_last[cid] - char_first[cid]

    # We need character names for stats - build a cid -> name map from records
    cid_names = {}
    for row in records:
        if row.cid not in excluded_cids:
            cid_names[row.cid] = row.cid  # fallback

    # Get names from the current snapshot query (done later), so build from records query
    # Actually we need names now - query latest names for non-excluded cids
    if char_deltas or char_last:
        name_cids = set(char_deltas.keys()) | set(char_last.keys())
        if name_cids:
            name_records = (
                db.session.query(GilRecord.cid, GilRecord.character_name)
                .filter(GilRecord.cid.in_(name_cids))
                .group_by(GilRecord.cid)
                .all()
            )
            cid_names = {r.cid: r.character_name for r in name_records}

    if char_deltas:
        best_cid = max(char_deltas, key=char_deltas.get)
        if char_deltas[best_cid] > 0:
            top_earner = {'name': cid_names.get(best_cid, '?'), 'delta': char_deltas[best_cid]}

    if char_last:
        rich_cid = max(char_last, key=char_last.get)
        richest_char = {'name': cid_names.get(rich_cid, '?'), 'total': char_last[rich_cid]}

    stats = {
        'net_change': net_change,
        'avg_daily': round(avg_daily) if avg_daily is not None else None,
        'top_earner': top_earner,
        'richest_char': richest_char,
    }

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
        is_excluded = record.cid in excluded_cids
        if not is_excluded:
            total_gil += current_total

        prev = previous_by_cid.get(record.cid)
        delta = current_total - (prev.gil_player + prev.gil_retainer) if prev else 0

        characters.append({
            'cid': record.cid,
            'character_name': record.character_name,
            'world': record.world,
            'gil_player': record.gil_player,
            'gil_retainer': record.gil_retainer,
            'total': current_total,
            'delta': delta,
            'excluded': is_excluded,
            'record_date': str((record.timestamp + tz_delta).date()) if record.timestamp else str(record.record_date),
            'last_updated': record.timestamp.isoformat() if record.timestamp else record.record_date.isoformat(),
            'client_nickname': record.client_nickname,
        })

    return jsonify({
        'chart': chart_data,
        'characters': characters,
        'total_gil': total_gil,
        'stats': stats,
    })
