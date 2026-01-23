"""
FC Tag management routes.
"""
from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

from app import db
from app.models.tag import FCTag, FCTagAssignment, get_all_tags, get_all_fc_tags_map
from app.decorators import writable_required

tags_bp = Blueprint('tags', __name__)


@tags_bp.route('/')
@login_required
def index():
    """Tag management page."""
    from app.services import get_fleet_manager

    tags = get_all_tags()
    fc_tags_map = get_all_fc_tags_map()

    # Get FC list from fleet manager
    fleet = get_fleet_manager()
    data = fleet.get_dashboard_data()

    # Build FC list with character info for the management table
    fcs = []
    for fc in data.get('fc_summaries', []):
        fc_id = str(fc.get('fc_id', ''))
        chars = fc.get('characters', [])
        # Get first character name and world
        char_name = ''
        char_world = ''
        if chars:
            char_name = chars[0].get('name', '')
            char_world = chars[0].get('world', '')

        fcs.append({
            'fc_id': fc_id,
            'fc_name': fc.get('fc_name', 'Unknown'),
            'character': char_name,
            'world': char_world,
            'tags': fc_tags_map.get(fc_id, [])
        })

    # Sort by FC name
    fcs.sort(key=lambda x: x['fc_name'].lower())

    return render_template('tags.html', tags=tags, fcs=fcs)


@tags_bp.route('/list')
@login_required
def list_tags():
    """Get all tags as JSON."""
    tags = get_all_tags()
    return jsonify([t.to_dict() for t in tags])


@tags_bp.route('/create', methods=['POST'])
@login_required
@writable_required
def create_tag():
    """Create a new tag."""
    data = request.get_json() or request.form
    name = data.get('name', '').strip()
    color = data.get('color', 'secondary').strip()

    if not name:
        return jsonify({'success': False, 'message': 'Tag name is required'}), 400

    # Check for duplicate
    existing = FCTag.query.filter_by(name=name).first()
    if existing:
        return jsonify({'success': False, 'message': f'Tag "{name}" already exists'}), 400

    tag = FCTag(name=name, color=color)
    db.session.add(tag)
    db.session.commit()

    return jsonify({'success': True, 'tag': tag.to_dict()})


@tags_bp.route('/delete/<int:tag_id>', methods=['POST', 'DELETE'])
@login_required
@writable_required
def delete_tag(tag_id: int):
    """Delete a tag."""
    tag = FCTag.query.get(tag_id)
    if not tag:
        return jsonify({'success': False, 'message': 'Tag not found'}), 404

    db.session.delete(tag)
    db.session.commit()

    return jsonify({'success': True})


@tags_bp.route('/rename/<int:tag_id>', methods=['POST'])
@login_required
@writable_required
def rename_tag(tag_id: int):
    """Rename a tag."""
    tag = FCTag.query.get(tag_id)
    if not tag:
        return jsonify({'success': False, 'message': 'Tag not found'}), 404

    data = request.get_json() or request.form
    new_name = data.get('name', '').strip()

    if not new_name:
        return jsonify({'success': False, 'message': 'Tag name is required'}), 400

    # Check for duplicate (excluding current tag)
    existing = FCTag.query.filter(FCTag.name == new_name, FCTag.id != tag_id).first()
    if existing:
        return jsonify({'success': False, 'message': f'Tag "{new_name}" already exists'}), 400

    tag.name = new_name
    db.session.commit()

    return jsonify({'success': True, 'tag': tag.to_dict()})


@tags_bp.route('/assign', methods=['POST'])
@login_required
@writable_required
def assign_tag():
    """Assign a tag to an FC."""
    data = request.get_json() or request.form
    fc_id = str(data.get('fc_id', '')).strip()
    tag_id = data.get('tag_id')

    if not fc_id:
        return jsonify({'success': False, 'message': 'FC ID is required'}), 400
    if not tag_id:
        return jsonify({'success': False, 'message': 'Tag ID is required'}), 400

    # Check tag exists
    tag = FCTag.query.get(int(tag_id))
    if not tag:
        return jsonify({'success': False, 'message': 'Tag not found'}), 404

    # Check if already assigned
    existing = FCTagAssignment.query.filter_by(fc_id=fc_id, tag_id=int(tag_id)).first()
    if existing:
        return jsonify({'success': True, 'message': 'Already assigned'})

    assignment = FCTagAssignment(fc_id=fc_id, tag_id=int(tag_id))
    db.session.add(assignment)
    db.session.commit()

    return jsonify({'success': True})


@tags_bp.route('/unassign', methods=['POST', 'DELETE'])
@login_required
@writable_required
def unassign_tag():
    """Remove a tag from an FC."""
    data = request.get_json() or request.form
    fc_id = str(data.get('fc_id', '')).strip()
    tag_id = data.get('tag_id')

    if not fc_id or not tag_id:
        return jsonify({'success': False, 'message': 'FC ID and Tag ID are required'}), 400

    FCTagAssignment.query.filter_by(fc_id=fc_id, tag_id=int(tag_id)).delete()
    db.session.commit()

    return jsonify({'success': True})


@tags_bp.route('/fc/<fc_id>')
@login_required
def get_fc_tags(fc_id: str):
    """Get tags for a specific FC."""
    assignments = FCTagAssignment.query.filter_by(fc_id=fc_id).all()
    tags = [a.tag.to_dict() for a in assignments if a.tag]
    return jsonify(tags)


@tags_bp.route('/assignments')
@login_required
def get_assignments():
    """Get all FC tag assignments."""
    fc_tags_map = get_all_fc_tags_map()
    return jsonify(fc_tags_map)
