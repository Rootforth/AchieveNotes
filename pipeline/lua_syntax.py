#!/usr/bin/env python3
"""Dependency-free fail-closed Lua syntax checker for AchieveNotes validation.

Implements the Lua 5.1 grammar used by WoW Retail plus Blizzard's commonly used
``continue`` statement. It validates syntax only; it does not execute addon code.
The parser enforces Rootforth's less-than-180 active-local ceiling per function.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

KEYWORDS = {
    "and", "break", "continue", "do", "else", "elseif", "end", "false", "for",
    "function", "goto", "if", "in", "local", "nil", "not", "or", "repeat",
    "return", "then", "true", "until", "while",
}
MULTI_SYMBOLS = ("...", "==", "~=", "<=", ">=", "..", "::", "<<", ">>", "//")
SINGLE_SYMBOLS = set("+-*/%^#=<>;:,(){}[].&|~")
NUMBER_RE = re.compile(
    r"""(?:
        0[xX][0-9A-Fa-f]+(?:\.[0-9A-Fa-f]*)?(?:[pP][+-]?\d+)?
      | (?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?
    )""",
    re.VERBOSE,
)


class LuaSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    offset: int
    line: int
    column: int


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last = text.rfind("\n", 0, offset)
    return line, offset + 1 if last < 0 else offset - last


def _long_bracket_level(text: str, index: int) -> int | None:
    if index >= len(text) or text[index] != "[":
        return None
    cursor = index + 1
    while cursor < len(text) and text[cursor] == "=":
        cursor += 1
    if cursor < len(text) and text[cursor] == "[":
        return cursor - index - 1
    return None


def _consume_long_bracket(text: str, index: int, level: int) -> int:
    close = "]" + ("=" * level) + "]"
    end = text.find(close, index + level + 2)
    if end < 0:
        line, col = _line_col(text, index)
        raise LuaSyntaxError(f"unterminated long bracket at {line}:{col}")
    return end + len(close)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    length = len(text)

    def emit(kind: str, value: str, offset: int) -> None:
        line, column = _line_col(text, offset)
        tokens.append(Token(kind, value, offset, line, column))

    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue

        if text.startswith("--", index):
            long_level = _long_bracket_level(text, index + 2)
            if long_level is not None:
                index = _consume_long_bracket(text, index + 2, long_level)
            else:
                newline = text.find("\n", index + 2)
                index = length if newline < 0 else newline + 1
            continue

        long_level = _long_bracket_level(text, index)
        if long_level is not None:
            start = index
            index = _consume_long_bracket(text, index, long_level)
            emit("string", text[start:index], start)
            continue

        if char in {"'", '"'}:
            quote = char
            start = index
            index += 1
            while index < length:
                current = text[index]
                if current == "\\":
                    index += 2
                    continue
                if current == quote:
                    index += 1
                    break
                if current in "\r\n":
                    line, col = _line_col(text, start)
                    raise LuaSyntaxError(f"newline in quoted string at {line}:{col}")
                index += 1
            else:
                line, col = _line_col(text, start)
                raise LuaSyntaxError(f"unterminated quoted string at {line}:{col}")
            emit("string", text[start:index], start)
            continue

        if char.isdigit() or (char == "." and index + 1 < length and text[index + 1].isdigit()):
            match = NUMBER_RE.match(text, index)
            if not match:
                line, col = _line_col(text, index)
                raise LuaSyntaxError(f"invalid number at {line}:{col}")
            emit("number", match.group(0), index)
            index = match.end()
            continue

        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < length and (text[index].isalnum() or text[index] == "_"):
                index += 1
            value = text[start:index]
            emit("keyword" if value in KEYWORDS else "name", value, start)
            continue

        for symbol in MULTI_SYMBOLS:
            if text.startswith(symbol, index):
                emit("symbol", symbol, index)
                index += len(symbol)
                break
        else:
            if char in SINGLE_SYMBOLS:
                emit("symbol", char, index)
                index += 1
                continue
            line, col = _line_col(text, index)
            raise LuaSyntaxError(f"unsupported character {char!r} at {line}:{col}")
            continue
        continue

    line, column = _line_col(text, length)
    tokens.append(Token("eof", "", length, line, column))
    return tokens


class Parser:
    PRECEDENCE = {
        "or": 1,
        "and": 2,
        "<": 3, ">": 3, "<=": 3, ">=": 3, "~=": 3, "==": 3,
        "|": 4,
        "~": 5,
        "&": 6,
        "<<": 7, ">>": 7,
        "..": 8,
        "+": 9, "-": 9,
        "*": 10, "/": 10, "//": 10, "%": 10,
        "^": 12,
    }
    RIGHT_ASSOCIATIVE = {"..", "^"}
    UNARY_PRECEDENCE = 11
    ACTIVE_LOCAL_LIMIT = 179

    def __init__(self, text: str) -> None:
        self.tokens = tokenize(text)
        self.index = 0
        self._function_active: list[int] = [0]
        self._function_max: list[int] = [0]
        self._scope_locals: list[list[int]] = [[0]]

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def error(self, message: str, token: Token | None = None) -> LuaSyntaxError:
        token = token or self.current
        return LuaSyntaxError(f"{message} at {token.line}:{token.column}")

    def at(self, value: str) -> bool:
        return self.current.value == value

    def consume(self, value: str | None = None, kind: str | None = None) -> Token:
        token = self.current
        if value is not None and token.value != value:
            raise self.error(f"expected {value!r}, found {token.value!r}", token)
        if kind is not None and token.kind != kind:
            raise self.error(f"expected {kind}, found {token.kind}:{token.value!r}", token)
        self.index += 1
        return token

    def enter_scope(self) -> None:
        self._scope_locals[-1].append(0)

    def exit_scope(self) -> None:
        count = self._scope_locals[-1].pop()
        self._function_active[-1] -= count

    def add_locals(self, count: int, token: Token | None = None) -> None:
        if count <= 0:
            return
        active = self._function_active[-1] + count
        if active > self.ACTIVE_LOCAL_LIMIT:
            raise self.error(
                f"too many active local variables ({active}; Rootforth ceiling {self.ACTIVE_LOCAL_LIMIT})",
                token,
            )
        self._function_active[-1] = active
        self._function_max[-1] = max(self._function_max[-1], active)
        self._scope_locals[-1][-1] += count

    def push_function(self, parameter_count: int, token: Token | None = None) -> None:
        self._function_active.append(0)
        self._function_max.append(0)
        self._scope_locals.append([0])
        self.add_locals(parameter_count, token)

    def pop_function(self) -> None:
        self._function_max.pop()
        self._function_active.pop()
        self._scope_locals.pop()

    def parse(self) -> int:
        self.parse_block(set(), new_scope=False)
        self.consume(kind="eof")
        return self._function_max[0]

    def parse_block(self, stop_words: set[str], *, new_scope: bool = True) -> None:
        if new_scope:
            self.enter_scope()
        try:
            while self.current.kind != "eof" and self.current.value not in stop_words:
                self.parse_statement()
                while self.at(";"):
                    self.consume(";")
        finally:
            if new_scope:
                self.exit_scope()

    def parse_statement(self) -> None:
        value = self.current.value
        if value == ";":
            self.consume(";")
            return
        if value == "if":
            self.parse_if()
            return
        if value == "while":
            self.consume("while")
            self.parse_expression()
            self.consume("do")
            self.parse_block({"end"})
            self.consume("end")
            return
        if value == "repeat":
            self.consume("repeat")
            self.enter_scope()
            try:
                self.parse_block({"until"}, new_scope=False)
                self.consume("until")
                self.parse_expression()
            finally:
                self.exit_scope()
            return
        if value == "do":
            self.consume("do")
            self.parse_block({"end"})
            self.consume("end")
            return
        if value == "for":
            self.parse_for()
            return
        if value == "function":
            self.consume("function")
            method = self.parse_function_name()
            self.parse_function_body(1 if method else 0)
            return
        if value == "local":
            self.parse_local()
            return
        if value == "return":
            self.consume("return")
            if self.current.kind != "eof" and self.current.value not in {"end", "elseif", "else", "until", ";"}:
                self.parse_expression_list()
            return
        if value in {"break", "continue"}:
            self.consume(value)
            return
        if value == "goto":
            self.consume("goto")
            self.consume(kind="name")
            return
        if value == "::":
            self.consume("::")
            self.consume(kind="name")
            self.consume("::")
            return

        assignable, called = self.parse_prefix_expression()
        if self.at("=") or self.at(","):
            if not assignable:
                raise self.error("assignment target is not assignable")
            while self.at(","):
                self.consume(",")
                other_assignable, _ = self.parse_prefix_expression()
                if not other_assignable:
                    raise self.error("assignment target is not assignable")
            self.consume("=")
            self.parse_expression_list()
            return
        if not called:
            raise self.error("statement must be an assignment or function call")

    def parse_if(self) -> None:
        self.consume("if")
        self.parse_expression()
        self.consume("then")
        self.parse_block({"elseif", "else", "end"})
        while self.at("elseif"):
            self.consume("elseif")
            self.parse_expression()
            self.consume("then")
            self.parse_block({"elseif", "else", "end"})
        if self.at("else"):
            self.consume("else")
            self.parse_block({"end"})
        self.consume("end")

    def parse_for(self) -> None:
        self.consume("for")
        first = self.consume(kind="name")
        if self.at("="):
            self.consume("=")
            self.parse_expression()
            self.consume(",")
            self.parse_expression()
            if self.at(","):
                self.consume(",")
                self.parse_expression()
            self.consume("do")
            self.enter_scope()
            try:
                self.add_locals(1, first)
                self.parse_block({"end"}, new_scope=False)
            finally:
                self.exit_scope()
            self.consume("end")
            return

        names = [first]
        while self.at(","):
            self.consume(",")
            names.append(self.consume(kind="name"))
        self.consume("in")
        self.parse_expression_list()
        self.consume("do")
        self.enter_scope()
        try:
            self.add_locals(len(names), first)
            self.parse_block({"end"}, new_scope=False)
        finally:
            self.exit_scope()
        self.consume("end")

    def parse_local(self) -> None:
        local_token = self.consume("local")
        if self.at("function"):
            self.consume("function")
            self.consume(kind="name")
            self.add_locals(1, local_token)
            self.parse_function_body()
            return
        names = [self.consume(kind="name")]
        while self.at(","):
            self.consume(",")
            names.append(self.consume(kind="name"))
        if self.at("="):
            self.consume("=")
            self.parse_expression_list()
        self.add_locals(len(names), local_token)

    def parse_function_name(self) -> bool:
        self.consume(kind="name")
        while self.at("."):
            self.consume(".")
            self.consume(kind="name")
        if self.at(":"):
            self.consume(":")
            self.consume(kind="name")
            return True
        return False

    def parse_function_body(self, implicit_parameters: int = 0) -> None:
        opening = self.consume("(")
        parameter_count = implicit_parameters
        if not self.at(")"):
            if self.at("..."):
                self.consume("...")
            else:
                self.consume(kind="name")
                parameter_count += 1
                while self.at(","):
                    self.consume(",")
                    if self.at("..."):
                        self.consume("...")
                        break
                    self.consume(kind="name")
                    parameter_count += 1
        self.consume(")")
        self.push_function(parameter_count, opening)
        try:
            self.parse_block({"end"}, new_scope=False)
            self.consume("end")
        finally:
            self.pop_function()

    def parse_expression_list(self) -> None:
        self.parse_expression()
        while self.at(","):
            self.consume(",")
            self.parse_expression()

    def parse_expression(self, minimum_precedence: int = 1) -> None:
        if self.current.value in {"not", "-", "#", "~"}:
            self.consume()
            self.parse_expression(self.UNARY_PRECEDENCE)
        else:
            self.parse_primary()
        while True:
            operator = self.current.value
            precedence = self.PRECEDENCE.get(operator)
            if precedence is None or precedence < minimum_precedence:
                break
            self.consume()
            next_minimum = precedence if operator in self.RIGHT_ASSOCIATIVE else precedence + 1
            self.parse_expression(next_minimum)

    def parse_primary(self) -> None:
        token = self.current
        if token.value in {"nil", "true", "false", "..."} or token.kind in {"number", "string"}:
            self.consume()
            return
        if token.value == "function":
            self.consume("function")
            self.parse_function_body()
            return
        if token.value == "{":
            self.parse_table_constructor()
            return
        if token.kind == "name" or token.value == "(":
            self.parse_prefix_expression()
            return
        raise self.error(f"expected expression, found {token.value!r}", token)

    def parse_table_constructor(self) -> None:
        self.consume("{")
        if self.at("}"):
            self.consume("}")
            return
        while True:
            if self.at("["):
                self.consume("[")
                self.parse_expression()
                self.consume("]")
                self.consume("=")
                self.parse_expression()
            elif self.current.kind == "name" and self.tokens[self.index + 1].value == "=":
                self.consume(kind="name")
                self.consume("=")
                self.parse_expression()
            else:
                self.parse_expression()
            if self.at(",") or self.at(";"):
                self.consume()
                if self.at("}"):
                    break
                continue
            break
        self.consume("}")

    def parse_arguments(self) -> None:
        if self.at("("):
            self.consume("(")
            if not self.at(")"):
                self.parse_expression_list()
            self.consume(")")
            return
        if self.at("{"):
            self.parse_table_constructor()
            return
        if self.current.kind == "string":
            self.consume(kind="string")
            return
        raise self.error("expected function-call arguments")

    def parse_prefix_expression(self) -> tuple[bool, bool]:
        if self.current.kind == "name":
            self.consume(kind="name")
            assignable = True
            called = False
        elif self.at("("):
            self.consume("(")
            self.parse_expression()
            self.consume(")")
            assignable = False
            called = False
        else:
            raise self.error("expected prefix expression")

        while True:
            if self.at("["):
                self.consume("[")
                self.parse_expression()
                self.consume("]")
                assignable = True
            elif self.at("."):
                self.consume(".")
                self.consume(kind="name")
                assignable = True
            elif self.at(":"):
                self.consume(":")
                self.consume(kind="name")
                self.parse_arguments()
                assignable = False
                called = True
            elif self.at("(") or self.at("{") or self.current.kind == "string":
                self.parse_arguments()
                assignable = False
                called = True
            else:
                break
        return assignable, called


def validate_lua_source(text: str) -> int:
    """Validate one Lua source and return max active locals in its top chunk."""
    return Parser(text).parse()
