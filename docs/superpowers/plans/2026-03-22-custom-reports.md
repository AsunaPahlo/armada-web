# Custom Reports & Query Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a custom reporting page with a hybrid visual/text query builder powered by a custom DSL, enabling users to query fleet data across FCs, submarines, voyages, loot, and activity.

**Architecture:** Three-stage backend pipeline (Lexer → Parser → Executor) processes a custom DSL into SQLAlchemy queries (for DB entities) or Python filters (for live FleetManager data). The frontend has a tabbed Visual Builder / Query Text interface where the query text is the canonical format. Results are rendered as sortable tables or aggregate summaries with CSV export.

**Tech Stack:** Flask, SQLAlchemy, Jinja2, vanilla JavaScript, Bootstrap 5

**Spec:** `docs/superpowers/specs/2026-03-22-custom-reports-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `app/services/report_engine/` | Package directory for the query engine |
| `app/services/report_engine/__init__.py` | Public API: `run_query()`, `get_schema()`, `ParseError` |
| `app/services/report_engine/lexer.py` | Tokenizer: query string → token list |
| `app/services/report_engine/parser.py` | Parser: token list → AST dict |
| `app/services/report_engine/schema.py` | Entity/field definitions, type info, field mappings |
| `app/services/report_engine/executor.py` | AST → results (DB queries + live data filtering) |
| `app/services/report_engine/formatter.py` | Result formatting: table rows, summary aggregates, CSV |
| `app/models/saved_report.py` | SavedReport SQLAlchemy model |
| `app/routes/reports.py` | Reports blueprint — page, API endpoints |
| `app/templates/reports.html` | Reports page template |
| `app/static/js/reports.js` | Visual builder, query editor, results rendering |
| `tests/conftest.py` | Pytest configuration (adds project root to sys.path) |
| `tests/test_lexer.py` | Lexer unit tests |
| `tests/test_parser.py` | Parser unit tests |
| `tests/test_executor.py` | Executor unit tests |

### Modified Files
| File | Change |
|------|--------|
| `app/__init__.py` | Register reports blueprint, import saved_report model |
| `app/models/__init__.py` | Add SavedReport to imports and `__all__` |
| `app/templates/base.html` | Add "Reports" nav item after "Gil" |

---

## Task 1: Schema Definition & Field Mappings

**Files:**
- Create: `app/services/report_engine/__init__.py`
- Create: `app/services/report_engine/schema.py`
- Test: `tests/test_lexer.py` (schema validation tests)

This defines the source of truth for all queryable entities, fields, operators, and relationships.

- [ ] **Step 1: Create the report_engine package**

Create `app/services/report_engine/__init__.py`:

```python
"""
Armada Report Engine — custom DSL for querying fleet data.

Usage:
    from app.services.report_engine import run_query, get_schema, ParseError
"""
```

- [ ] **Step 2: Create the schema module**

Create `app/services/report_engine/schema.py`:

```python
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
        parent_def = ENTITY_FIELDS.get(prefix)
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
```

- [ ] **Step 3: Commit**

```bash
git add app/services/report_engine/__init__.py app/services/report_engine/schema.py
git commit -m "feat(reports): add report engine schema definitions"
```

---

## Task 2: Lexer (Tokenizer)

**Files:**
- Create: `app/services/report_engine/lexer.py`
- Create: `tests/test_lexer.py`

- [ ] **Step 1: Create test infrastructure**

Create `tests/conftest.py`:

```python
"""Pytest configuration — ensures app imports work from the tests/ directory."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
```

- [ ] **Step 2: Write lexer tests**

Create `tests/test_lexer.py`:

```python
"""Tests for the report engine lexer."""
import pytest
from app.services.report_engine.lexer import tokenize, Token, TokenType, LexerError


class TestTokenizeBasic:
    def test_simple_find(self):
        tokens = tokenize('FIND fcs')
        assert tokens[0] == Token(TokenType.KEYWORD, 'FIND', 0)
        assert tokens[1] == Token(TokenType.IDENTIFIER, 'fcs', 5)

    def test_find_with_where(self):
        tokens = tokenize('FIND subs WHERE level > 100')
        assert len(tokens) == 5
        assert tokens[2].type == TokenType.KEYWORD
        assert tokens[2].value == 'WHERE'
        assert tokens[3].type == TokenType.IDENTIFIER
        assert tokens[4].type == TokenType.VALUE

    def test_string_value(self):
        tokens = tokenize('FIND fcs WHERE name = "My FC"')
        value_token = [t for t in tokens if t.type == TokenType.VALUE][0]
        assert value_token.value == 'My FC'

    def test_dotted_field(self):
        tokens = tokenize('FIND fcs WHERE subs.level > 100')
        field_token = [t for t in tokens if t.value == 'subs.level'][0]
        assert field_token.type == TokenType.IDENTIFIER

    def test_quantifiers(self):
        tokens = tokenize('FIND fcs WHERE ALL subs.level > 100')
        assert tokens[3] == Token(TokenType.QUANTIFIER, 'ALL', 15)

    def test_parentheses(self):
        tokens = tokenize('FIND subs WHERE (level > 50 OR level < 10)')
        types = [t.type for t in tokens]
        assert TokenType.LPAREN in types
        assert TokenType.RPAREN in types

    def test_between(self):
        tokens = tokenize('FIND voyages WHERE duration BETWEEN 20 AND 48')
        keywords = [t.value for t in tokens if t.type == TokenType.KEYWORD]
        assert 'BETWEEN' in keywords

    def test_in_list(self):
        tokens = tokenize('FIND subs WHERE route IN ("CSUZ", "MOJ")')
        assert TokenType.LPAREN in [t.type for t in tokens]
        assert TokenType.COMMA in [t.type for t in tokens]

    def test_multi_word_operators(self):
        tokens = tokenize('FIND fcs WHERE name STARTS WITH "Storm"')
        ops = [t for t in tokens if t.type == TokenType.OPERATOR]
        assert any(t.value == 'STARTS WITH' for t in ops)

    def test_not_contains(self):
        tokens = tokenize('FIND fcs WHERE tags NOT CONTAINS "Mining"')
        ops = [t for t in tokens if t.type == TokenType.OPERATOR]
        assert any(t.value == 'NOT CONTAINS' for t in ops)

    def test_is_empty(self):
        tokens = tokenize('FIND fcs WHERE tags IS EMPTY')
        ops = [t for t in tokens if t.type == TokenType.OPERATOR]
        assert any(t.value == 'IS EMPTY' for t in ops)

    def test_submarines_alias(self):
        tokens = tokenize('FIND submarines WHERE level > 50')
        assert tokens[1].value == 'submarines'

    def test_order_by(self):
        tokens = tokenize('FIND fcs ORDER BY gil_per_day DESC')
        keywords = [t.value for t in tokens if t.type == TokenType.KEYWORD]
        assert 'ORDER' in keywords
        assert 'BY' in keywords
        assert 'DESC' in keywords

    def test_group_by(self):
        tokens = tokenize('FIND voyages GROUP BY route')
        keywords = [t.value for t in tokens if t.type == TokenType.KEYWORD]
        assert 'GROUP' in keywords

    def test_limit(self):
        tokens = tokenize('FIND fcs LIMIT 10')
        assert tokens[-1] == Token(TokenType.VALUE, 10, 14)

    def test_numeric_value_types(self):
        tokens = tokenize('FIND subs WHERE level >= 111')
        value = [t for t in tokens if t.type == TokenType.VALUE][0]
        assert value.value == 111
        assert isinstance(value.value, int)

    def test_float_value(self):
        tokens = tokenize('FIND voyages WHERE duration > 23.5')
        value = [t for t in tokens if t.type == TokenType.VALUE][0]
        assert value.value == 23.5

    def test_comparison_operators(self):
        for op in ['=', '!=', '>', '<', '>=', '<=']:
            tokens = tokenize(f'FIND subs WHERE level {op} 100')
            ops = [t for t in tokens if t.type == TokenType.OPERATOR]
            assert len(ops) == 1
            assert ops[0].value == op


class TestTokenizeErrors:
    def test_unterminated_string(self):
        with pytest.raises(LexerError, match='Unterminated string'):
            tokenize('FIND fcs WHERE name = "unclosed')

    def test_unexpected_character(self):
        with pytest.raises(LexerError):
            tokenize('FIND fcs WHERE name @ "test"')
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/test_lexer.py -v
```

Expected: FAIL (module not found)

- [ ] **Step 4: Implement the lexer**

Create `app/services/report_engine/lexer.py`:

```python
"""Lexer for the Armada report query DSL.

Tokenizes a query string like:
    FIND fcs WHERE ALL subs.level > 111 AND NO subs.build CONTAINS "SSUC"
into a list of typed Token objects.
"""
from dataclasses import dataclass
from enum import Enum, auto
from typing import List


class TokenType(Enum):
    KEYWORD = auto()      # FIND, WHERE, AND, OR, ORDER, BY, GROUP, ASC, DESC, LIMIT, BETWEEN
    IDENTIFIER = auto()   # field names, entity names (e.g., fcs, subs.level)
    OPERATOR = auto()     # =, !=, >, <, >=, <=, CONTAINS, STARTS WITH, etc.
    VALUE = auto()        # "string", 123, 45.6
    QUANTIFIER = auto()   # ALL, ANY, NO
    LPAREN = auto()       # (
    RPAREN = auto()       # )
    COMMA = auto()        # ,


@dataclass(frozen=True)
class Token:
    type: TokenType
    value: object  # str, int, or float
    pos: int       # position in source string


class LexerError(Exception):
    def __init__(self, message, pos):
        self.pos = pos
        super().__init__(f'{message} at position {pos}')


# Keywords recognized by the lexer
KEYWORDS = {
    'FIND', 'WHERE', 'AND', 'OR', 'GROUP', 'BY', 'ORDER',
    'ASC', 'DESC', 'LIMIT', 'BETWEEN', 'IN',
}
QUANTIFIERS = {'ALL', 'ANY', 'NO'}

# Multi-word operators: checked in order (longest first)
MULTI_WORD_OPS = [
    ('NOT', 'CONTAINS'),
    ('NOT', 'IN'),
    ('STARTS', 'WITH'),
    ('ENDS', 'WITH'),
    ('IS', 'NOT', 'EMPTY'),
    ('IS', 'EMPTY'),
]

# Single-word keyword-operators
KEYWORD_OPS = {'CONTAINS'}

# Symbol operators
SYMBOL_OPS = {'>=', '<=', '!=', '=', '>', '<'}


def tokenize(query: str) -> List[Token]:
    """Tokenize a query string into a list of Tokens.

    Raises LexerError for invalid input.
    """
    tokens = []
    i = 0
    n = len(query)

    while i < n:
        # Skip whitespace
        if query[i].isspace():
            i += 1
            continue

        # Parentheses
        if query[i] == '(':
            tokens.append(Token(TokenType.LPAREN, '(', i))
            i += 1
            continue
        if query[i] == ')':
            tokens.append(Token(TokenType.RPAREN, ')', i))
            i += 1
            continue

        # Comma
        if query[i] == ',':
            tokens.append(Token(TokenType.COMMA, ',', i))
            i += 1
            continue

        # Quoted string
        if query[i] == '"':
            start = i
            i += 1
            while i < n and query[i] != '"':
                i += 1
            if i >= n:
                raise LexerError('Unterminated string', start)
            tokens.append(Token(TokenType.VALUE, query[start + 1:i], start))
            i += 1
            continue

        # Symbol operators (>=, <=, !=, =, >, <)
        matched_op = None
        for op in SYMBOL_OPS:
            if query[i:i + len(op)] == op:
                if matched_op is None or len(op) > len(matched_op):
                    matched_op = op
        if matched_op:
            tokens.append(Token(TokenType.OPERATOR, matched_op, i))
            i += len(matched_op)
            continue

        # Numbers
        if query[i].isdigit() or (query[i] == '-' and i + 1 < n and query[i + 1].isdigit()):
            start = i
            if query[i] == '-':
                i += 1
            while i < n and query[i].isdigit():
                i += 1
            if i < n and query[i] == '.' and i + 1 < n and query[i + 1].isdigit():
                i += 1
                while i < n and query[i].isdigit():
                    i += 1
                tokens.append(Token(TokenType.VALUE, float(query[start:i]), start))
            else:
                tokens.append(Token(TokenType.VALUE, int(query[start:i]), start))
            continue

        # Words (identifiers, keywords, quantifiers, keyword-operators)
        if query[i].isalpha() or query[i] == '_':
            start = i
            while i < n and (query[i].isalnum() or query[i] in '_.'):
                i += 1
            word = query[start:i]
            word_upper = word.upper()

            # Check for multi-word operators by peeking ahead
            multi_matched = False
            for mw_op in MULTI_WORD_OPS:
                if word_upper == mw_op[0]:
                    # Try to match remaining words
                    saved_i = i
                    parts = [word_upper]
                    temp_i = i
                    matched_all = True
                    for part_idx in range(1, len(mw_op)):
                        # Skip whitespace
                        while temp_i < n and query[temp_i].isspace():
                            temp_i += 1
                        # Read next word
                        if temp_i < n and (query[temp_i].isalpha() or query[temp_i] == '_'):
                            ws = temp_i
                            while temp_i < n and (query[temp_i].isalnum() or query[temp_i] == '_'):
                                temp_i += 1
                            next_word = query[ws:temp_i].upper()
                            if next_word == mw_op[part_idx]:
                                parts.append(next_word)
                            else:
                                matched_all = False
                                break
                        else:
                            matched_all = False
                            break
                    if matched_all and len(parts) == len(mw_op):
                        tokens.append(Token(TokenType.OPERATOR, ' '.join(mw_op), start))
                        i = temp_i
                        multi_matched = True
                        break

            if multi_matched:
                continue

            # Classify the word
            if word_upper in QUANTIFIERS:
                tokens.append(Token(TokenType.QUANTIFIER, word_upper, start))
            elif word_upper in KEYWORD_OPS:
                tokens.append(Token(TokenType.OPERATOR, word_upper, start))
            elif word_upper in KEYWORDS:
                tokens.append(Token(TokenType.KEYWORD, word_upper, start))
            else:
                # Identifier (field or entity name) — preserve original case for values
                tokens.append(Token(TokenType.IDENTIFIER, word, start))
            continue

        raise LexerError(f'Unexpected character: {query[i]!r}', i)

    return tokens
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/test_lexer.py -v
```

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py app/services/report_engine/lexer.py tests/test_lexer.py
git commit -m "feat(reports): implement DSL lexer with tests"
```

---

## Task 3: Parser (Tokens → AST)

**Files:**
- Create: `app/services/report_engine/parser.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Write parser tests**

Create `tests/test_parser.py`:

```python
"""Tests for the report engine parser."""
import pytest
from app.services.report_engine.parser import parse, ParseError


class TestParseBasic:
    def test_find_entity(self):
        ast = parse('FIND fcs')
        assert ast['entity'] == 'fcs'
        assert ast['conditions'] is None
        assert ast['group_by'] is None
        assert ast['order_by'] is None
        assert ast['limit'] is None

    def test_submarines_alias(self):
        ast = parse('FIND submarines')
        assert ast['entity'] == 'subs'

    def test_simple_condition(self):
        ast = parse('FIND subs WHERE level > 100')
        cond = ast['conditions']
        assert cond['field'] == 'level'
        assert cond['operator'] == '>'
        assert cond['value'] == 100
        assert cond['quantifier'] is None

    def test_and_conditions(self):
        ast = parse('FIND subs WHERE level > 100 AND status = "ready"')
        cond = ast['conditions']
        assert cond['type'] == 'AND'
        assert len(cond['children']) == 2

    def test_or_conditions(self):
        ast = parse('FIND subs WHERE route = "CSUZ" OR route = "MOJ"')
        cond = ast['conditions']
        assert cond['type'] == 'OR'

    def test_quantifier(self):
        ast = parse('FIND fcs WHERE ALL subs.level > 111')
        cond = ast['conditions']
        assert cond['quantifier'] == 'ALL'
        assert cond['field'] == 'subs.level'

    def test_no_quantifier(self):
        ast = parse('FIND fcs WHERE NO subs.build CONTAINS "SSUC"')
        cond = ast['conditions']
        assert cond['quantifier'] == 'NO'

    def test_mixed_and_or_with_parens(self):
        ast = parse('FIND subs WHERE level > 100 AND (route = "CSUZ" OR route = "MOJ")')
        cond = ast['conditions']
        assert cond['type'] == 'AND'
        assert cond['children'][1]['type'] == 'OR'

    def test_between(self):
        ast = parse('FIND voyages WHERE duration BETWEEN 20 AND 48')
        cond = ast['conditions']
        assert cond['operator'] == 'BETWEEN'
        assert cond['value'] == [20, 48]

    def test_in_list(self):
        ast = parse('FIND subs WHERE route IN ("CSUZ", "MOJ", "OJ")')
        cond = ast['conditions']
        assert cond['operator'] == 'IN'
        assert cond['value'] == ['CSUZ', 'MOJ', 'OJ']

    def test_group_by(self):
        ast = parse('FIND voyages GROUP BY route')
        assert ast['group_by'] == 'route'

    def test_order_by_asc(self):
        ast = parse('FIND fcs ORDER BY gil_per_day ASC')
        assert ast['order_by'] == {'field': 'gil_per_day', 'direction': 'ASC'}

    def test_order_by_desc(self):
        ast = parse('FIND fcs ORDER BY name DESC')
        assert ast['order_by'] == {'field': 'name', 'direction': 'DESC'}

    def test_order_by_default_asc(self):
        ast = parse('FIND fcs ORDER BY name')
        assert ast['order_by'] == {'field': 'name', 'direction': 'ASC'}

    def test_limit(self):
        ast = parse('FIND fcs LIMIT 10')
        assert ast['limit'] == 10

    def test_full_query(self):
        ast = parse('FIND fcs WHERE ALL subs.level > 111 AND NO subs.build CONTAINS "SSUC" ORDER BY gil_per_day DESC LIMIT 50')
        assert ast['entity'] == 'fcs'
        assert ast['conditions']['type'] == 'AND'
        assert ast['order_by'] == {'field': 'gil_per_day', 'direction': 'DESC'}
        assert ast['limit'] == 50

    def test_is_empty(self):
        ast = parse('FIND fcs WHERE tags IS EMPTY')
        cond = ast['conditions']
        assert cond['operator'] == 'IS EMPTY'
        assert cond['value'] is None

    def test_parent_reference(self):
        ast = parse('FIND subs WHERE fc.world = "Gilgamesh"')
        cond = ast['conditions']
        assert cond['field'] == 'fc.world'
        assert cond['quantifier'] is None


class TestParseErrors:
    def test_missing_find(self):
        with pytest.raises(ParseError, match='Expected FIND'):
            parse('WHERE level > 100')

    def test_missing_entity(self):
        with pytest.raises(ParseError, match='Expected entity'):
            parse('FIND WHERE level > 100')

    def test_unknown_entity(self):
        with pytest.raises(ParseError, match='Unknown entity'):
            parse('FIND badentity WHERE level > 100')

    def test_quantifier_on_direct_field(self):
        with pytest.raises(ParseError, match='Quantifier'):
            parse('FIND subs WHERE ALL level > 100')

    def test_quantifier_on_parent_field(self):
        with pytest.raises(ParseError, match='Quantifier'):
            parse('FIND subs WHERE ALL fc.world = "Gilgamesh"')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/test_parser.py -v
```

Expected: FAIL (module not found)

- [ ] **Step 3: Implement the parser**

Create `app/services/report_engine/parser.py`:

```python
"""Parser for the Armada report query DSL.

Converts a token stream from the lexer into an AST (dict).
Grammar:
    query     = FIND entity [WHERE conditions] [GROUP BY field] [ORDER BY field [ASC|DESC]] [LIMIT number]
    conditions = condition ((AND|OR) condition)*
    condition  = [quantifier] field operator value
               | LPAREN conditions RPAREN
    quantifier = ALL | ANY | NO
    operator   = comparison | text_op | set_op | null_op
"""
from app.services.report_engine.lexer import tokenize, Token, TokenType, LexerError
from app.services.report_engine.schema import (
    resolve_entity, get_entity_def, get_field_info, ENTITY_FIELDS,
)


class ParseError(Exception):
    def __init__(self, message, pos=None):
        self.pos = pos
        prefix = f' at position {pos}' if pos is not None else ''
        super().__init__(f'{message}{prefix}')


class _Parser:
    """Recursive descent parser for the query DSL."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.entity = None  # set after parsing FIND <entity>

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def advance(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, token_type, value=None):
        token = self.peek()
        if token is None:
            raise ParseError(f'Expected {token_type.name}' + (f' {value}' if value else '') + ', got end of query')
        if token.type != token_type or (value is not None and token.value != value):
            raise ParseError(
                f'Expected {value or token_type.name}, got {token.value!r}',
                token.pos,
            )
        return self.advance()

    def match(self, token_type, value=None):
        token = self.peek()
        if token and token.type == token_type and (value is None or token.value == value):
            return self.advance()
        return None

    def parse_query(self):
        """Parse full query → AST dict."""
        self.expect(TokenType.KEYWORD, 'FIND')

        # Entity
        entity_token = self.peek()
        if not entity_token or entity_token.type != TokenType.IDENTIFIER:
            raise ParseError(
                'Expected entity name (fcs, subs, voyages, loot, activity)',
                entity_token.pos if entity_token else None,
            )
        self.advance()
        entity_name = resolve_entity(entity_token.value)
        if entity_name not in ENTITY_FIELDS:
            raise ParseError(f'Unknown entity: {entity_token.value!r}', entity_token.pos)
        self.entity = entity_name

        # Optional clauses
        conditions = None
        group_by = None
        order_by = None
        limit = None

        if self.match(TokenType.KEYWORD, 'WHERE'):
            conditions = self.parse_conditions()

        if self.match(TokenType.KEYWORD, 'GROUP'):
            self.expect(TokenType.KEYWORD, 'BY')
            field_token = self.expect(TokenType.IDENTIFIER)
            group_by = field_token.value

        if self.match(TokenType.KEYWORD, 'ORDER'):
            self.expect(TokenType.KEYWORD, 'BY')
            field_token = self.expect(TokenType.IDENTIFIER)
            direction = 'ASC'
            dir_token = self.match(TokenType.KEYWORD, 'ASC') or self.match(TokenType.KEYWORD, 'DESC')
            if dir_token:
                direction = dir_token.value
            order_by = {'field': field_token.value, 'direction': direction}

        if self.match(TokenType.KEYWORD, 'LIMIT'):
            limit_token = self.expect(TokenType.VALUE)
            limit = int(limit_token.value)

        # Should have consumed everything
        if self.peek():
            raise ParseError(f'Unexpected token: {self.peek().value!r}', self.peek().pos)

        return {
            'entity': entity_name,
            'conditions': conditions,
            'group_by': group_by,
            'order_by': order_by,
            'limit': limit,
        }

    def parse_conditions(self):
        """Parse a chain of conditions joined by AND/OR."""
        left = self.parse_single_condition()

        while True:
            op_token = self.match(TokenType.KEYWORD, 'AND') or self.match(TokenType.KEYWORD, 'OR')
            if not op_token:
                break
            right = self.parse_single_condition()

            # Flatten same-type logical nodes
            if isinstance(left, dict) and left.get('type') == op_token.value:
                left['children'].append(right)
            else:
                left = {'type': op_token.value, 'children': [left, right]}

        return left

    def parse_single_condition(self):
        """Parse one condition or a parenthesized group."""
        # Parenthesized group
        if self.match(TokenType.LPAREN):
            inner = self.parse_conditions()
            self.expect(TokenType.RPAREN)
            return inner

        # Optional quantifier
        quantifier = None
        quant_token = self.match(TokenType.QUANTIFIER)
        if quant_token:
            quantifier = quant_token.value

        # Field name
        field_token = self.expect(TokenType.IDENTIFIER)
        field_name = field_token.value

        # Validate field and quantifier
        field_info = get_field_info(self.entity, field_name)
        if not field_info:
            # Try to suggest close matches
            from difflib import get_close_matches
            entity_def = get_entity_def(self.entity)
            all_fields = list(entity_def['fields'].keys()) if entity_def else []
            matches = get_close_matches(field_name, all_fields, n=1, cutoff=0.6)
            suggestion = f' — did you mean {matches[0]!r}?' if matches else ''
            raise ParseError(f'Unknown field {field_name!r} on {self.entity}{suggestion}', field_token.pos)

        _, _, ref_type = field_info
        if quantifier and ref_type != 'child':
            raise ParseError(
                f'Quantifier {quantifier} can only be used with child entity fields, '
                f'not {ref_type} field {field_name!r}',
                quant_token.pos,
            )

        # Operator
        op_token = self.expect(TokenType.OPERATOR)
        operator = op_token.value

        # Value (depends on operator)
        value = self._parse_value(operator)

        return {
            'field': field_name,
            'operator': operator,
            'value': value,
            'quantifier': quantifier,
        }

    def _parse_value(self, operator):
        """Parse the value part of a condition based on operator type."""
        if operator in ('IS EMPTY', 'IS NOT EMPTY'):
            return None

        if operator == 'BETWEEN':
            low = self.expect(TokenType.VALUE).value
            self.expect(TokenType.KEYWORD, 'AND')
            high = self.expect(TokenType.VALUE).value
            return [low, high]

        if operator in ('IN', 'NOT IN'):
            self.expect(TokenType.LPAREN)
            values = [self.expect(TokenType.VALUE).value]
            while self.match(TokenType.COMMA):
                values.append(self.expect(TokenType.VALUE).value)
            self.expect(TokenType.RPAREN)
            return values

        # Single value
        return self.expect(TokenType.VALUE).value


def parse(query: str) -> dict:
    """Parse a query string into an AST dict.

    Raises ParseError for invalid queries.
    """
    try:
        tokens = tokenize(query)
    except LexerError as e:
        raise ParseError(str(e), e.pos) from e

    if not tokens:
        raise ParseError('Empty query')

    parser = _Parser(tokens)
    return parser.parse_query()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/test_parser.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/report_engine/parser.py tests/test_parser.py
git commit -m "feat(reports): implement DSL parser with tests"
```

---

## Task 4: Executor — Live Entities (fcs, subs)

**Files:**
- Create: `app/services/report_engine/executor.py`
- Create: `tests/test_executor.py`

- [ ] **Step 1: Write executor tests for live entities**

Create `tests/test_executor.py`:

```python
"""Tests for the report engine executor."""
import pytest
from app.services.report_engine.executor import execute_live, _apply_condition


# Mock fleet data for testing
MOCK_FC_SUMMARIES = [
    {
        'fc_id': '1', 'fc_name': 'Storm Armada', 'world': 'Gilgamesh', 'region': 'NA',
        'fc_gil': 5000000, 'ceruleum': 800, 'repair_kits': 200, 'dive_credits': 10,
        'total_subs': 4, 'ready_subs': 2, 'leveling_subs': 1,
        'gil_per_day': 285000, 'house_size': 'Large', 'tags': ['Mining'],
    },
    {
        'fc_id': '2', 'fc_name': 'Ocean Fleet', 'world': 'Cactuar', 'region': 'NA',
        'fc_gil': 3000000, 'ceruleum': 400, 'repair_kits': 100, 'dive_credits': 5,
        'total_subs': 4, 'ready_subs': 0, 'leveling_subs': 0,
        'gil_per_day': 312000, 'house_size': 'Medium', 'tags': [],
    },
    {
        'fc_id': '3', 'fc_name': 'Deep Divers', 'world': 'Tonberry', 'region': 'JP',
        'fc_gil': 1000000, 'ceruleum': 100, 'repair_kits': 50, 'dive_credits': 0,
        'total_subs': 2, 'ready_subs': 1, 'leveling_subs': 1,
        'gil_per_day': 198000, 'house_size': None, 'tags': ['Mining', 'Leveling'],
    },
]

MOCK_ALL_SUBS = [
    {'name': 'Sub1', 'level': 120, 'build': 'S+S+U+C+', 'parts': ['Shark Hull', 'Shark Stern', 'Unkiu Bow', 'Coelacanth Bridge'],
     'route': 'CSUZ', 'status': 'ready', 'gil_per_day': 71000, 'exp_progress': 100, 'fc_id': '1', 'fc_name': 'Storm Armada', 'world': 'Gilgamesh'},
    {'name': 'Sub2', 'level': 90, 'build': 'W+W+W+W+', 'parts': ['Whale Hull', 'Whale Stern', 'Whale Bow', 'Whale Bridge'],
     'route': 'MOJ', 'status': 'voyaging', 'gil_per_day': 65000, 'exp_progress': 45, 'fc_id': '1', 'fc_name': 'Storm Armada', 'world': 'Gilgamesh'},
    {'name': 'Sub3', 'level': 115, 'build': 'S+S+U+C+', 'parts': ['Shark Hull', 'Shark Stern', 'Unkiu Bow', 'Coelacanth Bridge'],
     'route': 'CSUZ', 'status': 'ready', 'gil_per_day': 78000, 'exp_progress': 80, 'fc_id': '2', 'fc_name': 'Ocean Fleet', 'world': 'Cactuar'},
]


class TestApplyCondition:
    def test_equals_string(self):
        assert _apply_condition({'fc_name': 'Storm Armada'}, 'fc_name', '=', 'Storm Armada')
        assert not _apply_condition({'fc_name': 'Storm Armada'}, 'fc_name', '=', 'Other')

    def test_greater_than(self):
        assert _apply_condition({'level': 120}, 'level', '>', 100)
        assert not _apply_condition({'level': 80}, 'level', '>', 100)

    def test_contains(self):
        assert _apply_condition({'build': 'S+S+U+C+'}, 'build', 'CONTAINS', 'SSUC')
        assert not _apply_condition({'build': 'W+W+W+W+'}, 'build', 'CONTAINS', 'SSUC')

    def test_in_list(self):
        assert _apply_condition({'route': 'CSUZ'}, 'route', 'IN', ['CSUZ', 'MOJ'])
        assert not _apply_condition({'route': 'OJ'}, 'route', 'IN', ['CSUZ', 'MOJ'])

    def test_between(self):
        assert _apply_condition({'level': 100}, 'level', 'BETWEEN', [90, 110])
        assert not _apply_condition({'level': 80}, 'level', 'BETWEEN', [90, 110])

    def test_is_empty(self):
        assert _apply_condition({'tags': []}, 'tags', 'IS EMPTY', None)
        assert not _apply_condition({'tags': ['Mining']}, 'tags', 'IS EMPTY', None)

    def test_is_not_empty(self):
        assert _apply_condition({'tags': ['Mining']}, 'tags', 'IS NOT EMPTY', None)

    def test_set_contains(self):
        assert _apply_condition({'tags': ['Mining', 'Leveling']}, 'tags', 'CONTAINS', 'Mining')
        assert not _apply_condition({'tags': ['Mining']}, 'tags', 'CONTAINS', 'Leveling')


class TestExecuteLive:
    def test_find_all_fcs(self):
        ast = {'entity': 'fcs', 'conditions': None, 'group_by': None, 'order_by': None, 'limit': None}
        results = execute_live(ast, MOCK_FC_SUMMARIES, MOCK_ALL_SUBS)
        assert len(results) == 3

    def test_filter_by_region(self):
        ast = {
            'entity': 'fcs',
            'conditions': {'field': 'region', 'operator': '=', 'value': 'NA', 'quantifier': None},
            'group_by': None, 'order_by': None, 'limit': None,
        }
        results = execute_live(ast, MOCK_FC_SUMMARIES, MOCK_ALL_SUBS)
        assert len(results) == 2

    def test_quantifier_all(self):
        ast = {
            'entity': 'fcs',
            'conditions': {'field': 'subs.level', 'operator': '>', 'value': 100, 'quantifier': 'ALL'},
            'group_by': None, 'order_by': None, 'limit': None,
        }
        results = execute_live(ast, MOCK_FC_SUMMARIES, MOCK_ALL_SUBS)
        # Only Ocean Fleet (fc_id 2) has all subs > 100. Storm Armada has Sub2 at level 90.
        assert len(results) == 1
        assert results[0]['fc_name'] == 'Ocean Fleet'

    def test_quantifier_any(self):
        ast = {
            'entity': 'fcs',
            'conditions': {'field': 'subs.level', 'operator': '>', 'value': 100, 'quantifier': 'ANY'},
            'group_by': None, 'order_by': None, 'limit': None,
        }
        results = execute_live(ast, MOCK_FC_SUMMARIES, MOCK_ALL_SUBS)
        assert len(results) == 2  # Storm Armada (Sub1=120) and Ocean Fleet (Sub3=115)

    def test_quantifier_no(self):
        ast = {
            'entity': 'fcs',
            'conditions': {'field': 'subs.build', 'operator': 'CONTAINS', 'value': 'SSUC', 'quantifier': 'NO'},
            'group_by': None, 'order_by': None, 'limit': None,
        }
        results = execute_live(ast, MOCK_FC_SUMMARIES, MOCK_ALL_SUBS)
        # Deep Divers has no subs in our mock data, so NO condition is vacuously true
        assert any(r['fc_name'] == 'Deep Divers' for r in results)

    def test_find_subs_direct(self):
        ast = {
            'entity': 'subs',
            'conditions': {'field': 'level', 'operator': '>=', 'value': 100, 'quantifier': None},
            'group_by': None, 'order_by': None, 'limit': None,
        }
        results = execute_live(ast, MOCK_FC_SUMMARIES, MOCK_ALL_SUBS)
        assert len(results) == 2  # Sub1 (120) and Sub3 (115)

    def test_subs_parent_reference(self):
        ast = {
            'entity': 'subs',
            'conditions': {'field': 'fc.world', 'operator': '=', 'value': 'Gilgamesh', 'quantifier': None},
            'group_by': None, 'order_by': None, 'limit': None,
        }
        results = execute_live(ast, MOCK_FC_SUMMARIES, MOCK_ALL_SUBS)
        assert len(results) == 2  # Sub1 and Sub2

    def test_order_by(self):
        ast = {
            'entity': 'fcs',
            'conditions': None,
            'group_by': None,
            'order_by': {'field': 'gil_per_day', 'direction': 'DESC'},
            'limit': None,
        }
        results = execute_live(ast, MOCK_FC_SUMMARIES, MOCK_ALL_SUBS)
        assert results[0]['fc_name'] == 'Ocean Fleet'

    def test_limit(self):
        ast = {
            'entity': 'fcs', 'conditions': None,
            'group_by': None, 'order_by': None, 'limit': 2,
        }
        results = execute_live(ast, MOCK_FC_SUMMARIES, MOCK_ALL_SUBS)
        assert len(results) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/test_executor.py -v
```

- [ ] **Step 3: Implement the executor for live entities**

Create `app/services/report_engine/executor.py`:

```python
"""Executor for the Armada report query engine.

Evaluates an AST against live FleetManager data (fcs, subs)
or SQLAlchemy DB models (voyages, loot, activity).
"""
from app.services.report_engine.schema import (
    ENTITY_FIELDS, CHILD_ENTITY_FIELDS, get_field_info, FieldType,
)


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


def _evaluate_condition(record, condition, entity_name, all_subs=None, fc_summaries=None):
    """Evaluate a single condition or logical group against a record.

    For child entity conditions (quantifiers), uses all_subs to check children.
    """
    # Logical group (AND/OR)
    if 'type' in condition:
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
        fc_id = record.get('fc_id')
        fc_subs = [s for s in (all_subs or []) if s.get('fc_id') == fc_id]

        # For child fields like subs.level, source_key is 'level' from subs schema
        child_prefix, child_field = field.split('.', 1)
        child_entity_def = ENTITY_FIELDS.get(child_prefix)
        if child_entity_def and child_field in child_entity_def['fields']:
            child_source_key = child_entity_def['fields'][child_field][0]
        else:
            child_source_key = child_field

        results = [_apply_condition(sub, child_source_key, operator, value) for sub in fc_subs]

        if not results:
            # No children: ALL is vacuously true, ANY is false, NO is true
            if quantifier == 'ALL' or quantifier == 'NO':
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
    order_by = ast.get('order_by')
    limit = ast.get('limit')

    if entity == 'fcs':
        data = fc_summaries
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
        source_key = _resolve_source_key(entity, order_by['field'])
        reverse = order_by['direction'] == 'DESC'
        results.sort(key=lambda r: (r.get(source_key) is None, r.get(source_key, 0)), reverse=reverse)

    # Limit (cap at 1000)
    max_limit = min(limit or 1000, 1000)
    results = results[:max_limit]

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/test_executor.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/report_engine/executor.py tests/test_executor.py
git commit -m "feat(reports): implement executor for live entities (fcs, subs)"
```

---

## Task 5: Executor — DB Entities (voyages, loot, activity)

**Files:**
- Modify: `app/services/report_engine/executor.py`

- [ ] **Step 1: Add DB executor function**

Add to `app/services/report_engine/executor.py`:

```python
from datetime import datetime
from sqlalchemy import and_, or_, func
from app import db


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
        return column.ilike(f'%{value}%')
    if operator == 'NOT CONTAINS':
        return ~column.ilike(f'%{value}%')
    if operator == 'STARTS WITH':
        return column.ilike(f'{value}%')
    if operator == 'ENDS WITH':
        return column.ilike(f'%{value}')
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
                col = getattr(Voyage, voyage_col)
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
            neg_filter = None
            if isinstance(child_source_key, list):
                neg_parts = []
                for col_name in child_source_key:
                    f = _build_sqlalchemy_filter(child_model, col_name, operator, value)
                    if f is not None:
                        neg_parts.append(f)
                if neg_parts:
                    neg_filter = or_(*neg_parts)
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
    group_by = ast.get('group_by')
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
        # Add parent fields if present
        parent_map = entity_def.get('parent_field_map', {})
        for parent_field, mapped_key in parent_map.items():
            if mapped_key.startswith('_'):
                continue  # Skip special join markers
            record[parent_field] = getattr(row, mapped_key, None)
        results.append(record)

    return results
```

- [ ] **Step 2: Commit**

```bash
git add app/services/report_engine/executor.py
git commit -m "feat(reports): implement executor for DB entities (voyages, loot, activity)"
```

---

## Task 6: Result Formatter

**Files:**
- Create: `app/services/report_engine/formatter.py`

- [ ] **Step 1: Implement the formatter**

Create `app/services/report_engine/formatter.py`:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add app/services/report_engine/formatter.py
git commit -m "feat(reports): implement result formatter (table, summary, CSV)"
```

---

## Task 7: Report Engine Public API

**Files:**
- Modify: `app/services/report_engine/__init__.py`

- [ ] **Step 1: Wire up the public API**

Update `app/services/report_engine/__init__.py`:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add app/services/report_engine/__init__.py
git commit -m "feat(reports): wire up report engine public API"
```

---

## Task 8: SavedReport Model

**Files:**
- Create: `app/models/saved_report.py`
- Modify: `app/models/__init__.py`
- Modify: `app/__init__.py` (line 99, add model import for db.create_all)

- [ ] **Step 1: Create the model**

Create `app/models/saved_report.py`:

```python
"""Saved report model for persisting user queries."""
from datetime import datetime
from app import db


class SavedReport(db.Model):
    __tablename__ = 'saved_reports'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    query_text = db.Column(db.Text, nullable=False)
    display_config = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<SavedReport {self.name!r}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'query_text': self.query_text,
            'display_config': self.display_config or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
```

- [ ] **Step 2: Register the model**

Add to `app/models/__init__.py` after the GilRecord import:

```python
from app.models.saved_report import SavedReport
```

Add `'SavedReport'` to the `__all__` list.

Add to `app/__init__.py` after line 98 (`from app.models import route_override  # noqa: F401`):

```python
        from app.models import saved_report  # noqa: F401
```

- [ ] **Step 3: Commit**

```bash
git add app/models/saved_report.py app/models/__init__.py app/__init__.py
git commit -m "feat(reports): add SavedReport model"
```

---

## Task 9: Reports Blueprint & Routes

**Files:**
- Create: `app/routes/reports.py`
- Modify: `app/__init__.py` (blueprint registration)

- [ ] **Step 1: Create the reports route blueprint**

Create `app/routes/reports.py`:

```python
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
```

- [ ] **Step 2: Register the blueprint**

Add to `app/__init__.py` after line 69 (`from app.routes.gil_config import gil_config_bp`):

```python
    from app.routes.reports import reports_bp
```

Add after line 86 (`app.register_blueprint(gil_config_bp, url_prefix='/settings/gil-config')`):

```python
    app.register_blueprint(reports_bp, url_prefix='/reports')
```

- [ ] **Step 3: Add Reports to navigation**

In `app/templates/base.html`, insert a new `<li>` after the Gil `</li>` (after line 278), before the closing `</ul>` on line 279 that ends the left nav group:

```html
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint and request.endpoint.startswith('reports.') %}active{% endif %}"
                           href="{{ url_for('reports.index') }}">
                            <i class="bi bi-clipboard-data"></i> Reports
                        </a>
                    </li>
```

- [ ] **Step 4: Commit**

```bash
git add app/routes/reports.py app/__init__.py app/templates/base.html
git commit -m "feat(reports): add reports blueprint, routes, and nav link"
```

---

## Task 10: Reports Page Template

**Files:**
- Create: `app/templates/reports.html`

- [ ] **Step 1: Create the reports template**

Create `app/templates/reports.html`:

```html
{% extends "base.html" %}

{% block title %}Reports{% endblock %}

{% block extra_css %}
<style>
    .query-builder {
        background: var(--bs-dark);
        border: 1px solid var(--bs-border-color);
        border-radius: 0.5rem;
        padding: 1rem;
    }
    .condition-row {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 0.5rem;
        flex-wrap: wrap;
    }
    .condition-row select, .condition-row input {
        font-size: 0.85rem;
        padding: 0.25rem 0.5rem;
    }
    .condition-row .form-select {
        width: auto;
        min-width: 120px;
    }
    .condition-row .value-input {
        min-width: 150px;
        max-width: 250px;
    }
    .condition-row .btn-remove {
        padding: 0.15rem 0.4rem;
        font-size: 0.75rem;
    }
    .query-text-editor {
        font-family: 'Consolas', 'Monaco', monospace;
        font-size: 0.9rem;
        min-height: 100px;
        background: var(--bs-body-bg);
        color: var(--bs-body-color);
        border: 1px solid var(--bs-border-color);
        border-radius: 0.375rem;
        padding: 0.75rem;
        width: 100%;
        resize: vertical;
    }
    .query-text-editor:focus {
        border-color: #4a9eff;
        box-shadow: 0 0 0 0.2rem rgba(74, 158, 255, 0.25);
        outline: none;
    }
    .tab-btn {
        background: var(--bs-dark);
        border: 1px solid var(--bs-border-color);
        color: var(--bs-secondary-color);
        padding: 0.35rem 1rem;
        cursor: pointer;
        font-size: 0.85rem;
    }
    .tab-btn:first-child { border-radius: 0.375rem 0 0 0.375rem; }
    .tab-btn:last-child { border-radius: 0 0.375rem 0.375rem 0; }
    .tab-btn.active {
        background: #4a9eff;
        color: white;
        border-color: #4a9eff;
    }
    .results-table {
        font-size: 0.85rem;
    }
    .results-table th {
        cursor: pointer;
        user-select: none;
        white-space: nowrap;
    }
    .results-table th:hover {
        color: #4a9eff;
    }
    .parse-error {
        background: rgba(220, 53, 69, 0.1);
        border: 1px solid var(--bs-danger);
        border-radius: 0.375rem;
        padding: 0.5rem 0.75rem;
        color: var(--bs-danger);
        font-size: 0.85rem;
        margin-top: 0.5rem;
    }
    .summary-card {
        background: var(--bs-dark);
        border: 1px solid var(--bs-border-color);
        border-radius: 0.375rem;
        padding: 0.75rem;
    }
    .quantifier-select {
        min-width: 70px;
    }
    #saved-reports-list .list-group-item {
        cursor: pointer;
        font-size: 0.85rem;
    }
    #saved-reports-list .list-group-item:hover {
        background: rgba(74, 158, 255, 0.1);
    }
</style>
{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
    <h2><i class="bi bi-clipboard-data"></i> Reports</h2>
    <div class="d-flex gap-2">
        <div class="dropdown">
            <button class="btn btn-sm btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown" id="savedReportsBtn">
                <i class="bi bi-folder2-open"></i> Saved Reports
            </button>
            <div class="dropdown-menu dropdown-menu-end p-2" style="min-width: 250px;">
                <div id="saved-reports-list" class="list-group list-group-flush">
                    <div class="text-muted small text-center py-2">Loading...</div>
                </div>
            </div>
        </div>
        <button class="btn btn-sm btn-outline-primary" onclick="saveReport()">
            <i class="bi bi-floppy"></i> Save
        </button>
    </div>
</div>

<!-- Query Builder -->
<div class="query-builder mb-3">
    <div class="d-flex justify-content-between align-items-center mb-2">
        <div>
            <button class="tab-btn active" data-tab="visual" onclick="switchTab('visual')">Visual</button>
            <button class="tab-btn" data-tab="query" onclick="switchTab('query')">Query</button>
        </div>
        <div class="d-flex align-items-center gap-2">
            <label class="text-muted small mb-0">Entity:</label>
            <select class="form-select form-select-sm" id="entity-select" style="width: auto; min-width: 140px;"
                    onchange="onEntityChange()">
                <option value="fcs">FCs</option>
                <option value="subs">Submarines</option>
                <option value="voyages">Voyages</option>
                <option value="loot">Loot</option>
                <option value="activity">Activity</option>
            </select>
        </div>
    </div>

    <!-- Visual Builder Tab -->
    <div id="tab-visual">
        <div id="conditions-container">
            <!-- Condition rows rendered by JS -->
        </div>
        <button class="btn btn-sm btn-outline-info mt-1" onclick="addCondition()">
            <i class="bi bi-plus"></i> Add condition
        </button>
    </div>

    <!-- Query Text Tab -->
    <div id="tab-query" style="display: none;">
        <textarea class="query-text-editor" id="query-editor"
                  placeholder='FIND fcs WHERE ALL subs.level > 111 AND NO subs.build CONTAINS "SSUC"'
                  spellcheck="false"></textarea>
    </div>

    <!-- Error display -->
    <div id="parse-error" class="parse-error" style="display: none;"></div>

    <!-- Run button -->
    <div class="d-flex justify-content-end mt-2">
        <button class="btn btn-primary btn-sm" onclick="runQuery()">
            <i class="bi bi-play-fill"></i> Run Query
        </button>
    </div>
</div>

<!-- Results Area -->
<div id="results-area" style="display: none;">
    <div class="d-flex justify-content-between align-items-center mb-2">
        <div id="results-info" class="text-muted small"></div>
        <div class="d-flex gap-2">
            <div>
                <button class="tab-btn active" data-view="table" onclick="switchView('table')">Table</button>
                <button class="tab-btn" data-view="summary" onclick="switchView('summary')">Summary</button>
            </div>
            <button class="btn btn-sm btn-outline-secondary" onclick="exportCsv()">
                <i class="bi bi-download"></i> CSV
            </button>
        </div>
    </div>

    <!-- Table View -->
    <div id="view-table">
        <div class="table-responsive">
            <table class="table table-dark table-striped table-hover results-table" id="results-table">
                <thead><tr id="table-header"></tr></thead>
                <tbody id="table-body"></tbody>
            </table>
        </div>
        <nav id="pagination-nav" style="display: none;">
            <ul class="pagination pagination-sm justify-content-center" id="pagination"></ul>
        </nav>
    </div>

    <!-- Summary View -->
    <div id="view-summary" style="display: none;"></div>
</div>

<!-- Loading spinner -->
<div id="loading" style="display: none;" class="text-center py-4">
    <div class="spinner-border text-primary" role="status">
        <span class="visually-hidden">Running query...</span>
    </div>
</div>

<script src="{{ url_for('static', filename='js/reports.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add app/templates/reports.html
git commit -m "feat(reports): add reports page template"
```

---

## Task 11: Reports JavaScript — Core & Visual Builder

**Files:**
- Create: `app/static/js/reports.js`

- [ ] **Step 1: Create the reports JavaScript**

Create `app/static/js/reports.js`. This is a large file — the full implementation of the visual builder, query text editor, sync logic, results rendering, saved reports management, and CSV export.

```javascript
/**
 * Armada Reports — Query Builder & Results
 */
class ArmadaReports {
    constructor() {
        this.schema = null;
        this.currentEntity = 'fcs';
        this.activeTab = 'visual';
        this.activeView = 'table';
        this.conditions = [];
        this.conditionId = 0;
        this.currentResults = null;
        this.currentQueryText = '';
        this.currentPage = 1;
        this.savedReportId = null;

        this.init();
    }

    async init() {
        await this.loadSchema();
        this.loadSavedReports();
        this.syncVisualToText();
    }

    async loadSchema() {
        try {
            const resp = await fetch('/reports/schema');
            this.schema = await resp.json();
        } catch (e) {
            console.error('Failed to load schema:', e);
        }
    }

    // ── Tab Switching ──

    switchTab(tab) {
        this.activeTab = tab;
        document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tab);
        });
        document.getElementById('tab-visual').style.display = tab === 'visual' ? '' : 'none';
        document.getElementById('tab-query').style.display = tab === 'query' ? '' : 'none';

        if (tab === 'query') {
            this.syncVisualToText();
        } else {
            // Try to parse text back to visual
            this.syncTextToVisual();
        }
    }

    switchView(view) {
        this.activeView = view;
        document.querySelectorAll('.tab-btn[data-view]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === view);
        });
        document.getElementById('view-table').style.display = view === 'table' ? '' : 'none';
        document.getElementById('view-summary').style.display = view === 'summary' ? '' : 'none';

        if (this.currentQueryText) {
            this.runQuery();
        }
    }

    // ── Entity Change ──

    onEntityChange() {
        this.currentEntity = document.getElementById('entity-select').value;
        this.conditions = [];
        this.renderConditions();
        this.syncVisualToText();
        this.hideError();
    }

    // ── Conditions Management ──

    getFieldsForEntity(entity) {
        if (!this.schema) return {};
        const entityDef = this.schema.entities[entity];
        return entityDef ? entityDef.fields : {};
    }

    addCondition() {
        this.conditionId++;
        this.conditions.push({
            id: this.conditionId,
            logic: this.conditions.length > 0 ? 'AND' : null,
            quantifier: null,
            field: '',
            operator: '=',
            value: '',
        });
        this.renderConditions();
        this.syncVisualToText();
    }

    removeCondition(id) {
        this.conditions = this.conditions.filter(c => c.id !== id);
        if (this.conditions.length > 0) {
            this.conditions[0].logic = null;
        }
        this.renderConditions();
        this.syncVisualToText();
    }

    updateCondition(id, key, value) {
        const cond = this.conditions.find(c => c.id === id);
        if (!cond) return;
        cond[key] = value;

        if (key === 'field') {
            // Reset operator and value when field changes
            const fields = this.getFieldsForEntity(this.currentEntity);
            const fieldDef = fields[value];
            if (fieldDef) {
                cond.operator = fieldDef.operators[0] || '=';
                cond.value = '';
                // Auto-show quantifier for child fields
                cond.quantifier = fieldDef.ref_type === 'child' ? 'ALL' : null;
            }
        }

        this.renderConditions();
        this.syncVisualToText();
    }

    renderConditions() {
        const container = document.getElementById('conditions-container');
        const fields = this.getFieldsForEntity(this.currentEntity);

        container.innerHTML = this.conditions.map(cond => {
            const fieldDef = fields[cond.field] || {};
            const operators = fieldDef.operators || ['=', '!=', '>', '<', '>=', '<=', 'CONTAINS'];
            const isChild = fieldDef.ref_type === 'child';
            const enumValues = fieldDef.enum_values;

            const showQuantifier = isChild;
            const isNullOp = cond.operator === 'IS EMPTY' || cond.operator === 'IS NOT EMPTY';

            return `
                <div class="condition-row" data-id="${cond.id}">
                    ${cond.logic !== null ? `
                        <select class="form-select form-select-sm" style="width: 80px;"
                                onchange="reports.updateCondition(${cond.id}, 'logic', this.value)">
                            <option value="AND" ${cond.logic === 'AND' ? 'selected' : ''}>AND</option>
                            <option value="OR" ${cond.logic === 'OR' ? 'selected' : ''}>OR</option>
                        </select>
                    ` : '<span style="width: 80px; display: inline-block;"></span>'}
                    ${showQuantifier ? `
                        <select class="form-select form-select-sm quantifier-select"
                                onchange="reports.updateCondition(${cond.id}, 'quantifier', this.value)">
                            <option value="ALL" ${cond.quantifier === 'ALL' ? 'selected' : ''}>ALL</option>
                            <option value="ANY" ${cond.quantifier === 'ANY' ? 'selected' : ''}>ANY</option>
                            <option value="NO" ${cond.quantifier === 'NO' ? 'selected' : ''}>NO</option>
                        </select>
                    ` : ''}
                    <select class="form-select form-select-sm"
                            onchange="reports.updateCondition(${cond.id}, 'field', this.value)">
                        <option value="">Select field...</option>
                        ${this._renderFieldOptions(fields, cond.field)}
                    </select>
                    <select class="form-select form-select-sm" style="width: auto;"
                            onchange="reports.updateCondition(${cond.id}, 'operator', this.value)">
                        ${operators.map(op =>
                            `<option value="${op}" ${cond.operator === op ? 'selected' : ''}>${op}</option>`
                        ).join('')}
                    </select>
                    ${!isNullOp ? `
                        ${enumValues ? `
                            <select class="form-select form-select-sm value-input"
                                    onchange="reports.updateCondition(${cond.id}, 'value', this.value)">
                                <option value="">Select...</option>
                                ${enumValues.map(v =>
                                    `<option value="${v}" ${cond.value === v ? 'selected' : ''}>${v}</option>`
                                ).join('')}
                            </select>
                        ` : `
                            <input type="${fieldDef.type === 'number' ? 'number' : 'text'}"
                                   class="form-control form-control-sm value-input"
                                   value="${cond.value}"
                                   placeholder="Value..."
                                   onchange="reports.updateCondition(${cond.id}, 'value', this.value)"
                                   onkeydown="if(event.key==='Enter'){event.preventDefault();reports.runQuery();}">
                        `}
                    ` : ''}
                    <button class="btn btn-outline-danger btn-remove"
                            onclick="reports.removeCondition(${cond.id})">
                        <i class="bi bi-x"></i>
                    </button>
                </div>
            `;
        }).join('');
    }

    _renderFieldOptions(fields, selectedField) {
        const directFields = [];
        const parentFields = [];
        const childFields = [];

        for (const [name, def] of Object.entries(fields)) {
            if (def.ref_type === 'parent') parentFields.push(name);
            else if (def.ref_type === 'child') childFields.push(name);
            else directFields.push(name);
        }

        let html = '';
        if (directFields.length) {
            html += `<optgroup label="Fields">`;
            html += directFields.map(f =>
                `<option value="${f}" ${selectedField === f ? 'selected' : ''}>${f}</option>`
            ).join('');
            html += `</optgroup>`;
        }
        if (parentFields.length) {
            html += `<optgroup label="Parent (FC)">`;
            html += parentFields.map(f =>
                `<option value="${f}" ${selectedField === f ? 'selected' : ''}>${f}</option>`
            ).join('');
            html += `</optgroup>`;
        }
        if (childFields.length) {
            html += `<optgroup label="Children">`;
            html += childFields.map(f =>
                `<option value="${f}" ${selectedField === f ? 'selected' : ''}>${f}</option>`
            ).join('');
            html += `</optgroup>`;
        }
        return html;
    }

    // ── Sync: Visual ↔ Text ──

    syncVisualToText() {
        let query = `FIND ${this.currentEntity}`;
        const validConditions = this.conditions.filter(c => c.field && c.operator);

        if (validConditions.length > 0) {
            query += ' WHERE ';
            query += validConditions.map((cond, i) => {
                let part = '';
                if (i > 0 && cond.logic) part += `${cond.logic} `;
                if (cond.quantifier) part += `${cond.quantifier} `;
                part += cond.field;
                part += ` ${cond.operator}`;
                if (cond.operator !== 'IS EMPTY' && cond.operator !== 'IS NOT EMPTY') {
                    const fields = this.getFieldsForEntity(this.currentEntity);
                    const fieldDef = fields[cond.field] || {};
                    if (fieldDef.type === 'number') {
                        part += ` ${cond.value}`;
                    } else {
                        part += ` "${cond.value}"`;
                    }
                }
                return part;
            }).join(' ');
        }

        this.currentQueryText = query;
        document.getElementById('query-editor').value = query;
    }

    syncTextToVisual() {
        const text = document.getElementById('query-editor').value.trim();
        if (!text) return;
        this.currentQueryText = text;

        // Extract entity
        const findMatch = text.match(/^FIND\s+(\w+)/i);
        if (!findMatch) return;

        const entity = findMatch[1].toLowerCase();
        const entityMap = { submarines: 'subs' };
        this.currentEntity = entityMap[entity] || entity;
        document.getElementById('entity-select').value = this.currentEntity;

        // Check if there are WHERE conditions
        const whereMatch = text.match(/WHERE\s+(.*?)(?:\s+(?:GROUP|ORDER|LIMIT)\s|$)/i);
        if (!whereMatch) {
            this.conditions = [];
            this.renderConditions();
            this.hideError();
            return;
        }

        // Show info banner that conditions should be edited in Query tab
        if (this.conditions.length === 0 && whereMatch[1].trim()) {
            this.showError('This query has conditions that were entered in the Query tab. Switch to the Query tab to edit them, or clear and rebuild here.');
        }
        // Don't clear conditions if user has been building in visual mode
    }

    // ── Query Execution ──

    async runQuery() {
        const queryText = this.activeTab === 'query'
            ? document.getElementById('query-editor').value.trim()
            : this.currentQueryText;

        if (!queryText) {
            this.showError('Enter a query to run');
            return;
        }

        this.hideError();
        document.getElementById('loading').style.display = '';
        document.getElementById('results-area').style.display = 'none';

        try {
            const resp = await fetch('/reports/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: queryText,
                    view_mode: this.activeView,
                    page: this.currentPage,
                }),
            });

            const data = await resp.json();
            if (!resp.ok || data.error) {
                this.showError(data.error || 'Query failed');
                document.getElementById('loading').style.display = 'none';
                return;
            }

            this.currentResults = data;
            this.currentQueryText = queryText;

            if (this.activeView === 'summary') {
                this.renderSummary(data);
            } else {
                this.renderTable(data);
            }

            document.getElementById('loading').style.display = 'none';
            document.getElementById('results-area').style.display = '';
        } catch (e) {
            this.showError('Network error: ' + e.message);
            document.getElementById('loading').style.display = 'none';
        }
    }

    // ── Results Rendering ──

    renderTable(data) {
        const header = document.getElementById('table-header');
        const body = document.getElementById('table-body');

        header.innerHTML = (data.columns || []).map(col =>
            `<th onclick="reports.sortBy('${col.name}')">${col.name}</th>`
        ).join('');

        body.innerHTML = (data.rows || []).map(row => {
            return '<tr>' + (data.columns || []).map(col => {
                let val = row[col.name];
                if (val === null || val === undefined) val = '';
                if (typeof val === 'object') val = JSON.stringify(val);
                return `<td>${this._escapeHtml(String(val))}</td>`;
            }).join('') + '</tr>';
        }).join('');

        const info = document.getElementById('results-info');
        let infoText = `${data.total} results`;
        if (data.truncated) infoText += ' (capped at 1000)';
        info.textContent = infoText;

        this.renderPagination(data);
    }

    renderPagination(data) {
        const nav = document.getElementById('pagination-nav');
        const pagination = document.getElementById('pagination');
        const totalPages = Math.ceil(data.total / data.per_page);

        if (totalPages <= 1) {
            nav.style.display = 'none';
            return;
        }

        nav.style.display = '';
        let html = '';

        html += `<li class="page-item ${data.page <= 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="event.preventDefault();reports.goToPage(${data.page - 1})">‹</a></li>`;

        for (let i = 1; i <= totalPages; i++) {
            if (i === 1 || i === totalPages || Math.abs(i - data.page) <= 2) {
                html += `<li class="page-item ${i === data.page ? 'active' : ''}">
                    <a class="page-link" href="#" onclick="event.preventDefault();reports.goToPage(${i})">${i}</a></li>`;
            } else if (Math.abs(i - data.page) === 3) {
                html += `<li class="page-item disabled"><span class="page-link">…</span></li>`;
            }
        }

        html += `<li class="page-item ${data.page >= totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="event.preventDefault();reports.goToPage(${data.page + 1})">›</a></li>`;

        pagination.innerHTML = html;
    }

    goToPage(page) {
        this.currentPage = page;
        this.runQuery();
    }

    renderSummary(data) {
        const container = document.getElementById('view-summary');
        let html = `<div class="mb-3"><strong>Total: ${data.total} records</strong></div>`;

        if (data.groups) {
            html += `<p class="text-muted small">Grouped by: ${data.group_by}</p>`;
            data.groups.forEach(group => {
                html += `<div class="summary-card mb-2">`;
                html += `<h6>${group.group} <span class="text-muted">(${group.count})</span></h6>`;
                html += this._renderFieldAggregates(group.fields);
                html += `</div>`;
            });
        } else if (data.fields) {
            html += this._renderFieldAggregates(data.fields);
        }

        container.innerHTML = html;
        document.getElementById('results-info').textContent = `${data.total} results`;
    }

    _renderFieldAggregates(fields) {
        let html = '<div class="row g-2">';
        for (const [name, agg] of Object.entries(fields)) {
            if (agg.count === 0) continue;
            html += `<div class="col-md-4 col-lg-3"><div class="summary-card">`;
            html += `<div class="text-muted small mb-1">${name}</div>`;
            if (agg.type === 'number') {
                html += `<div>Count: ${agg.count}</div>`;
                html += `<div>Sum: ${agg.sum.toLocaleString()}</div>`;
                html += `<div>Avg: ${agg.avg.toLocaleString()}</div>`;
                html += `<div>Min: ${agg.min?.toLocaleString() ?? '—'} / Max: ${agg.max?.toLocaleString() ?? '—'}</div>`;
            } else if (agg.type === 'string') {
                html += `<div>${agg.distinct} distinct values</div>`;
                if (agg.top && agg.top.length) {
                    html += `<div class="small text-muted mt-1">Top: ${agg.top.slice(0, 3).map(t => t[0]).join(', ')}</div>`;
                }
            } else if (agg.type === 'datetime') {
                html += `<div>Count: ${agg.count}</div>`;
                html += `<div class="small">From: ${agg.min || '—'}</div>`;
                html += `<div class="small">To: ${agg.max || '—'}</div>`;
            }
            html += `</div></div>`;
        }
        html += '</div>';
        return html;
    }

    // ── Saved Reports ──

    async loadSavedReports() {
        try {
            const resp = await fetch('/reports/saved');
            const reports = await resp.json();
            const list = document.getElementById('saved-reports-list');

            if (!reports.length) {
                list.innerHTML = '<div class="text-muted small text-center py-2">No saved reports</div>';
                return;
            }

            list.innerHTML = reports.map(r => `
                <div class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                     onclick="reports.loadReport(${r.id}, '${this._escapeHtml(r.query_text)}')">
                    <span>${this._escapeHtml(r.name)}</span>
                    <button class="btn btn-sm btn-outline-danger" onclick="event.stopPropagation();reports.deleteReport(${r.id})">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            `).join('');
        } catch (e) {
            console.error('Failed to load saved reports:', e);
        }
    }

    loadReport(id, queryText) {
        this.savedReportId = id;
        document.getElementById('query-editor').value = queryText;
        this.currentQueryText = queryText;
        this.switchTab('query');
        this.runQuery();
    }

    async saveReport() {
        const name = prompt('Report name:');
        if (!name) return;

        const queryText = this.activeTab === 'query'
            ? document.getElementById('query-editor').value.trim()
            : this.currentQueryText;

        if (!queryText) {
            this.showError('Build a query before saving');
            return;
        }

        try {
            const resp = await fetch('/reports/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name,
                    query: queryText,
                    display_config: { view_mode: this.activeView },
                }),
            });

            if (resp.ok) {
                this.loadSavedReports();
            }
        } catch (e) {
            this.showError('Failed to save report');
        }
    }

    async deleteReport(id) {
        if (!confirm('Delete this saved report?')) return;
        try {
            await fetch(`/reports/saved/${id}`, { method: 'DELETE' });
            this.loadSavedReports();
        } catch (e) {
            this.showError('Failed to delete report');
        }
    }

    // ── CSV Export ──

    async exportCsv() {
        if (!this.currentQueryText) return;
        try {
            const resp = await fetch('/reports/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: this.currentQueryText }),
            });
            if (!resp.ok) {
                const err = await resp.json();
                this.showError(err.error || 'Export failed');
                return;
            }
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'report.csv';
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            this.showError('Export failed: ' + e.message);
        }
    }

    // ── Helpers ──

    showError(msg) {
        const el = document.getElementById('parse-error');
        el.textContent = msg;
        el.style.display = '';
    }

    hideError() {
        document.getElementById('parse-error').style.display = 'none';
    }

    sortBy(field) {
        // Append or toggle ORDER BY in query text
        const text = this.currentQueryText;
        const orderMatch = text.match(/\s+ORDER\s+BY\s+(\w+(?:\.\w+)?)\s*(ASC|DESC)?/i);
        if (orderMatch && orderMatch[1] === field) {
            const dir = (orderMatch[2] || 'ASC').toUpperCase() === 'ASC' ? 'DESC' : 'ASC';
            this.currentQueryText = text.replace(/\s+ORDER\s+BY\s+\w+(?:\.\w+)?\s*(?:ASC|DESC)?/i, ` ORDER BY ${field} ${dir}`);
        } else if (orderMatch) {
            this.currentQueryText = text.replace(/\s+ORDER\s+BY\s+\w+(?:\.\w+)?\s*(?:ASC|DESC)?/i, ` ORDER BY ${field} ASC`);
        } else {
            this.currentQueryText = text + ` ORDER BY ${field} ASC`;
        }
        document.getElementById('query-editor').value = this.currentQueryText;
        this.runQuery();
    }

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

// Global instance and helper functions for onclick handlers
let reports;
document.addEventListener('DOMContentLoaded', () => {
    reports = new ArmadaReports();
});

function switchTab(tab) { reports.switchTab(tab); }
function switchView(view) { reports.switchView(view); }
function onEntityChange() { reports.onEntityChange(); }
function addCondition() { reports.addCondition(); }
function runQuery() { reports.runQuery(); }
function saveReport() { reports.saveReport(); }
function exportCsv() { reports.exportCsv(); }
```

- [ ] **Step 2: Commit**

```bash
git add app/static/js/reports.js
git commit -m "feat(reports): add reports page JavaScript (visual builder, results, saved reports)"
```

---

## Task 12: Integration Testing & Polish

**Files:**
- Modify: Various files for bug fixes found during manual testing

- [ ] **Step 1: Run the app and verify the page loads**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python run.py
```

Open `http://localhost:5000/reports` in a browser. Verify:
- Page loads without errors
- "Reports" nav item is visible and active
- Entity dropdown works
- Visual builder renders
- Tab switching works

- [ ] **Step 2: Test a basic query**

In the Query tab, enter: `FIND fcs`
Click Run. Verify results appear (or helpful empty message if no data).

- [ ] **Step 3: Test the visual builder**

Switch to Visual tab, select "FCs" entity, add a condition:
- Field: `region`, Operator: `=`, Value: `NA`
- Verify query text syncs
- Click Run

- [ ] **Step 4: Test saved reports**

- Save a report with a name
- Reload the page
- Open saved reports dropdown
- Click to load the saved report
- Delete it

- [ ] **Step 5: Test CSV export**

Run any query, click the CSV button. Verify a file downloads.

- [ ] **Step 6: Test error handling**

Enter invalid query: `FIND badentity`
Verify a clear error message appears.

- [ ] **Step 7: Fix any issues found and commit**

```bash
git add -A
git commit -m "fix(reports): polish and bug fixes from integration testing"
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | Schema definitions | `report_engine/schema.py` |
| 2 | Lexer (tokenizer) | `report_engine/lexer.py`, `tests/test_lexer.py` |
| 3 | Parser (tokens → AST) | `report_engine/parser.py`, `tests/test_parser.py` |
| 4 | Executor — live entities | `report_engine/executor.py`, `tests/test_executor.py` |
| 5 | Executor — DB entities | `report_engine/executor.py` (extend) |
| 6 | Result formatter | `report_engine/formatter.py` |
| 7 | Public API | `report_engine/__init__.py` |
| 8 | SavedReport model | `models/saved_report.py` |
| 9 | Routes & nav | `routes/reports.py`, `__init__.py`, `base.html` |
| 10 | Page template | `templates/reports.html` |
| 11 | JavaScript | `static/js/reports.js` |
| 12 | Integration testing | Various |
