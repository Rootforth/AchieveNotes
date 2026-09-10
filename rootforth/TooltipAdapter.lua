-- AchieveNotes Rootforth modification, 2026.
-- Replaces the upstream LibQTip dependency with an addon-owned GameTooltip adapter.

local ADDON_NAME = ...

local Adapter = {}
Adapter.__index = Adapter

local function getTooltip(self)
    if self.frame then
        return self.frame
    end

    local frame = CreateFrame("GameTooltip", nil, UIParent, "GameTooltipTemplate")
    frame:SetFrameStrata("TOOLTIP")
    self.frame = frame
    return frame
end

function Adapter:Acquire()
    local frame = getTooltip(self)
    frame:Hide()
    frame:ClearLines()
    return self
end

function Adapter:Release()
    local frame = getTooltip(self)
    frame:Hide()
    frame:ClearLines()
end

function Adapter:AddSeparator()
    getTooltip(self):AddLine(" ")
end

function Adapter:SetHeaderFont()
    -- Header presentation is owned by AddHeader below.
end

function Adapter:SetFont()
    -- Body presentation uses GameTooltip's normal font objects.
end

function Adapter:AddHeader(text)
    getTooltip(self):AddLine(tostring(text or ""), 0.2, 1.0, 0.2, true)
end

function Adapter:AddLine(left, right)
    local frame = getTooltip(self)
    if right ~= nil and tostring(right) ~= "" then
        frame:AddDoubleLine(tostring(left or ""), tostring(right), 1, 1, 1, 1, 1, 1)
    else
        frame:AddLine(tostring(left or ""), 1, 1, 1, true)
    end
end

function Adapter:SmartAnchorTo(anchor)
    local frame = getTooltip(self)
    frame:SetOwner(anchor or UIParent, "ANCHOR_CURSOR")
end

function Adapter:Show()
    getTooltip(self):Show()
end

_G.AchieveNotesTooltipAdapter = Adapter
