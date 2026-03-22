"""Tests for the report engine executor."""
import pytest
from app.services.report_engine.executor import execute_live, _apply_condition, _evaluate_expression


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
        assert _apply_condition({'build': 'S+S+U+C+'}, 'build', 'CONTAINS', 'S+S+')
        assert not _apply_condition({'build': 'W+W+W+W+'}, 'build', 'CONTAINS', 'S+S+')

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
        # Ocean Fleet (fc_id 2) has all subs > 100 (Sub3=115).
        # Deep Divers (fc_id 3) has no subs in mock data — excluded (no subs = no match for ALL).
        # Storm Armada has Sub2 at level 90, so it is excluded.
        assert len(results) == 1
        assert results[0]['name'] == 'Ocean Fleet'

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
        assert any(r['name'] == 'Deep Divers' for r in results)

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
        assert results[0]['name'] == 'Ocean Fleet'

    def test_limit(self):
        ast = {
            'entity': 'fcs', 'conditions': None,
            'group_by': None, 'order_by': None, 'limit': 2,
        }
        results = execute_live(ast, MOCK_FC_SUMMARIES, MOCK_ALL_SUBS)
        assert len(results) == 2


class TestEvaluateExpression:
    def test_literal(self):
        result = _evaluate_expression({'type': 'literal', 'value': 42}, {}, 'fcs')
        assert result == 42

    def test_field_ref(self):
        record = {'total_subs': 4, 'fc_name': 'Test', 'world': 'Gilgamesh'}
        result = _evaluate_expression({'type': 'field_ref', 'field': 'total_subs'}, record, 'fcs')
        assert result == 4

    def test_field_ref_missing(self):
        result = _evaluate_expression({'type': 'field_ref', 'field': 'total_subs'}, {}, 'fcs')
        assert result == 0

    def test_binop_add(self):
        expr = {'type': 'binop', 'op': '+',
                'left': {'type': 'literal', 'value': 3},
                'right': {'type': 'literal', 'value': 4}}
        assert _evaluate_expression(expr, {}, 'fcs') == 7

    def test_binop_multiply(self):
        expr = {'type': 'binop', 'op': '*',
                'left': {'type': 'field_ref', 'field': 'total_subs'},
                'right': {'type': 'literal', 'value': 2}}
        assert _evaluate_expression(expr, {'total_subs': 4}, 'fcs') == 8

    def test_binop_divide(self):
        expr = {'type': 'binop', 'op': '/',
                'left': {'type': 'literal', 'value': 10},
                'right': {'type': 'literal', 'value': 3}}
        result = _evaluate_expression(expr, {}, 'fcs')
        assert abs(result - 3.333) < 0.01

    def test_divide_by_zero(self):
        expr = {'type': 'binop', 'op': '/',
                'left': {'type': 'literal', 'value': 10},
                'right': {'type': 'literal', 'value': 0}}
        assert _evaluate_expression(expr, {}, 'fcs') == 0

    def test_count_field_set(self):
        record = {'inventory_parts': ['Shark-class Bow', 'Shark-class Stern', 'Whale-class Bow']}
        expr = {'type': 'count_field', 'field': 'inventory_parts', 'pattern': 'Shark'}
        result = _evaluate_expression(expr, record, 'fcs')
        assert result == 2

    def test_count_field_quantity_aware(self):
        # inventory_parts_raw has quantities; count_field should sum quantities
        record = {
            'inventory_parts': ['Shark-class Bow', 'Shark-class Stern', 'Whale-class Bow'],
            'inventory_parts_qty': {21792: 3, 21795: 2, 22526: 1},  # 3 Shark Bows, 2 Shark Sterns, 1 Whale Bow
        }
        expr = {'type': 'count_field', 'field': 'inventory_parts', 'pattern': 'Shark'}
        result = _evaluate_expression(expr, record, 'fcs', use_quantities=True)
        assert result == 5  # 3 + 2

    def test_count_field_child_set(self):
        # COUNT(subs.parts, "Shark") should flatten across all subs
        record = {'fc_id': '1'}
        all_subs = [
            {'fc_id': '1', 'parts': ['Shark-class Bow', 'Shark-class Stern', 'Unkiu-class Bow', 'Coelacanth-class Bridge']},
            {'fc_id': '1', 'parts': ['Shark-class Bow', 'Whale-class Stern', 'Whale-class Bow', 'Whale-class Bridge']},
        ]
        expr = {'type': 'count_field', 'field': 'subs.parts', 'pattern': 'Shark'}
        result = _evaluate_expression(expr, record, 'fcs', all_subs=all_subs)
        assert result == 3  # 2 from sub1 + 1 from sub2

    def test_count_where(self):
        record = {'fc_id': '1'}
        all_subs = [
            {'fc_id': '1', 'level': 120, 'status': 'ready'},
            {'fc_id': '1', 'level': 90, 'status': 'voyaging'},
            {'fc_id': '1', 'level': 115, 'status': 'ready'},
        ]
        expr = {'type': 'count_where', 'child': 'subs',
                'condition': {'field': 'level', 'operator': '>', 'value': 100, 'quantifier': None}}
        result = _evaluate_expression(expr, record, 'fcs', all_subs=all_subs)
        assert result == 2

    def test_count_where_no_matches(self):
        record = {'fc_id': '1'}
        all_subs = [
            {'fc_id': '1', 'level': 50},
        ]
        expr = {'type': 'count_where', 'child': 'subs',
                'condition': {'field': 'level', 'operator': '>', 'value': 100, 'quantifier': None}}
        result = _evaluate_expression(expr, record, 'fcs', all_subs=all_subs)
        assert result == 0


class TestExpressionConditions:
    def test_expression_condition_in_execute_live(self):
        fc_summaries = [
            {'fc_id': '1', 'fc_name': 'Big FC', 'total_subs': 4, 'gil_per_day': 400000,
             'world': 'Gilgamesh', 'region': 'NA', 'ceruleum': 0, 'repair_kits': 0,
             'dive_credits': 0, 'ready_subs': 0, 'leveling_subs': 0,
             'inventory_parts': ['Shark-class Bow'], 'inventory_parts_qty': {}},
            {'fc_id': '2', 'fc_name': 'Small FC', 'total_subs': 2, 'gil_per_day': 100000,
             'world': 'Cactuar', 'region': 'NA', 'ceruleum': 0, 'repair_kits': 0,
             'dive_credits': 0, 'ready_subs': 0, 'leveling_subs': 0,
             'inventory_parts': [], 'inventory_parts_qty': {}},
        ]
        all_subs = [
            {'fc_id': '1', 'name': 'S1', 'level': 120, 'build': 'S+S+U+C+', 'parts': [], 'route': '', 'status': 'ready', 'gil_per_day': 100000, 'exp_progress': 100},
            {'fc_id': '1', 'name': 'S2', 'level': 120, 'build': 'S+S+U+C+', 'parts': [], 'route': '', 'status': 'ready', 'gil_per_day': 100000, 'exp_progress': 100},
            {'fc_id': '2', 'name': 'S3', 'level': 50, 'build': 'W+W+W+W+', 'parts': [], 'route': '', 'status': 'ready', 'gil_per_day': 50000, 'exp_progress': 50},
        ]
        # Query: FCs with gil_per_day / total_subs > 60000
        ast = {
            'entity': 'fcs',
            'conditions': {
                'type': 'expression_condition',
                'left': {'type': 'binop', 'op': '/', 'left': {'type': 'field_ref', 'field': 'gil_per_day'}, 'right': {'type': 'field_ref', 'field': 'total_subs'}},
                'operator': '>',
                'right': {'type': 'literal', 'value': 60000},
            },
            'group_by': None, 'order_by': None, 'limit': None,
        }
        results = execute_live(ast, fc_summaries, all_subs)
        assert len(results) == 1
        assert results[0]['name'] == 'Big FC'
