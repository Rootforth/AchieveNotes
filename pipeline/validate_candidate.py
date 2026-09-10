#!/usr/bin/env python3
from __future__ import annotations

from bisect import bisect_right
import json
import re
import sys
from pathlib import Path

import lua_syntax
from lua_syntax import LuaSyntaxError, Parser, Token
from materialize_runtime import materialize

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "addon" / "AchieveNotes"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+\.\d+$")
EXPECTED_TOP_LEVEL = {
    "AchieveNotes.build.json",
    "AchieveNotes.lua",
    "AchieveNotes.toc",
    "FamilyInfo.lua",
    "LICENSE",
    "Libs",
    "Locale",
    "TooltipAdapter.lua",
    "UPSTREAM.md",
}

_LINE_TEXT: str | None = None
_LINE_STARTS: list[int] = [0]


def _fast_line_col(text: str, offset: int) -> tuple[int, int]:
    global _LINE_TEXT, _LINE_STARTS
    if text is not _LINE_TEXT:
        starts = [0]
        cursor = text.find("\n")
        while cursor >= 0:
            starts.append(cursor + 1)
            cursor = text.find("\n", cursor + 1)
        _LINE_TEXT = text
        _LINE_STARTS = starts
    line_index = bisect_right(_LINE_STARTS, offset) - 1
    return line_index + 1, offset - _LINE_STARTS[line_index] + 1


lua_syntax._line_col = _fast_line_col


def fail(message: str) -> None:
    raise RuntimeError(message)


def toc_value(text: str, key: str) -> str:
    match = re.search(rf"^##\s+{re.escape(key)}:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        fail(f"TOC header missing: {key}")
    return match.group(1).strip()


class UpvalueSafeParser(Parser):
    CAPTURED_UPVALUE_LIMIT = 49

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._binding_scopes: list[list[dict[str, int]]] = [[{}]]
        self._upvalues: list[set[int]] = [set()]
        self._next_binding_id = 1
        self.max_captured_upvalues = 0

    def enter_scope(self) -> None:
        super().enter_scope()
        self._binding_scopes[-1].append({})

    def exit_scope(self) -> None:
        self._binding_scopes[-1].pop()
        super().exit_scope()

    def _declare_names(self, names: list[str], token: Token | None = None) -> None:
        if not names:
            return
        super().add_locals(len(names), token)
        scope = self._binding_scopes[-1][-1]
        for name in names:
            scope[name] = self._next_binding_id
            self._next_binding_id += 1

    def _note_reference(self, name: str, token: Token) -> None:
        for scope in reversed(self._binding_scopes[-1]):
            if name in scope:
                return
        for function_index in range(len(self._binding_scopes) - 2, -1, -1):
            for scope in reversed(self._binding_scopes[function_index]):
                binding_id = scope.get(name)
                if binding_id is None:
                    continue
                captures = self._upvalues[-1]
                captures.add(binding_id)
                self.max_captured_upvalues = max(self.max_captured_upvalues, len(captures))
                if len(captures) > self.CAPTURED_UPVALUE_LIMIT:
                    raise self.error(
                        f"too many captured upvalues ({len(captures)}; Rootforth ceiling {self.CAPTURED_UPVALUE_LIMIT})",
                        token,
                    )
                return

    def _push_named_function(self, names: list[str], token: Token | None = None) -> None:
        super().push_function(0, token)
        self._binding_scopes.append([{}])
        self._upvalues.append(set())
        self._declare_names(names, token)

    def _pop_named_function(self) -> None:
        self._binding_scopes.pop()
        self._upvalues.pop()
        super().pop_function()

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
                self._declare_names([first.value], first)
                self.parse_block({"end"}, new_scope=False)
            finally:
                self.exit_scope()
            self.consume("end")
            return

        names = [first.value]
        while self.at(","):
            self.consume(",")
            names.append(self.consume(kind="name").value)
        self.consume("in")
        self.parse_expression_list()
        self.consume("do")
        self.enter_scope()
        try:
            self._declare_names(names, first)
            self.parse_block({"end"}, new_scope=False)
        finally:
            self.exit_scope()
        self.consume("end")

    def parse_local(self) -> None:
        local_token = self.consume("local")
        if self.at("function"):
            self.consume("function")
            name = self.consume(kind="name").value
            self._declare_names([name], local_token)
            self.parse_function_body()
            return
        names = [self.consume(kind="name").value]
        while self.at(","):
            self.consume(",")
            names.append(self.consume(kind="name").value)
        if self.at("="):
            self.consume("=")
            self.parse_expression_list()
        self._declare_names(names, local_token)

    def parse_function_name(self) -> bool:
        first = self.consume(kind="name")
        self._note_reference(first.value, first)
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
        names: list[str] = ["self"] if implicit_parameters else []
        if not self.at(")"):
            if self.at("..."):
                self.consume("...")
            else:
                names.append(self.consume(kind="name").value)
                while self.at(","):
                    self.consume(",")
                    if self.at("..."):
                        self.consume("...")
                        break
                    names.append(self.consume(kind="name").value)
        self.consume(")")
        self._push_named_function(names, opening)
        try:
            self.parse_block({"end"}, new_scope=False)
            self.consume("end")
        finally:
            self._pop_named_function()

    def parse_prefix_expression(self) -> tuple[bool, bool]:
        if self.current.kind == "name":
            token = self.consume(kind="name")
            self._note_reference(token.value, token)
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
    parser = UpvalueSafeParser(text)
    parser.parse()
    return parser.max_captured_upvalues


def validate_runtime() -> None:
    if not RUNTIME.is_dir():
        fail("runtime root was not materialized")
    actual_top = {path.name for path in RUNTIME.iterdir()}
    if actual_top != EXPECTED_TOP_LEVEL:
        fail(f"runtime top-level boundary mismatch: {sorted(actual_top)}")

    for path in RUNTIME.rglob("*"):
        if path.is_symlink():
            fail(f"symlink/reparse-like source is prohibited: {path.relative_to(RUNTIME)}")
        if path.name == ".git" or ".git" in path.parts:
            fail(f"Git metadata leaked into runtime package: {path.relative_to(RUNTIME)}")
        if path.is_file() and path.suffix.lower() in {".zip", ".7z", ".rar", ".tmp", ".bak"}:
            fail(f"prohibited package file type: {path.relative_to(RUNTIME)}")

    toc = (RUNTIME / "AchieveNotes.toc").read_text(encoding="utf-8-sig")
    build = json.loads((RUNTIME / "AchieveNotes.build.json").read_text(encoding="utf-8-sig"))
    version = toc_value(toc, "Version")
    if not VERSION_RE.fullmatch(version):
        fail(f"TOC version is not five-part: {version}")
    if build.get("schemaVersion") != 1 or build.get("project") != "AchieveNotes":
        fail("build metadata product identity mismatch")
    if build.get("version") != version:
        fail("TOC/build version mismatch")
    if version != (ROOT / "rootforth" / "version.txt").read_text(encoding="utf-8").strip():
        fail("materialized version does not match product version source")
    if toc_value(toc, "Interface") != "120100":
        fail("Retail interface must be 120100")
    if toc_value(toc, "Dependencies") != "HandyNotes":
        fail("AchieveNotes must depend only on HandyNotes")
    if toc_value(toc, "Category") != "Map":
        fail("Blizzard AddOn List category must be Map")
    if not toc_value(toc, "IconTexture"):
        fail("Blizzard AddOn List icon metadata is required")
    if "LibQTip" in toc or "Libs/Ace3" in toc or "Libs/LibStub" in toc:
        fail("removed bundled-library dependency remains in runtime TOC")

    main = (RUNTIME / "AchieveNotes.lua").read_text(encoding="utf-8-sig")
    family = (RUNTIME / "FamilyInfo.lua").read_text(encoding="utf-8-sig")
    combined = main + "\n" + family
    if "GetTrackedAchievements(" in combined:
        fail("removed GetTrackedAchievements API remains in effective runtime source")
    if "C_ContentTracking.GetTrackedIDs(Enum.ContentTrackingType.Achievement)" not in combined:
        fail("current achievement content-tracking API is missing")
    if "factionData.reaction == 8" not in main:
        fail("current C_Reputation faction-data handling is missing")
    if "function HNA:GetNodes2(" not in family:
        fail("modern HandyNotes GetNodes2 adapter is missing")
    if "HereBeDragons-Migrate" not in family:
        fail("modern uiMapID migration dependency is missing from the interaction adapter")
    if "modernActiveNodes[requestUIMapID] = nil" not in family:
        fail("modern interaction cache reset is missing")
    if "Modified by Rootforth for AchieveNotes, 2026." not in main:
        fail("Apache modified-file notice is missing from modified upstream source")
    if "Copyright 2015-2020, r. brian harrison" not in main:
        fail("upstream copyright notice was not preserved")

    for required in (
        "Created by Willbearal-Area52",
        "Willbearal's Workshop",
        "https://discord.gg/xVmydh94SB",
        "ShowDiscordCopyDialog",
    ):
        if required not in combined:
            fail(f"required Rootforth family information is missing: {required}")

    license_text = (RUNTIME / "LICENSE").read_text(encoding="utf-8-sig")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        fail("Apache-2.0 license was not preserved in the runtime package")

    provenance = (RUNTIME / "UPSTREAM.md").read_text(encoding="utf-8-sig")
    for required in (
        "idiomatic/HandyNotes_Achievements",
        "13305ad39850ef57c6d72635eed6d340016644b2",
        "cd1c91997edc45998d1ac36cff37e050ca1a46b1",
        "internal development candidate",
        "not authorized for public Rootforth distribution",
    ):
        if required not in provenance:
            fail(f"runtime provenance marker is missing: {required}")

    lua_files = sorted(RUNTIME.rglob("*.lua"))
    if not lua_files:
        fail("runtime package contains no Lua source")
    max_upvalues = 0
    max_upvalue_file = None
    for path in lua_files:
        text = path.read_text(encoding="utf-8-sig")
        try:
            captured = validate_lua_source(text)
        except LuaSyntaxError as exc:
            fail(f"Lua validation failed for {path.relative_to(RUNTIME)}: {exc}")
        if captured > max_upvalues:
            max_upvalues = captured
            max_upvalue_file = path.relative_to(RUNTIME)

    print(f"Validated {len(lua_files)} Lua files; max captured upvalues={max_upvalues} ({max_upvalue_file})")


def main() -> int:
    try:
        materialize()
        validate_runtime()
    except Exception as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1
    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
