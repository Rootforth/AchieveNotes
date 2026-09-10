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
