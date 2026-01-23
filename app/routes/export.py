"""
Data export routes for downloading fleet data as CSV files.
"""
import csv
import io
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, Response, render_template, request, jsonify
from flask_login import login_required

from app import db
from app.models.voyage_loot import VoyageLoot, VoyageLootItem
from app.models.fc_housing import get_all_fc_housing
from app.models.app_settings import AppSettings
from app.models.tag import get_all_fc_tags_map, get_all_tags

export_bp = Blueprint('export', __name__)


# World -> Datacenter mapping
WORLD_TO_DATACENTER = {
    # NA - Aether
    'Adamantoise': 'Aether', 'Cactuar': 'Aether', 'Faerie': 'Aether', 'Gilgamesh': 'Aether',
    'Jenova': 'Aether', 'Midgardsormr': 'Aether', 'Sargatanas': 'Aether', 'Siren': 'Aether',
    # NA - Primal
    'Behemoth': 'Primal', 'Excalibur': 'Primal', 'Exodus': 'Primal', 'Famfrit': 'Primal',
    'Hyperion': 'Primal', 'Lamia': 'Primal', 'Leviathan': 'Primal', 'Ultros': 'Primal',
    # NA - Crystal
    'Balmung': 'Crystal', 'Brynhildr': 'Crystal', 'Coeurl': 'Crystal', 'Diabolos': 'Crystal',
    'Goblin': 'Crystal', 'Malboro': 'Crystal', 'Mateus': 'Crystal', 'Zalera': 'Crystal',
    # NA - Dynamis
    'Halicarnassus': 'Dynamis', 'Maduin': 'Dynamis', 'Marilith': 'Dynamis', 'Seraph': 'Dynamis',
    'Cuchulainn': 'Dynamis', 'Golem': 'Dynamis', 'Kraken': 'Dynamis', 'Rafflesia': 'Dynamis',
    # EU - Chaos
    'Cerberus': 'Chaos', 'Louisoix': 'Chaos', 'Moogle': 'Chaos', 'Omega': 'Chaos',
    'Phantom': 'Chaos', 'Ragnarok': 'Chaos', 'Sagittarius': 'Chaos', 'Spriggan': 'Chaos',
    # EU - Light
    'Alpha': 'Light', 'Lich': 'Light', 'Odin': 'Light', 'Phoenix': 'Light',
    'Raiden': 'Light', 'Shiva': 'Light', 'Twintania': 'Light', 'Zodiark': 'Light',
    # JP - Elemental
    'Aegis': 'Elemental', 'Atomos': 'Elemental', 'Carbuncle': 'Elemental', 'Garuda': 'Elemental',
    'Gungnir': 'Elemental', 'Kujata': 'Elemental', 'Tonberry': 'Elemental', 'Typhon': 'Elemental',
    # JP - Gaia
    'Alexander': 'Gaia', 'Bahamut': 'Gaia', 'Durandal': 'Gaia', 'Fenrir': 'Gaia',
    'Ifrit': 'Gaia', 'Ridill': 'Gaia', 'Tiamat': 'Gaia', 'Ultima': 'Gaia',
    # JP - Mana
    'Anima': 'Mana', 'Asura': 'Mana', 'Chocobo': 'Mana', 'Hades': 'Mana',
    'Ixion': 'Mana', 'Masamune': 'Mana', 'Pandaemonium': 'Mana', 'Titan': 'Mana',
    # JP - Meteor
    'Belias': 'Meteor', 'Mandragora': 'Meteor', 'Ramuh': 'Meteor', 'Shinryu': 'Meteor',
    'Unicorn': 'Meteor', 'Valefor': 'Meteor', 'Yojimbo': 'Meteor', 'Zeromus': 'Meteor',
    # OCE - Materia
    'Bismarck': 'Materia', 'Ravana': 'Materia', 'Sephirot': 'Materia', 'Sophia': 'Materia', 'Zurvan': 'Materia',
}

# District name abbreviations for Lifestream
DISTRICT_ABBREV = {
    'Mist': 'Mist',
    'The Lavender Beds': 'LB',
    'Lavender Beds': 'LB',
    'The Goblet': 'Gob',
    'Goblet': 'Gob',
    'Shirogane': 'Shiro',
    'Empyreum': 'Emp',
}


def get_datacenter(world: str) -> str:
    """Get datacenter name from world name."""
    return WORLD_TO_DATACENTER.get(world, 'Unknown')


def get_house_size(district: str, plot: int) -> str:
    """
    Get house size from Lumina database for the given district and plot.
    """
    if not district or not plot:
        return ''

    from app.services.lumina_service import get_house_size as lumina_get_house_size
    from app.models.lumina import HousingPlotSize

    # Ensure housing data is loaded - check we have all 300 plots (5 districts × 60 plots)
    total_count = HousingPlotSize.query.count()
    if total_count < 300:
        from app.services.lumina_service import lumina_service
        # Clear old incomplete data and reload
        HousingPlotSize.query.delete()
        db.session.commit()
        lumina_service.update_housing_plot_sizes(force=True)

    return lumina_get_house_size(district, plot)


def verify_export_token(token: str) -> bool:
    """Verify the export token matches the stored one."""
    stored_token = AppSettings.get('sheets_export_token')
    if not stored_token:
        return False
    return secrets.compare_digest(token, stored_token)


@export_bp.route('/sheets/token', methods=['POST'])
@login_required
def generate_sheets_token():
    """Generate a new token for Google Sheets API access."""
    token = secrets.token_urlsafe(32)
    AppSettings.set('sheets_export_token', token, 'Token for Google Sheets export API')
    return jsonify({'token': token})


@export_bp.route('/sheets/token', methods=['GET'])
@login_required
def get_sheets_token():
    """Get the current Google Sheets export token."""
    token = AppSettings.get('sheets_export_token')
    return jsonify({'token': token or None})


@export_bp.route('/api/sheets')
def sheets_export_api():
    """
    JSON API endpoint for Google Sheets to fetch FC data.
    Requires token authentication via query parameter.

    Returns:
        JSON with 'all' (all FCs) and 'by_tag' (FCs grouped by tag name)
    """
    token = request.args.get('token', '')
    if not token or not verify_export_token(token):
        return jsonify({'error': 'Invalid or missing token'}), 401

    from app.services import get_fleet_manager
    from app.models.fc_config import get_all_fc_notes

    fleet = get_fleet_manager()
    accounts = fleet.get_data(force_refresh=True)
    fc_housing = get_all_fc_housing()
    fc_tags_map = get_all_fc_tags_map()
    fc_notes_map = get_all_fc_notes()

    # Build FC data
    fc_data = {}
    for account in accounts:
        for char in account.characters:
            fc_id = char.fc_id
            fc_id_str = str(fc_id) if fc_id else 'unknown'

            if fc_id_str not in fc_data:
                fc_info = account.fc_data.get(fc_id)
                fc_name = fc_info.name if fc_info and fc_info.name else f"FC-{fc_id}"
                housing = fc_housing.get(fc_id_str)

                # Get unique routes from all submarines in this FC
                routes = set()

                fc_data[fc_id_str] = {
                    'fc_id': fc_id_str,
                    'fc_name': fc_name,
                    'characters': [],
                    'housing': housing,
                    'tags': fc_tags_map.get(fc_id_str, []),
                    'routes': routes,
                    'notes': fc_notes_map.get(fc_id_str, ''),
                }

            # Add character info
            fc_entry = fc_data[fc_id_str]

            # Collect routes from submarines
            for sub in char.submarines:
                route_name = ''
                if hasattr(sub, 'route_name') and sub.route_name:
                    route_name = sub.route_name
                elif hasattr(sub, 'route') and sub.route:
                    route_name = sub.route
                if route_name:
                    fc_entry['routes'].add(route_name)

            # Add character if not already added
            char_key = f"{char.name}@{char.world}"
            existing_chars = [c['key'] for c in fc_entry['characters']]
            if char_key not in existing_chars:
                fc_entry['characters'].append({
                    'key': char_key,
                    'name': char.name,
                    'world': char.world,
                    'datacenter': get_datacenter(char.world),
                })

    # Get list of known farming routes from RouteStats
    from app.models.lumina import RouteStats
    farming_routes = set(r.route_name for r in RouteStats.query.all() if r.gil_per_sub_day and r.gil_per_sub_day > 0)

    # Format output rows
    untagged_rows = []  # FCs with no tags go here
    by_tag = {}  # tag_name -> list of rows (tagged FCs only)

    for fc_id_str, fc in fc_data.items():
        housing = fc['housing']
        world = housing.world if housing else (fc['characters'][0]['world'] if fc['characters'] else '')
        datacenter = get_datacenter(world)
        district = housing.district if housing else ''
        ward = housing.ward if housing else None
        plot = housing.plot if housing else None

        # Get first character for the "Character @ World" field
        char_display = ''
        if fc['characters']:
            c = fc['characters'][0]
            char_display = f"{c['name']} @ {c['world']}"

        # Determine route - check if any are farming routes, otherwise LEVELING
        routes = fc['routes']
        route_display = 'LEVELING'
        if routes:
            # Check if any route is a known farming route
            farming_found = [r for r in routes if r in farming_routes]
            if farming_found:
                route_display = ', '.join(sorted(farming_found))
            # If no farming routes found, it's leveling

        # Get house size - try with and without "The " prefix
        house_size = get_house_size(district, plot) if district and plot else ''

        row = {
            'character': char_display,
            'fc_name': fc['fc_name'],
            'datacenter': datacenter,
            'world': world,
            'housing_area': district,
            'ward': ward or '',
            'plot': plot or '',
            'route': route_display,
            'house_size': house_size,
            'notes': fc.get('notes', ''),
        }

        # FCs with no tags go to untagged list, tagged FCs go to their tag sheets
        if not fc['tags']:
            untagged_rows.append(row)
        else:
            for tag in fc['tags']:
                tag_name = tag['name']
                if tag_name not in by_tag:
                    by_tag[tag_name] = []
                by_tag[tag_name].append(row)

    # Sort rows by FC name
    untagged_rows.sort(key=lambda r: r['fc_name'].lower())
    for tag_name in by_tag:
        by_tag[tag_name].sort(key=lambda r: r['fc_name'].lower())

    return jsonify({
        'untagged': untagged_rows,
        'by_tag': by_tag,
        'columns': [
            'character', 'fc_name', 'datacenter', 'world',
            'housing_area', 'ward', 'plot', 'route', 'house_size', 'notes'
        ],
        'generated_at': datetime.utcnow().isoformat() + 'Z'
    })


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
    from app.models.fc_config import get_all_fc_notes

    fleet = get_fleet_manager()
    accounts = fleet.get_data(force_refresh=True)
    fc_housing = get_all_fc_housing()
    fc_notes_map = get_all_fc_notes()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'fc_id', 'fc_name', 'holder_character', 'world',
        'district', 'ward', 'plot', 'submarine_count', 'notes'
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

            # Get notes
            notes = fc_notes_map.get(fc_id_str, '')

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
                sub_count,
                notes
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
