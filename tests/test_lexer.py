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
        assert len(tokens) == 6
        assert tokens[2].type == TokenType.KEYWORD
        assert tokens[2].value == 'WHERE'
        assert tokens[3].type == TokenType.IDENTIFIER
        assert tokens[5].type == TokenType.VALUE

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
        assert tokens[-1] == Token(TokenType.VALUE, 10, 15)

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
