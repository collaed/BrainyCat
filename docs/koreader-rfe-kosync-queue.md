# KOReader Feature Request: kosync offline queue with retry

**Filed by:** BrainyCat project (https://github.com/collaed/BrainyCat)
**Target repo:** https://github.com/koreader/koreader
**Related issues:** #9267 (WiFi disconnect), #10678 (sync with WiFi disabled), #11105 (sync after reading)

---

## Problem

When KOReader can't reach the sync server (offline reading, intermittent WiFi on e-readers, server temporarily down), progress updates are silently lost. The next successful sync only sends the *current* position, not the history of positions since the last successful sync.

## Impact

- Users who read offline (commute, airplane, poor WiFi) lose reading statistics granularity
- Server-side features like reading streaks, heatmaps, and time-per-session tracking become inaccurate
- Self-hosted sync servers (BrainyCat, Komga, Kavita) rely on progress history for analytics

## Proposed Solution

1. On sync failure, persist the progress payload to a local queue file
2. On next successful connectivity, batch-send queued items before sending current position
3. Cap queue at ~100 entries to avoid unbounded growth
4. Include timestamp in queued items so server can reconstruct reading timeline

## Demo Implementation (Lua)

This is a **demo/proof-of-concept** showing the approach. Not production-ready.

```lua
-- kosync_queue.lua — Demo offline queue for kosync plugin
-- Drop this alongside kosync.koplugin/main.lua

local DataStorage = require("datastorage")
local json = require("json")
local logger = require("logger")

local QUEUE_FILE = DataStorage:getSettingsDir() .. "/kosync_queue.json"
local MAX_QUEUE_SIZE = 100

local KosyncQueue = {}

function KosyncQueue:load()
    local f = io.open(QUEUE_FILE, "r")
    if not f then return {} end
    local content = f:read("*all")
    f:close()
    local ok, data = pcall(json.decode, content)
    if ok and type(data) == "table" then
        return data
    end
    return {}
end

function KosyncQueue:save(queue)
    local f = io.open(QUEUE_FILE, "w")
    if f then
        f:write(json.encode(queue))
        f:close()
    end
end

function KosyncQueue:push(item)
    local queue = self:load()
    -- Add timestamp
    item.queued_at = os.time()
    table.insert(queue, item)
    -- Cap size
    while #queue > MAX_QUEUE_SIZE do
        table.remove(queue, 1)
    end
    self:save(queue)
    logger.dbg("KosyncQueue: queued item, total:", #queue)
end

function KosyncQueue:drain(sync_func)
    -- Send all queued items, remove successful ones
    local queue = self:load()
    if #queue == 0 then return 0 end

    logger.info("KosyncQueue: draining", #queue, "queued items")
    local sent = 0
    local remaining = {}

    for _, item in ipairs(queue) do
        local ok = sync_func(item)
        if ok then
            sent = sent + 1
        else
            -- Still can't reach server, keep in queue
            table.insert(remaining, item)
            break -- Stop trying if server is still down
        end
    end

    -- Keep unsent items
    for i = sent + #remaining + 1, #queue do
        table.insert(remaining, queue[i])
    end

    self:save(remaining)
    logger.info("KosyncQueue: sent", sent, "remaining", #remaining)
    return sent
end

function KosyncQueue:count()
    return #self:load()
end

return KosyncQueue
```

## Integration Point (in kosync.koplugin/main.lua)

```lua
-- Demo: where to hook into existing kosync code
-- In the updateProgress function, after HTTP call fails:

local KosyncQueue = require("kosync_queue")

-- Original code (simplified):
function KOSync:updateProgress(document, progress, percentage)
    local ok, err = self:httpPUT("/syncs/progress", {
        document = document,
        progress = progress,
        percentage = percentage,
        device = self.device_name,
        device_id = self.device_id,
    })

    if not ok then
        -- NEW: Queue for retry instead of silently dropping
        KosyncQueue:push({
            document = document,
            progress = progress,
            percentage = percentage,
            device = self.device_name,
            device_id = self.device_id,
        })
    end
end

-- On successful sync, drain queue first:
function KOSync:onSync()
    -- Drain any queued items first
    KosyncQueue:drain(function(item)
        local ok = self:httpPUT("/syncs/progress", item)
        return ok
    end)
    -- Then do normal sync
    self:getProgress()
end
```

## Server-Side Support

BrainyCat's kosync endpoint already handles this correctly:
- Accepts progress updates at any time (no ordering requirement)
- `ON CONFLICT DO UPDATE` means repeated updates for same document just overwrite
- If we add a `synced_at` timestamp field, we can reconstruct the reading timeline from queued items

## Backward Compatibility

- Queue file is optional — if it doesn't exist, behavior is unchanged
- Server doesn't need changes (standard kosync PUT)
- No protocol changes needed
- Graceful degradation: if queue code fails, falls back to current behavior (silent drop)

---

*This RFE was generated by the BrainyCat project. We maintain a kosync-compatible server and would benefit from reliable offline sync. Happy to contribute a PR if the approach is accepted.*
