"""Result formatter for the report engine.

Formats raw result lists into table or summary responses, and generates CSV.
"""
import csv
import io
from collections import Counter
from app.services.report_engine.schema import ENTITY_FIELDS, FieldType


def format_table(results, entity_name, page=1, per_page=100):
    """Format results as a paginated table response.

    Returns: {
        'columns': [{'name': 'field_name', 'type': 'string'}],
        'rows': [{'field_name': value, ...}],
        'total': total_count,
        'page': current_page,
        'per_page': per_page,
        'truncated': bool (true if total > 1000)
    }
    """
    entity_def = ENTITY_FIELDS.get(entity_name, {})
    fields = entity_def.get('fields', {})

    # Build columns
    columns = []
    for fname, (source_key, ftype) in fields.items():
        columns.append({'name': fname, 'type': ftype.value})
    # Add parent ref columns that appear in results
    if results:
        for key in results[0]:
            if '.' in key and key not in [c['name'] for c in columns]:
                columns.append({'name': key, 'type': 'string'})

    total = len(results)
    truncated = total >= 1000

    # Paginate
    start = (page - 1) * per_page
    end = start + per_page
    page_rows = results[start:end]

    return {
        'columns': columns,
        'rows': page_rows,
        'total': total,
        'page': page,
        'per_page': per_page,
        'truncated': truncated,
    }


def format_summary(results, entity_name, group_by=None):
    """Format results as summary/aggregate statistics.

    Returns: {
        'total': count,
        'fields': {
            'field_name': {'type': 'number', 'sum': X, 'avg': X, 'min': X, 'max': X}
            'field_name': {'type': 'string', 'distinct': N, 'top': [('val', count), ...]}
        },
        'groups': [...]  (if group_by specified)
    }
    """
    entity_def = ENTITY_FIELDS.get(entity_name, {})
    fields = entity_def.get('fields', {})

    def compute_aggregates(records):
        aggs = {}
        for fname, (source_key, ftype) in fields.items():
            values = [r.get(fname) for r in records if r.get(fname) is not None]

            if ftype == FieldType.NUMBER:
                if values:
                    aggs[fname] = {
                        'type': 'number',
                        'count': len(values),
                        'sum': sum(values),
                        'avg': round(sum(values) / len(values), 2),
                        'min': min(values),
                        'max': max(values),
                    }
                else:
                    aggs[fname] = {'type': 'number', 'count': 0, 'sum': 0, 'avg': 0, 'min': None, 'max': None}

            elif ftype == FieldType.STRING:
                counter = Counter(values)
                aggs[fname] = {
                    'type': 'string',
                    'count': len(values),
                    'distinct': len(counter),
                    'top': counter.most_common(10),
                }

            elif ftype == FieldType.DATETIME:
                if values:
                    aggs[fname] = {
                        'type': 'datetime',
                        'count': len(values),
                        'min': str(min(values)),
                        'max': str(max(values)),
                    }
                else:
                    aggs[fname] = {'type': 'datetime', 'count': 0, 'min': None, 'max': None}

        return aggs

    if group_by:
        groups = {}
        for record in results:
            key = record.get(group_by, '_ungrouped')
            groups.setdefault(key, []).append(record)

        group_results = []
        for group_key, group_records in sorted(groups.items(), key=lambda x: x[0] or ''):
            group_results.append({
                'group': group_key,
                'count': len(group_records),
                'fields': compute_aggregates(group_records),
            })

        return {
            'total': len(results),
            'group_by': group_by,
            'groups': group_results,
        }

    return {
        'total': len(results),
        'fields': compute_aggregates(results),
    }


def format_csv(results, entity_name):
    """Generate CSV string from results.

    Returns: string (CSV content)
    """
    if not results:
        return ''

    entity_def = ENTITY_FIELDS.get(entity_name, {})
    fields = entity_def.get('fields', {})

    # Use field names as headers, plus any parent ref keys
    headers = list(fields.keys())
    if results:
        for key in results[0]:
            if key not in headers:
                headers.append(key)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction='ignore')
    writer.writeheader()
    for row in results:
        writer.writerow(row)

    return output.getvalue()
