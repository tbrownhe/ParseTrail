"""Strict parser and evaluator for plugin substring-routing expressions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias


class SearchExpressionError(ValueError):
    """A plugin search expression is syntactically invalid."""


class TokenKind(StrEnum):
    LITERAL = "literal"
    AND = "&&"
    OR = "||"
    OPEN = "("
    CLOSE = ")"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    value: str
    offset: int


@dataclass(frozen=True, slots=True)
class Literal:
    value: str


@dataclass(frozen=True, slots=True)
class And:
    left: Expression
    right: Expression


@dataclass(frozen=True, slots=True)
class Or:
    left: Expression
    right: Expression


Expression: TypeAlias = Literal | And | Or


def _decode_literal(raw: str, offset: int) -> str:
    value = raw.strip()
    if not value:
        raise SearchExpressionError(f"Empty literal at offset {offset}")
    if value.startswith('"') or value.endswith('"'):
        if not (value.startswith('"') and value.endswith('"')):
            raise SearchExpressionError(f"Unmatched quote at offset {offset}")
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SearchExpressionError(f"Invalid quoted literal at offset {offset}") from exc
        if not isinstance(decoded, str) or not decoded.strip():
            raise SearchExpressionError(f"Empty quoted literal at offset {offset}")
        value = decoded
    return value.casefold()


def tokenize(expression: str) -> tuple[Token, ...]:
    if not isinstance(expression, str) or not expression.strip():
        raise SearchExpressionError("Search expression must be a non-empty string")

    tokens: list[Token] = []
    literal: list[str] = []
    literal_offset = 0
    in_quotes = False
    escaped = False
    index = 0

    def flush_literal() -> None:
        if not literal:
            return
        raw = "".join(literal)
        if raw.strip():
            tokens.append(Token(TokenKind.LITERAL, _decode_literal(raw, literal_offset), literal_offset))
        literal.clear()

    while index < len(expression):
        char = expression[index]
        if escaped:
            literal.append(char)
            escaped = False
            index += 1
            continue
        if in_quotes and char == "\\":
            literal.append(char)
            escaped = True
            index += 1
            continue
        if char == '"':
            if not literal:
                literal_offset = index
            literal.append(char)
            in_quotes = not in_quotes
            index += 1
            continue
        if in_quotes:
            literal.append(char)
            index += 1
            continue

        operator = expression[index : index + 2]
        if operator in (TokenKind.AND.value, TokenKind.OR.value):
            flush_literal()
            kind = TokenKind.AND if operator == TokenKind.AND.value else TokenKind.OR
            tokens.append(Token(kind, operator, index))
            index += 2
            literal_offset = index
            continue
        if char in "()":
            flush_literal()
            kind = TokenKind.OPEN if char == "(" else TokenKind.CLOSE
            tokens.append(Token(kind, char, index))
            index += 1
            literal_offset = index
            continue
        if char in "&|":
            raise SearchExpressionError(f"Use doubled operator at offset {index}")
        if not literal:
            literal_offset = index
        literal.append(char)
        index += 1

    if in_quotes or escaped:
        raise SearchExpressionError(f"Unmatched quote at offset {literal_offset}")
    flush_literal()
    if not tokens:
        raise SearchExpressionError("Search expression must contain a literal")
    return tuple(tokens)


class _Parser:
    def __init__(self, tokens: tuple[Token, ...]):
        self.tokens = tokens
        self.index = 0

    def parse(self) -> Expression:
        expression = self.parse_or()
        if self.index != len(self.tokens):
            token = self.tokens[self.index]
            raise SearchExpressionError(f"Unexpected token {token.value!r} at offset {token.offset}")
        return expression

    def parse_or(self) -> Expression:
        expression = self.parse_and()
        while self._accept(TokenKind.OR):
            expression = Or(expression, self.parse_and())
        return expression

    def parse_and(self) -> Expression:
        expression = self.parse_primary()
        while self._accept(TokenKind.AND):
            expression = And(expression, self.parse_primary())
        return expression

    def parse_primary(self) -> Expression:
        token = self._peek()
        if token is None:
            raise SearchExpressionError("Expression ends before an operand")
        if token.kind is TokenKind.LITERAL:
            self.index += 1
            return Literal(token.value)
        if token.kind is TokenKind.OPEN:
            self.index += 1
            expression = self.parse_or()
            closing = self._peek()
            if closing is None or closing.kind is not TokenKind.CLOSE:
                raise SearchExpressionError(f"Unmatched opening parenthesis at offset {token.offset}")
            self.index += 1
            return expression
        raise SearchExpressionError(f"Expected literal at offset {token.offset}, found {token.value!r}")

    def _accept(self, kind: TokenKind) -> bool:
        token = self._peek()
        if token is None or token.kind is not kind:
            return False
        self.index += 1
        return True

    def _peek(self) -> Token | None:
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]


def parse_search_string(search_string: str) -> Expression:
    """Parse with conventional precedence: parentheses, ``&&``, then ``||``."""
    return _Parser(tokenize(search_string)).parse()


def evaluate_search_expression(expression: Expression, text: str) -> bool:
    searchable = text.casefold()

    def evaluate(node: Expression) -> bool:
        if isinstance(node, Literal):
            return node.value in searchable
        if isinstance(node, And):
            return evaluate(node.left) and evaluate(node.right)
        return evaluate(node.left) or evaluate(node.right)

    return evaluate(expression)


def match_search_string(search_string: str, text: str) -> bool:
    return evaluate_search_expression(parse_search_string(search_string), text)
