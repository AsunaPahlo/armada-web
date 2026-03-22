# COUNT Expressions & Arithmetic — Design Spec

## Overview

Extends the report query DSL with `COUNT()` functions and full arithmetic expressions, enabling analytical queries like "find FCs that don't have enough SSUC parts across all subs + inventory."

This is an extension to the existing custom reports engine (see `2026-03-22-custom-reports-design.md`).

## Grammar Extensions

### COUNT Function — Two Forms

**Form 1: Count matches in a set/list field**

```
COUNT(field, "pattern")
```

Counts the **total quantity** of items in a set or list field that contain the given pattern (case-insensitive substring match, same semantics as CONTAINS).

For `inventory_parts`, each matching part contributes its **quantity** (not just 1), since inventory tracks counts per item. For example, if an FC has 3 Shark-class Bows and 2 Shark-class Sterns, `COUNT(inventory_parts, "Shark")` returns 5.

For other set fields (like `parts` on subs), each matching entry counts as 1.

Examples:
- `COUNT(inventory_parts, "Shark")` — total quantity of Shark parts in inventory
- `COUNT(subs.parts, "Coelacanth")` — total Coelacanth parts equipped across all subs in this FC

When the field is a child set field (e.g., `subs.parts`), the executor **flattens** all children's field values into one list and counts across all of them. This differs from quantifiers (which check per-child); COUNT aggregates.

**Form 2: Count child entities matching a condition**

```
COUNT(child_entity WHERE condition)
```

Counts how many child entities satisfy the given condition.

Examples:
- `COUNT(subs WHERE level > 100)` — how many subs above level 100
- `COUNT(subs WHERE status = "ready")` — how many idle subs
- `COUNT(subs WHERE build CONTAINS "SSUC")` — how many subs with SSUC build

The condition inside COUNT supports compound conditions with AND/OR and parentheses, using the same syntax as regular WHERE conditions. The closing `)` of COUNT delimits the scope — the parser matches parentheses to know where the COUNT ends. No nesting of COUNT within COUNT for v1.

Example with compound condition:
```
COUNT(subs WHERE level > 100 AND status = "ready")
```

### Arithmetic Operators

`+`, `-`, `*`, `/` with standard mathematical precedence:
- `*` and `/` bind tighter than `+` and `-`
- Parentheses override precedence

### Expressions

An **expression** evaluates to a number. Valid expression components:

| Component | Example | Description |
|-----------|---------|-------------|
| Literal number | `4`, `2.5` | Numeric constant |
| Field reference | `total_subs`, `gil_per_day` | Numeric field on the queried entity |
| COUNT (form 1) | `COUNT(inventory_parts, "Shark")` | Count matches in set field |
| COUNT (form 2) | `COUNT(subs WHERE level > 100)` | Count matching children |
| Arithmetic | `expr + expr`, `expr * expr` | Binary arithmetic |
| Parenthesized | `(expr + expr)` | Grouping |

### Expression Conditions

Expressions can appear on either side of a comparison operator in WHERE:

```
expression operator expression
```

Examples:
```
FIND fcs WHERE COUNT(subs.parts, "Shark") + COUNT(inventory_parts, "Shark") >= total_subs * 2
FIND fcs WHERE COUNT(subs WHERE status = "ready") > total_subs / 2
FIND fcs WHERE (gil_per_day / total_subs) > 50000
```

### Expressions in ORDER BY

Expressions can be used in ORDER BY:

```
FIND fcs ORDER BY COUNT(subs WHERE status = "ready") DESC
FIND fcs ORDER BY gil_per_day / total_subs DESC
```

### Backward Compatibility

All existing query syntax continues to work unchanged. Expression conditions are a new alternative to the existing `[quantifier] field operator value` pattern.

### Parser Detection Strategy

The parser uses a **try-expression-first** approach in `parse_single_condition()`:

1. If the next token is `COUNT` followed by `(`, parse as expression condition.
2. If the next token is `(` (not preceded by a quantifier), try parsing as parenthesized expression. If that fails, fall back to parenthesized condition group.
3. If the next token is a numeric literal, parse as expression condition (numbers can't start legacy conditions).
4. Otherwise, parse as a legacy condition (`[quantifier] field operator value`). **After** parsing the legacy condition, check if the next token is an arithmetic operator (`+`, `-`, `*`, `/`). If so, reinterpret the parsed field as a `field_ref` expression atom and continue parsing as an expression condition.

**Minus sign ambiguity:** The lexer currently absorbs `-` into negative number literals (e.g., `-2`). To support `total_subs - 2`, the lexer is modified: `-` is only treated as part of a negative literal when the previous token is an operator, keyword, `(`, `,`, or when there is no previous token. Otherwise, `-` is emitted as an `ARITHMETIC` token. This matches standard expression lexing behavior.

### Unary Minus

Unary minus is **not supported** for v1. Write `0 - total_subs` instead of `-total_subs`. This avoids additional parser complexity.

### Multi-line Queries

Multi-line queries are valid — the lexer skips all whitespace including newlines.

## AST Node Types

### New Node Types

```python
# COUNT form 1: count matches in a set field
{"type": "count_field", "field": "inventory_parts", "pattern": "Shark"}
{"type": "count_field", "field": "subs.parts", "pattern": "Coelacanth"}

# COUNT form 2: count children matching condition
{"type": "count_where", "child": "subs", "condition": {"field": "level", "operator": ">", "value": 100}}

# Binary arithmetic operation
{"type": "binop", "op": "+", "left": <expr_node>, "right": <expr_node>}

# Numeric field reference
{"type": "field_ref", "field": "total_subs"}

# Literal number
{"type": "literal", "value": 4}

# Expression-based condition (new condition node type)
{
    "type": "expression_condition",
    "left": <expr_node>,
    "operator": ">=",        # standard comparison operator
    "right": <expr_node>
}
```

### Example AST

Query: `COUNT(subs.parts, "Shark") + COUNT(inventory_parts, "Shark") >= total_subs * 2`

```python
{
    "type": "expression_condition",
    "left": {
        "type": "binop", "op": "+",
        "left": {"type": "count_field", "field": "subs.parts", "pattern": "Shark"},
        "right": {"type": "count_field", "field": "inventory_parts", "pattern": "Shark"}
    },
    "operator": ">=",
    "right": {
        "type": "binop", "op": "*",
        "left": {"type": "field_ref", "field": "total_subs"},
        "right": {"type": "literal", "value": 2}
    }
}
```

## Implementation Changes

### Lexer (`lexer.py`)

- Add `COUNT` to the `KEYWORDS` set
- Add new token type `ARITHMETIC` for `+`, `-`, `*`, `/`
- These are single-character tokens, recognized in the symbol matching section (before the existing symbol operator matching, since `*` and `/` are new)
- **Minus sign rule:** `-` is only absorbed into a negative number literal when the previous token is an operator (`=`, `>`, `<`, etc.), keyword, `(`, `,`, or when there is no previous token. In all other cases (e.g., after an IDENTIFIER or VALUE), `-` is emitted as an `ARITHMETIC` token. This ensures `total_subs - 2` parses as three tokens rather than `total_subs` followed by `-2`.

### Parser (`parser.py`)

- Add `parse_expression()` method implementing precedence climbing:
  - Level 1 (lowest): `+`, `-`
  - Level 2 (highest): `*`, `/`
  - Atoms: `COUNT(...)`, numeric literals, field references, parenthesized expressions
- Add `parse_count()` method:
  - Detects form 1 vs form 2 by checking for `WHERE` keyword after the first identifier
  - Form 1: `COUNT(field, "pattern")` → `count_field` node
  - Form 2: `COUNT(child WHERE condition)` → `count_where` node
- Modify `parse_single_condition()`:
  - If the token stream starts with `COUNT(` or if after parsing a field/value the next token is an arithmetic operator, switch to expression condition parsing
  - Parse left expression, comparison operator, right expression → `expression_condition` node
- Modify ORDER BY parsing to accept expressions (not just identifiers)

### Executor (`executor.py`)

- Add `_evaluate_expression(expr, record, all_subs, fc_summaries)` recursive function:
  - `literal` → return value
  - `field_ref` → look up source key from schema, return `record.get(key, 0)`
  - `count_field` → count items matching the pattern (case-insensitive CONTAINS). For `inventory_parts`, the executor must use the raw `{item_id: count}` dict (before name conversion) and sum the quantities of matching items. For other set fields, each matching entry counts as 1. For child set fields like `subs.parts`, flatten across all children first.
  - `count_where` → filter children by condition, return count
  - `binop` → evaluate both sides, apply operator. Division by zero returns 0.
- Modify `_evaluate_condition()` to handle `expression_condition` nodes:
  - Evaluate left and right expressions to numbers
  - Apply comparison operator
- Modify ORDER BY evaluation to handle expression AST nodes (evaluate expression per record for sort key)

### Scope & Error Handling

- **Live entities only** (fcs, subs) for v1. Using COUNT or arithmetic expressions in a query on a DB entity (voyages, loot, activity) produces a **parse error**: `"Expression queries are only supported for live entities (fcs, subs)"`. The parser validates the entity before allowing expression conditions.
- No nesting COUNT within COUNT
- No string expressions — expressions always evaluate to numbers
- Division by zero returns 0 (not an error)
- **COUNT on non-set fields** (e.g., `COUNT(name, "foo")`) produces a **parse error**: `"COUNT() requires a set or list field, got string field 'name'"`. Validated against schema field type at parse time.
- **Non-numeric field_ref in expressions** (e.g., `name + 1`) produces a **parse error**: `"Field 'name' is not numeric and cannot be used in expressions"`. Validated against schema field type at parse time.
- **ORDER BY with expressions + GROUP BY**: When GROUP BY is active, ORDER BY expressions are not supported — use a direct field for ordering. This is a parse error if both are present with an expression ORDER BY.

## Example Queries

**SSUC readiness — find FCs that DON'T have enough parts:**
```
FIND fcs WHERE ALL subs.level > 111
  AND COUNT(subs.parts, "Shark") + COUNT(inventory_parts, "Shark") < total_subs * 2
  AND COUNT(subs.parts, "Unkiu") + COUNT(inventory_parts, "Unkiu") < total_subs
  AND COUNT(subs.parts, "Coelacanth") + COUNT(inventory_parts, "Coelacanth") < total_subs
```

**FCs with more than half their subs idle:**
```
FIND fcs WHERE COUNT(subs WHERE status = "ready") > total_subs / 2
```

**FCs sorted by gil efficiency per sub:**
```
FIND fcs ORDER BY gil_per_day / total_subs DESC
```

**FCs with at least 3 max-level subs:**
```
FIND fcs WHERE COUNT(subs WHERE level >= 125) >= 3
```

**FCs with more idle subs than active:**
```
FIND fcs WHERE COUNT(subs WHERE status = "ready") > COUNT(subs WHERE status = "voyaging")
```
