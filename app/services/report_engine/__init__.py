"""
Armada Report Engine — custom DSL for querying fleet data.

Usage:
    from app.services.report_engine import run_query, get_schema, ParseError
"""
import concurrent.futures

from app.services.report_engine.parser import parse, ParseError
from app.services.report_engine.schema import (
    get_schema_for_frontend, ENTITY_FIELDS, EntitySource,
)
from app.services.report_engine.executor import execute_live, execute_db
from app.services.report_engine.formatter import format_table, format_summary, format_csv


class QueryTimeout(Exception):
    pass


def _execute_with_timeout(fn, timeout=10):
    """Run a function with a timeout. Raises QueryTimeout if exceeded."""
    from flask import current_app

    app = current_app._get_current_object()

    def run_with_context():
        with app.app_context():
            return fn()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_with_context)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise QueryTimeout('Query timed out after 10 seconds')


def run_query(query_text, fleet_manager=None, view_mode='table', page=1, per_page=100):
    """Parse and execute a report query.

    Args:
        query_text: DSL query string
        fleet_manager: FleetManager instance (needed for live entities)
        view_mode: 'table' or 'summary'
        page: Page number for table view
        per_page: Results per page (max 100)

    Returns: dict with results in requested format
    Raises: ParseError for invalid queries, QueryTimeout if query takes too long
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
        all_subs = dashboard.get('submarines', [])
        try:
            results = _execute_with_timeout(lambda: execute_live(ast, fc_summaries, all_subs))
        except QueryTimeout as e:
            return {'error': str(e), 'rows': [], 'total': 0}
    else:
        try:
            results = _execute_with_timeout(lambda: execute_db(ast))
        except QueryTimeout as e:
            return {'error': str(e), 'rows': [], 'total': 0}

    per_page = min(max(per_page, 10), 100)

    if view_mode == 'summary':
        return format_summary(results, entity, group_by=ast.get('group_by'))
    else:
        return format_table(results, entity, page=page, per_page=per_page, select=ast.get('select'))


def export_csv(query_text, fleet_manager=None):
    """Parse, execute, and format results as CSV.

    Returns: CSV string
    Raises: ParseError for invalid queries, QueryTimeout if query takes too long
    """
    ast = parse(query_text)
    entity = ast['entity']
    entity_def = ENTITY_FIELDS[entity]

    if entity_def['source'] == EntitySource.LIVE:
        if fleet_manager is None:
            return ''
        dashboard = fleet_manager.get_dashboard_data()
        results = _execute_with_timeout(
            lambda: execute_live(ast, dashboard.get('fc_summaries', []),
                                 dashboard.get('submarines', []))
        )
    else:
        results = _execute_with_timeout(lambda: execute_db(ast))

    return format_csv(results, entity)


def get_schema():
    """Return the schema dict for the frontend visual builder."""
    return get_schema_for_frontend()


__all__ = ['run_query', 'export_csv', 'get_schema', 'ParseError', 'QueryTimeout']
