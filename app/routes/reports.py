"""Reports page routes — custom query builder and saved reports."""
import time
from flask import Blueprint, render_template, request, jsonify, Response, abort
from flask_login import login_required, current_user

from app import db
from app.models.saved_report import SavedReport
from app.services import get_fleet_manager
from app.services.report_engine import run_query, export_csv, get_schema, ParseError

reports_bp = Blueprint('reports', __name__)

# Simple rate limiting: user_id -> last_query_time
_rate_limit = {}


@reports_bp.route('/')
@login_required
def index():
    """Render the reports page."""
    return render_template('reports.html')


@reports_bp.route('/run', methods=['POST'])
@login_required
def run():
    """Execute a query and return results."""
    # Rate limit
    now = time.time()
    last = _rate_limit.get(current_user.id, 0)
    if now - last < 1.0:
        return jsonify({'error': 'Rate limited. Please wait 1 second between queries.'}), 429
    _rate_limit[current_user.id] = now

    data = request.get_json()
    if not data or 'query' not in data:
        return jsonify({'error': 'Missing query text'}), 400

    query_text = data['query'].strip()
    if not query_text:
        return jsonify({'error': 'Empty query'}), 400

    view_mode = data.get('view_mode', 'table')
    page = data.get('page', 1)

    try:
        fleet = get_fleet_manager()
        result = run_query(query_text, fleet_manager=fleet, view_mode=view_mode, page=page)
        return jsonify(result)
    except ParseError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Query execution error: {str(e)}'}), 500


@reports_bp.route('/schema')
@login_required
def schema():
    """Return the query schema for the visual builder."""
    return jsonify(get_schema())


@reports_bp.route('/export', methods=['POST'])
@login_required
def export():
    """Export query results as CSV."""
    data = request.get_json()
    if not data or 'query' not in data:
        return jsonify({'error': 'Missing query text'}), 400

    try:
        fleet = get_fleet_manager()
        csv_content = export_csv(data['query'], fleet_manager=fleet)
        return Response(
            csv_content,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=report.csv'},
        )
    except ParseError as e:
        return jsonify({'error': str(e)}), 400


@reports_bp.route('/save', methods=['POST'])
@login_required
def save():
    """Save a new report."""
    data = request.get_json()
    if not data or 'name' not in data or 'query' not in data:
        return jsonify({'error': 'Missing name or query'}), 400

    report = SavedReport(
        user_id=current_user.id,
        name=data['name'],
        query_text=data['query'],
        display_config=data.get('display_config', {}),
    )
    db.session.add(report)
    db.session.commit()
    return jsonify(report.to_dict()), 201


@reports_bp.route('/saved')
@login_required
def list_saved():
    """List current user's saved reports."""
    reports = SavedReport.query.filter_by(user_id=current_user.id)\
        .order_by(SavedReport.updated_at.desc()).all()
    return jsonify([r.to_dict() for r in reports])


@reports_bp.route('/saved/<int:report_id>', methods=['PUT'])
@login_required
def update_saved(report_id):
    """Update a saved report."""
    report = SavedReport.query.get_or_404(report_id)
    if report.user_id != current_user.id:
        abort(403)

    data = request.get_json()
    if 'name' in data:
        report.name = data['name']
    if 'query' in data:
        report.query_text = data['query']
    if 'display_config' in data:
        report.display_config = data['display_config']

    db.session.commit()
    return jsonify(report.to_dict())


@reports_bp.route('/saved/<int:report_id>', methods=['DELETE'])
@login_required
def delete_saved(report_id):
    """Delete a saved report."""
    report = SavedReport.query.get_or_404(report_id)
    if report.user_id != current_user.id:
        abort(403)

    db.session.delete(report)
    db.session.commit()
    return jsonify({'ok': True})
