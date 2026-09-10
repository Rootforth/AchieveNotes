#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "addon" / "AchieveNotes"
VERSION_FILE = ROOT / "rootforth" / "version.txt"
UPSTREAM_SHA = "13305ad39850ef57c6d72635eed6d340016644b2"
ACHIEVEMENT_LOCATIONS_PATH = Path("Libs/AchievementLocations-1.0")
ACHIEVEMENT_LOCATIONS_SHA = "cd1c91997edc45998d1ac36cff37e050ca1a46b1"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+\.\d+$")

ACHIEVEMENT_LOCATION_FILES = (
    "AchievementLocations-1.0.lua",
    "AchievementLocations_data.lua",
    "AchievementLocations_cartography.lua",
    "AchievementLocations_soloable.lua",
    "AchievementLocations_group.lua",
    "AchievementLocations_pvp.lua",
    "AchievementLocations_reputation.lua",
    "AchievementLocations_pet.lua",
    "AchievementLocations_seasonal.lua",
    "AchievementLocations_seasonal_brew.lua",
    "AchievementLocations_seasonal_children.lua",
    "AchievementLocations_seasonal_darkmoon.lua",
    "AchievementLocations_seasonal_hallow.lua",
    "AchievementLocations_seasonal_love.lua",
    "AchievementLocations_seasonal_lunar.lua",
    "AchievementLocations_seasonal_mid.lua",
    "AchievementLocations_seasonal_noble.lua",
    "AchievementLocations_seasonal_pilgrim.lua",
    "AchievementLocations_seasonal_winter.lua",
)

TRACKED_REPLACEMENT = '''local function SortByTrackedAchievement(nodes)
    local trackedAchievements = {}
    if C_ContentTracking and C_ContentTracking.GetTrackedIDs and Enum and Enum.ContentTrackingType then
        local trackedIDs = C_ContentTracking.GetTrackedIDs(Enum.ContentTrackingType.Achievement) or EMPTY
        for _, achievementID in ipairs(trackedIDs) do
            trackedAchievements[achievementID] = true
        end
    end

    local sortedNodes = {}
    local notTrackedNodes = {}

    for nodeIndex = 1, #nodes, 2 do
        local row = nodes[nodeIndex + 1]
        local achievementID = row[2]

        if trackedAchievements[achievementID] then
            table.insert(sortedNodes, nodes[nodeIndex])
            table.insert(sortedNodes, nodes[nodeIndex + 1])
        else
            table.insert(notTrackedNodes, nodes[nodeIndex])
            table.insert(notTrackedNodes, nodes[nodeIndex + 1])
        end
    end

    for nodeIndex = 1, #notTrackedNodes, 2 do
        table.insert(sortedNodes, notTrackedNodes[nodeIndex])
        table.insert(sortedNodes, notTrackedNodes[nodeIndex + 1])
    end

    return sortedNodes
end
'''

ABOUT_REPLACEMENT = '''            sort_by_tracked = {
                type = "toggle",
                name = L["Sort by tracked"],
                desc = L["Sort achievements by tracked"],
                width = "full",
                arg = "sort_by_tracked",
                order = 7
            },
            rootforth_about = {
                type = "group",
                name = "About AchieveNotes",
                inline = true,
                order = 100,
                args = {
                    creator = {
                        type = "description",
                        name = "Created by Willbearal-Area52",
                        order = 1,
                    },
                    workshop = {
                        type = "description",
                        name = "Willbearal's Workshop",
                        order = 2,
                    },
                    discord = {
                        type = "execute",
                        name = "|cff3399ffhttps://discord.gg/xVmydh94SB|r",
                        desc = "Open a copy box for the Willbearal's Workshop Discord invitation.",
                        width = "full",
                        order = 3,
                        func = function()
                            self:ShowDiscordCopyDialog()
                        end,
                    },
                },
            }
'''


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        list(args), cwd=cwd or ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stdout}")
    return result.stdout.strip()


def verify_parent() -> None:
    head = run("git", "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RuntimeError("unable to resolve candidate Git HEAD")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", UPSTREAM_SHA, head], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    if ancestor.returncode != 0:
        raise RuntimeError("candidate is not descended from the selected upstream source")

    entry = run("git", "ls-tree", "HEAD", ACHIEVEMENT_LOCATIONS_PATH.as_posix())
    parts = entry.split()
    if len(parts) < 3 or parts[0] != "160000" or parts[1] != "commit" or parts[2] != ACHIEVEMENT_LOCATIONS_SHA:
        raise RuntimeError("AchievementLocations gitlink does not match the authorized exact pin")


def materialize_dependency() -> Path:
    run("git", "submodule", "sync", "--", ACHIEVEMENT_LOCATIONS_PATH.as_posix())
    run("git", "submodule", "update", "--init", "--depth", "1", "--", ACHIEVEMENT_LOCATIONS_PATH.as_posix())
    source = ROOT / ACHIEVEMENT_LOCATIONS_PATH
    head = run("git", "rev-parse", "HEAD", cwd=source)
    if head != ACHIEVEMENT_LOCATIONS_SHA:
        raise RuntimeError(f"AchievementLocations checkout mismatch: {head}")
    return source


def patch_main_source() -> str:
    source = (ROOT / "HandyNotes_Achievements.lua").read_text(encoding="utf-8-sig")
    copyright_line = "-- Copyright 2015-2020, r. brian harrison.  all rights reserved."
    if source.count(copyright_line) != 1:
        raise RuntimeError("upstream copyright marker changed unexpectedly")
    source = source.replace(
        copyright_line,
        copyright_line + "\n-- Modified by Rootforth for AchieveNotes, 2026.",
        1,
    )

    qtip_old = '''local QTip = LibStub:GetLibrary("LibQTip-1.0")
assert(QTip, string.format(L["%s requires %s"], ADDON_NAME, "LibQTip-1.0"))'''
    qtip_new = '''local QTip = AchieveNotesTooltipAdapter
assert(QTip, string.format("%s tooltip adapter failed to load", ADDON_NAME))'''
    if source.count(qtip_old) != 1:
        raise RuntimeError("upstream LibQTip block changed unexpectedly")
    source = source.replace(qtip_old, qtip_new, 1)

    sort_start = source.find("function SortByTrackedAchievement(nodes)")
    sort_end = source.find("\nfunction HNA:OnEnter", sort_start)
    if sort_start < 0 or sort_end < 0:
        raise RuntimeError("upstream tracked-achievement block changed unexpectedly")
    source = source[:sort_start] + TRACKED_REPLACEMENT + source[sort_end:]

    rep_old = '''        local _, _, standing = C_Reputation.GetFactionDataByID(row.faction)
        completed = (standing == 8)'''
    rep_new = '''        local factionData = C_Reputation.GetFactionDataByID(row.faction)
        completed = factionData ~= nil and factionData.reaction == 8'''
    if source.count(rep_old) != 1:
        raise RuntimeError("upstream reputation completion block changed unexpectedly")
    source = source.replace(rep_old, rep_new, 1)

    about_old = '''            sort_by_tracked = {
                type = "toggle",
                name = L["Sort by tracked"],
                desc = L["Sort achievements by tracked"],
                width = "full",
                arg = "sort_by_tracked",
                order = 7
            }
'''
    if source.count(about_old) != 1:
        raise RuntimeError("upstream options block changed unexpectedly")
    source = source.replace(about_old, ABOUT_REPLACEMENT, 1)
    return source


def materialize() -> Path:
    verify_parent()
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(version):
        raise RuntimeError(f"invalid five-part AchieveNotes version: {version}")

    dependency = materialize_dependency()

    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir(parents=True)

    shutil.copy2(ROOT / "LICENSE", RUNTIME / "LICENSE")
    shutil.copytree(ROOT / "Locale", RUNTIME / "Locale")
    shutil.copytree(ROOT / "Libs" / "InstanceLocations-1.0", RUNTIME / "Libs" / "InstanceLocations-1.0")
    shutil.copytree(ROOT / "Libs" / "InSeason-1.1", RUNTIME / "Libs" / "InSeason-1.1")

    dep_target = RUNTIME / "Libs" / "AchievementLocations-1.0"
    dep_target.mkdir(parents=True)
    for name in ACHIEVEMENT_LOCATION_FILES:
        source_file = dependency / name
        if not source_file.is_file():
            raise RuntimeError(f"pinned AchievementLocations file is missing: {name}")
        shutil.copy2(source_file, dep_target / name)

    shutil.copy2(ROOT / "rootforth" / "TooltipAdapter.lua", RUNTIME / "TooltipAdapter.lua")
    shutil.copy2(ROOT / "rootforth" / "FamilyInfo.lua", RUNTIME / "FamilyInfo.lua")
    (RUNTIME / "AchieveNotes.lua").write_text(patch_main_source(), encoding="utf-8", newline="\n")

    toc_template = (ROOT / "rootforth" / "AchieveNotes.toc.in").read_text(encoding="utf-8")
    if toc_template.count("@VERSION@") != 1:
        raise RuntimeError("TOC template version marker is invalid")
    (RUNTIME / "AchieveNotes.toc").write_text(toc_template.replace("@VERSION@", version), encoding="utf-8", newline="\n")

    build = {
        "schemaVersion": 1,
        "project": "AchieveNotes",
        "version": version,
        "upstreamRepository": "idiomatic/HandyNotes_Achievements",
        "upstreamCommit": UPSTREAM_SHA,
        "achievementLocationsCommit": ACHIEVEMENT_LOCATIONS_SHA,
        "distributionState": "internal-test-only",
    }
    (RUNTIME / "AchieveNotes.build.json").write_text(
        json.dumps(build, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (RUNTIME / "UPSTREAM.md").write_text(
        "# AchieveNotes provenance\n\n"
        "AchieveNotes is a Rootforth-maintained derivative of idiomatic/HandyNotes_Achievements, "
        f"based on exact upstream commit `{UPSTREAM_SHA}` under Apache License 2.0.\n\n"
        "The runtime used for internal development currently materializes the exact published "
        f"AchievementLocations commit `{ACHIEVEMENT_LOCATIONS_SHA}`. That separate repository does "
        "not declare a redistribution license in its repository. This internal development candidate "
        "is therefore not authorized for public Rootforth distribution until redistribution rights "
        "are established or that dependency is replaced.\n",
        encoding="utf-8",
        newline="\n",
    )
    return RUNTIME


if __name__ == "__main__":
    print(materialize())
