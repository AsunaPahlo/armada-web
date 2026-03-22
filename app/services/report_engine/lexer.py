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
