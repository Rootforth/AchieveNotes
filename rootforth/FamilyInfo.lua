-- AchieveNotes Rootforth modification, 2026.

local ADDON_NAME = ...
local DISCORD_URL = "https://discord.gg/xVmydh94SB"
local HNA = LibStub("AceAddon-3.0"):GetAddon(ADDON_NAME, true)
if not HNA then return end

local copyFrame
local copyBox

local function createCopyFrame()
    local frame = CreateFrame("Frame", nil, UIParent, "BackdropTemplate")
    frame:SetSize(500, 150)
    frame:SetPoint("CENTER")
    frame:SetFrameStrata("DIALOG")
    frame:SetClampedToScreen(true)
    frame:EnableMouse(true)
    frame:SetMovable(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", frame.StartMoving)
    frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
    frame:SetBackdrop({
        bgFile = "Interface/Tooltips/UI-Tooltip-Background",
        edgeFile = "Interface/Tooltips/UI-Tooltip-Border",
        tile = true,
        tileSize = 16,
        edgeSize = 16,
        insets = { left = 4, right = 4, top = 4, bottom = 4 },
    })
    frame:SetBackdropColor(0.05, 0.05, 0.05, 0.95)

    local title = frame:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
    title:SetPoint("TOP", 0, -18)
    title:SetText("Willbearal's Workshop")

    local instruction = frame:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
    instruction:SetPoint("TOP", title, "BOTTOM", 0, -12)
    instruction:SetText("Copy the Discord invitation below:")

    local edit = CreateFrame("EditBox", nil, frame, "InputBoxTemplate")
    edit:SetSize(390, 28)
    edit:SetPoint("TOP", instruction, "BOTTOM", 0, -10)
    edit:SetAutoFocus(false)
    edit:SetText(DISCORD_URL)
    edit:SetScript("OnEscapePressed", function(self)
        self:ClearFocus()
        frame:Hide()
    end)
    edit:SetScript("OnEnterPressed", function(self)
        self:HighlightText()
    end)

    local close = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    close:SetSize(80, 24)
    close:SetPoint("BOTTOM", 0, 14)
    close:SetText("Close")
    close:SetScript("OnClick", function()
        frame:Hide()
    end)

    frame:Hide()
    copyFrame = frame
    copyBox = edit
end

function HNA:ShowDiscordCopyDialog()
    if not copyFrame then
        createCopyFrame()
    end
    copyBox:SetText(DISCORD_URL)
    copyFrame:Show()
    copyBox:SetFocus()
    copyBox:HighlightText()
end

-- Modern HandyNotes adapter. The upstream addon used the deprecated GetNodes
-- mapFile path and a global interaction cache that could be wiped after pins
-- were drawn. Current HandyNotes 12.1 prefers GetNodes2(uiMapID, minimap).
local HandyNotes = LibStub("AceAddon-3.0"):GetAddon("HandyNotes", true)
local HBDMigrate = LibStub:GetLibrary("HereBeDragons-Migrate", true)
local AchievementLocations = LibStub:GetLibrary("AchievementLocations-1.0", true)
local InstanceLocations = LibStub:GetLibrary("InstanceLocations-1.0", true)
local TooltipAdapter = _G.AchieveNotesTooltipAdapter
local EMPTY = {}
local modernActiveNodes = {}

assert(HandyNotes, ADDON_NAME .. " requires HandyNotes")
assert(HBDMigrate, ADDON_NAME .. " requires HereBeDragons-Migrate")
assert(AchievementLocations, ADDON_NAME .. " requires AchievementLocations-1.0")
assert(InstanceLocations, ADDON_NAME .. " requires InstanceLocations-1.0")
assert(TooltipAdapter, ADDON_NAME .. " tooltip adapter failed to load")

local function addActiveNode(touched, uiMapID, coord, row)
    if not uiMapID or not coord or not row then return end
    if not touched[uiMapID] then
        modernActiveNodes[uiMapID] = {}
        touched[uiMapID] = true
    end
    local nodes = modernActiveNodes[uiMapID]
    nodes[#nodes + 1] = coord
    nodes[#nodes + 1] = row
end

local function sortActiveNodes(nodes)
    if not HNA.db or not HNA.db.profile.sort_by_tracked then return nodes end
    local tracked = {}
    if C_ContentTracking and C_ContentTracking.GetTrackedIDs and Enum and Enum.ContentTrackingType then
        for _, achievementID in ipairs(C_ContentTracking.GetTrackedIDs(Enum.ContentTrackingType.Achievement) or EMPTY) do
            tracked[achievementID] = true
        end
    end

    local first = {}
    local rest = {}
    for index = 1, #nodes, 2 do
        local row = nodes[index + 1]
        local target = tracked[row[2]] and first or rest
        target[#target + 1] = nodes[index]
        target[#target + 1] = row
    end
    for index = 1, #rest do
        first[#first + 1] = rest[index]
    end
    return first
end

function HNA:GetNodes2(requestUIMapID, minimap)
    local touched = {}
    modernActiveNodes[requestUIMapID] = nil

    local function validRows(uiMapID, overrideUIMapID, overrideCoord)
        local _, dungeonLevel, mapFile = HBDMigrate:GetLegacyMapInfo(uiMapID)
        if not mapFile then return end

        for _, row in ipairs(AchievementLocations:Get(mapFile) or EMPTY) do
            if (dungeonLevel or row.floor) == (row.floor or dungeonLevel) and self:Valid(row) then
                local coord = row[3] and row[4] and HandyNotes:getCoord(row[3], row[4])
                local displayMapID = overrideUIMapID or uiMapID
                local displayCoord = overrideCoord or coord or self.DEFAULT_COORD
                addActiveNode(touched, displayMapID, displayCoord, row)
                coroutine.yield(displayCoord, displayMapID, row)
            end
        end

        local zones = HandyNotes:GetContinentZoneList(uiMapID)
        for _, subMapID in ipairs(zones or EMPTY) do
            validRows(
                subMapID,
                overrideUIMapID,
                overrideCoord or (self.db.profile.clean_continents and self.ZONE_COORD)
            )
        end

        for _, instanceMapFile in ipairs(InstanceLocations:GetBelow(mapFile) or EMPTY) do
            local parentMapFile, instanceX, instanceY = unpack(InstanceLocations:GetLocation(instanceMapFile))
            local instanceMapID = HBDMigrate:GetUIMapIDFromMapFile(instanceMapFile)
            local parentMapID = HBDMigrate:GetUIMapIDFromMapFile(parentMapFile)
            local coord = instanceX and instanceY and HandyNotes:getCoord(instanceX, instanceY)
            if instanceMapID then
                validRows(instanceMapID, parentMapID or overrideUIMapID, overrideCoord or coord)
            end
        end
    end

    local producer = coroutine.create(function()
        validRows(requestUIMapID, nil, nil)
    end)

    local function iterator()
        local okay, coord, uiMapID, row = coroutine.resume(producer)
        if not okay then
            print(string.format("|cffff0000%s Error:|r %s", ADDON_NAME, tostring(coord)))
            return nil
        end
        if not row then return nil end
        return coord, uiMapID, self.ICON_PATH, self.db.profile.icon_scale, self.db.profile.icon_alpha
    end

    return iterator, nil, nil
end

function HNA:OnEnter(uiMapID, nearCoord)
    local nodes = sortActiveNodes(modernActiveNodes[uiMapID] or EMPTY)
    local tooltip = TooltipAdapter:Acquire(ADDON_NAME, 2, "LEFT", "RIGHT")
    local firstRow = true
    local previousAchievementID

    for index = 1, #nodes, 2 do
        local coord, row = nodes[index], nodes[index + 1]
        if HNA:HandyNotesCoordsNear(coord, nearCoord) and HNA:Valid(row) then
            local achievementID = row[2]
            local criterion = row.criterion
            local _, name, _, _, _, _, _, description = GetAchievementInfo(achievementID)

            if achievementID ~= previousAchievementID then
                if not firstRow then tooltip:AddSeparator() end
                firstRow = false
                tooltip:AddHeader(name)
                tooltip:AddLine(description)
                previousAchievementID = achievementID
            end

            if row.faction then
                local factionName, _, standing = HNA:GetFactionInfoByID(row.faction)
                local color = FACTION_BAR_COLORS[standing]
                local standingText = HNA.FACTION_STANDING_LABELS[standing] or "Unknown"
                if color then standingText = HNA:RGBToColorCode(color) .. standingText .. "|r" end
                tooltip:AddSeparator()
                tooltip:AddLine(factionName, standingText)
            end

            if criterion then
                local criterionDescription, quantityString
                if type(criterion) == "number" then
                    criterionDescription, _, _, _, _, _, _, _, quantityString = GetAchievementCriteriaInfoByID(achievementID, criterion)
                else
                    criterionDescription, _, _, _, _, _, _, _, quantityString = HNA:GetAchievementCriteriaInfoByDescription(achievementID, criterion)
                end
                if quantityString == "0" then quantityString = "" end
                if criterionDescription then
                    tooltip:AddSeparator()
                    tooltip:AddLine(criterionDescription, quantityString)
                end
            end
        end
    end

    if firstRow then
        TooltipAdapter:Release(tooltip)
        return
    end
    tooltip:SmartAnchorTo(self)
    tooltip:Show()
end

function HNA:OnLeave()
    TooltipAdapter:Release()
end

function HNA:OnClick(button, down, uiMapID, nearCoord)
    if down or button ~= "LeftButton" then return end
    local nodes = modernActiveNodes[uiMapID] or EMPTY
    for index = 1, #nodes, 2 do
        local coord, row = nodes[index], nodes[index + 1]
        if HNA:HandyNotesCoordsNear(coord, nearCoord) and HNA:Valid(row) then
            local achievementID = row[2]
            if type(AchievementFrame_LoadUI) == "function" and not AchievementFrame then
                pcall(AchievementFrame_LoadUI)
            end
            local opened = false
            if AchievementFrame and type(ShowUIPanel) == "function" then
                opened = pcall(ShowUIPanel, AchievementFrame)
            end
            if type(AchievementFrame_SelectAchievement) == "function" then
                opened = pcall(AchievementFrame_SelectAchievement, achievementID) or opened
            end
            if not opened then
                local link = GetAchievementLink(achievementID)
                if link then print(link) end
            end
            return
        end
    end
end
