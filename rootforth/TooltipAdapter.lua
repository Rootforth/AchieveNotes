-- AchieveNotes Rootforth modification, 2026.
-- Replaces the upstream LibQTip dependency with an addon-owned GameTooltip adapter.

local Adapter = {}
Adapter.__index = Adapter

local function getTooltip(self)
    if self.frame then return self.frame end
    local frame = CreateFrame("GameTooltip", nil, UIParent, "GameTooltipTemplate")
    frame:SetFrameStrata("TOOLTIP")
    self.frame = frame
    return frame
end

local function resetLines(self)
    self.lines = {}
    self.rendered = false
    self.lastLineCount = 0
end

local function renderLines(self)
    if self.rendered then return end
    local frame = getTooltip(self)
    frame:ClearLines()
    local lines = self.lines or {}
    for index = 1, #lines do
        local line = lines[index]
        if line.kind == "separator" then
            frame:AddLine(" ")
        elseif line.kind == "header" then
            frame:AddLine(line.left, 0.2, 1.0, 0.2, true)
        elseif line.right ~= nil and line.right ~= "" then
            frame:AddDoubleLine(line.left, line.right, 1, 1, 1, 1, 1, 1)
        else
            frame:AddLine(line.left, 1, 1, 1, true)
        end
    end
    self.lastLineCount = #lines
    self.rendered = true
end

function Adapter:Acquire()
    local frame = getTooltip(self)
    frame:Hide()
    frame:ClearLines()
    self.ownerReady = false
    resetLines(self)
    return self
end

function Adapter:Release()
    local frame = getTooltip(self)
    frame:Hide()
    frame:ClearLines()
    self.ownerReady = false
    resetLines(self)
end

function Adapter:AddSeparator()
    local lines = self.lines or {}
    self.lines = lines
    lines[#lines + 1] = { kind = "separator" }
end

function Adapter:SetHeaderFont()
    -- Header presentation is owned by AddHeader below.
end

function Adapter:SetFont()
    -- Body presentation uses GameTooltip's normal font objects.
end

function Adapter:AddHeader(text)
    local lines = self.lines or {}
    self.lines = lines
    lines[#lines + 1] = { kind = "header", left = tostring(text or "") }
end

function Adapter:AddLine(left, right)
    local lines = self.lines or {}
    self.lines = lines
    lines[#lines + 1] = {
        kind = "line",
        left = tostring(left or ""),
        right = right ~= nil and tostring(right) or nil,
    }
end

function Adapter:SmartAnchorTo(anchor)
    local frame = getTooltip(self)
    -- GameTooltip ownership must be established before content is rendered.
    -- SetOwner can reset tooltip state, so render the buffered rows afterwards.
    frame:SetOwner(anchor or UIParent, "ANCHOR_CURSOR")
    self.ownerReady = true
    self.rendered = false
    renderLines(self)
end

function Adapter:Show()
    local frame = getTooltip(self)
    if not self.ownerReady then
        frame:SetOwner(UIParent, "ANCHOR_CURSOR")
        self.ownerReady = true
        self.rendered = false
    end
    renderLines(self)
    frame:Show()
end

function Adapter:IsShown()
    local frame = self.frame
    return frame ~= nil and frame:IsShown() == true and (self.lastLineCount or 0) > 0
end

function Adapter:GetLineCount()
    return tonumber(self.lastLineCount) or 0
end

_G.AchieveNotesTooltipAdapter = Adapter
