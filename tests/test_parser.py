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


class TestParseExpressions:
    def test_count_field_form(self):
        ast = parse('FIND fcs WHERE COUNT(inventory_parts, "Shark") >= 4')
        cond = ast['conditions']
        assert cond['type'] == 'expression_condition'
        assert cond['left']['type'] == 'count_field'
        assert cond['left']['field'] == 'inventory_parts'
        assert cond['left']['pattern'] == 'Shark'
        assert cond['operator'] == '>='
        assert cond['right']['type'] == 'literal'
        assert cond['right']['value'] == 4

    def test_count_where_form(self):
        ast = parse('FIND fcs WHERE COUNT(subs WHERE level > 100) >= 3')
        cond = ast['conditions']
        assert cond['type'] == 'expression_condition'
        assert cond['left']['type'] == 'count_where'
        assert cond['left']['child'] == 'subs'
        assert cond['left']['condition']['field'] == 'level'

    def test_count_where_compound_condition(self):
        ast = parse('FIND fcs WHERE COUNT(subs WHERE level > 100 AND status = "ready") >= 2')
        cond = ast['conditions']
        assert cond['left']['type'] == 'count_where'
        assert cond['left']['condition']['type'] == 'AND'

    def test_arithmetic_expression(self):
        ast = parse('FIND fcs WHERE COUNT(inventory_parts, "Shark") + COUNT(subs.parts, "Shark") >= total_subs * 2')
        cond = ast['conditions']
        assert cond['type'] == 'expression_condition'
        assert cond['left']['type'] == 'binop'
        assert cond['left']['op'] == '+'
        assert cond['right']['type'] == 'binop'
        assert cond['right']['op'] == '*'

    def test_field_ref_expression(self):
        ast = parse('FIND fcs WHERE gil_per_day / total_subs > 50000')
        cond = ast['conditions']
        assert cond['type'] == 'expression_condition'
        assert cond['left']['type'] == 'binop'
        assert cond['left']['op'] == '/'
        assert cond['left']['left']['type'] == 'field_ref'
        assert cond['left']['right']['type'] == 'field_ref'

    def test_precedence_multiply_before_add(self):
        ast = parse('FIND fcs WHERE total_subs * 2 + 1 > 5')
        cond = ast['conditions']
        left = cond['left']
        # Should be (total_subs * 2) + 1, not total_subs * (2 + 1)
        assert left['type'] == 'binop'
        assert left['op'] == '+'
        assert left['left']['type'] == 'binop'
        assert left['left']['op'] == '*'

    def test_parenthesized_expression(self):
        ast = parse('FIND fcs WHERE (total_subs + 1) * 2 > 10')
        cond = ast['conditions']
        left = cond['left']
        assert left['type'] == 'binop'
        assert left['op'] == '*'
        assert left['left']['type'] == 'binop'
        assert left['left']['op'] == '+'

    def test_expression_order_by(self):
        ast = parse('FIND fcs ORDER BY COUNT(subs WHERE status = "ready") DESC')
        assert ast['order_by']['expression']['type'] == 'count_where'
        assert ast['order_by']['direction'] == 'DESC'

    def test_expression_order_by_arithmetic(self):
        ast = parse('FIND fcs ORDER BY gil_per_day / total_subs DESC')
        assert ast['order_by']['expression']['type'] == 'binop'

    def test_mixed_legacy_and_expression(self):
        ast = parse('FIND fcs WHERE ALL subs.level > 111 AND COUNT(inventory_parts, "Shark") >= 4')
        cond = ast['conditions']
        assert cond['type'] == 'AND'
        # First child is legacy condition
        assert 'field' in cond['children'][0]
        # Second child is expression condition
        assert cond['children'][1]['type'] == 'expression_condition'

    def test_count_child_set_field(self):
        ast = parse('FIND fcs WHERE COUNT(subs.parts, "Shark") >= 8')
        cond = ast['conditions']
        assert cond['left']['type'] == 'count_field'
        assert cond['left']['field'] == 'subs.parts'

    def test_expression_both_sides(self):
        ast = parse('FIND fcs WHERE COUNT(subs WHERE status = "ready") > COUNT(subs WHERE status = "voyaging")')
        cond = ast['conditions']
        assert cond['left']['type'] == 'count_where'
        assert cond['right']['type'] == 'count_where'


class TestParseExpressionErrors:
    def test_expressions_on_db_entity(self):
        with pytest.raises(ParseError, match='only supported for live entities'):
            parse('FIND voyages WHERE COUNT(loot WHERE value > 1000) > 5')

    def test_arithmetic_on_db_entity(self):
        with pytest.raises(ParseError, match='only supported for live entities'):
            parse('FIND voyages WHERE duration / 2 > 10')

    def test_count_on_non_set_field(self):
        with pytest.raises(ParseError, match='requires a set or list field'):
            parse('FIND fcs WHERE COUNT(name, "foo") > 0')

    def test_non_numeric_field_in_expression(self):
        with pytest.raises(ParseError, match='not numeric'):
            parse('FIND fcs WHERE name + 1 > 0')

    def test_expression_order_by_with_group_by(self):
        with pytest.raises(ParseError, match='not supported with GROUP BY'):
            parse('FIND fcs GROUP BY region ORDER BY COUNT(subs WHERE level > 100) DESC')
