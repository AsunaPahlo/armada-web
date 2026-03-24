"""Parser for the Armada report query DSL.

Converts a token stream from the lexer into an AST (dict).
Grammar:
    query     = FIND entity [WHERE conditions] [GROUP BY field] [ORDER BY field [ASC|DESC]] [LIMIT number]
    conditions = condition ((AND|OR) condition)*
    condition  = [quantifier] field operator value
               | LPAREN conditions RPAREN
               | expression_condition
    quantifier = ALL | ANY | NO
    operator   = comparison | text_op | set_op | null_op
    expression = add_sub
    add_sub    = mul_div ((+|-) mul_div)*
    mul_div    = atom ((*|/) atom)*
    atom       = COUNT(...) | number | field_ref | (expression)
"""
from app.services.report_engine.lexer import tokenize, Token, TokenType, LexerError
from app.services.report_engine.schema import (
    resolve_entity, get_entity_def, get_field_info, ENTITY_FIELDS,
    FieldType, EntitySource,
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
        select = None
        conditions = None
        group_by = None
        order_by = None
        limit = None

        # SELECT clause: FIND fcs SELECT name, world, COUNT(...) AS alias
        if self.match(TokenType.KEYWORD, 'SELECT'):
            select = self._parse_select()

        if self.match(TokenType.KEYWORD, 'WHERE'):
            conditions = self.parse_conditions()

        if self.match(TokenType.KEYWORD, 'GROUP'):
            self.expect(TokenType.KEYWORD, 'BY')
            field_token = self.expect(TokenType.IDENTIFIER)
            group_by = field_token.value

        if self.match(TokenType.KEYWORD, 'ORDER'):
            self.expect(TokenType.KEYWORD, 'BY')
            # Check if it's an expression (COUNT or arithmetic) or simple field
            if self._is_expression_start():
                expr = self.parse_expression()
                direction = 'ASC'
                dir_token = self.match(TokenType.KEYWORD, 'ASC') or self.match(TokenType.KEYWORD, 'DESC')
                if dir_token:
                    direction = dir_token.value
                order_by = {'expression': expr, 'direction': direction}
            else:
                field_token = self.expect(TokenType.IDENTIFIER)
                # Check if followed by arithmetic
                next_t = self.peek()
                if next_t and next_t.type == TokenType.ARITHMETIC:
                    # Parse as expression starting from this field_ref
                    left = {'type': 'field_ref', 'field': field_token.value}
                    # Build full expression using precedence climbing
                    while True:
                        t = self.peek()
                        if t and t.type == TokenType.ARITHMETIC and t.value in ('*', '/'):
                            self.advance()
                            r = self._parse_atom()
                            left = {'type': 'binop', 'op': t.value, 'left': left, 'right': r}
                        else:
                            break
                    while True:
                        t = self.peek()
                        if t and t.type == TokenType.ARITHMETIC and t.value in ('+', '-'):
                            self.advance()
                            r = self._parse_mul_div()
                            left = {'type': 'binop', 'op': t.value, 'left': left, 'right': r}
                        else:
                            break
                    direction = 'ASC'
                    dir_token = self.match(TokenType.KEYWORD, 'ASC') or self.match(TokenType.KEYWORD, 'DESC')
                    if dir_token:
                        direction = dir_token.value
                    order_by = {'expression': left, 'direction': direction}
                else:
                    direction = 'ASC'
                    dir_token = self.match(TokenType.KEYWORD, 'ASC') or self.match(TokenType.KEYWORD, 'DESC')
                    if dir_token:
                        direction = dir_token.value
                    order_by = {'field': field_token.value, 'direction': direction}

        if self.match(TokenType.KEYWORD, 'LIMIT'):
            limit_token = self.expect(TokenType.VALUE)
            limit = int(limit_token.value)

        # Validate: expression ORDER BY + GROUP BY is not supported
        if group_by and order_by and 'expression' in order_by:
            raise ParseError('Expression ORDER BY is not supported with GROUP BY')

        # Should have consumed everything
        if self.peek():
            raise ParseError(f'Unexpected token: {self.peek().value!r}', self.peek().pos)

        return {
            'entity': entity_name,
            'select': select,
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
        """Parse one condition, parenthesized group, or expression condition."""
        # If starts with COUNT or a number, it's an expression condition
        token = self.peek()
        if token and token.type == TokenType.KEYWORD and token.value == 'COUNT':
            return self._parse_expression_condition()
        if token and token.type == TokenType.VALUE and isinstance(token.value, (int, float)):
            return self._parse_expression_condition()

        # Parenthesized: try expression first, fall back to condition group
        if token and token.type == TokenType.LPAREN:
            saved_pos = self.pos
            try:
                return self._parse_expression_condition()
            except ParseError:
                # Not an expression — fall back to parenthesized condition group
                self.pos = saved_pos
            self.advance()  # consume (
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

        # Check if this is actually an expression condition (field followed by arithmetic)
        next_token = self.peek()
        if next_token and next_token.type == TokenType.ARITHMETIC and quantifier is None:
            # Validate field is numeric before using in expression
            field_info_check = get_field_info(self.entity, field_name)
            if field_info_check:
                _, ftype_check, _ = field_info_check
                if ftype_check != FieldType.NUMBER:
                    raise ParseError(
                        f"Field '{field_name}' is not numeric and cannot be used in expressions",
                        field_token.pos,
                    )
            # Reinterpret field as field_ref and parse as expression condition
            left_expr = {'type': 'field_ref', 'field': field_name}
            return self._parse_expression_condition_from(left_expr)

        # Legacy condition parsing (existing behavior)
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

    # ── Expression parsing ──────────────────────────────────────────────

    def _is_expression_start(self):
        """Check if the current position starts an expression."""
        token = self.peek()
        if not token:
            return False
        if token.type == TokenType.KEYWORD and token.value == 'COUNT':
            return True
        if token.type == TokenType.VALUE and isinstance(token.value, (int, float)):
            return True
        if token.type == TokenType.LPAREN:
            return True
        return False

    def parse_expression(self):
        """Parse an arithmetic expression with precedence climbing.

        Precedence: +/- (lowest) < */ (highest)
        Atoms: COUNT(...), number literal, field reference, (expr)
        """
        return self._parse_add_sub()

    def _parse_add_sub(self):
        """Parse + and - (lowest precedence)."""
        left = self._parse_mul_div()
        while True:
            token = self.peek()
            if token and token.type == TokenType.ARITHMETIC and token.value in ('+', '-'):
                self.advance()
                right = self._parse_mul_div()
                left = {'type': 'binop', 'op': token.value, 'left': left, 'right': right}
            else:
                break
        return left

    def _parse_mul_div(self):
        """Parse * and / (highest precedence)."""
        left = self._parse_atom()
        while True:
            token = self.peek()
            if token and token.type == TokenType.ARITHMETIC and token.value in ('*', '/'):
                self.advance()
                right = self._parse_atom()
                left = {'type': 'binop', 'op': token.value, 'left': left, 'right': right}
            else:
                break
        return left

    def _parse_atom(self):
        """Parse an expression atom: COUNT(...), number, field ref, or (expr)."""
        token = self.peek()
        if not token:
            raise ParseError('Expected expression, got end of query')

        # COUNT(...)
        if token.type == TokenType.KEYWORD and token.value == 'COUNT':
            return self._parse_count()

        # Parenthesized expression
        if token.type == TokenType.LPAREN:
            self.advance()
            expr = self.parse_expression()
            self.expect(TokenType.RPAREN)
            return expr

        # Numeric literal
        if token.type == TokenType.VALUE and isinstance(token.value, (int, float)):
            self.advance()
            return {'type': 'literal', 'value': token.value}

        # Field reference (must be a numeric field)
        if token.type == TokenType.IDENTIFIER:
            self.advance()
            field_info = get_field_info(self.entity, token.value)
            if field_info:
                _, ftype, _ = field_info
                if ftype != FieldType.NUMBER:
                    raise ParseError(
                        f"Field '{token.value}' is not numeric and cannot be used in expressions",
                        token.pos,
                    )
            return {'type': 'field_ref', 'field': token.value}

        raise ParseError(f'Expected expression, got {token.value!r}', token.pos)

    def _parse_select(self):
        """Parse SELECT clause: comma-separated list of fields/expressions with optional AS alias.

        Returns list of {'expression': expr_node_or_field_name, 'alias': str_or_None}
        """
        columns = []
        while True:
            # Each select item is either an expression or a simple field name
            if self._is_expression_start():
                expr = self.parse_expression()
            elif self.peek() and self.peek().type == TokenType.IDENTIFIER:
                token = self.advance()
                # Check if followed by arithmetic
                if self.peek() and self.peek().type == TokenType.ARITHMETIC:
                    left = {'type': 'field_ref', 'field': token.value}
                    # Parse full expression using precedence climbing
                    while True:
                        t = self.peek()
                        if t and t.type == TokenType.ARITHMETIC and t.value in ('*', '/'):
                            self.advance()
                            r = self._parse_atom()
                            left = {'type': 'binop', 'op': t.value, 'left': left, 'right': r}
                        else:
                            break
                    while True:
                        t = self.peek()
                        if t and t.type == TokenType.ARITHMETIC and t.value in ('+', '-'):
                            self.advance()
                            r = self._parse_mul_div()
                            left = {'type': 'binop', 'op': t.value, 'left': left, 'right': r}
                        else:
                            break
                    expr = left
                else:
                    expr = token.value  # plain field name (string, not expression node)
            else:
                break

            # Optional AS alias
            alias = None
            if self.match(TokenType.KEYWORD, 'AS'):
                alias_token = self.expect(TokenType.IDENTIFIER)
                alias = alias_token.value

            columns.append({'expression': expr, 'alias': alias})

            # Comma means more columns
            if not self.match(TokenType.COMMA):
                break

        if not columns:
            raise ParseError('Expected at least one column after SELECT')

        return columns

    def _parse_count(self):
        """Parse COUNT(field, "pattern") or COUNT(child WHERE condition)."""
        self.expect(TokenType.KEYWORD, 'COUNT')
        self.expect(TokenType.LPAREN)

        # First token is always an identifier (field name or child entity name)
        field_token = self.expect(TokenType.IDENTIFIER)

        # Determine form: if next is WHERE, it's form 2; if COMMA, it's form 1
        if self.match(TokenType.COMMA):
            # Form 1: COUNT(field, "pattern")
            # Validate the field is a SET type
            field_info = get_field_info(self.entity, field_token.value)
            if field_info:
                _, ftype, _ = field_info
                if ftype not in (FieldType.SET,):
                    raise ParseError(
                        f"COUNT() requires a set or list field, got {ftype.value} field '{field_token.value}'",
                        field_token.pos,
                    )
            pattern_token = self.expect(TokenType.VALUE)
            self.expect(TokenType.RPAREN)
            return {
                'type': 'count_field',
                'field': field_token.value,
                'pattern': pattern_token.value,
            }
        elif self.match(TokenType.KEYWORD, 'WHERE'):
            # Form 2: COUNT(child WHERE condition)
            # Temporarily swap entity context so field validation works against child entity
            saved_entity = self.entity
            self.entity = field_token.value  # e.g., 'subs'
            condition = self.parse_conditions()
            self.entity = saved_entity
            self.expect(TokenType.RPAREN)
            return {
                'type': 'count_where',
                'child': field_token.value,
                'condition': condition,
            }
        else:
            token = self.peek()
            raise ParseError(
                f'Expected , or WHERE after COUNT field, got {token.value!r}' if token else 'Unexpected end of COUNT',
                token.pos if token else None,
            )

    def _parse_expression_condition(self):
        """Parse a full expression condition: expr operator expr."""
        # Validate entity is live
        entity_def = ENTITY_FIELDS.get(self.entity)
        if entity_def and entity_def['source'] != EntitySource.LIVE:
            raise ParseError(f'Expression queries are only supported for live entities (fcs, subs), not {self.entity!r}')

        left = self.parse_expression()
        # Comparison operator
        op_token = self.match(TokenType.OPERATOR)
        if op_token is None:
            token = self.peek()
            raise ParseError(
                f'Expected comparison operator, got {token.value!r}' if token else 'Expected comparison operator',
                token.pos if token else None,
            )
        right = self.parse_expression()
        return {
            'type': 'expression_condition',
            'left': left,
            'operator': op_token.value,
            'right': right,
        }

    def _parse_expression_condition_from(self, left_start):
        """Continue parsing an expression condition where left side started as a field_ref."""
        # Validate entity is live
        entity_def = ENTITY_FIELDS.get(self.entity)
        if entity_def and entity_def['source'] != EntitySource.LIVE:
            raise ParseError(f'Expression queries are only supported for live entities (fcs, subs), not {self.entity!r}')

        # Continue building the left expression (handle arithmetic after the field_ref)
        left = left_start
        # Check for * / first (higher precedence)
        while True:
            token = self.peek()
            if token and token.type == TokenType.ARITHMETIC and token.value in ('*', '/'):
                self.advance()
                right = self._parse_atom()
                left = {'type': 'binop', 'op': token.value, 'left': left, 'right': right}
            else:
                break
        # Then + -
        while True:
            token = self.peek()
            if token and token.type == TokenType.ARITHMETIC and token.value in ('+', '-'):
                self.advance()
                right = self._parse_mul_div()
                left = {'type': 'binop', 'op': token.value, 'left': left, 'right': right}
            else:
                break

        # Comparison operator
        op_token = self.match(TokenType.OPERATOR)
        if op_token is None:
            token = self.peek()
            raise ParseError(
                f'Expected comparison operator, got {token.value!r}' if token else 'Expected comparison operator',
                token.pos if token else None,
            )
        right = self.parse_expression()
        return {
            'type': 'expression_condition',
            'left': left,
            'operator': op_token.value,
            'right': right,
        }


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
