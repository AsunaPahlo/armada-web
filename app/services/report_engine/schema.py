"""Entity and field definitions for the report query engine."""
from enum import Enum


class FieldType(Enum):
    STRING = 'string'
    NUMBER = 'number'
    DATETIME = 'datetime'
    BOOLEAN = 'boolean'
    SET = 'set'


class EntitySource(Enum):
    LIVE = 'live'       # FleetManager data
    DB = 'db'           # SQLAlchemy model


# Field definition: (dsl_name, source_key, type)
# source_key is the model column name or FleetManager dict key
ENTITY_FIELDS = {
    'fcs': {
        'source': EntitySource.LIVE,
        'fields': {
            'name':          ('fc_name', FieldType.STRING),
            'world':         ('world', FieldType.STRING),
            'region':        ('region', FieldType.STRING),
            'gil':           ('fc_gil', FieldType.NUMBER),
            'ceruleum':      ('ceruleum', FieldType.NUMBER),
            'repair_kits':   ('repair_kits', FieldType.NUMBER),
            'dive_credits':  ('dive_credits', FieldType.NUMBER),
            'total_subs':    ('total_subs', FieldType.NUMBER),
            'ready_subs':    ('ready_subs', FieldType.NUMBER),
            'leveling_subs': ('leveling_subs', FieldType.NUMBER),
            'gil_per_day':   ('gil_per_day', FieldType.NUMBER),
            'house_size':    ('house_size', FieldType.STRING),
            'tags':          ('tags', FieldType.SET),
        },
        'children': {'subs'},
        'parents': set(),
    },
    'subs': {
        'source': EntitySource.LIVE,
        'fields': {
            'name':         ('name', FieldType.STRING),
            'level':        ('level', FieldType.NUMBER),
            'build':        ('build', FieldType.STRING),
            'parts':        ('parts', FieldType.SET),
            'route':        ('route', FieldType.STRING),
            'status':       ('status', FieldType.STRING),
            'gil_per_day':  ('gil_per_day', FieldType.NUMBER),
            'exp_progress': ('exp_progress', FieldType.NUMBER),
        },
        'children': set(),
        'parents': {'fc'},
    },
    'voyages': {
        'source': EntitySource.DB,
        'model': 'Voyage',
        'fields': {
            'submarine':   ('submarine_name', FieldType.STRING),
            'world':       ('world', FieldType.STRING),
            'route':       ('route_name', FieldType.STRING),
            'departure':   ('departure_time', FieldType.DATETIME),
            'return_time': ('return_time', FieldType.DATETIME),
            'duration':    ('duration_hours', FieldType.NUMBER),
            'level':       ('submarine_level', FieldType.NUMBER),
            'build':       ('submarine_build', FieldType.STRING),
            'collected':   ('was_collected', FieldType.BOOLEAN),
        },
        'children': set(),
        'parents': {'fc'},
        'parent_field_map': {
            'fc.name': 'fc_name',
            'fc.world': 'world',
        },
    },
    'loot': {
        'source': EntitySource.DB,
        'model': 'VoyageLoot',
        'fields': {
            'submarine': ('submarine_name', FieldType.STRING),
            'route':     ('route_name', FieldType.STRING),
            'value':     ('total_gil_value', FieldType.NUMBER),
            'date':      ('captured_at', FieldType.DATETIME),
        },
        'children': {'items'},
        'parents': {'fc'},
        'parent_field_map': {
            # Requires join: VoyageLoot.fc_id -> Voyage.fc_id -> Voyage columns
            'fc.name': '_join_voyage_fc_name',
            'fc.world': '_join_voyage_world',
        },
    },
    'activity': {
        'source': EntitySource.DB,
        'model': 'ActivityLog',
        'fields': {
            'activity_type': ('activity_type', FieldType.STRING),
            'submarine':     ('submarine_name', FieldType.STRING),
            'old_value':     ('old_value', FieldType.STRING),
            'new_value':     ('new_value', FieldType.STRING),
            'date':          ('created_at', FieldType.DATETIME),
        },
        'children': set(),
        'parents': {'fc'},
        'parent_field_map': {
            'fc.name': 'fc_name',
        },
    },
}

# Child entity field definitions (only for WHERE filtering, not result columns)
CHILD_ENTITY_FIELDS = {
    'items': {
        'model': 'VoyageLootItem',
        'parent_fk': 'voyage_loot_id',
        'fields': {
            'name':   (['item_name_primary', 'item_name_additional'], FieldType.STRING),
            'sector': ('sector_id', FieldType.NUMBER),
            # Note: items.value is omitted because VoyageLootItem.total_value is a Python
            # @property (not a DB column) and cannot be used in SQLAlchemy filters.
        },
    },
}

# Entity aliases
ENTITY_ALIASES = {
    'submarines': 'subs',
}

# Operators by field type
OPERATORS_BY_TYPE = {
    FieldType.STRING: ['=', '!=', 'CONTAINS', 'NOT CONTAINS', 'STARTS WITH', 'ENDS WITH',
                       'IN', 'NOT IN', 'IS EMPTY', 'IS NOT EMPTY'],
    FieldType.NUMBER: ['=', '!=', '>', '<', '>=', '<=', 'BETWEEN', 'IN', 'NOT IN',
                       'IS EMPTY', 'IS NOT EMPTY'],
    FieldType.DATETIME: ['=', '!=', '>', '<', '>=', '<=', 'BETWEEN', 'IS EMPTY', 'IS NOT EMPTY'],
    FieldType.BOOLEAN: ['=', '!='],
    FieldType.SET: ['CONTAINS', 'NOT CONTAINS', 'IN', 'IS EMPTY', 'IS NOT EMPTY'],
}

# Enum values for dropdown suggestions
ENUM_VALUES = {
    'fcs.region': ['NA', 'EU', 'JP', 'OCE'],
    'fcs.house_size': ['Small', 'Medium', 'Large'],
    'subs.status': ['ready', 'voyaging', 'returning_soon'],
    'activity.activity_type': [
        'build_change', 'level_up', 'route_change',
        'sector_unlock', 'submarine_added', 'submarine_removed',
    ],
}


def resolve_entity(name):
    """Resolve entity name or alias to canonical name."""
    name = name.lower()
    return ENTITY_ALIASES.get(name, name)


def get_entity_def(entity_name):
    """Get entity definition or None."""
    return ENTITY_FIELDS.get(resolve_entity(entity_name))


def get_field_info(entity_name, field_name):
    """Get (source_key, FieldType) for a field, or None.

    Handles direct fields, parent refs (fc.name), and child refs (subs.level).
    Returns: (source_key, field_type, ref_type)
    ref_type is 'direct', 'parent', or 'child'.
    """
    entity = resolve_entity(entity_name)
    entity_def = ENTITY_FIELDS.get(entity)
    if not entity_def:
        return None

    # Direct field
    if '.' not in field_name:
        if field_name in entity_def['fields']:
            source_key, ftype = entity_def['fields'][field_name]
            return source_key, ftype, 'direct'
        return None

    prefix, suffix = field_name.split('.', 1)

    # Child entity reference
    if prefix in entity_def.get('children', set()):
        # Check CHILD_ENTITY_FIELDS for 'items', or ENTITY_FIELDS for 'subs'
        if prefix in CHILD_ENTITY_FIELDS:
            child_def = CHILD_ENTITY_FIELDS[prefix]
        elif prefix in ENTITY_FIELDS:
            child_def = ENTITY_FIELDS[prefix]
        else:
            return None
        if suffix in child_def['fields']:
            source_key, ftype = child_def['fields'][suffix]
            return source_key, ftype, 'child'
        return None

    # Parent entity reference
    if prefix in entity_def.get('parents', set()):
        parent_map = entity_def.get('parent_field_map', {})
        if field_name in parent_map:
            return parent_map[field_name], FieldType.STRING, 'parent'
        # For live entities, try resolving from parent's fields
        # Note: parents set uses short names (e.g., 'fc') but ENTITY_FIELDS uses plural (e.g., 'fcs')
        resolved_prefix = resolve_entity(prefix + 's') if ENTITY_FIELDS.get(prefix) is None else prefix
        parent_def = ENTITY_FIELDS.get(resolved_prefix) or ENTITY_FIELDS.get(prefix)
        if parent_def and suffix in parent_def['fields']:
            source_key, ftype = parent_def['fields'][suffix]
            return source_key, ftype, 'parent'
        return None

    return None


def get_schema_for_frontend():
    """Build the schema dict sent to the frontend for the visual builder."""
    schema = {'entities': {}, 'operators': {}}

    for entity_name, entity_def in ENTITY_FIELDS.items():
        fields = {}
        for fname, (source_key, ftype) in entity_def['fields'].items():
            full_name = f'{entity_name}.{fname}'
            fields[fname] = {
                'type': ftype.value,
                'operators': OPERATORS_BY_TYPE[ftype],
                'enum_values': ENUM_VALUES.get(full_name),
            }
        # Add parent reference fields — only expose fields that have explicit mappings
        # or that exist as denormalized columns on the entity's model
        parent_map = entity_def.get('parent_field_map', {})
        for parent in entity_def.get('parents', set()):
            parent_def = ENTITY_FIELDS.get(parent)
            if parent_def:
                # For live entities (subs), expose common parent fields available on the record
                if entity_def['source'] == EntitySource.LIVE:
                    for pfield, (_, pftype) in parent_def['fields'].items():
                        ref_name = f'{parent}.{pfield}'
                        # Only expose name and world — these are on the sub record
                        if pfield in ('name', 'world'):
                            fields[ref_name] = {
                                'type': pftype.value,
                                'operators': OPERATORS_BY_TYPE[pftype],
                                'ref_type': 'parent',
                            }
                else:
                    # For DB entities, only expose fields with explicit parent_field_map entries
                    for ref_name in parent_map:
                        parent_field = ref_name.split('.', 1)[1] if '.' in ref_name else ref_name
                        if parent_field in parent_def['fields']:
                            _, pftype = parent_def['fields'][parent_field]
                            fields[ref_name] = {
                                'type': pftype.value,
                                'operators': OPERATORS_BY_TYPE[pftype],
                                'ref_type': 'parent',
                            }
        # Add child entity fields (for quantifier conditions)
        for child in entity_def.get('children', set()):
            child_src = CHILD_ENTITY_FIELDS.get(child, ENTITY_FIELDS.get(child))
            if child_src:
                for cfield, (_, cftype) in child_src['fields'].items():
                    ref_name = f'{child}.{cfield}'
                    fields[ref_name] = {
                        'type': cftype.value,
                        'operators': OPERATORS_BY_TYPE[cftype],
                        'ref_type': 'child',
                    }

        schema['entities'][entity_name] = {
            'fields': fields,
            'has_children': bool(entity_def.get('children')),
        }

    return schema
