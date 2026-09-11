-- AchieveNotes-owned Enhanced Diagnostics v1 provider.
-- This is the sole AchieveNotes integration point for the shared protocol.
-- Gameplay never depends on Addon Diagnostics being installed or healthy.

local ADDON_NAME = ...
local PROVIDER_ID = "AchieveNotes"
local PROTOCOL_IDENTIFIER = "Enhanced Diagnostics"
local PROTOCOL_VERSION = 1
local PROVIDER_SCHEMA = 1
local STARTUP_CAPTURE_SECONDS = 5.0
local PERFORMANCE_ARM_KEY = "performanceArm"
local PERFORMANCE_ARM_MAX_AGE_SECONDS = 24 * 60 * 60
local MAX_PERFORMANCE_RECORDS = 24

local HNA = LibStub("AceAddon-3.0"):GetAddon(ADDON_NAME, true)
if not HNA then return end

local Provider = {}
HNA.EnhancedDiagnostics = Provider

local runtimeState = {
    instrumented = false,
    lastMapID = 0,
    lastNodeCount = 0,
    refreshCount = 0,
    lastTooltipShown = false,
    lastTooltipLines = 0,
}

local performance = {
    active = false,
    mode = nil,
    domainID = nil,
    startupPhase = false,
    records = {},
    order = {},
}

local function nowMs()
    if type(debugprofilestop) == "function" then
        local ok, value = pcall(debugprofilestop)
        if ok and type(value) == "number" and value == value then return value end
    end
    if type(GetTime) == "function" then
        local ok, value = pcall(GetTime)
        if ok and type(value) == "number" and value == value then return value * 1000 end
    end
    return 0
end

local function safeNumber(value)
    value = tonumber(value) or 0
    if value ~= value or value == math.huge or value == -math.huge or value < 0 then return 0 end
    return value
end

local function cleanText(value, fallback, maximum)
    if type(value) ~= "string" or value == "" then value = fallback end
    if type(value) ~= "string" then return nil end
    value = value:gsub("[\r\n|]", " ")
    maximum = tonumber(maximum) or 80
    if #value > maximum then value = value:sub(1, maximum) end
    return value
end

local function performanceDB(create)
    if type(AchieveNotesDiagnosticsDB) ~= "table" and create then AchieveNotesDiagnosticsDB = {} end
    return type(AchieveNotesDiagnosticsDB) == "table" and AchieveNotesDiagnosticsDB or nil
end

local function clearPerformanceArm()
    local db = performanceDB(false)
    if db then db[PERFORMANCE_ARM_KEY] = nil end
end

local function savePerformanceArm(mode, domainID)
    local db = performanceDB(true)
    if not db then return end
    db[PERFORMANCE_ARM_KEY] = {
        armed = true,
        mode = mode,
        domainID = domainID,
        armedAt = type(time) == "function" and time() or 0,
    }
end

local function restorePerformanceArm()
    local db = performanceDB(false)
    local arm = db and db[PERFORMANCE_ARM_KEY] or nil
    if type(arm) ~= "table" or arm.armed ~= true then return end
    if arm.mode ~= "whole_addon" and arm.mode ~= "specific_feature" then
        clearPerformanceArm()
        return
    end
    if arm.mode == "specific_feature" and (type(arm.domainID) ~= "string" or arm.domainID == "") then
        clearPerformanceArm()
        return
    end
    local now = type(time) == "function" and time() or 0
    local armedAt = tonumber(arm.armedAt) or 0
    if now > 0 and armedAt > 0 and now - armedAt > PERFORMANCE_ARM_MAX_AGE_SECONDS then
        clearPerformanceArm()
        return
    end
    performance.active = true
    performance.mode = arm.mode
    performance.domainID = arm.domainID
    performance.startupPhase = true
end

local function resetRecords()
    performance.records = {}
    performance.order = {}
end

local function selected(domainID)
    if not performance.active then return false end
    if performance.mode ~= "specific_feature" then return true end
    return performance.domainID == domainID
end

local function resolveDomain(domainID)
    if performance.startupPhase then return "startup_login", "startup" end
    return domainID, "runtime"
end

local function getRecord(domainID, operation, trigger, phase)
    local key = table.concat({ domainID, operation, trigger, phase }, "\031")
    local record = performance.records[key]
    if record then return record end
    if #performance.order >= MAX_PERFORMANCE_RECORDS then return nil end
    record = {
        domainID = domainID,
        operation = operation,
        trigger = trigger,
        phase = phase,
        invocationCount = 0,
        cumulativeDurationMs = 0,
        worstInvocationMs = 0,
        actualWorkCount = 0,
        noOpCount = 0,
        suppressedCount = 0,
        workUnitCount = 0,
        tested = false,
    }
    performance.records[key] = record
    performance.order[#performance.order + 1] = key
    return record
end

function Provider:PerformanceStart(domainID, operation, trigger)
    if not performance.active then return nil end
    local resolvedDomain, phase = resolveDomain(domainID)
    if not selected(resolvedDomain) then return nil end
    operation = cleanText(operation, "unspecified", 80)
    trigger = cleanText(trigger, "unspecified", 80)
    if not operation or not trigger then return nil end
    return { domainID = resolvedDomain, operation = operation, trigger = trigger, phase = phase, startedAt = nowMs() }
end

function Provider:PerformanceFinish(token, actualWorkCount, noOpCount, workUnitCount, tested)
    if type(token) ~= "table" or not performance.active then return false end
    local record = getRecord(token.domainID, token.operation, token.trigger, token.phase)
    if not record then return false end
    local elapsed = nowMs() - safeNumber(token.startedAt)
    if elapsed < 0 or elapsed ~= elapsed then elapsed = 0 end
    record.invocationCount = record.invocationCount + 1
    record.cumulativeDurationMs = record.cumulativeDurationMs + elapsed
    if elapsed > record.worstInvocationMs then record.worstInvocationMs = elapsed end
    record.actualWorkCount = record.actualWorkCount + safeNumber(actualWorkCount)
    record.noOpCount = record.noOpCount + safeNumber(noOpCount)
    record.workUnitCount = record.workUnitCount + safeNumber(workUnitCount)
    if tested ~= false then record.tested = true end
    return true
end

local function beginPerformanceCapture(context)
    if type(context) ~= "table" then return false end
    local mode = context.mode
    local domainID = type(context.domainID) == "string" and context.domainID or nil
    if mode ~= "whole_addon" and mode ~= "specific_feature" then return false end
    if mode == "specific_feature" and (not domainID or domainID == "") then return false end
    resetRecords()
    performance.active = true
    performance.mode = mode
    performance.domainID = domainID
    performance.startupPhase = false
    savePerformanceArm(mode, domainID)
    return true
end

local function getPerformanceAggregateSnapshot()
    local snapshot = {}
    for _, key in ipairs(performance.order) do
        local record = performance.records[key]
        if record then
            snapshot[#snapshot + 1] = {
                domainID = record.domainID,
                operation = record.operation,
                trigger = record.trigger,
                phase = record.phase,
                invocationCount = record.invocationCount,
                cumulativeDurationMs = record.cumulativeDurationMs,
                worstInvocationMs = record.worstInvocationMs,
                actualWorkCount = record.actualWorkCount,
                noOpCount = record.noOpCount,
                suppressedCount = record.suppressedCount,
                workUnitCount = record.workUnitCount,
                tested = record.tested == true,
            }
        end
    end
    return snapshot
end

local function endPerformanceCapture()
    clearPerformanceArm()
    performance.active = false
    performance.mode = nil
    performance.domainID = nil
    performance.startupPhase = false
    resetRecords()
    return true
end

local function getPerformanceManifest()
    return {
        {
            domainID = "startup_login",
            label = "Startup / Login",
            phase = "startup",
            requiredForWholeAddon = true,
            available = true,
            actionHint = "Run the AchieveNotes Startup Test, reload or relaunch, and wait for the UI to settle.",
        },
        {
            domainID = "map_refresh",
            label = "Map Refresh",
            phase = "runtime",
            requiredForWholeAddon = true,
            available = true,
            actionHint = "Open the World Map and switch between a zone and continent several times.",
        },
        {
            domainID = "pin_interaction",
            label = "Pin Interaction",
            phase = "runtime",
            requiredForWholeAddon = true,
            available = true,
            actionHint = "Hover and left-click several AchieveNotes achievement-shield pins.",
        },
    }
end

local function breadcrumb(moduleName, action, fields)
    local api = _G.EnhancedDiagnostics
    if type(api) ~= "table" or api.protocolIdentifier ~= PROTOCOL_IDENTIFIER
        or api.protocolVersion ~= PROTOCOL_VERSION or type(api.Breadcrumb) ~= "function" then
        return false
    end
    local ok, accepted = pcall(api.Breadcrumb, PROVIDER_ID, moduleName, action, fields)
    return ok and accepted == true
end

local lastTooltipMissMapID
local function installInstrumentation()
    if runtimeState.instrumented then return end
    runtimeState.instrumented = true

    local originalUpdateVisible = HNA.UpdateVisible
    if type(originalUpdateVisible) == "function" then
        HNA.UpdateVisible = function(self, ...)
            local token = Provider:PerformanceStart("startup_login", "update_visible", "achievement_scan")
            local result = originalUpdateVisible(self, ...)
            Provider:PerformanceFinish(token, 1, 0, 1, true)
            return result
        end
    end

    local originalGetNodes2 = HNA.GetNodes2
    if type(originalGetNodes2) == "function" then
        HNA.GetNodes2 = function(self, mapID, minimap)
            local trigger = minimap and "minimap" or "world_map"
            local token = Provider:PerformanceStart("map_refresh", "prepare_nodes", trigger)
            local iterator, state, value = originalGetNodes2(self, mapID, minimap)
            local capture = token ~= nil
            Provider:PerformanceFinish(token, 1, 0, 0, true)
            runtimeState.lastMapID = tonumber(mapID) or 0
            runtimeState.refreshCount = runtimeState.refreshCount + 1
            if not capture or type(iterator) ~= "function" then return iterator, state, value end

            local yielded = 0
            local function measuredIterator(...)
                local iterToken = Provider:PerformanceStart("map_refresh", "iterate_nodes", trigger)
                local coord, nodeMapID, icon, scale, alpha = iterator(...)
                local didWork = coord ~= nil and 1 or 0
                if didWork == 1 then yielded = yielded + 1 else runtimeState.lastNodeCount = yielded end
                Provider:PerformanceFinish(iterToken, didWork, didWork == 0 and 1 or 0, didWork, true)
                return coord, nodeMapID, icon, scale, alpha
            end
            return measuredIterator, state, value
        end
    end

    local originalOnEnter = HNA.OnEnter
    if type(originalOnEnter) == "function" then
        HNA.OnEnter = function(pin, mapID, coord)
            local token = Provider:PerformanceStart("pin_interaction", "hover_tooltip", "mouse_enter")
            local result = originalOnEnter(pin, mapID, coord)
            local adapter = _G.AchieveNotesTooltipAdapter
            local shown = adapter and type(adapter.IsShown) == "function" and adapter:IsShown() == true or false
            local lineCount = adapter and type(adapter.GetLineCount) == "function" and adapter:GetLineCount() or 0
            runtimeState.lastTooltipShown = shown
            runtimeState.lastTooltipLines = tonumber(lineCount) or 0
            Provider:PerformanceFinish(token, shown and 1 or 0, shown and 0 or 1, 1, true)
            if shown then
                lastTooltipMissMapID = nil
            elseif lastTooltipMissMapID ~= mapID then
                lastTooltipMissMapID = mapID
                breadcrumb("PinInteraction", "TOOLTIP_NOT_SHOWN", { mapID = tonumber(mapID) or 0, lines = runtimeState.lastTooltipLines })
            end
            return result
        end
    end

    local originalOnClick = HNA.OnClick
    if type(originalOnClick) == "function" then
        HNA.OnClick = function(pin, button, down, mapID, coord)
            local token = Provider:PerformanceStart("pin_interaction", "click", button or "unknown")
            local result = originalOnClick(pin, button, down, mapID, coord)
            Provider:PerformanceFinish(token, down and 0 or 1, down and 1 or 0, 1, true)
            return result
        end
    end
end

local function getDiagnosticSnapshot()
    local handyNotes = LibStub("AceAddon-3.0"):GetAddon("HandyNotes", true)
    local profile = HNA.db and HNA.db.profile or nil
    return {
        ["provider.schema"] = PROVIDER_SCHEMA,
        ["plugin.registered"] = handyNotes and handyNotes.plugins and handyNotes.plugins[ADDON_NAME] == HNA or false,
        ["settings.completed"] = profile and profile.completed == true or false,
        ["settings.cleanContinents"] = profile and profile.clean_continents == true or false,
        ["settings.sortTracked"] = profile and profile.sort_by_tracked == true or false,
        ["map.lastID"] = runtimeState.lastMapID,
        ["map.lastNodeCount"] = runtimeState.lastNodeCount,
        ["map.refreshCount"] = runtimeState.refreshCount,
        ["tooltip.lastShown"] = runtimeState.lastTooltipShown,
        ["tooltip.lastLines"] = runtimeState.lastTooltipLines,
        ["performance.active"] = performance.active,
    }
end

local function getAddonVersion()
    local getter = _G.C_AddOns and _G.C_AddOns.GetAddOnMetadata or _G.GetAddOnMetadata
    if type(getter) ~= "function" then return "version unavailable" end
    local ok, value = pcall(getter, ADDON_NAME, "Version")
    return ok and type(value) == "string" and value ~= "" and value or "version unavailable"
end

local provider = {
    providerID = PROVIDER_ID,
    displayName = "AchieveNotes",
    addonVersion = getAddonVersion(),
    protocolVersion = PROTOCOL_VERSION,
    capabilities = {
        breadcrumbs = true,
        snapshots = true,
        performanceAttribution = true,
        startupPerformance = true,
    },
    GetDiagnosticSnapshot = getDiagnosticSnapshot,
    GetPerformanceManifest = getPerformanceManifest,
    BeginPerformanceCapture = beginPerformanceCapture,
    GetPerformanceAggregateSnapshot = getPerformanceAggregateSnapshot,
    EndPerformanceCapture = endPerformanceCapture,
}

local function queueProvider(api)
    if type(api.pendingProviders) ~= "table" then api.pendingProviders = {} end
    for _, pending in ipairs(api.pendingProviders) do
        if type(pending) == "table" and pending.providerID == PROVIDER_ID then return true end
    end
    api.pendingProviders[#api.pendingProviders + 1] = provider
    return true
end

local function registerProvider()
    local api = _G.EnhancedDiagnostics
    if type(api) ~= "table" then
        _G.EnhancedDiagnostics = {}
        api = _G.EnhancedDiagnostics
    end
    if api.protocolIdentifier ~= nil and api.protocolIdentifier ~= PROTOCOL_IDENTIFIER then return false end
    if api.protocolVersion ~= nil and api.protocolVersion ~= PROTOCOL_VERSION then return false end
    if type(api.RegisterProvider) ~= "function" then return queueProvider(api) end
    local ok, registered = pcall(api.RegisterProvider, provider)
    return ok and registered == true
end

installInstrumentation()
registerProvider()

local lifecycle = CreateFrame("Frame")
lifecycle:RegisterEvent("ADDON_LOADED")
lifecycle:RegisterEvent("PLAYER_LOGIN")
lifecycle:RegisterEvent("PLAYER_ENTERING_WORLD")
lifecycle:SetScript("OnEvent", function(self, event, addonName)
    if event == "ADDON_LOADED" then
        if addonName ~= ADDON_NAME then return end
        restorePerformanceArm()
        self:UnregisterEvent("ADDON_LOADED")
        return
    end
    installInstrumentation()
    registerProvider()
    if event == "PLAYER_ENTERING_WORLD" then
        local handyNotes = LibStub("AceAddon-3.0"):GetAddon("HandyNotes", true)
        breadcrumb("Lifecycle", "PLUGIN_READY", { registered = handyNotes and handyNotes.plugins and handyNotes.plugins[ADDON_NAME] == HNA or false })
    elseif event == "PLAYER_LOGIN" and performance.active and performance.startupPhase then
        if C_Timer and type(C_Timer.After) == "function" then
            C_Timer.After(STARTUP_CAPTURE_SECONDS, function() performance.startupPhase = false end)
        else
            performance.startupPhase = false
        end
    end
end)
