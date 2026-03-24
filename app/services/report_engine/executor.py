"""Executor for the Armada report query engine.

Evaluates an AST against live FleetManager data (fcs, subs)
or SQLAlchemy DB models (voyages, loot, activity).
"""
from datetime import datetime

from sqlalchemy import and_, or_

from app.services.report_engine.schema import (
    ENTITY_FIELDS, CHILD_ENTITY_FIELDS, get_field_info, FieldType,
)


# ---------------------------------------------------------------------------
# Live entity executor (fcs, subs)
# ---------------------------------------------------------------------------

def _resolve_house_size(fc_id):
    """Look up house size for an FC from FCHousing model."""
    if not fc_id:
        return None
    try:
        from app.models.fc_housing import FCHousing
        housing = FCHousing.query.filter_by(fc_id=str(fc_id)).first()
        return housing.house_size if housing else None
    except Exception:
        return None


def _normalize_tags(val):
    """Normalize tags from tag dicts to string list for comparison."""
    if isinstance(val, list) and val and isinstance(val[0], dict):
        return [t.get('name', '') for t in val]
    return val


def _apply_condition(record, source_key, operator, value):
    """Test whether a single record satisfies a condition.

    Args:
        record: dict of field values
        source_key: key to look up in record
        operator: comparison operator string
        value: comparison value

    Returns: True if condition is satisfied
    """
    actual = record.get(source_key)

    # Normalize tag dicts to string lists for comparison
    actual = _normalize_tags(actual)

    if operator == 'IS EMPTY':
        if isinstance(actual, (list, set)):
            return len(actual) == 0
        return actual is None or actual == ''

    if operator == 'IS NOT EMPTY':
        if isinstance(actual, (list, set)):
            return len(actual) > 0
        return actual is not None and actual != ''

    if operator == 'BETWEEN':
        if actual is None:
            return False
        return value[0] <= actual <= value[1]

    if operator == 'IN':
        if isinstance(actual, (list, set)):
            return bool(set(actual) & set(value))
        return actual in value

    if operator == 'NOT IN':
        if isinstance(actual, (list, set)):
            return not bool(set(actual) & set(value))
        return actual not in value

    if operator == 'CONTAINS':
        if isinstance(actual, (list, set)):
            return value in actual
        if actual is None:
            return False
        return str(value).lower() in str(actual).lower()

    if operator == 'NOT CONTAINS':
        if isinstance(actual, (list, set)):
            return value not in actual
        if actual is None:
            return True
        return str(value).lower() not in str(actual).lower()

    if operator == 'STARTS WITH':
        return actual is not None and str(actual).lower().startswith(str(value).lower())

    if operator == 'ENDS WITH':
        return actual is not None and str(actual).lower().endswith(str(value).lower())

    # Comparison operators
    if actual is None:
        return False
    if operator == '=':
        return actual == value
    if operator == '!=':
        return actual != value
    if operator == '>':
        return actual > value
    if operator == '<':
        return actual < value
    if operator == '>=':
        return actual >= value
    if operator == '<=':
        return actual <= value

    return False


def _resolve_source_key(entity_name, field_name):
    """Get the source key for a field, handling parent refs."""
    info = get_field_info(entity_name, field_name)
    if info:
        return info[0]  # source_key
    return field_name


def _evaluate_expression(expr, record, entity_name, all_subs=None, fc_summaries=None, use_quantities=False):
    """Recursively evaluate an expression AST node to a number.

    Args:
        expr: Expression AST node
        record: Current record dict (fc_summary or sub dict)
        entity_name: 'fcs' or 'subs'
        all_subs: List of all submarine dicts (for child operations)
        fc_summaries: List of all FC summaries
        use_quantities: If True, count_field on inventory_parts sums quantities

    Returns: numeric result
    """
    if expr['type'] == 'literal':
        return expr['value']

    if expr['type'] == 'field_ref':
        field_name = expr['field']
        info = get_field_info(entity_name, field_name)
        if info:
            source_key = info[0]
            val = record.get(source_key, 0)
            return val if isinstance(val, (int, float)) else 0
        return 0

    if expr['type'] == 'binop':
        left = _evaluate_expression(expr['left'], record, entity_name, all_subs, fc_summaries, use_quantities)
        right = _evaluate_expression(expr['right'], record, entity_name, all_subs, fc_summaries, use_quantities)
        op = expr['op']
        if op == '+':
            return left + right
        elif op == '-':
            return left - right
        elif op == '*':
            return left * right
        elif op == '/':
            return left / right if right != 0 else 0
        return 0

    if expr['type'] == 'count_field':
        return _count_field(expr, record, entity_name, all_subs, use_quantities)

    if expr['type'] == 'count_where':
        return _count_where(expr, record, entity_name, all_subs)

    return 0


def _count_field(expr, record, entity_name, all_subs=None, use_quantities=False):
    """Count items in a set/list field that match a pattern."""
    field = expr['field']
    pattern = str(expr['pattern']).lower()

    # Child set field (e.g., subs.parts) — flatten across all children
    if '.' in field:
        prefix, suffix = field.split('.', 1)
        fc_id = str(record.get('fc_id', ''))
        children = [s for s in (all_subs or []) if str(s.get('fc_id', '')) == fc_id]
        count = 0
        for child in children:
            items = child.get(suffix, [])
            if isinstance(items, list):
                count += sum(1 for item in items if pattern in str(item).lower())
        return count

    # Direct set field
    # inventory_parts: always use actual quantities from the raw inventory dict
    if field == 'inventory_parts':
        from app.services.submarine_data import SUB_PARTS_LOOKUP
        qty_dict = record.get('inventory_parts_qty', {})
        if qty_dict:
            count = 0
            for item_id, qty in qty_dict.items():
                part_name = SUB_PARTS_LOOKUP.get(item_id, '')
                if pattern in part_name.lower():
                    count += qty
            return count

    items = record.get(field, [])
    if isinstance(items, list):
        return sum(1 for item in items if pattern in str(item).lower())
    return 0


def _count_where(expr, record, entity_name, all_subs=None):
    """Count child entities matching a condition."""
    child_entity = expr['child']
    condition = expr['condition']

    fc_id = str(record.get('fc_id', ''))
    if child_entity == 'subs':
        children = [s for s in (all_subs or []) if str(s.get('fc_id', '')) == fc_id]
    else:
        return 0

    count = 0
    for child in children:
        if _evaluate_condition(child, condition, child_entity, all_subs, None):
            count += 1
    return count


def _evaluate_condition(record, condition, entity_name, all_subs=None, fc_summaries=None):
    """Evaluate a single condition or logical group against a record.

    For child entity conditions (quantifiers), uses all_subs to check children.
    """
    # Expression condition (must be checked BEFORE AND/OR)
    if condition.get('type') == 'expression_condition':
        left_val = _evaluate_expression(condition['left'], record, entity_name, all_subs, fc_summaries)
        right_val = _evaluate_expression(condition['right'], record, entity_name, all_subs, fc_summaries)
        op = condition['operator']
        if op == '=':
            return left_val == right_val
        elif op == '!=':
            return left_val != right_val
        elif op == '>':
            return left_val > right_val
        elif op == '<':
            return left_val < right_val
        elif op == '>=':
            return left_val >= right_val
        elif op == '<=':
            return left_val <= right_val
        return False

    # Logical group (AND/OR) — use explicit check to avoid matching expression_condition
    if condition.get('type') in ('AND', 'OR'):
        children_results = [
            _evaluate_condition(record, child, entity_name, all_subs, fc_summaries)
            for child in condition['children']
        ]
        if condition['type'] == 'AND':
            return all(children_results)
        else:  # OR
            return any(children_results)

    field = condition['field']
    operator = condition['operator']
    value = condition['value']
    quantifier = condition.get('quantifier')

    info = get_field_info(entity_name, field)
    if not info:
        return False

    source_key, field_type, ref_type = info

    if ref_type == 'child' and entity_name == 'fcs':
        # Get this FC's submarines
        fc_id = str(record.get('fc_id', ''))
        fc_subs = [s for s in (all_subs or []) if str(s.get('fc_id', '')) == fc_id]

        # For child fields like subs.level, source_key is 'level' from subs schema
        child_prefix, child_field = field.split('.', 1)
        child_entity_def = ENTITY_FIELDS.get(child_prefix)
        if child_entity_def and child_field in child_entity_def['fields']:
            child_source_key = child_entity_def['fields'][child_field][0]
        else:
            child_source_key = child_field

        results = [_apply_condition(sub, child_source_key, operator, value) for sub in fc_subs]

        if not results:
            # No children: practically, FCs with no subs should not match
            # ALL or ANY conditions. NO is true (no sub violates the condition).
            if quantifier == 'NO':
                return True
            return False

        if quantifier == 'ALL' or quantifier is None:
            return all(results)
        elif quantifier == 'ANY':
            return any(results)
        elif quantifier == 'NO':
            return not any(results)
        return False

    if ref_type == 'parent':
        # For subs, parent ref like fc.world — look up from the record directly
        # The subs data from FleetManager includes fc_name, world etc
        if entity_name == 'subs':
            _, child_field = field.split('.', 1)
            parent_def = ENTITY_FIELDS.get('fcs')
            if parent_def and child_field in parent_def['fields']:
                parent_source_key = parent_def['fields'][child_field][0]
                return _apply_condition(record, parent_source_key, operator, value)
        return False

    # Direct field
    return _apply_condition(record, source_key, operator, value)


def execute_live(ast, fc_summaries, all_submarines):
    """Execute a query against live FleetManager data.

    Args:
        ast: Parsed AST dict
        fc_summaries: List of FC summary dicts from get_dashboard_data()
        all_submarines: List of submarine dicts from get_dashboard_data()

    Returns: List of matching record dicts
    """
    entity = ast['entity']
    conditions = ast['conditions']
    select = ast.get('select')
    order_by = ast.get('order_by')
    limit = ast.get('limit')

    if entity == 'fcs':
        # Enrich fc_summaries with computed fields (house_size)
        # Use copies to avoid mutating the original data
        data = []
        for fc in fc_summaries:
            enriched = dict(fc)
            if 'house_size' not in enriched:
                enriched['house_size'] = _resolve_house_size(enriched.get('fc_id'))
            # Treat -1 gil as 0 (plugin lacks FC chest access)
            if enriched.get('fc_gil', 0) < 0:
                enriched['fc_gil'] = 0
            # Convert inventory_parts from {item_id: count} to list of part names
            raw_inv = enriched.get('inventory_parts', {})
            if isinstance(raw_inv, dict):
                from app.services.submarine_data import SUB_PARTS_LOOKUP
                # Preserve raw inventory quantities for COUNT expressions
                enriched['inventory_parts_qty'] = dict(raw_inv)
                enriched['inventory_parts'] = [
                    SUB_PARTS_LOOKUP[item_id]
                    for item_id in raw_inv
                    if item_id in SUB_PARTS_LOOKUP
                ]
            data.append(enriched)
    elif entity == 'subs':
        data = all_submarines
    else:
        raise ValueError(f'Not a live entity: {entity}')

    # Filter
    if conditions:
        results = [
            record for record in data
            if _evaluate_condition(record, conditions, entity, all_submarines, fc_summaries)
        ]
    else:
        results = list(data)

    # Order
    if order_by:
        if 'expression' in order_by:
            # Expression-based ordering
            expr = order_by['expression']
            reverse = order_by['direction'] == 'DESC'
            sort_keys = []
            for record in results:
                val = _evaluate_expression(expr, record, entity, all_submarines, fc_summaries)
                sort_keys.append(val)
            paired = list(zip(sort_keys, results))
            paired.sort(key=lambda x: (x[0] is None, x[0] or 0), reverse=reverse)
            results = [r for _, r in paired]
        else:
            source_key = _resolve_source_key(entity, order_by['field'])
            reverse = order_by['direction'] == 'DESC'
            results.sort(key=lambda r: (r.get(source_key) is None, r.get(source_key, 0)), reverse=reverse)

    # Limit (cap at 1000)
    max_limit = min(limit or 1000, 1000)
    results = results[:max_limit]

    # Remap source keys to DSL field names for display
    entity_def = ENTITY_FIELDS[entity]
    remapped = []
    for record in results:
        row = {}
        for dsl_name, (source_key, ftype) in entity_def['fields'].items():
            val = record.get(source_key)
            # Normalize tags: extract names from tag dicts
            if dsl_name == 'tags' and isinstance(val, list):
                val = [t['name'] if isinstance(t, dict) else t for t in val]
            # Resolve house_size from FCHousing
            if dsl_name == 'house_size' and val is None and entity == 'fcs':
                val = _resolve_house_size(record.get('fc_id'))
            row[dsl_name] = val
        # Add parent ref fields for subs
        if entity == 'subs':
            for parent in entity_def.get('parents', set()):
                parent_def = ENTITY_FIELDS.get('fcs')
                if parent_def:
                    for pfield in ('name', 'world'):
                        if pfield in parent_def['fields']:
                            psource = parent_def['fields'][pfield][0]
                            row[f'{parent}.{pfield}'] = record.get(psource)
        # Evaluate SELECT expressions and add computed columns
        if select:
            for col in select:
                expr = col['expression']
                alias = col['alias']
                if isinstance(expr, str):
                    # Plain field reference — already in row
                    if alias and expr in row:
                        row[alias] = row[expr]
                else:
                    # Expression node — evaluate against the raw (pre-remap) record
                    val = _evaluate_expression(expr, record, entity, all_submarines)
                    col_name = alias or _expr_to_label(expr)
                    row[col_name] = val

        remapped.append(row)

    return remapped


def _expr_to_label(expr):
    """Generate a display label from an expression AST node."""
    if expr['type'] == 'literal':
        return str(expr['value'])
    if expr['type'] == 'field_ref':
        return expr['field']
    if expr['type'] == 'count_field':
        return f"COUNT({expr['field']}, \"{expr['pattern']}\")"
    if expr['type'] == 'count_where':
        return f"COUNT({expr['child']} WHERE ...)"
    if expr['type'] == 'binop':
        return f"{_expr_to_label(expr['left'])} {expr['op']} {_expr_to_label(expr['right'])}"
    return 'expr'


# ---------------------------------------------------------------------------
# DB entity executor (voyages, loot, activity)
# ---------------------------------------------------------------------------

def _get_model_class(model_name):
    """Import and return a SQLAlchemy model class by name."""
    if model_name == 'Voyage':
        from app.models.voyage import Voyage
        return Voyage
    elif model_name == 'VoyageLoot':
        from app.models.voyage_loot import VoyageLoot
        return VoyageLoot
    elif model_name == 'VoyageLootItem':
        from app.models.voyage_loot import VoyageLootItem
        return VoyageLootItem
    elif model_name == 'ActivityLog':
        from app.models.activity_log import ActivityLog
        return ActivityLog
    raise ValueError(f'Unknown model: {model_name}')


def _escape_like(value):
    """Escape LIKE special characters."""
    s = str(value)
    s = s.replace('\\', '\\\\')
    s = s.replace('%', '\\%')
    s = s.replace('_', '\\_')
    return s


def _build_sqlalchemy_filter(model, source_key, operator, value):
    """Build a SQLAlchemy filter expression for a single condition."""
    column = getattr(model, source_key, None)
    if column is None:
        return None

    if operator == '=':
        return column == value
    if operator == '!=':
        return column != value
    if operator == '>':
        return column > value
    if operator == '<':
        return column < value
    if operator == '>=':
        return column >= value
    if operator == '<=':
        return column <= value
    if operator == 'CONTAINS':
        return column.ilike(f'%{_escape_like(value)}%', escape='\\')
    if operator == 'NOT CONTAINS':
        return ~column.ilike(f'%{_escape_like(value)}%', escape='\\')
    if operator == 'STARTS WITH':
        return column.ilike(f'{_escape_like(value)}%', escape='\\')
    if operator == 'ENDS WITH':
        return column.ilike(f'%{_escape_like(value)}', escape='\\')
    if operator == 'IN':
        return column.in_(value)
    if operator == 'NOT IN':
        return ~column.in_(value)
    if operator == 'BETWEEN':
        return column.between(value[0], value[1])
    if operator == 'IS EMPTY':
        return or_(column.is_(None), column == '')
    if operator == 'IS NOT EMPTY':
        return and_(column.isnot(None), column != '')
    return None


def _build_condition_filter(model, condition, entity_name):
    """Recursively build SQLAlchemy filter from condition AST node."""
    from app import db

    # Logical group
    if 'type' in condition:
        child_filters = [
            _build_condition_filter(model, child, entity_name)
            for child in condition['children']
        ]
        child_filters = [f for f in child_filters if f is not None]
        if not child_filters:
            return None
        if condition['type'] == 'AND':
            return and_(*child_filters)
        else:
            return or_(*child_filters)

    field = condition['field']
    operator = condition['operator']
    value = condition['value']
    quantifier = condition.get('quantifier')

    info = get_field_info(entity_name, field)
    if not info:
        return None

    source_key, field_type, ref_type = info

    # Handle datetime string values
    if field_type == FieldType.DATETIME and isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            pass
    if field_type == FieldType.DATETIME and isinstance(value, list):
        parsed = []
        for v in value:
            if isinstance(v, str):
                try:
                    parsed.append(datetime.fromisoformat(v))
                except ValueError:
                    parsed.append(v)
            else:
                parsed.append(v)
        value = parsed

    # Parent reference — use denormalized column or join
    if ref_type == 'parent':
        entity_def = ENTITY_FIELDS[entity_name]
        parent_map = entity_def.get('parent_field_map', {})
        mapped_key = parent_map.get(field, source_key)

        if mapped_key.startswith('_join_voyage_'):
            # Loot parent refs use a subquery against Voyage to avoid duplicate rows.
            # We find fc_ids that match the condition, then filter VoyageLoot.fc_id IN those.
            Voyage = _get_model_class('Voyage')
            voyage_col_map = {
                '_join_voyage_fc_name': 'fc_name',
                '_join_voyage_world': 'world',
            }
            voyage_col = voyage_col_map.get(mapped_key)
            if voyage_col:
                voyage_filter = _build_sqlalchemy_filter(Voyage, voyage_col, operator, value)
                if voyage_filter is not None:
                    subq = db.session.query(Voyage.fc_id).filter(voyage_filter).distinct().subquery()
                    return model.fc_id.in_(db.session.query(subq))
            return None

        return _build_sqlalchemy_filter(model, mapped_key, operator, value)

    # Child entity reference (items on loot)
    if ref_type == 'child':
        child_prefix, child_field = field.split('.', 1)
        child_def = CHILD_ENTITY_FIELDS.get(child_prefix)
        if not child_def:
            return None
        child_model = _get_model_class(child_def['model'])
        child_source = child_def['fields'].get(child_field)
        if not child_source:
            return None

        child_source_key, _ = child_source

        # For items.name, source_key is a list ['item_name_primary', 'item_name_additional']
        if isinstance(child_source_key, list):
            # Build OR across multiple columns
            sub_filters = []
            for col_name in child_source_key:
                f = _build_sqlalchemy_filter(child_model, col_name, operator, value)
                if f is not None:
                    sub_filters.append(f)
            if not sub_filters:
                return None
            item_filter = or_(*sub_filters)
        else:
            item_filter = _build_sqlalchemy_filter(child_model, child_source_key, operator, value)

        if item_filter is None:
            return None

        # Build EXISTS subquery
        parent_fk = child_def['parent_fk']
        exists_query = child_model.query.filter(
            getattr(child_model, parent_fk) == model.id,
            item_filter,
        ).exists()

        if quantifier == 'NO':
            return ~exists_query
        elif quantifier == 'ALL':
            # ALL: no child fails the condition
            if isinstance(child_source_key, list):
                neg_parts = []
                for col_name in child_source_key:
                    f = _build_sqlalchemy_filter(child_model, col_name, operator, value)
                    if f is not None:
                        neg_parts.append(f)
                if neg_parts:
                    neg_filter = or_(*neg_parts)
                else:
                    return None
            else:
                neg_filter = _build_sqlalchemy_filter(child_model, child_source_key, operator, value)

            if neg_filter is not None:
                not_exists = ~child_model.query.filter(
                    getattr(child_model, parent_fk) == model.id,
                    ~neg_filter,
                ).exists()
                return not_exists
            return None
        else:
            # ANY (default for child)
            return exists_query

    # Direct field
    return _build_sqlalchemy_filter(model, source_key, operator, value)


def execute_db(ast):
    """Execute a query against DB-backed entities.

    Args:
        ast: Parsed AST dict

    Returns: List of result dicts
    """
    entity = ast['entity']
    conditions = ast['conditions']
    order_by = ast.get('order_by')
    limit = ast.get('limit')

    entity_def = ENTITY_FIELDS[entity]
    model = _get_model_class(entity_def['model'])
    query = model.query

    if conditions:
        filter_expr = _build_condition_filter(model, conditions, entity)
        if filter_expr is not None:
            query = query.filter(filter_expr)

    # Order
    if order_by:
        if 'expression' in order_by:
            # Expression ORDER BY is not supported for DB entities — ignore silently
            pass
        else:
            source_key = _resolve_source_key(entity, order_by['field'])
            column = getattr(model, source_key, None)
            if column is not None:
                if order_by['direction'] == 'DESC':
                    query = query.order_by(column.desc())
                else:
                    query = query.order_by(column.asc())

    # Limit (cap at 1000)
    max_limit = min(limit or 1000, 1000)
    query = query.limit(max_limit)

    # Execute and convert to dicts
    rows = query.all()
    results = []
    for row in rows:
        record = {}
        for dsl_name, (source_key, _) in entity_def['fields'].items():
            record[dsl_name] = getattr(row, source_key, None)
        # Add parent fields if present (denormalized columns only; skip join markers)
        parent_map = entity_def.get('parent_field_map', {})
        for parent_field, mapped_key in parent_map.items():
            if mapped_key.startswith('_'):
                continue  # Skip special join markers
            record[parent_field] = getattr(row, mapped_key, None)
        results.append(record)

    # Resolve join-marker parent fields for loot
    if entity == 'loot' and results:
        from app.models.voyage import Voyage
        # Get unique fc_ids from the raw rows
        fc_ids = set()
        for row in rows:
            fid = getattr(row, 'fc_id', None)
            if fid:
                fc_ids.add(fid)
        if fc_ids:
            # Query distinct fc_id -> fc_name, world from Voyage table
            fc_lookup = {}
            voyages = Voyage.query.filter(Voyage.fc_id.in_(fc_ids)).with_entities(
                Voyage.fc_id, Voyage.fc_name, Voyage.world
            ).distinct().all()
            for v in voyages:
                fc_lookup[v.fc_id] = {'fc.name': v.fc_name, 'fc.world': v.world}
            # Populate results
            for i, row in enumerate(rows):
                fid = getattr(row, 'fc_id', None)
                if fid and fid in fc_lookup:
                    results[i].update(fc_lookup[fid])

    return results
