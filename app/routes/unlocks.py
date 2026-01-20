"""
Submarine Sector Unlocks routes - Flowchart visualization of sector unlock dependencies.
"""
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required

from app.services.unlock_service import unlock_service
from app.data.unlock_tree import MAP_NAMES

unlocks_bp = Blueprint('unlocks', __name__)


@unlocks_bp.route('/')
@login_required
def index():
    """Render the unlocks flowchart page."""
    # Get FC list for selector
    fcs = unlock_service.get_fc_list()

    # Get FC ID from query param, or default to first FC or 'all'
    requested_fc = request.args.get('fc_id')
    if requested_fc:
        # Validate the requested FC exists
        fc_ids = [fc["fc_id"] for fc in fcs]
        if requested_fc in fc_ids:
            default_fc = requested_fc
        else:
            default_fc = fcs[0]["fc_id"] if fcs else "all"
    else:
        default_fc = fcs[0]["fc_id"] if fcs else "all"

    # Get map summary for selected FC
    map_summary = unlock_service.get_map_summary(default_fc)

    return render_template(
        'unlocks.html',
        fcs=fcs,
        default_fc=default_fc,
        map_summary=map_summary,
        map_names=MAP_NAMES
    )


@unlocks_bp.route('/api/flowchart/<fc_id>/<int:map_id>')
@login_required
def get_flowchart(fc_id: str, map_id: int):
    """
    Get vis.js network data for a specific map and FC.

    Args:
        fc_id: FC ID or "all" for aggregate
        map_id: Map ID (1-7)

    Returns:
        JSON with nodes and edges for vis.js
    """
    if map_id < 1 or map_id > 7:
        return jsonify({"error": "Invalid map ID"}), 400

    unlocked = unlock_service.get_fc_unlock_status(fc_id)
    flowchart_data = unlock_service.build_flowchart_data(map_id, unlocked)

    return jsonify(flowchart_data)


@unlocks_bp.route('/api/summary')
@login_required
def get_summary():
    """
    Get unlock progress summary for all maps.

    Query params:
        fc_id: FC ID to filter by (default: "all")

    Returns:
        JSON with map progress data
    """
    fc_id = request.args.get('fc_id', 'all')
    summary = unlock_service.get_map_summary(fc_id)
    return jsonify(summary)


@unlocks_bp.route('/api/fcs')
@login_required
def get_fcs():
    """Get list of FCs for the selector dropdown."""
    fcs = unlock_service.get_fc_list()
    return jsonify(fcs)
