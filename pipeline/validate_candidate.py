#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from lua_syntax import LuaSyntaxError, tokenize, validate_lua_source
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


def fail(message: str) -> None:
    raise RuntimeError(message)


def toc_value(text: str, key: str) -> str:
    match = re.search(rf"^##\s+{re.escape(key)}:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        fail(f"TOC header missing: {key}")
    return match.group(1).strip()


def conservative_local_binding_count(text: str) -> int:
    """Return a safe whole-file upper bound for any function's captured upvalues.

    Every captured upvalue must originate from a local binding in the same Lua
    chunk. Requiring fewer than 50 local bindings in the entire shipped file is
    stricter than the Rootforth <50 captured-upvalue requirement and therefore
    fails closed for this small addon without undercounting lexical captures.
    """
    tokens = tokenize(text)
    total = 0
    index = 0
    while index < len(tokens) - 1:
        if tokens[index].value != "local":
            index += 1
            continue
        cursor = index + 1
        if tokens[cursor].value == "function":
            total += 1
            index = cursor + 2
            continue
        while cursor < len(tokens) and tokens[cursor].kind == "name":
            total += 1
            cursor += 1
            if tokens[cursor].value != ",":
                break
            cursor += 1
        index = max(index + 1, cursor)
    return total


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
    if "GetTrackedAchievements(" in main:
        fail("removed GetTrackedAchievements API remains in effective runtime source")
    if "C_ContentTracking.GetTrackedIDs(Enum.ContentTrackingType.Achievement)" not in main:
        fail("current achievement content-tracking API is missing")
    if "factionData.reaction == 8" not in main:
        fail("current C_Reputation faction-data handling is missing")
    if "Modified by Rootforth for AchieveNotes, 2026." not in main:
        fail("Apache modified-file notice is missing from modified upstream source")
    if "Copyright 2015-2020, r. brian harrison" not in main:
        fail("upstream copyright notice was not preserved")

    family = (RUNTIME / "FamilyInfo.lua").read_text(encoding="utf-8-sig")
    combined = main + "\n" + family
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
    if "internal development candidate" not in provenance or "not authorized for public Rootforth distribution" not in provenance:
        fail("public-distribution dependency warning is missing")

    lua_files = sorted(RUNTIME.rglob("*.lua"))
    if not lua_files:
        fail("runtime package contains no Lua source")
    for path in lua_files:
        text = path.read_text(encoding="utf-8-sig")
        try:
            validate_lua_source(text)
        except LuaSyntaxError as exc:
            fail(f"Lua syntax/local-budget failure in {path.relative_to(RUNTIME)}: {exc}")
        local_bindings = conservative_local_binding_count(text)
        if local_bindings >= 50:
            fail(
                f"conservative upvalue safety ceiling exceeded in {path.relative_to(RUNTIME)}: "
                f"{local_bindings} local bindings (must remain <50 for this validator model)"
            )

    print(
        f"PASS AchieveNotes {version}: {len(lua_files)} Lua files; "
        "Retail/API identity, licensing boundary, syntax, local and upvalue safety checks passed"
    )


def main() -> int:
    try:
        materialize()
        validate_runtime()
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
