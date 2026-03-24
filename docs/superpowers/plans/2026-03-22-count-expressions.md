# COUNT Expressions & Arithmetic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `COUNT()` functions and full arithmetic expressions to the report query DSL, enabling analytical queries like counting parts across subs + inventory and comparing to thresholds.

**Architecture:** Extends the existing lexer/parser/executor pipeline. The lexer gets a new `ARITHMETIC` token type and `COUNT` keyword. The parser gets expression parsing with precedence climbing. The executor gets a recursive `_evaluate_expression()` function that handles COUNT (both forms), arithmetic, field refs, and literals. All changes are backward-compatible.

**Tech Stack:** Python, existing report_engine modules

**Spec:** `docs/superpowers/specs/2026-03-22-count-expressions-design.md`

---

## File Structure

### Modified Files
| File | Change |
|------|--------|
| `app/services/report_engine/lexer.py` | Add ARITHMETIC token type, COUNT keyword, minus-sign context rule |
| `app/services/report_engine/parser.py` | Add expression parsing, COUNT parsing, expression conditions, ORDER BY expressions |
| `app/services/report_engine/executor.py` | Add `_evaluate_expression()`, quantity-aware COUNT for inventory_parts, expression condition evaluation, expression ORDER BY |
| `tests/test_lexer.py` | Add tests for ARITHMETIC tokens, COUNT keyword, minus-sign context |
| `tests/test_parser.py` | Add tests for COUNT forms, arithmetic expressions, expression conditions |
| `tests/test_executor.py` | Add tests for expression evaluation, COUNT both forms |

---

## Task 1: Lexer — ARITHMETIC Token Type & COUNT Keyword

**Files:**
- Modify: `app/services/report_engine/lexer.py`
- Modify: `tests/test_lexer.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_lexer.py`:

```python
class TestTokenizeExpressions:
    def test_count_keyword(self):
        tokens = tokenize('COUNT(subs.parts, "Shark")')
        assert tokens[0] == Token(TokenType.KEYWORD, 'COUNT', 0)
        assert tokens[1].type == TokenType.LPAREN

    def test_arithmetic_operators(self):
        tokens = tokenize('FIND fcs WHERE total_subs + 2 > 5')
        arith = [t for t in tokens if t.type == TokenType.ARITHMETIC]
        assert len(arith) == 1
        assert arith[0].value == '+'

    def test_all_arithmetic_ops(self):
        for op in ['+', '*', '/']:
            tokens = tokenize(f'FIND fcs WHERE a {op} b > 1')
            arith = [t for t in tokens if t.type == TokenType.ARITHMETIC]
            assert len(arith) == 1
            assert arith[0].value == op

    def test_minus_as_arithmetic(self):
        # After an identifier, - should be ARITHMETIC, not part of negative number
        tokens = tokenize('FIND fcs WHERE total_subs - 2 > 0')
        types = [(t.type, t.value) for t in tokens]
        # total_subs should be IDENTIFIER, then - should be ARITHMETIC, then 2 should be VALUE
        assert (TokenType.IDENTIFIER, 'total_subs') in types
        assert (TokenType.ARITHMETIC, '-') in types
        assert (TokenType.VALUE, 2) in types

    def test_minus_as_negative_number(self):
        # After an operator like =, - should be part of negative number
        tokens = tokenize('FIND fcs WHERE level = -5')
        values = [t for t in tokens if t.type == TokenType.VALUE]
        assert values[0].value == -5

    def test_multiply_and_divide(self):
        tokens = tokenize('total_subs * 2 / 3')
        arith = [t for t in tokens if t.type == TokenType.ARITHMETIC]
        assert len(arith) == 2
        assert arith[0].value == '*'
        assert arith[1].value == '/'

    def test_count_with_where(self):
        tokens = tokenize('COUNT(subs WHERE level > 100)')
        assert tokens[0].type == TokenType.KEYWORD
        assert tokens[0].value == 'COUNT'
        # WHERE inside COUNT is still a KEYWORD token
        where_tokens = [t for t in tokens if t.type == TokenType.KEYWORD and t.value == 'WHERE']
        assert len(where_tokens) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/test_lexer.py::TestTokenizeExpressions -v
```

Expected: FAIL (TokenType.ARITHMETIC does not exist)

- [ ] **Step 3: Implement lexer changes**

In `app/services/report_engine/lexer.py`:

1. Add `ARITHMETIC = auto()` to `TokenType` enum (after COMMA)
2. Add `'COUNT'` to the `KEYWORDS` set
3. Add arithmetic token recognition BEFORE the number matching section. Check for `+`, `*`, `/` characters:

```python
        # Arithmetic operators (+, -, *, /)
        if query[i] in '+*/':
            tokens.append(Token(TokenType.ARITHMETIC, query[i], i))
            i += 1
            continue
```

4. Modify the minus sign handling. Replace the current number matching line:
```python
        if query[i].isdigit() or (query[i] == '-' and i + 1 < n and query[i + 1].isdigit()):
```

With context-aware minus handling:
```python
        # Minus sign: arithmetic operator or part of negative number?
        # It's a negative number only when previous token is an operator, keyword, (, comma, or nothing
        if query[i] == '-':
            prev_type = tokens[-1].type if tokens else None
            is_negative = prev_type in (None, TokenType.OPERATOR, TokenType.KEYWORD, TokenType.LPAREN, TokenType.COMMA, TokenType.ARITHMETIC)
            if is_negative and i + 1 < n and query[i + 1].isdigit():
                # Fall through to number parsing below
                pass
            else:
                tokens.append(Token(TokenType.ARITHMETIC, '-', i))
                i += 1
                continue

        # Numbers (positive, or negative when flagged above)
        if query[i].isdigit() or (query[i] == '-' and i + 1 < n and query[i + 1].isdigit()):
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/test_lexer.py -v
```

Expected: All tests PASS (both old and new)

- [ ] **Step 5: Commit**

```bash
git add app/services/report_engine/lexer.py tests/test_lexer.py
git commit -m "feat(reports): add ARITHMETIC token type and COUNT keyword to lexer"
```

---

## Task 2: Parser — Expression Parsing & COUNT

**Files:**
- Modify: `app/services/report_engine/parser.py`
- Modify: `tests/test_parser.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_parser.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/test_parser.py::TestParseExpressions -v
```

- [ ] **Step 3: Implement parser changes**

In `app/services/report_engine/parser.py`, add these methods to the `_Parser` class and modify existing methods:

**Add expression parsing methods:**

```python
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
            return {'type': 'field_ref', 'field': token.value}

        raise ParseError(f'Expected expression, got {token.value!r}', token.pos)

    def _parse_count(self):
        """Parse COUNT(field, "pattern") or COUNT(child WHERE condition)."""
        self.expect(TokenType.KEYWORD, 'COUNT')
        self.expect(TokenType.LPAREN)

        # First token is always an identifier (field name or child entity name)
        field_token = self.expect(TokenType.IDENTIFIER)

        # Determine form: if next is WHERE, it's form 2; if COMMA, it's form 1
        if self.match(TokenType.COMMA):
            # Form 1: COUNT(field, "pattern")
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
```

**Modify `parse_single_condition()`** to detect expression conditions:

Replace the current `parse_single_condition` method. The new version uses a try-expression-first approach:

```python
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
            # Reinterpret field as field_ref and parse as expression condition
            left_expr = {'type': 'field_ref', 'field': field_name}
            return self._parse_expression_condition_from(left_expr)

        # Legacy condition parsing (existing behavior)
        field_info = get_field_info(self.entity, field_name)
        if not field_info:
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
        op_token = self.match(TokenType.OPERATOR)
        if op_token is None:
            op_token = self.match(TokenType.KEYWORD, 'BETWEEN') or self.match(TokenType.KEYWORD, 'IN')
        if op_token is None:
            token = self.peek()
            raise ParseError(
                f'Expected operator, got {token.value!r}' if token else 'Expected operator, got end of query',
                token.pos if token else None,
            )
        operator = op_token.value

        value = self._parse_value(operator)

        return {
            'field': field_name,
            'operator': operator,
            'value': value,
            'quantifier': quantifier,
        }

    def _parse_expression_condition(self):
        """Parse a full expression condition: expr operator expr."""
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
        # Continue building the left expression (handle arithmetic after the field_ref)
        left = left_start
        # Check for arithmetic
        while True:
            token = self.peek()
            if token and token.type == TokenType.ARITHMETIC and token.value in ('*', '/'):
                self.advance()
                right = self._parse_atom()
                left = {'type': 'binop', 'op': token.value, 'left': left, 'right': right}
            else:
                break
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
```

**Modify ORDER BY parsing** in `parse_query()` to accept expressions:

Replace the ORDER BY section:

```python
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
                    # Build full expression
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
```

**Add validation checks:**

In `_parse_expression_condition()` and `_parse_expression_condition_from()`, after building the expression condition, validate the entity is live:

```python
        from app.services.report_engine.schema import ENTITY_FIELDS, EntitySource
        entity_def = ENTITY_FIELDS.get(self.entity)
        if entity_def and entity_def['source'] != EntitySource.LIVE:
            raise ParseError(f'Expression queries are only supported for live entities (fcs, subs), not {self.entity!r}')
```

In `_parse_count()` form 1, validate the field is a SET type:

```python
        field_info = get_field_info(self.entity, field_token.value)
        if field_info:
            _, ftype, _ = field_info
            if ftype not in (FieldType.SET,):
                raise ParseError(
                    f"COUNT() requires a set or list field, got {ftype.value} field '{field_token.value}'",
                    field_token.pos,
                )
```

(Import `FieldType` from schema at the top of the file.)

In `_parse_atom()` for field_ref, validate the field is numeric:

```python
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
```

In `parse_query()`, after parsing both GROUP BY and ORDER BY, validate they don't conflict:

```python
        if group_by and order_by and 'expression' in order_by:
            raise ParseError('Expression ORDER BY is not supported with GROUP BY')
```

Also add `TokenType.ARITHMETIC` to the imports from lexer:

```python
from app.services.report_engine.lexer import tokenize, Token, TokenType, LexerError
```

(This import already exists, and TokenType.ARITHMETIC is on the enum, so no change needed.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/test_parser.py -v
```

Expected: All tests PASS (both old and new)

- [ ] **Step 5: Commit**

```bash
git add app/services/report_engine/parser.py tests/test_parser.py
git commit -m "feat(reports): add expression parsing with COUNT and arithmetic"
```

---

## Task 3: Executor — Expression Evaluation

**Files:**
- Modify: `app/services/report_engine/executor.py`
- Modify: `tests/test_executor.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_executor.py`:

```python
from app.services.report_engine.executor import _evaluate_expression


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/test_executor.py::TestEvaluateExpression -v
```

- [ ] **Step 3: Implement executor changes**

In `app/services/report_engine/executor.py`:

Add the `_evaluate_expression()` function and modify `_evaluate_condition()` and `execute_live()`.

```python
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
        fc_id = record.get('fc_id')
        children = [s for s in (all_subs or []) if s.get('fc_id') == fc_id]
        count = 0
        for child in children:
            items = child.get(suffix, [])
            if isinstance(items, list):
                count += sum(1 for item in items if pattern in str(item).lower())
        return count

    # Direct set field
    # Special handling for inventory_parts with quantities
    if field == 'inventory_parts' and use_quantities:
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

    fc_id = record.get('fc_id')
    if child_entity == 'subs':
        children = [s for s in (all_subs or []) if s.get('fc_id') == fc_id]
    else:
        return 0

    count = 0
    for child in children:
        if _evaluate_condition(child, condition, child_entity, all_subs, None):
            count += 1
    return count
```

**Modify `_evaluate_condition()`** to handle `expression_condition` nodes. Add this check at the **very top** of the function, before the existing AND/OR logic. Also change the existing AND/OR check from `if 'type' in condition:` to `if condition.get('type') in ('AND', 'OR'):` to avoid collision with expression_condition nodes:

```python
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
```

**IMPORTANT:** Replace the existing `if 'type' in condition:` check with `if condition.get('type') in ('AND', 'OR'):` to prevent expression_condition nodes from being incorrectly handled as logical groups.

**Modify `execute_live()`** to handle expression ORDER BY. In the ordering section, check if `order_by` has an `expression` key:

```python
    # Order
    if order_by:
        if 'expression' in order_by:
            # Expression-based ordering
            expr = order_by['expression']
            reverse = order_by['direction'] == 'DESC'
            # Evaluate expression on the raw (pre-remap) record for sorting
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
```

**Also:** To support quantity-aware COUNT for inventory_parts, the enrichment section of `execute_live()` needs to preserve the raw inventory_parts dict as `inventory_parts_qty` before converting to name list. Add this in the fcs enrichment loop, before the inventory_parts conversion:

```python
            # Preserve raw inventory quantities for COUNT expressions
            raw_inv = enriched.get('inventory_parts', {})
            if isinstance(raw_inv, dict):
                enriched['inventory_parts_qty'] = dict(raw_inv)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/report_engine/executor.py tests/test_executor.py
git commit -m "feat(reports): add expression evaluation with COUNT and arithmetic to executor"
```

---

## Task 4: Integration Testing

- [ ] **Step 1: Run all tests**

```bash
cd C:\Users\Asuna\PycharmProjects\Armada-web && python -m pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 2: Test end-to-end via the app**

Start the app and test these queries on the reports page:

```
FIND fcs WHERE COUNT(subs WHERE level > 100) >= 2
FIND fcs WHERE COUNT(subs.parts, "Shark") + COUNT(inventory_parts, "Shark") >= total_subs * 2
FIND fcs ORDER BY gil_per_day / total_subs DESC
FIND fcs WHERE ALL subs.level > 111 AND COUNT(inventory_parts, "Shark") >= 1
```

- [ ] **Step 3: Fix any issues and commit**

```bash
git add -A
git commit -m "fix(reports): polish COUNT expressions integration"
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | Lexer: ARITHMETIC token + COUNT keyword | `lexer.py`, `test_lexer.py` |
| 2 | Parser: expression parsing + COUNT | `parser.py`, `test_parser.py` |
| 3 | Executor: expression evaluation | `executor.py`, `test_executor.py` |
| 4 | Integration testing | Various |
