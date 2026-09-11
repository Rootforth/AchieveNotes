# Changelog

## 12.1.0.0.3 - internal test candidate
- Move AchieveNotes onto HandyNotes' current `GetNodes2(uiMapID, minimap)` plugin path.
- Keep pin interaction backing data keyed by the same modern UI map ID that HandyNotes assigns to the pin instead of relying on the deprecated mapFile round-trip.
- Stop globally wiping interaction backing data when world-map/minimap node requests occur independently.
- Restore functional hover tooltips and meaningful left-click behavior for AchieveNotes pins.
- Retain the 12.1.0.0.2 removal of the unused AceTimer-3.0 embed and all earlier Retail 12.1 compatibility changes.
- Keep the historical AchievementLocations database unchanged; modern expansion coverage remains a separate data-maintenance concern.

## 12.1.0.0.2 - internal test candidate
- Remove the inherited but unused AceTimer-3.0 embed that prevented AchieveNotes from loading when the HandyNotes runtime did not expose AceTimer.
- Preserve all 12.1.0.0.1 compatibility and packaging work.

## 12.1.0.0.1 - internal test candidate
- Establish AchieveNotes as a Rootforth-maintained derivative of HandyNotes: Achievements.
- Update Retail interface metadata to 12.1.0.
- Replace removed achievement tracking calls with `C_ContentTracking`.
- Correct `C_Reputation.GetFactionDataByID()` handling.
- Replace the old LibQTip dependency with an addon-owned tooltip adapter.
- Establish deterministic internal materialization, validation, provenance, and Rootforth product identity.

## Upstream history
The original upstream changelog is preserved in Git history and the exact upstream source anchor `13305ad39850ef57c6d72635eed6d340016644b2`.
