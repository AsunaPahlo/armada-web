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
