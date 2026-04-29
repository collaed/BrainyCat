# KOReader Feature Request: KOSync Offline Queue with Retry

**Target repo:** https://github.com/koreader/koreader
**Related issues:** #9267 (WiFi disconnect), #10678 (sync with WiFi disabled), #11105 (sync after reading)

---

## Problem

When KOReader can't reach the sync server (offline reading, intermittent WiFi on e-readers, server temporarily down), progress updates are silently lost. The next successful sync only sends the *current* position, not the history of positions since the last successful sync.

In `kosync.koplugin/main.lua`, the `updateProgress` function calls `client.update_progress` with a callback, but when `ok = false` is returned, the progress payload is simply discarded (only an error message is shown if interactive).

## Impact

- Users who read offline (commute, airplane, poor WiFi) lose reading statistics granularity
- Server-side features like reading streaks, heatmaps, and time-per-session tracking become inaccurate
- Self-hosted kosync-compatible servers rely on progress history for analytics

## Proposed Solution

1. On sync failure due to connectivity (pcall failure or timeout), persist the progress payload to a local queue
2. On next successful connectivity (`_onNetworkConnected`), drain queued items before pulling current position
3. Cap queue at configurable size (default 50) to avoid unbounded growth on devices with limited storage
4. Deduplicate: only keep the latest entry per document digest
5. Include timestamp in queued items so server can reconstruct reading timeline

## Analysis of Current Code

Two distinct failure modes exist:

1. **`pcall` fails** (line ~706) — HTTP call couldn't be initiated (no network interface, DNS failure, socket error). **Always queue.**
2. **Callback receives `ok = false`** (line ~719) — HTTP call was made but server returned non-200. Queue only on connectivity issues (5xx/timeout), **not** on auth failures (401/403).

Integration points:
- **`updateProgress`:** Queue on failure
- **`_onNetworkConnected`:** Drain queue before pull
- **`_onCloseDocument`:** If `goOnlineToRun` can't connect, queue instead of blocking forever
- **Debouncing:** Queue drain respects `API_CALL_DEBOUNCE_DELAY`

## Implementation

### `plugins/kosync.koplugin/KOSyncQueue.lua`

Uses the project's `Persist` module with `dump` codec (human-readable, debuggable, consistent with other settings files).

```lua
local DataStorage = require("datastorage")
local Persist = require("persist")
local logger = require("logger")

local QUEUE_PATH = DataStorage:getSettingsDir() .. "/kosync_queue.lua"
local MAX_QUEUE_SIZE = 50

local KOSyncQueue = {}

function KOSyncQueue:_storage()
    if not self._persist then
        self._persist = Persist:new{ path = QUEUE_PATH, codec = "dump" }
    end
    return self._persist
end

function KOSyncQueue:load()
    local storage = self:_storage()
    if not storage:exists() then return {} end
    local data, err = storage:load()
    if not data then
        logger.warn("KOSyncQueue: failed to load queue:", err)
        return {}
    end
    return data
end

function KOSyncQueue:save(queue)
    local storage = self:_storage()
    local ok, err = storage:save(queue)
    if not ok then
        logger.warn("KOSyncQueue: failed to save queue:", err)
    end
end

--- Queue a failed progress update for later retry.
-- Deduplicates by document: only the latest progress per document is kept.
function KOSyncQueue:push(item)
    local queue = self:load()
    item.queued_at = os.time()

    -- Deduplicate: remove any existing entry for the same document
    for i = #queue, 1, -1 do
        if queue[i].document == item.document then
            table.remove(queue, i)
        end
    end

    table.insert(queue, item)

    -- Cap size (oldest first)
    while #queue > MAX_QUEUE_SIZE do
        table.remove(queue, 1)
    end

    self:save(queue)
    logger.dbg("KOSyncQueue: queued progress for", item.document, "total:", #queue)
end

--- Attempt to send all queued items.
-- @param send_func function(item) -> bool: attempts to send one item, returns true on success
-- @return number of successfully sent items
function KOSyncQueue:drain(send_func)
    local queue = self:load()
    if #queue == 0 then return 0 end

    logger.info("KOSyncQueue: draining", #queue, "queued items")
    local remaining = {}
    local sent = 0

    for _, item in ipairs(queue) do
        if send_func(item) then
            sent = sent + 1
        else
            -- Server still unreachable, keep this and all subsequent items
            table.insert(remaining, item)
            -- Copy remaining items without retrying
            for j = _ + 1, #queue do
                table.insert(remaining, queue[j])
            end
            break
        end
    end

    self:save(remaining)
    logger.info("KOSyncQueue: sent", sent, ", remaining", #remaining)
    return sent
end

function KOSyncQueue:count()
    local queue = self:load()
    return #queue
end

function KOSyncQueue:clear()
    self:save({})
end

return KOSyncQueue
```

### Changes to `plugins/kosync.koplugin/main.lua`

#### 1. In `updateProgress` — queue on pcall failure:

```lua
-- Replace the existing failure block (around line 730):
    if not ok then
        if interactive then showSyncError() end
        if err then logger.dbg("err:", err) end
        -- Network unreachable: queue for retry
        local KOSyncQueue = require("KOSyncQueue")
        KOSyncQueue:push({
            document = doc_digest,
            metadata = metadata,
            progress = progress,
            percentage = percentage,
            device = chosen_device_name,
            device_id = self.device_id,
        })
    else
```

#### 2. In the `update_progress` callback — queue on non-auth server errors:

```lua
        function(ok, body)
            logger.dbg("KOSync: [Push] progress to", percentage * 100, "% =>", progress, "for", self.view.document.file)
            logger.dbg("KOSync: ok:", ok, "body:", body)
            if ok then
                if interactive then
                    UIManager:show(InfoMessage:new{
                        text = _("Progress has been pushed."),
                        timeout = 3,
                    })
                end
            else
                -- Don't queue auth failures (they won't resolve by retrying)
                local is_auth_failure = body and type(body) == "table" and body.status == 401
                if not is_auth_failure then
                    local KOSyncQueue = require("KOSyncQueue")
                    KOSyncQueue:push({
                        document = doc_digest,
                        metadata = metadata,
                        progress = progress,
                        percentage = percentage,
                        device = chosen_device_name,
                        device_id = self.device_id,
                    })
                end
                if interactive then showSyncError() end
            end
        end)
```

#### 3. In `_onNetworkConnected` — drain queue:

```lua
function KOSync:_onNetworkConnected()
    logger.dbg("KOSync: onNetworkConnected")
    UIManager:scheduleIn(0.5, function()
        -- Drain any queued progress updates first
        self:drainQueue()
        -- Then pull as normal
        self:getProgress(false, false)
    end)
end

function KOSync:drainQueue()
    local KOSyncQueue = require("KOSyncQueue")
    if KOSyncQueue:count() == 0 then return end

    local KOSyncClient = require("KOSyncClient")
    local client = KOSyncClient:new{
        custom_url = self.settings.custom_server,
        service_spec = self.path .. "/api.json"
    }

    KOSyncQueue:drain(function(item)
        -- Use a synchronous pcall here since we're already online
        -- and this runs in a scheduled callback
        local ok, err = pcall(client.update_progress,
            client,
            self.settings.username,
            self.settings.userkey,
            item.document,
            item.metadata,
            item.progress,
            item.percentage,
            item.device,
            item.device_id,
            function(ok, body)
                -- We only care about the outer pcall success for queue drain
            end)
        return ok
    end)
end
```

#### 4. In `_onCloseDocument` — fallback to queue if offline:

```lua
function KOSync:_onCloseDocument()
    logger.dbg("KOSync: onCloseDocument")
    self.onResume = nil
    self.onSuspend = nil

    -- If we're already online, push normally
    if NetworkMgr:isOnline() then
        self:updateProgress(false, false)
    else
        -- Can't connect: queue current progress for later
        local doc_digest = self:getDocumentDigest()
        local metadata = self:getMetadata()
        local progress = self:getLastProgress()
        local percentage = self:getLastPercent()
        local chosen_device_name = self.settings.kosync_hostname or Device.model
        local KOSyncQueue = require("KOSyncQueue")
        KOSyncQueue:push({
            document = doc_digest,
            metadata = metadata,
            progress = progress,
            percentage = percentage,
            device = chosen_device_name,
            device_id = self.device_id,
        })
    end
end
```

## Backward Compatibility

- Queue file is optional — if it doesn't exist, behavior is unchanged
- Server doesn't need changes (standard kosync PUT endpoint)
- No protocol changes needed
- Graceful degradation: if queue code fails, falls back to current behavior (silent drop)
- The `queued_at` timestamp is extra metadata the server can ignore
- Uses existing `Persist` infrastructure, no new dependencies

## Open Questions for PR Discussion

1. Should there be a UI indicator showing queued items count? (e.g., in the KOSync menu)
2. Should the drain use the async coroutine pattern (matching existing `update_progress`) or synchronous pcall (simpler, since we know we're online)?
3. Should `_onCloseDocument` still attempt `goOnlineToRun` with a short timeout before falling back to queue?
4. Should the queue file be cleaned up on logout?
