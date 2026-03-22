"""
Armada Report Engine — custom DSL for querying fleet data.

Usage:
    from app.services.report_engine import run_query, get_schema, ParseError
"""
from app.services.report_engine.parser import parse, ParseError
from app.services.report_engine.schema import (
    get_schema_for_frontend, ENTITY_FIELDS, EntitySource,
)
from app.services.report_engine.executor import execute_live, execute_db
from app.services.report_engine.formatter import format_table, format_summary, format_csv


def run_query(query_text, fleet_manager=None, view_mode='table', page=1, per_page=100):
    """Parse and execute a report query.

    Args:
        query_text: DSL query string
        fleet_manager: FleetManager instance (needed for live entities)
        view_mode: 'table' or 'summary'
        page: Page number for table view
        per_page: Results per page (max 100)

    Returns: dict with results in requested format
    Raises: ParseError for invalid queries
    """
    ast = parse(query_text)
    entity = ast['entity']
    entity_def = ENTITY_FIELDS[entity]

    if entity_def['source'] == EntitySource.LIVE:
        if fleet_manager is None:
            return {
                'error': None,
                'columns': [],
                'rows': [],
                'total': 0,
                'message': 'No fleet data available. Connect a plugin to see live data.',
            }
        dashboard = fleet_manager.get_dashboard_data()
        fc_summaries = dashboard.get('fc_summaries', [])
        all_subs = dashboard.get('all_submarines', [])
        results = execute_live(ast, fc_summaries, all_subs)
    else:
        results = execute_db(ast)

    per_page = min(max(per_page, 10), 100)

    if view_mode == 'summary':
        return format_summary(results, entity, group_by=ast.get('group_by'))
    else:
        return format_table(results, entity, page=page, per_page=per_page)


def export_csv(query_text, fleet_manager=None):
    """Parse, execute, and format results as CSV.

    Returns: CSV string
    Raises: ParseError for invalid queries
    """
    ast = parse(query_text)
    entity = ast['entity']
    entity_def = ENTITY_FIELDS[entity]

    if entity_def['source'] == EntitySource.LIVE:
        if fleet_manager is None:
            return ''
        dashboard = fleet_manager.get_dashboard_data()
        results = execute_live(ast, dashboard.get('fc_summaries', []),
                               dashboard.get('all_submarines', []))
    else:
        results = execute_db(ast)

    return format_csv(results, entity)


def get_schema():
    """Return the schema dict for the frontend visual builder."""
    return get_schema_for_frontend()


__all__ = ['run_query', 'export_csv', 'get_schema', 'ParseError']
