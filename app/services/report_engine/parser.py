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

        # Operator — can be OPERATOR token or KEYWORD token (BETWEEN, IN)
        op_token = self.match(TokenType.OPERATOR)
        if op_token is None:
            # BETWEEN and IN are lexed as KEYWORD
            op_token = self.match(TokenType.KEYWORD, 'BETWEEN') or self.match(TokenType.KEYWORD, 'IN')
        if op_token is None:
            token = self.peek()
            raise ParseError(
                f'Expected operator, got {token.value!r}' if token else 'Expected operator, got end of query',
                token.pos if token else None,
            )
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
