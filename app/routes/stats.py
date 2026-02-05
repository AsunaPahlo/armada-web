"""
Statistics page routes
"""
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy import func

from app import db
from app.models.voyage import Voyage
from app.services.stats_tracker import StatsTracker
from app.services import get_fleet_manager

stats_bp = Blueprint('stats', __name__)

ALL_REGIONS = ['NA', 'EU', 'JP', 'OCE']


def resolve_filters(req):
    """Parse filter query params and resolve to FC ID sets and world sets."""
    from app.models.tag import FCTagAssignment, FCTag
    from app.services.submarine_data import get_worlds_for_region

    excluded_fc_ids = set()
    allowed_worlds = None

    # Parse exclude_tags param (comma-separated tag IDs)
    exclude_tags_str = req.args.get('exclude_tags', '')
    if exclude_tags_str:
        tag_ids = [int(t) for t in exclude_tags_str.split(',') if t.strip().isdigit()]
        if tag_ids:
            assignments = FCTagAssignment.query.filter(
                FCTagAssignment.tag_id.in_(tag_ids)
            ).all()
            excluded_fc_ids = {a.fc_id for a in assignments}

    # Parse regions param (comma-separated region codes)
    regions_str = req.args.get('regions', '')
    if regions_str:
        selected_regions = [r.strip().upper() for r in regions_str.split(',') if r.strip()]
        if selected_regions and set(selected_regions) != set(ALL_REGIONS):
            allowed_worlds = set()
            for region in selected_regions:
                if region in ALL_REGIONS:
                    allowed_worlds.update(get_worlds_for_region(region))

    # Get all tags for template rendering
    all_tags = FCTag.query.order_by(FCTag.name).all()
    exclude_tag_ids = [int(t) for t in exclude_tags_str.split(',') if t.strip().isdigit()] if exclude_tags_str else []
    active_regions = [r.strip().upper() for r in regions_str.split(',') if r.strip()] if regions_str else list(ALL_REGIONS)

    return excluded_fc_ids, allowed_worlds, all_tags, exclude_tag_ids, active_regions


def get_voyage_chart_data(days: int, excluded_fc_ids=None, allowed_worlds=None) -> dict:
    """Get voyage data aggregated by date for charts."""
    now = datetime.utcnow()

    # Get hidden FC IDs to exclude
    try:
        from app.models.fc_config import get_hidden_fc_ids
        hidden_fc_ids = get_hidden_fc_ids()
    except Exception:
        hidden_fc_ids = set()

    # Merge filter-excluded FCs with hidden FCs
    all_excluded = hidden_fc_ids | (excluded_fc_ids or set())

    # Query voyages (days=0 means all history)
    query = Voyage.query
    if all_excluded:
        query = query.filter(~Voyage.fc_id.in_(all_excluded))
    if allowed_worlds is not None:
        query = query.filter(Voyage.world.in_(allowed_worlds))
    if days > 0:
        cutoff = now - timedelta(days=days)
        query = query.filter(Voyage.return_time >= cutoff)
    voyages = query.all()

    # Aggregate by date
    by_date = defaultdict(lambda: {'total': 0, 'returned': 0, 'collected': 0})
    by_fc = defaultdict(lambda: {'total': 0, 'returned': 0, 'collected': 0, 'name': ''})
    by_route = defaultdict(int)
    by_hour = defaultdict(int)
    by_submarine = defaultdict(lambda: {'count': 0, 'name': '', 'fc': ''})

    for v in voyages:
        is_returned = v.return_time <= now

        date_str = v.return_time.strftime('%Y-%m-%d')
        by_date[date_str]['total'] += 1
        if is_returned:
            by_date[date_str]['returned'] += 1
        if v.was_collected:
            by_date[date_str]['collected'] += 1

        fc_key = v.fc_id or 'unknown'
        by_fc[fc_key]['total'] += 1
        by_fc[fc_key]['name'] = v.fc_name or 'Unknown'
        if is_returned:
            by_fc[fc_key]['returned'] += 1
        if v.was_collected:
            by_fc[fc_key]['collected'] += 1

        # Route tracking (only count returned voyages)
        if v.route_name and is_returned:
            by_route[v.route_name] += 1

        # Hour tracking (when voyages return) - only returned voyages
        if is_returned:
            hour = v.return_time.hour
            by_hour[hour] += 1

        # Submarine tracking
        sub_key = f"{v.character_cid}_{v.submarine_name}"
        by_submarine[sub_key]['count'] += 1
        by_submarine[sub_key]['name'] = v.submarine_name
        by_submarine[sub_key]['fc'] = v.fc_name or 'Unknown'

    # Convert to sorted lists
    dates_data = [
        {'date': d, 'total': v['total'], 'returned': v['returned'], 'collected': v['collected']}
        for d, v in sorted(by_date.items())
    ]

    fc_data = [
        {'fc_id': fc_id, 'fc_name': v['name'], 'total': v['total'], 'returned': v['returned'], 'collected': v['collected']}
        for fc_id, v in sorted(by_fc.items(), key=lambda x: x[1]['total'], reverse=True)
    ]

    route_data = [
        {'route': route, 'count': count}
        for route, count in sorted(by_route.items(), key=lambda x: x[1], reverse=True)
    ][:10]  # Top 10 routes

    hour_data = [{'hour': h, 'count': by_hour.get(h, 0)} for h in range(24)]

    top_subs = [
        {'name': v['name'], 'fc': v['fc'], 'count': v['count']}
        for v in sorted(by_submarine.values(), key=lambda x: x['count'], reverse=True)
    ][:10]  # Top 10 submarines

    return {
        'by_date': dates_data,
        'by_fc': fc_data[:15],
        'by_route': route_data,
        'by_hour': hour_data,
        'top_submarines': top_subs
    }


def get_supply_chart_data(fc_summaries: list) -> dict:
    """Get current supply levels per FC for charts."""
    supply_data = [
        {
            'fc_name': fc.get('fc_name', 'Unknown'),
            'ceruleum': fc.get('ceruleum', 0),
            'repair_kits': fc.get('repair_kits', 0),
            'days_until_restock': fc.get('days_until_restock')
        }
        for fc in fc_summaries
    ]

    # Sort by days until restock (lowest first, None at end)
    supply_data.sort(key=lambda x: x['days_until_restock'] if x['days_until_restock'] is not None else 9999)

    return supply_data[:15]  # Top 15 FCs needing restock


def get_fleet_chart_data(fc_summaries: list) -> dict:
    """Get fleet composition data for charts."""
    # Level distribution
    level_ranges = {'1-20': 0, '21-40': 0, '41-60': 0, '61-80': 0, '81-100': 0, '100+': 0}
    build_counts = defaultdict(int)

    for fc in fc_summaries:
        for sub in fc.get('submarines', []):
            level = sub.get('level', 0)
            if level <= 20:
                level_ranges['1-20'] += 1
            elif level <= 40:
                level_ranges['21-40'] += 1
            elif level <= 60:
                level_ranges['41-60'] += 1
            elif level <= 80:
                level_ranges['61-80'] += 1
            elif level <= 100:
                level_ranges['81-100'] += 1
            else:
                level_ranges['100+'] += 1

            build = sub.get('build')
            if build:
                build_counts[build] += 1

    # Top builds
    top_builds = [
        {'build': build, 'count': count}
        for build, count in sorted(build_counts.items(), key=lambda x: x[1], reverse=True)
    ][:8]

    return {
        'level_distribution': level_ranges,
        'top_builds': top_builds
    }


@stats_bp.route('/')
@login_required
def index():
    """Statistics overview page."""
    tracker = StatsTracker()

    days = request.args.get('days', 30, type=int)
    # days=0 means all history, otherwise clamp to 1-365
    if days != 0:
        days = min(max(days, 1), 365)

    # Resolve tag/region filters
    excluded_fc_ids, allowed_worlds, all_tags, exclude_tag_ids, active_regions = resolve_filters(request)

    summary = tracker.calculate_summary_stats(days=days, excluded_fc_ids=excluded_fc_ids, allowed_worlds=allowed_worlds)
    daily = tracker.get_daily_stats(days=days)

    # Get chart data
    chart_data = get_voyage_chart_data(days, excluded_fc_ids=excluded_fc_ids, allowed_worlds=allowed_worlds)

    # Get fleet data for region counts and supply info
    fleet = get_fleet_manager()
    fleet_data = fleet.get_dashboard_data()
    region_counts = fleet_data['summary'].get('region_counts', {})

    # Filter fc_summaries by excluded FCs and allowed worlds
    fc_summaries = fleet_data.get('fc_summaries', [])
    if excluded_fc_ids:
        fc_summaries = [fc for fc in fc_summaries if fc.get('fc_id') not in excluded_fc_ids]
    if allowed_worlds is not None:
        fc_summaries = [fc for fc in fc_summaries if fc.get('world') in allowed_worlds]

    # Recompute fleet summary from filtered fc_summaries
    filtered_summary = dict(fleet_data['summary'])
    filtered_summary['fc_count'] = len(fc_summaries)
    filtered_total_subs = sum(fc.get('total_subs', 0) for fc in fc_summaries)
    filtered_leveling = sum(fc.get('leveling_subs', 0) for fc in fc_summaries)
    filtered_summary['total_subs'] = filtered_total_subs
    filtered_summary['total_gil_per_day'] = sum(fc.get('gil_per_day', 0) for fc in fc_summaries)
    filtered_summary['farming_subs'] = filtered_total_subs - filtered_leveling
    filtered_summary['leveling_subs'] = filtered_leveling

    # Get supply chart data
    supply_data = get_supply_chart_data(fc_summaries)

    # Get fleet composition data
    fleet_chart_data = get_fleet_chart_data(fc_summaries)

    return render_template('stats.html',
                           summary=summary,
                           daily_stats=daily,
                           region_counts=region_counts,
                           fleet_summary=filtered_summary,
                           chart_data=chart_data,
                           supply_data=supply_data,
                           fleet_chart_data=fleet_chart_data,
                           days=days,
                           all_tags=all_tags,
                           exclude_tag_ids=exclude_tag_ids,
                           active_regions=active_regions,
                           all_regions=ALL_REGIONS)


@stats_bp.route('/voyages')
@login_required
def voyages():
    """Voyage history page."""
    tracker = StatsTracker()

    days = request.args.get('days', 30, type=int)
    # days=0 means all history, otherwise clamp to 1-365
    if days != 0:
        days = min(max(days, 1), 365)

    # Get first page of voyages with pagination info
    result = tracker.get_voyage_history(days=days, page=1, per_page=50)

    return render_template('voyages.html',
                           voyages=result['voyages'],
                           voyage_pagination={
                               'total': result['total'],
                               'page': result['page'],
                               'per_page': result['per_page'],
                               'pages': result['pages']
                           },
                           days=days)


@stats_bp.route('/api/voyage-history')
@login_required
def api_voyage_history():
    """API endpoint for paginated voyage history."""
    tracker = StatsTracker()

    days = request.args.get('days', 30, type=int)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    sort_by = request.args.get('sort_by', 'return_time', type=str)
    sort_dir = request.args.get('sort_dir', 'desc', type=str)
    account = request.args.get('account', None, type=str)
    fc_id = request.args.get('fc_id', None, type=int)

    # days=0 means all history, otherwise clamp to 1-365
    if days != 0:
        days = min(max(days, 1), 365)

    # Clamp per_page
    per_page = min(max(per_page, 10), 100)

    result = tracker.get_voyage_history(
        days=days,
        account_name=account,
        fc_id=fc_id,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_dir=sort_dir
    )

    return jsonify(result)


@stats_bp.route('/loot')
@login_required
def loot():
    """Loot statistics page."""
    from app.services.loot_tracker import loot_tracker

    days = request.args.get('days', 30, type=int)
    # days=0 means all history, otherwise clamp to 1-365
    if days != 0:
        days = min(max(days, 1), 365)

    summary = loot_tracker.get_loot_summary(days=days)
    # Get first page of history with pagination info
    history_data = loot_tracker.get_loot_history(days=days, page=1, per_page=50)

    # Calculate total salvage value across all characters
    total_salvage_value = 0
    try:
        fleet = get_fleet_manager()
        accounts = fleet.get_data(force_refresh=False)
        for account in accounts:
            for char in account.characters:
                total_salvage_value += getattr(char, 'salvage_value', 0)
    except Exception:
        pass  # If fleet data unavailable, leave as 0

    summary['total_salvage_value'] = total_salvage_value

    return render_template('loot.html',
                           summary=summary,
                           loot_history=history_data['items'],
                           loot_pagination={
                               'total': history_data['total'],
                               'page': history_data['page'],
                               'per_page': history_data['per_page'],
                               'pages': history_data['pages']
                           },
                           days=days)


@stats_bp.route('/api/loot-history')
@login_required
def api_loot_history():
    """API endpoint for paginated loot history."""
    from app.services.loot_tracker import loot_tracker

    days = request.args.get('days', 30, type=int)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    sort_by = request.args.get('sort_by', 'captured_at', type=str)
    sort_dir = request.args.get('sort_dir', 'desc', type=str)
    fc_id = request.args.get('fc_id', None, type=str)
    submarine = request.args.get('submarine', None, type=str)

    # days=0 means all history, otherwise clamp to 1-365
    if days != 0:
        days = min(max(days, 1), 365)

    # Clamp per_page
    per_page = min(max(per_page, 10), 100)

    history_data = loot_tracker.get_loot_history(
        days=days,
        fc_id=fc_id,
        submarine_name=submarine,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_dir=sort_dir
    )

    return jsonify(history_data)


@stats_bp.route('/api/top-routes')
@login_required
def api_top_routes():
    """API endpoint for top routes by gil/24h."""
    from app.services.loot_tracker import loot_tracker

    days = request.args.get('days', 30, type=int)
    known_only = request.args.get('known_only', 'true', type=str).lower() == 'true'

    # days=0 means all history, otherwise clamp to 1-365
    if days != 0:
        days = min(max(days, 1), 365)

    routes = loot_tracker.get_top_routes(days=days, known_only=known_only)

    return jsonify({'routes': routes, 'known_only': known_only})


@stats_bp.route('/loot/<int:loot_id>')
@login_required
def loot_details(loot_id: int):
    """Loot details page for a specific voyage."""
    from app.services.loot_tracker import loot_tracker

    details = loot_tracker.get_loot_details(loot_id)
    if not details:
        return render_template('errors/404.html'), 404

    return render_template('loot_details.html', loot=details)


@stats_bp.route('/profits')
@login_required
def profits():
    """Profit analysis and projections page."""
    from app.services.profit_tracker import profit_tracker

    days = request.args.get('days', 30, type=int)
    projection_days = request.args.get('projection', 30, type=int)
    tz_offset = request.args.get('tz', 0, type=int)  # Timezone offset in minutes

    # Clamp values
    if days != 0:
        days = min(max(days, 1), 365)
    projection_days = min(max(projection_days, 7), 90)
    # Clamp timezone offset to valid range (-720 to +840 minutes)
    tz_offset = max(-720, min(840, tz_offset))

    # Resolve tag/region filters
    excluded_fc_ids, allowed_worlds, all_tags, exclude_tag_ids, active_regions = resolve_filters(request)

    return render_template('profits.html',
                           days=days,
                           projection_days=projection_days,
                           all_tags=all_tags,
                           exclude_tag_ids=exclude_tag_ids,
                           active_regions=active_regions,
                           all_regions=ALL_REGIONS)


@stats_bp.route('/profits/data')
@login_required
def profits_data():
    """JSON API endpoint for profit data (used by AJAX on page load)."""
    from app.services.profit_tracker import profit_tracker

    days = request.args.get('days', 30, type=int)
    projection_days = request.args.get('projection', 30, type=int)
    tz_offset = request.args.get('tz', 0, type=int)  # Timezone offset in minutes

    # Clamp values
    if days != 0:
        days = min(max(days, 1), 365)
    projection_days = min(max(projection_days, 7), 90)
    # Clamp timezone offset to valid range (-720 to +840 minutes)
    tz_offset = max(-720, min(840, tz_offset))

    # Resolve tag/region filters
    excluded_fc_ids, allowed_worlds, _, _, _ = resolve_filters(request)

    profit_data = profit_tracker.get_profit_summary(
        days=days,
        projection_days=projection_days,
        tz_offset_minutes=tz_offset,
        excluded_fc_ids=excluded_fc_ids,
        allowed_worlds=allowed_worlds
    )

    return jsonify(profit_data)


@stats_bp.route('/profits/settings', methods=['GET', 'POST'])
@login_required
def profit_settings():
    """Configure material costs for profit calculations."""
    from app.models.app_settings import AppSettings

    if request.method == 'POST':
        # Update settings
        ceruleum_price = request.form.get('ceruleum_price', type=int)
        kit_price = request.form.get('kit_price', type=int)

        if ceruleum_price is not None:
            AppSettings.set('ceruleum_price_per_stack', ceruleum_price)
        if kit_price is not None:
            AppSettings.set('repair_kit_price_per_stack', kit_price)

        flash('Material costs updated successfully', 'success')
        return redirect(url_for('stats.profits'))

    # GET - show current settings
    settings = AppSettings.get_all()
    return render_template('profit_settings.html', settings=settings)


@stats_bp.route('/rebuild-daily-stats', methods=['POST'])
@login_required
def rebuild_daily_stats():
    """Rebuild daily stats from raw voyage/loot data (admin only)."""
    is_ajax = request.headers.get('Content-Type') == 'application/json' or request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    try:
        from app.models.daily_stats import DailyStats
        count = DailyStats.rebuild_from_raw_data()

        if is_ajax:
            return jsonify({'success': True, 'message': f'Daily stats rebuilt successfully. Created {count} records.', 'count': count})

        flash(f'Daily stats rebuilt successfully. Created {count} records.', 'success')
    except Exception as e:
        import traceback
        traceback.print_exc()

        if is_ajax:
            return jsonify({'success': False, 'message': f'Error rebuilding daily stats: {e}'}), 500

        flash(f'Error rebuilding daily stats: {e}', 'error')

    return redirect(url_for('stats.index'))


@stats_bp.route('/fc/<fc_id>')
@login_required
def fc_detail(fc_id):
    """FC detail page with leveling estimates."""
    from app.models.app_settings import AppSettings
    from app.models.fc_housing import get_fc_housing
    from app.models.fc_config import FCConfig
    from app.services.submarine_data import get_inventory_parts_with_details

    target_level = AppSettings.get_int('target_submarine_level', 85)

    # Get FC notes
    fc_config = FCConfig.query.filter_by(fc_id=str(fc_id)).first()
    fc_notes = fc_config.notes if fc_config else ''

    # Get fleet data
    fleet = get_fleet_manager()
    accounts = fleet.get_data(force_refresh=False)

    # Find FC info and submarines
    fc_info = None
    fc_submarines = []
    fc_characters = []
    fc_world = ''

    # Aggregate inventory parts and dive credits across all characters in this FC
    fc_inventory_parts = {}
    fc_dive_credits = 0
    fc_unlocked_slots = 0

    for account in accounts:
        # Check FC data for name
        for fid, info in account.fc_data.items():
            if str(fid) == str(fc_id):
                fc_info = info
                break

        # Collect submarines and characters from this FC
        for char in account.characters:
            if str(char.fc_id) == str(fc_id):
                fc_world = char.world
                fc_characters.append({
                    'name': char.name,
                    'world': char.world,
                    'ceruleum': char.ceruleum,
                    'repair_kits': char.repair_kits,
                    'gil': char.gil,
                    'salvage_value': getattr(char, 'salvage_value', 0),
                    'dive_credits': getattr(char, 'dive_credits', 0),
                    'free_inventory_slots': getattr(char, 'free_inventory_slots', 0),
                    'unlocked_sectors': getattr(char, 'unlocked_sectors', []),
                    'inventory_parts': getattr(char, 'inventory_parts', {})
                })
                fc_submarines.extend(char.submarines)

                # Aggregate dive credits for the FC
                fc_dive_credits += getattr(char, 'dive_credits', 0)

                # Track max unlocked slots (all chars in same FC share slots)
                fc_unlocked_slots = max(fc_unlocked_slots, getattr(char, 'num_sub_slots', 0))

                # Aggregate inventory parts for the FC
                char_parts = getattr(char, 'inventory_parts', {})
                for item_id, count in char_parts.items():
                    item_id = int(item_id)
                    fc_inventory_parts[item_id] = fc_inventory_parts.get(item_id, 0) + count

    fc_name = fc_info.name if fc_info else f'FC-{fc_id}'

    # Get FC housing address
    fc_housing = get_fc_housing(fc_id)
    fc_address = fc_housing.address if fc_housing else None
    fc_house_size = fc_housing.house_size if fc_housing else None

    # Convert inventory parts to detailed list with icons
    inventory_parts_list = get_inventory_parts_with_details(fc_inventory_parts)

    return render_template('fc_detail.html',
                           fc_id=fc_id,
                           fc_name=fc_name,
                           fc_world=fc_world,
                           fc_address=fc_address,
                           fc_house_size=fc_house_size,
                           fc_characters=fc_characters,
                           fc_notes=fc_notes,
                           target_level=target_level,
                           total_subs=len(fc_submarines),
                           fc_dive_credits=fc_dive_credits,
                           fc_unlocked_slots=fc_unlocked_slots,
                           inventory_parts=inventory_parts_list)


@stats_bp.route('/fc/<fc_id>/leveling')
@login_required
def fc_leveling_data(fc_id):
    """JSON API endpoint for FC leveling estimates."""
    from app.models.app_settings import AppSettings
    from app.services.leveling_estimator import leveling_estimator

    target_level = request.args.get('target', 90, type=int)
    target_level = max(1, min(125, target_level))

    # Get fleet data
    fleet = get_fleet_manager()
    accounts = fleet.get_data(force_refresh=False)

    # Find FC submarines and dive credits
    fc_info = None
    fc_submarines = []
    fc_world = ''
    fc_dive_credits = 0
    fc_unlocked_slots = 0

    for account in accounts:
        # Check FC data for name
        for fid, info in account.fc_data.items():
            if str(fid) == str(fc_id):
                fc_info = info
                break

        # Collect submarines from this FC
        for char in account.characters:
            if str(char.fc_id) == str(fc_id):
                fc_world = char.world
                fc_submarines.extend(char.submarines)
                fc_dive_credits += getattr(char, 'dive_credits', 0)
                fc_unlocked_slots = max(fc_unlocked_slots, getattr(char, 'num_sub_slots', 0))

    fc_name = fc_info.name if fc_info else f'FC-{fc_id}'

    # Calculate leveling estimates
    estimate = leveling_estimator.estimate_fc_leveling(
        fc_subs=fc_submarines,
        target_level=target_level,
        fc_id=str(fc_id),
        fc_name=fc_name,
        world=fc_world
    )

    # Calculate dive credit requirements for each slot
    # Cost: 1 for slot 1, 3 for slot 2, 5 for slot 3, 7 for slot 4
    slot_costs = [1, 3, 5, 7]  # Cost to unlock each slot
    cumulative_costs = [1, 4, 9, 16]  # Cumulative cost for 1, 2, 3, 4 slots

    return jsonify({
        'target_level': target_level,
        'estimate': estimate,
        'dive_credits': fc_dive_credits,
        'unlocked_slots': fc_unlocked_slots,
        'slot_costs': slot_costs,
        'cumulative_costs': cumulative_costs
    })


@stats_bp.route('/fc/<fc_id>/settings', methods=['POST'])
@login_required
def fc_leveling_settings(fc_id):
    """Update target level setting from FC detail page."""
    from app.models.app_settings import AppSettings

    target_level = request.form.get('target_level', type=int)
    if target_level is not None:
        target_level = max(1, min(125, target_level))
        AppSettings.set('target_submarine_level', target_level)
        flash(f'Target level updated to {target_level}', 'success')

    return redirect(url_for('stats.fc_detail', fc_id=fc_id))


@stats_bp.route('/fc/<fc_id>/activity')
@login_required
def fc_activity(fc_id):
    """API endpoint for FC activity log with pagination."""
    from app.models.activity_log import ActivityLog

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    activity_type = request.args.get('type', None, type=str)

    # Clamp per_page
    per_page = min(max(per_page, 10), 100)

    # Build filter for activity types
    activity_types = None
    if activity_type:
        activity_types = [activity_type]

    pagination = ActivityLog.get_fc_activity(
        fc_id=str(fc_id),
        page=page,
        per_page=per_page,
        activity_types=activity_types
    )

    return jsonify({
        'activities': [a.to_dict() for a in pagination.items],
        'page': pagination.page,
        'pages': pagination.pages,
        'per_page': per_page,
        'total': pagination.total,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev
    })


@stats_bp.route('/fc/<fc_id>/notes', methods=['POST'])
@login_required
def fc_notes_update(fc_id):
    """Update notes for an FC."""
    from app.models.fc_config import update_fc_config
    from flask_login import current_user

    # Check if user has write permission
    if hasattr(current_user, 'is_readonly') and current_user.is_readonly:
        return jsonify({'success': False, 'message': 'Read-only users cannot edit notes'}), 403

    data = request.get_json() or {}
    notes = data.get('notes', '').strip()

    # Allow empty notes (to clear)
    if notes == '':
        notes = None

    try:
        update_fc_config(str(fc_id), notes=notes)
        return jsonify({'success': True, 'notes': notes or ''})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
