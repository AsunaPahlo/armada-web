"""
Data export routes for downloading fleet data as CSV files.
"""
import csv
import io
from datetime import datetime, timedelta
from flask import Blueprint, Response, render_template, request
from flask_login import login_required

from app import db
from app.models.voyage_loot import VoyageLoot, VoyageLootItem
from app.models.fc_housing import get_all_fc_housing

export_bp = Blueprint('export', __name__)


@export_bp.route('/')
@login_required
def index():
    """Export settings page."""
    return render_template('settings/export.html')


@export_bp.route('/fc')
@login_required
def export_fc():
    """Export Free Companies data as CSV."""
    from app.services import get_fleet_manager

    fleet = get_fleet_manager()
    accounts = fleet.get_data(force_refresh=True)
    fc_housing = get_all_fc_housing()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'fc_id', 'fc_name', 'holder_character', 'world',
        'district', 'ward', 'plot', 'submarine_count'
    ])

    seen_fc_ids = set()
    for account in accounts:
        for char in account.characters:
            fc_id = char.fc_id
            fc_id_str = str(fc_id) if fc_id else 'unknown'

            if fc_id_str in seen_fc_ids:
                continue
            seen_fc_ids.add(fc_id_str)

            fc_info = account.fc_data.get(fc_id)
            fc_name = fc_info.name if fc_info and fc_info.name else f"FC-{fc_id}"

            # Get housing info
            housing = fc_housing.get(fc_id_str)
            district = housing.district if housing else ''
            ward = housing.ward if housing else ''
            plot = housing.plot if housing else ''

            # Count submarines for this FC
            sub_count = 0
            for acc in accounts:
                for c in acc.characters:
                    if str(c.fc_id) == fc_id_str:
                        sub_count += len(c.submarines)

            writer.writerow([
                fc_id_str,
                fc_name,
                char.name,
                char.world,
                district,
                ward,
                plot,
                sub_count
            ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=fc_export.csv'}
    )


@export_bp.route('/characters')
@login_required
def export_characters():
    """Export Characters data as CSV."""
    from app.services import get_fleet_manager

    fleet = get_fleet_manager()
    accounts = fleet.get_data(force_refresh=True)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'character_name', 'character_cid', 'world', 'fc_name', 'submarine_count'
    ])

    for account in accounts:
        for char in account.characters:
            fc_id = char.fc_id
            fc_info = account.fc_data.get(fc_id)
            fc_name = fc_info.name if fc_info and fc_info.name else f"FC-{fc_id}"

            writer.writerow([
                char.name,
                char.cid,
                char.world,
                fc_name,
                len(char.submarines)
            ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=characters_export.csv'}
    )


@export_bp.route('/submarines')
@login_required
def export_submarines():
    """Export Submarines data as CSV."""
    from app.services import get_fleet_manager

    fleet = get_fleet_manager()
    accounts = fleet.get_data(force_refresh=True)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'character_name', 'fc_name', 'submarine_name', 'level', 'build',
        'status', 'return_time', 'route_name'
    ])

    for account in accounts:
        for char in account.characters:
            fc_id = char.fc_id
            fc_info = account.fc_data.get(fc_id)
            fc_name = fc_info.name if fc_info and fc_info.name else f"FC-{fc_id}"

            for sub in char.submarines:
                # Build string from parts
                build = sub.build if hasattr(sub, 'build') and sub.build else ''

                # Determine status
                status = 'Unknown'
                if hasattr(sub, 'return_time') and sub.return_time:
                    if sub.return_time > datetime.utcnow():
                        status = 'Voyaging'
                    else:
                        status = 'Returned'
                elif hasattr(sub, 'status'):
                    status = sub.status

                # Return time
                return_time = ''
                if hasattr(sub, 'return_time') and sub.return_time:
                    return_time = sub.return_time.isoformat()

                # Route name
                route_name = ''
                if hasattr(sub, 'route_name') and sub.route_name:
                    route_name = sub.route_name
                elif hasattr(sub, 'route') and sub.route:
                    route_name = sub.route

                writer.writerow([
                    char.name,
                    fc_name,
                    sub.name,
                    sub.level if hasattr(sub, 'level') else '',
                    build,
                    status,
                    return_time,
                    route_name
                ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=submarines_export.csv'}
    )


@export_bp.route('/loot')
@login_required
def export_loot():
    """Export Voyage Loot data as CSV."""
    # Get date range from query parameters
    days = request.args.get('days', 30, type=int)
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    # Build query
    query = db.session.query(VoyageLoot).order_by(VoyageLoot.captured_at.desc())

    if start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(VoyageLoot.captured_at >= start_dt)
        except ValueError:
            pass

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(VoyageLoot.captured_at < end_dt)
        except ValueError:
            pass

    if not start_date and not end_date:
        # Default to last N days
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.filter(VoyageLoot.captured_at >= cutoff)

    loot_records = query.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'captured_at', 'character_name', 'fc_name', 'submarine_name',
        'route_name', 'sector_id', 'item_name_primary', 'count_primary',
        'hq_primary', 'item_name_additional', 'count_additional',
        'hq_additional', 'total_gil_value'
    ])

    for loot in loot_records:
        # Get items for this loot record
        items = VoyageLootItem.query.filter_by(voyage_loot_id=loot.id).all()

        if items:
            for item in items:
                writer.writerow([
                    loot.captured_at.isoformat() if loot.captured_at else '',
                    loot.character_name,
                    loot.fc_tag or '',
                    loot.submarine_name,
                    loot.route_name or '',
                    item.sector_id,
                    item.item_name_primary or '',
                    item.count_primary,
                    'Yes' if item.hq_primary else 'No',
                    item.item_name_additional or '',
                    item.count_additional,
                    'Yes' if item.hq_additional else 'No',
                    item.total_value
                ])
        else:
            # No items, write a single row with loot summary
            writer.writerow([
                loot.captured_at.isoformat() if loot.captured_at else '',
                loot.character_name,
                loot.fc_tag or '',
                loot.submarine_name,
                loot.route_name or '',
                '',
                '',
                '',
                '',
                '',
                '',
                '',
                loot.total_gil_value
            ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=loot_export.csv'}
    )
