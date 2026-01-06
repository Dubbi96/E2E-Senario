// Content script: record actions + support element picker for assertions.

const STATE_KEY = 'dubbi_recorder_state_v1'

const DEFAULT_STATE = {
  recording: false,
  playing: false,
  playIndex: 0,
  uiOpen: false,
  events: [],
  config: { apiBaseUrl: 'http://localhost:8000', token: '', scenarioName: 'recorded_scenario', assertType: 'assert_text' },
}

function cssEscapeIdent(s) {
  // minimal escape for attribute value (not full CSS.escape)
  return String(s).replace(/"/g, '\\"')
}

function cssEsc(s) {
  try {
    if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') return CSS.escape(String(s))
  } catch {}
  return cssEscapeIdent(s)
}

function nowId() {
  return `${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function normalizeState(st) {
  const s = st || {}
  return {
    recording: Boolean(s.recording),
    playing: Boolean(s.playing),
    playIndex: Number.isFinite(s.playIndex) ? s.playIndex : 0,
    uiOpen: Boolean(s.uiOpen),
    events: Array.isArray(s.events) ? s.events : [],
    config: { ...DEFAULT_STATE.config, ...(s.config || {}) },
  }
}

function withMeta(ev, delayMs) {
  const e = { ...ev }
  if (!e.id) e.id = nowId()
  if (!e.ts) e.ts = Date.now()
  if (e.delay == null) e.delay = Number.isFinite(delayMs) ? delayMs : 1500
  if (!e.frame) {
    e.frame = {
      href: String(window.location.href || ''),
      name: String(window.name || ''),
      isTop: window === window.top,
    }
  }
  return e
}

function flattenEvents(events) {
  const out = []
  const visit = (ev) => {
    if (!ev) return
    const t = String(ev.type || '')
    if (t === 'group' && Array.isArray(ev.events)) {
      ev.events.forEach(visit)
    } else {
      out.push(ev)
    }
  }
  ;(events || []).forEach(visit)
  return out
}

function selectorFrom(el) {
  if (!el || el.nodeType !== 1) return null

  // Prefer data-testid if present
  const tid = el.getAttribute('data-testid')
  if (tid) return `[data-testid="${cssEsc(tid)}"]`

  // id (unique-ish)
  if (el.id) {
    const sid = `#${cssEsc(el.id)}`
    try {
      if (document.querySelectorAll(sid).length === 1) return sid
    } catch {}
  }

  // role+name (best-effort)
  const role = el.getAttribute('role')
  const aria = el.getAttribute('aria-label')
  if (role && aria) return `[role="${cssEsc(role)}"][aria-label="${cssEsc(aria)}"]`

  // name (common for inputs)
  const name = el.getAttribute('name')
  if (name) return `${el.tagName.toLowerCase()}[name="${cssEsc(name)}"]`

  // aria-label alone
  if (aria) return `${el.tagName.toLowerCase()}[aria-label="${cssEsc(aria)}"]`

  // tag + nth-of-type path (fallback)
  const parts = []
  let cur = el
  for (let i = 0; i < 6 && cur && cur.nodeType === 1; i++) {
    const tag = cur.tagName.toLowerCase()
    const parent = cur.parentElement
    if (!parent) {
      parts.unshift(tag)
      break
    }
    // Try tag + stable classes first
    const cls = String(cur.getAttribute('class') || '')
      .split(/\s+/)
      .map((c) => c.trim())
      .filter(Boolean)
      .filter((c) => c.length >= 2 && c.length <= 40)
      .filter((c) => !/\d{4,}/.test(c)) // avoid long numeric hashes
      .slice(0, 2)
    if (cls.length) {
      const cand = `${tag}.${cls.map(cssEsc).join('.')}`
      const partial = [...parts]
      partial.unshift(cand)
      const sel = partial.join(' > ')
      try {
        if (document.querySelectorAll(sel).length === 1) return sel
      } catch {}
    }

    const siblings = Array.from(parent.children).filter((c) => c.tagName === cur.tagName)
    const idx = siblings.indexOf(cur) + 1
    parts.unshift(`${tag}:nth-of-type(${idx})`)
    cur = parent
  }
  return parts.join(' > ')
}

async function appendEventToStorage(event) {
  try {
    const r = await chrome.storage.local.get([STATE_KEY])
    const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
    if (!st.recording) return
    const next = { ...st, events: [...(st.events || []), event] }
    await chrome.storage.local.set({ [STATE_KEY]: next })
  } catch {
    // ignore
  }
}

async function addEvent(event) {
  // primary: persist directly to storage (survives popup close, even if service worker sleeps)
  await appendEventToStorage(event)
  // best-effort: also notify background (if alive)
  try {
    await chrome.runtime.sendMessage({ type: 'ADD_EVENT', event })
  } catch {
    // ignore
  }
}

// Record programmatic popups (window.open). Fire-and-forget (must not block window.open).
try {
  if (!window.__DUBBI_OPEN_PATCHED__) {
    window.__DUBBI_OPEN_PATCHED__ = true
    const __origOpen = window.open
    if (typeof __origOpen === 'function') {
      window.open = function (url, name, features) {
        try {
          if (window.__DUBBI_RECORDER_ON__) {
            const u = String(url || '').trim()
            if (u) appendEventToStorage(withMeta({ kind: 'action', type: 'popup_open', url: u }, 0))
          }
        } catch {}
        return __origOpen.apply(this, arguments)
      }
    }
  }
} catch {}

async function updateEventAt(index, patch) {
  const r = await chrome.storage.local.get([STATE_KEY])
  const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
  const evs = [...(st.events || [])]
  if (index < 0 || index >= evs.length) return
  evs[index] = { ...evs[index], ...patch }
  await chrome.storage.local.set({ [STATE_KEY]: { ...st, events: evs } })
}

async function deleteEventAt(index) {
  const r = await chrome.storage.local.get([STATE_KEY])
  const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
  const evs = [...(st.events || [])]
  if (index < 0 || index >= evs.length) return
  evs.splice(index, 1)
  await chrome.storage.local.set({ [STATE_KEY]: { ...st, events: evs } })
}

function ensureRecBadge(on, isRecording) {
  // UI badge is top-frame only
  if (window !== window.top) return
  const id = '__dubbi_rec_badge'
  const existing = document.getElementById(id)
  if (!on) {
    if (existing) existing.remove()
    return
  }
  let badge = existing
  if (!badge) badge = document.createElement('div')
  badge.id = id
  badge.style.position = 'fixed'
  badge.style.top = '10px'
  badge.style.right = '10px'
  badge.style.zIndex = '2147483647'
  badge.style.background = isRecording ? 'rgba(185, 28, 28, 0.72)' : 'rgba(0,0,0,0.65)'
  badge.style.color = 'white'
  badge.style.border = '1px solid rgba(255,255,255,0.15)'
  badge.style.borderRadius = '999px'
  badge.style.padding = '6px 10px'
  badge.style.fontFamily = 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif'
  badge.style.fontWeight = '800'
  badge.style.fontSize = '12px'
  badge.textContent = isRecording ? '● REC' : 'Dubbi'
  badge.style.cursor = 'pointer'
  badge.style.pointerEvents = 'auto'
  badge.style.userSelect = 'none'
  if (!existing) document.documentElement.appendChild(badge)
}

let panelOpen = false

let panelMsgEl = null
let panelCountEl = null
let panelStatusEl = null
let panelApiEl = null
let panelEventsListEl = null
let panelAssertTypeEl = null
let editingEventIndex = null
let selectedEventIdx = new Set()

let uiHost = null
let uiShadow = null

function isUiEventTarget(e) {
  try {
    const path = typeof e?.composedPath === 'function' ? e.composedPath() : []
    if (uiHost && path.includes(uiHost)) return true
    const t = e?.target
    if (t && (t.id === '__dubbi_rec_badge' || t.id === '__dubbi_pick_box')) return true
  } catch {}
  return false
}

// Optional: dock panel to the right side without covering the page (AuTomato-style)
const PANEL_DOCK_WIDTH = 320
let origDocWidth = ''
let origDocPos = ''
let dockApplied = false

function applyDock(on) {
  try {
    // Only apply dock on sufficiently wide viewports to avoid breaking small screens
    const shouldDock = on && window.innerWidth >= PANEL_DOCK_WIDTH + 520
    if (shouldDock && !dockApplied) {
      origDocWidth = document.documentElement.style.width || ''
      origDocPos = document.documentElement.style.position || ''
      document.documentElement.style.width = `calc(100% - ${PANEL_DOCK_WIDTH}px)`
      document.documentElement.style.position = 'relative'
      dockApplied = true
    } else if (!shouldDock && dockApplied) {
      document.documentElement.style.width = origDocWidth
      document.documentElement.style.position = origDocPos
      dockApplied = false
    }
  } catch {
    // ignore
  }
}

function ensurePanel(state) {
  // UI panel is top-frame only
  if (window !== window.top) return
  const hostId = '__dubbi_rec_panel'
  if (!uiHost) {
    uiHost = document.getElementById(hostId)
  }
  if (!uiHost) {
    uiHost = document.createElement('div')
    uiHost.id = hostId
    uiHost.style.position = 'fixed'
    uiHost.style.top = '0'
    uiHost.style.right = '0'
    uiHost.style.zIndex = '2147483647'
    uiHost.style.width = `${PANEL_DOCK_WIDTH}px`
    uiHost.style.height = '100vh'
    uiHost.style.pointerEvents = 'auto'
    uiHost.style.display = 'none'
    document.documentElement.appendChild(uiHost)
    uiShadow = uiHost.attachShadow({ mode: 'open' })

    uiShadow.innerHTML = `
      <style>
        :host { all: initial; }
        .wrap {
          width: ${PANEL_DOCK_WIDTH}px;
          height: 100vh;
          overflow: auto;
          background: rgba(15, 23, 42, 0.96);
          border: 1px solid rgba(255,255,255,0.14);
          border-radius: 12px 0 0 12px;
          box-shadow: 0 10px 30px rgba(0,0,0,0.35);
          color: #E5E7EB;
          font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
          font-size: 12px;
          padding: 10px;
          box-sizing: border-box;
        }
        * { box-sizing: border-box; }
        .top { display:flex; align-items:center; gap:8px; }
        .brand { font-weight: 900; }
        .status { margin-left:auto; color:#98A2B3; font-family: ui-monospace, Menlo, monospace; }
        .muted { color:#98A2B3; }
        .row { margin-top: 8px; display:grid; gap: 8px; }
        .field { display:grid; gap:4px; }
        .label { color:#98A2B3; font-weight: 800; }
        input, select {
          padding: 8px;
          border-radius: 10px;
          border: 1px solid rgba(255,255,255,0.14);
          background: #111827;
          color: #E5E7EB;
          outline: none;
          width: 100%;
        }
        button {
          padding: 6px 10px;
          border-radius: 10px;
          border: 1px solid rgba(255,255,255,0.14);
          background: #111827;
          color: #E5E7EB;
          font-weight: 800;
          cursor: pointer;
          max-width: 100%;
        }
        button.primary {
          border-color: rgba(21,94,239,0.9);
          background: #155EEF;
          color: white;
          font-weight: 900;
        }
        .btnRow { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
        .btnRow .spacer { margin-left:auto; }
        .msg { margin-top: 8px; color:#98A2B3; white-space: pre-wrap; }
        .list {
          margin-top: 10px;
          border-top: 1px solid rgba(255,255,255,0.10);
          padding-top: 10px;
          display: grid;
          gap: 8px;
        }
        .eventList {
          display: grid;
          gap: 6px;
          max-height: 46vh;
          overflow: auto;
          padding-right: 4px;
        }
        .eventItem {
          border: 1px solid rgba(255,255,255,0.10);
          border-radius: 12px;
          padding: 8px;
          background: rgba(17, 24, 39, 0.72);
        }
        .eventTop { display:flex; gap:8px; align-items:center; }
        .eventTitle { font-weight: 900; }
        .eventActions { margin-left:auto; display:flex; gap:6px; align-items:center; }
        .chk { display:flex; align-items:center; gap:6px; }
        .chk input { width: 14px; height: 14px; }
        .miniBtn { padding: 4px 8px; border-radius: 10px; font-size: 11px; }
        .miniBtn.danger { border-color: rgba(244, 63, 94, 0.55); color: #fecdd3; }
        .miniBtn.warn { border-color: rgba(245, 158, 11, 0.55); color: #fde68a; }
        .kv { margin-top: 6px; display:grid; gap: 6px; }
        .kvRow { display:grid; gap: 4px; }
        .smallInput { padding: 6px 8px; border-radius: 10px; font-size: 12px; }
        .split2 { display:grid; grid-template-columns: 1fr 110px; gap: 8px; align-items:end; }
        .mono { font-family: ui-monospace, Menlo, monospace; }
      </style>
      <div class="wrap" data-dubbi-ui="1">
        <div class="top">
          <div class="brand">Dubbi Recorder</div>
          <div id="__dubbi_status" class="status"></div>
        </div>

        <div class="row">
          <div class="muted">Events: <span id="__dubbi_events" class="mono"></span></div>
          <div class="muted">API: <span id="__dubbi_api" class="mono"></span></div>
        </div>

        <div class="row">
          <label class="field">
            <span class="label">Scenario name</span>
            <input id="__dubbi_scn_name" />
          </label>
        </div>

        <div class="row">
          <div class="btnRow">
            <label class="field" style="flex: 1; min-width: 180px;">
              <span class="label">Assertion</span>
              <select id="__dubbi_assert_type">
                <option value="assert_text">expect_text</option>
                <option value="assert_visible">expect_visible</option>
                <option value="assert_url">expect_url</option>
              </select>
            </label>
            <button id="__dubbi_pick">Pick</button>
          </div>
          <div class="muted">Tip: Alt 키를 누른 채 클릭하면 Assertion이 추가됩니다.</div>
        </div>

        <div class="row">
          <div class="btnRow">
            <button id="__dubbi_start">Start</button>
            <button id="__dubbi_stop">Stop</button>
            <button id="__dubbi_clear">Clear</button>
            <button id="__dubbi_upload" class="primary">Upload</button>
            <button id="__dubbi_play">Play</button>
            <button id="__dubbi_pause">Pause</button>
            <button id="__dubbi_stop_play">StopPlay</button>
            <span class="spacer"></span>
            <button id="__dubbi_close">Close</button>
          </div>
        </div>

        <div class="row" style="margin-top: 10px;">
          <div class="label">Auth session (storageState)</div>
          <div class="muted">Hogak 로그인(특히 Apple 2FA) 우회용. 로그인된 Hogak 탭에서 사용하세요.</div>
          <div class="btnRow">
            <button id="__dubbi_auth_export" class="miniBtn">Export(.json)</button>
            <button id="__dubbi_auth_upload" class="miniBtn primary">Export+Upload</button>
          </div>
        </div>

        <div class="list">
          <div class="btnRow">
            <div class="label">Events</div>
            <span class="spacer"></span>
            <button id="__dubbi_group" class="miniBtn">Group</button>
            <button id="__dubbi_ungroup" class="miniBtn warn">Ungroup</button>
            <button id="__dubbi_clear_sel" class="miniBtn">ClearSel</button>
          </div>
          <div id="__dubbi_events_list" class="eventList"></div>
        </div>

        <div id="__dubbi_msg" class="msg"></div>
      </div>
    `

    panelMsgEl = uiShadow.getElementById('__dubbi_msg')
    panelCountEl = uiShadow.getElementById('__dubbi_events')
    panelStatusEl = uiShadow.getElementById('__dubbi_status')
    panelApiEl = uiShadow.getElementById('__dubbi_api')
    panelEventsListEl = uiShadow.getElementById('__dubbi_events_list')
    panelAssertTypeEl = uiShadow.getElementById('__dubbi_assert_type')
    // Persist selected assertion type for Alt-mode (also used in iframes later)
    panelAssertTypeEl?.addEventListener('change', async () => {
      const r = await chrome.storage.local.get([STATE_KEY])
      const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
      const next = { ...st, config: { ...st.config, assertType: String(panelAssertTypeEl.value || 'assert_text') } }
      await chrome.storage.local.set({ [STATE_KEY]: next })
    })

    uiShadow.getElementById('__dubbi_clear_sel')?.addEventListener('click', async () => {
      selectedEventIdx = new Set()
      await refreshOverlayFromStorage()
    })

    uiShadow.getElementById('__dubbi_group')?.addEventListener('click', async () => {
      const indices = Array.from(selectedEventIdx).sort((a, b) => a - b)
      if (indices.length < 2) {
        if (panelMsgEl) panelMsgEl.textContent = 'Group: 2개 이상 선택하세요.'
        return
      }
      const rr = await chrome.storage.local.get([STATE_KEY])
      const st = normalizeState(rr[STATE_KEY] || DEFAULT_STATE)
      const evs = st.events || []
      const pick = new Set(indices)
      const min = indices[0]
      const grouped = indices.map((i) => evs[i]).filter(Boolean)
      const groupEv = withMeta({ kind: 'group', type: 'group', events: grouped }, 0)
      const nextEvents = []
      for (let i = 0; i < evs.length; i++) {
        if (i === min) nextEvents.push(groupEv)
        if (pick.has(i)) continue
        nextEvents.push(evs[i])
      }
      await chrome.storage.local.set({ [STATE_KEY]: { ...st, events: nextEvents } })
      selectedEventIdx = new Set([min])
      editingEventIndex = null
      if (panelMsgEl) panelMsgEl.textContent = `Grouped ${indices.length} events.`
    })

    uiShadow.getElementById('__dubbi_ungroup')?.addEventListener('click', async () => {
      const indices = Array.from(selectedEventIdx).sort((a, b) => a - b)
      if (!indices.length) {
        if (panelMsgEl) panelMsgEl.textContent = 'Ungroup: 선택된 항목이 없습니다.'
        return
      }
      const rr = await chrome.storage.local.get([STATE_KEY])
      const st = normalizeState(rr[STATE_KEY] || DEFAULT_STATE)
      const evs = [...(st.events || [])]
      // process descending to keep indices stable
      for (const i of indices.slice().sort((a, b) => b - a)) {
        const ev = evs[i]
        if (ev && String(ev.type) === 'group' && Array.isArray(ev.events)) {
          evs.splice(i, 1, ...ev.events)
        }
      }
      await chrome.storage.local.set({ [STATE_KEY]: { ...st, events: evs } })
      selectedEventIdx = new Set()
      editingEventIndex = null
      if (panelMsgEl) panelMsgEl.textContent = 'Ungrouped.'
    })

    const scnInput = uiShadow.getElementById('__dubbi_scn_name')
    scnInput?.addEventListener('change', async (e) => {
      const v = e.target?.value || ''
      const r = await chrome.storage.local.get([STATE_KEY])
      const st = r[STATE_KEY] || DEFAULT_STATE
      const next = { ...st, config: { ...st.config, scenarioName: v } }
      await chrome.storage.local.set({ [STATE_KEY]: next })
    })

    uiShadow.getElementById('__dubbi_close')?.addEventListener('click', () => {
      panelOpen = false
      uiHost.style.display = 'none'
      applyDock(false)
      // Persist user intent: closed
      chrome.storage.local.get([STATE_KEY]).then((r) => {
        const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
        chrome.storage.local.set({ [STATE_KEY]: { ...st, uiOpen: false } })
      })
    })

    uiShadow.getElementById('__dubbi_pick')?.addEventListener('click', async () => {
      if (!window.__DUBBI_RECORDER_ON__) {
        if (panelMsgEl) panelMsgEl.textContent = 'Not recording. Start recording first.'
        return
      }
      const at = panelAssertTypeEl?.value || 'assert_text'
      if (panelMsgEl) panelMsgEl.textContent = 'Picker ON: click an element on the page to add assertion step.'
      startPicker(at)
    })

    uiShadow.getElementById('__dubbi_start')?.addEventListener('click', async () => {
      const r = await chrome.storage.local.get([STATE_KEY])
      const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
      // Start recording: clear existing events (same semantics as popup START)
      await chrome.storage.local.set({
        [STATE_KEY]: { ...st, recording: true, playing: false, playIndex: 0, events: [] },
      })
      window.__DUBBI_RECORDER_ON__ = true
      await ensureInitialNavigate()
      await refreshOverlayFromStorage()
      if (panelMsgEl) panelMsgEl.textContent = 'REC ON'
    })

    uiShadow.getElementById('__dubbi_stop')?.addEventListener('click', async () => {
      const r = await chrome.storage.local.get([STATE_KEY])
      const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
      await chrome.storage.local.set({ [STATE_KEY]: { ...st, recording: false } })
      window.__DUBBI_RECORDER_ON__ = false
      await refreshOverlayFromStorage()
      if (panelMsgEl) panelMsgEl.textContent = 'Stopped.'
    })

    uiShadow.getElementById('__dubbi_clear')?.addEventListener('click', async () => {
      const r = await chrome.storage.local.get([STATE_KEY])
      const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
      await chrome.storage.local.set({ [STATE_KEY]: { ...st, events: [] } })
      if (panelMsgEl) panelMsgEl.textContent = 'Cleared.'
    })

    uiShadow.getElementById('__dubbi_play')?.addEventListener('click', async () => {
      await startPlayback(0)
    })
    uiShadow.getElementById('__dubbi_pause')?.addEventListener('click', async () => {
      pausedNow = !pausedNow
      if (panelMsgEl) panelMsgEl.textContent = pausedNow ? 'Paused.' : 'Resumed.'
    })
    uiShadow.getElementById('__dubbi_stop_play')?.addEventListener('click', async () => {
      await stopPlayback('Stopped play.')
    })

    uiShadow.getElementById('__dubbi_upload')?.addEventListener('click', async () => {
      if (!panelMsgEl) return
      const r = await chrome.storage.local.get([STATE_KEY])
      const st = r[STATE_KEY] || DEFAULT_STATE
      try {
        const base = String(st.config?.apiBaseUrl || '').replace(/\/$/, '')
        const token = String(st.config?.token || '')
        if (!base || !token) {
          panelMsgEl.textContent =
            'Missing apiBaseUrl/token. (Dubbi E2E 웹앱에서 Recorder 시작으로 prefill하거나, popup에서 직접 설정하세요.)'
          return
        }

        // keep panel visible for user feedback
        panelOpen = true
        ensurePanel(st)

        // stop recording immediately (user expectation) but keep events for upload/retry
        await chrome.storage.local.set({ [STATE_KEY]: { ...normalizeState(st), recording: false } })
        window.__DUBBI_RECORDER_ON__ = false
        await refreshOverlayFromStorage()
        panelMsgEl.textContent = 'Uploading via extension background...'

        // Prefer background upload (avoids CORS/preflight issues on arbitrary pages)
        try {
          const resp = await new Promise((resolve, reject) => {
            let settled = false
            const timer = setTimeout(() => {
              if (settled) return
              settled = true
              reject(new Error('timeout waiting background response'))
            }, 12_000)
            try {
              chrome.runtime.sendMessage({ type: 'UPLOAD' }, (rmsg) => {
                if (settled) return
                settled = true
                clearTimeout(timer)
                const le = chrome.runtime.lastError
                if (le?.message) {
                  reject(new Error(le.message))
                  return
                }
                resolve(rmsg)
              })
            } catch (e) {
              if (settled) return
              settled = true
              clearTimeout(timer)
              reject(e)
            }
          })
          if (resp?.ok) {
            panelMsgEl.textContent = `Upload OK. scenario_id=${resp.data?.id}`
            return
          }
          panelMsgEl.textContent = `Upload failed (background): ${resp?.error || 'unknown error'}`
          return
        } catch (e) {
          const errMsg = String(e?.message || e)
          panelMsgEl.textContent = `Upload failed (background): ${errMsg}\nTrying direct upload...`
          // Fallback: direct upload (CORS is handled server-side; should work everywhere now)
          try {
            const ctrl = new AbortController()
            const t = setTimeout(() => ctrl.abort(), 12_000)
            const res = await fetch(`${base}/recordings/to-scenario`, {
              method: 'POST',
              headers: { 'content-type': 'application/json', Authorization: `Bearer ${token}` },
              signal: ctrl.signal,
              body: JSON.stringify({
                name: st.config?.scenarioName || 'recorded_scenario',
                events: flattenEvents(st.events || []),
              }),
            })
            clearTimeout(t)
            const data = await res.json().catch(() => ({}))
            if (!res.ok) {
              panelMsgEl.textContent = `Upload failed (direct): ${data?.detail || res.statusText}`
              return
            }
            panelMsgEl.textContent = `Upload OK (direct). scenario_id=${data?.id}`
            return
          } catch (e2) {
            const m2 = String(e2?.name === 'AbortError' ? 'timeout uploading to api' : e2?.message || e2)
            panelMsgEl.textContent = `Upload failed (direct): ${m2}`
            return
          }
        }
      } catch (e) {
        panelMsgEl.textContent = `Upload error: ${String(e?.message || e)}`
      }
    })

    async function captureStorageStateViaBg() {
      return await new Promise((resolve, reject) => {
        chrome.runtime.sendMessage({ type: 'CAPTURE_STORAGE_STATE' }, (resp) => {
          const le = chrome.runtime.lastError
          if (le?.message) return reject(new Error(le.message))
          if (!resp?.ok) return reject(new Error(resp?.error || 'capture failed'))
          resolve(resp.storageState)
        })
      })
    }

    async function downloadStorageStateViaBg(filename, storageState) {
      return await new Promise((resolve, reject) => {
        chrome.runtime.sendMessage({ type: 'DOWNLOAD_STORAGE_STATE', filename, storageState }, (resp) => {
          const le = chrome.runtime.lastError
          if (le?.message) return reject(new Error(le.message))
          if (!resp?.ok) return reject(new Error(resp?.error || 'download failed'))
          resolve(true)
        })
      })
    }

    async function uploadAuthStateViaBg({ apiBaseUrl, token, name, provider, storageState }) {
      return await new Promise((resolve, reject) => {
        chrome.runtime.sendMessage(
          { type: 'UPLOAD_AUTH_STATE', apiBaseUrl, token, name, provider, storageState },
          (resp) => {
            const le = chrome.runtime.lastError
            if (le?.message) return reject(new Error(le.message))
            if (!resp?.ok) return reject(new Error(resp?.error || 'upload failed'))
            resolve(resp.data)
          }
        )
      })
    }

    uiShadow.getElementById('__dubbi_auth_export')?.addEventListener('click', async () => {
      if (!panelMsgEl) return
      try {
        const r = await chrome.storage.local.get([STATE_KEY])
        const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
        const name = String(st.config?.authStateName || 'hogak-google').trim() || 'hogak-google'
        panelMsgEl.textContent = 'Capturing storageState...'
        const storageState = await captureStorageStateViaBg()
        await downloadStorageStateViaBg(`${name}.storage_state.json`, storageState)
        panelMsgEl.textContent = `storageState exported: ${name}.storage_state.json`
      } catch (e) {
        panelMsgEl.textContent = `storageState export failed: ${String(e?.message || e)}`
      }
    })

    uiShadow.getElementById('__dubbi_auth_upload')?.addEventListener('click', async () => {
      if (!panelMsgEl) return
      try {
        const r = await chrome.storage.local.get([STATE_KEY])
        const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
        const apiBaseUrl = String(st.config?.apiBaseUrl || '').replace(/\/$/, '')
        const token = String(st.config?.token || '')
        if (!apiBaseUrl || !token) {
          panelMsgEl.textContent = 'Missing apiBaseUrl/token. Dubbi FE 로그인 후 토큰을 설정하세요.'
          return
        }
        const name = String(st.config?.authStateName || 'hogak-google').trim() || 'hogak-google'
        const provider = String(st.config?.authProvider || 'google')
        panelMsgEl.textContent = 'Capturing storageState...'
        const storageState = await captureStorageStateViaBg()
        panelMsgEl.textContent = 'Uploading storageState...'
        const data = await uploadAuthStateViaBg({ apiBaseUrl, token, name, provider, storageState })
        panelMsgEl.textContent = `storageState upload OK. auth_state_id=${data?.id || '(unknown)'}`
      } catch (e) {
        panelMsgEl.textContent = `storageState upload failed: ${String(e?.message || e)}`
      }
    })
  }

  uiHost.style.display = panelOpen ? 'block' : 'none'
  applyDock(panelOpen)

  const safe = (s) => String(s || '')
  const eventsCount = (state.events || []).length
  if (panelCountEl) panelCountEl.textContent = String(eventsCount)
  if (panelStatusEl) {
    if (state.playing) {
      panelStatusEl.textContent = `PLAY ${Math.max(0, Number(state.playIndex || 0)) + 1}/${(state.events || []).length || 0}`
    } else {
      panelStatusEl.textContent = state.recording ? 'REC ON' : 'REC OFF'
    }
  }
  if (panelApiEl) panelApiEl.textContent = safe(state.config?.apiBaseUrl)
  const scnInput = uiShadow?.getElementById('__dubbi_scn_name')
  if (scnInput && scnInput.value !== safe(state.config?.scenarioName)) {
    scnInput.value = safe(state.config?.scenarioName)
  }

  // Event list render (edit/delete; playback comes next)
  if (panelEventsListEl) {
    const total = (state.events || []).length
    const rows = (state.events || []).slice(-120)
    const startIndex = Math.max(0, total - rows.length)
    panelEventsListEl.innerHTML = ''
    rows.forEach((ev, localIdx) => {
      const idx = startIndex + localIdx
      const item = document.createElement('div')
      item.className = 'eventItem'

      const type = String(ev?.type || ev?.kind || 'event')
      const main =
        type === 'group'
          ? `GROUP (${Array.isArray(ev?.events) ? ev.events.length : 0} events)`
          : ev?.selector || ev?.url || ev?.text || ev?.value || ''
      const delay = Number.isFinite(ev?.delay) ? Number(ev.delay) : 0

      const top = document.createElement('div')
      top.className = 'eventTop'
      top.innerHTML = `<div class="eventTitle">${idx + 1}. ${type}</div>`

      const chkWrap = document.createElement('label')
      chkWrap.className = 'chk'
      const chk = document.createElement('input')
      chk.type = 'checkbox'
      chk.checked = selectedEventIdx.has(idx)
      chk.addEventListener('click', (ev2) => {
        ev2.stopPropagation()
      })
      chk.addEventListener('change', async () => {
        if (chk.checked) selectedEventIdx.add(idx)
        else selectedEventIdx.delete(idx)
        await refreshOverlayFromStorage()
      })
      const chkTxt = document.createElement('span')
      chkTxt.className = 'muted'
      chkTxt.textContent = 'sel'
      chkWrap.appendChild(chk)
      chkWrap.appendChild(chkTxt)
      top.insertBefore(chkWrap, top.firstChild)

      const actions = document.createElement('div')
      actions.className = 'eventActions'

      const playBtn = document.createElement('button')
      playBtn.className = 'miniBtn'
      playBtn.textContent = '▶'
      playBtn.title = '여기부터 재생'
      playBtn.addEventListener('click', async (ev2) => {
        ev2.preventDefault()
        ev2.stopPropagation()
        await startPlayback(idx)
      })

      const editBtn = document.createElement('button')
      editBtn.className = 'miniBtn'
      editBtn.textContent = editingEventIndex === idx ? 'Close' : 'Edit'
      editBtn.addEventListener('click', async () => {
        editingEventIndex = editingEventIndex === idx ? null : idx
        await refreshOverlayFromStorage()
      })

      const delBtn = document.createElement('button')
      delBtn.className = 'miniBtn danger'
      delBtn.textContent = 'Del'
      delBtn.addEventListener('click', async () => {
        if (!confirm(`이 이벤트(#${idx + 1})를 삭제할까요?`)) return
        await deleteEventAt(idx)
        editingEventIndex = null
      })

      actions.appendChild(playBtn)
      actions.appendChild(editBtn)
      actions.appendChild(delBtn)
      top.appendChild(actions)
      item.appendChild(top)

      const body = document.createElement('div')
      body.className = 'muted mono'
      body.style.marginTop = '4px'
      body.style.wordBreak = 'break-all'
      body.textContent = String(main || '-').slice(0, 320)
      item.appendChild(body)

      const metaLine = document.createElement('div')
      metaLine.className = 'muted mono'
      metaLine.style.marginTop = '4px'
      metaLine.textContent = `delay=${delay}ms`
      item.appendChild(metaLine)

      if (editingEventIndex === idx) {
        const kv = document.createElement('div')
        kv.className = 'kv'

        const row1 = document.createElement('div')
        row1.className = 'split2'

        const mainWrap = document.createElement('label')
        mainWrap.className = 'kvRow'
        mainWrap.innerHTML = `<div class="label">selector/url/text/value</div>`
        const mainInput = document.createElement('input')
        mainInput.className = 'smallInput mono'
        mainInput.value = String(main || '')
        mainWrap.appendChild(mainInput)

        const delayWrap = document.createElement('label')
        delayWrap.className = 'kvRow'
        delayWrap.innerHTML = `<div class="label">delay(ms)</div>`
        const delayInput = document.createElement('input')
        delayInput.className = 'smallInput mono'
        delayInput.type = 'number'
        delayInput.min = '1500'
        delayInput.step = '1500'
        delayInput.value = String(delay)
        delayWrap.appendChild(delayInput)

        row1.appendChild(mainWrap)
        row1.appendChild(delayWrap)

        const btnRow = document.createElement('div')
        btnRow.className = 'btnRow'
        const saveBtn = document.createElement('button')
        saveBtn.className = 'miniBtn'
        saveBtn.textContent = 'Save'
        saveBtn.addEventListener('click', async () => {
          const nextDelay = Math.max(1500, Number(delayInput.value || 1500))
          const v = String(mainInput.value || '')
          const patch = { delay: nextDelay }
          if (type === 'group') {
            await updateEventAt(idx, patch)
            editingEventIndex = null
            return
          }
          if (String(ev?.selector || '') !== '' || (type === 'click' || type === 'input' || type.includes('assert'))) {
            if (ev?.selector != null) patch.selector = v
            else if (ev?.url != null) patch.url = v
            else if (ev?.text != null) patch.text = v
            else if (ev?.value != null) patch.value = v
            else patch.selector = v
          } else {
            if (ev?.url != null) patch.url = v
            else patch.selector = v
          }
          await updateEventAt(idx, patch)
          editingEventIndex = null
        })
        const cancelBtn = document.createElement('button')
        cancelBtn.className = 'miniBtn'
        cancelBtn.textContent = 'Cancel'
        cancelBtn.addEventListener('click', async () => {
          editingEventIndex = null
          await refreshOverlayFromStorage()
        })
        btnRow.appendChild(saveBtn)
        btnRow.appendChild(cancelBtn)

        kv.appendChild(row1)
        kv.appendChild(btnRow)
        item.appendChild(kv)
      }

      panelEventsListEl.appendChild(item)
    })

    if ((state.events || []).length > 120) {
      const more = document.createElement('div')
      more.className = 'muted'
      more.textContent = `… 최근 120개만 표시 (총 ${(state.events || []).length}개)`
      panelEventsListEl.appendChild(more)
    }
  }
}

async function refreshOverlayFromStorage() {
  const r = await chrome.storage.local.get([STATE_KEY])
  const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
  // Badge/panel state should be driven ONLY by persisted uiOpen + recording/playing.
  panelOpen = Boolean(st.uiOpen)
  ensureRecBadge(Boolean(st.recording || st.uiOpen || st.playing), Boolean(st.recording))
  ensurePanel(st)
}

async function onClick(e) {
  if (pickerMode) return
  if (isUiEventTarget(e)) return
  if (!window.__DUBBI_RECORDER_ON__) return

  // Alt + click => add assertion (AuTomato-style), don't record normal click.
  if (altPressed) {
    e.preventDefault()
    e.stopPropagation()
    let finalType = (panelAssertTypeEl?.value || '').trim()
    if (!finalType) {
      try {
        const r = await chrome.storage.local.get([STATE_KEY])
        const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
        finalType = String(st.config?.assertType || 'assert_text')
      } catch {
        finalType = 'assert_text'
      }
    }
    const el = e.target
    try {
      if (finalType === 'assert_url') {
        addEvent(withMeta({ kind: 'assert', type: 'assert_url', url: window.location.href }, 0))
        if (panelMsgEl) panelMsgEl.textContent = 'ALT: expect_url added.'
        return
      }
      const sel = selectorFrom(el)
      if (!sel) return
      if (finalType === 'assert_visible') {
        addEvent(withMeta({ kind: 'assert', type: 'assert_visible', selector: sel }, 0))
        if (panelMsgEl) panelMsgEl.textContent = 'ALT: expect_visible added.'
        return
      }
      // assert_text default
      const txt = (el?.innerText || el?.textContent || '').trim().slice(0, 200)
      addEvent(withMeta({ kind: 'assert', type: 'assert_text', selector: sel, text: txt || '' }, 0))
      if (panelMsgEl) panelMsgEl.textContent = 'ALT: expect_text added.'
      return
    } catch {}
  }

  const sel = selectorFrom(e.target)
  if (!sel) return
  // If this click is likely to open a new tab/popup (target=_blank), record as click_popup.
  try {
    const a = e.target?.closest?.('a')
    const target = a ? String(a.getAttribute('target') || '').toLowerCase() : ''
    const href = a ? String(a.href || '').trim() : ''
    if (a && target === '_blank' && href) {
      const aSel = selectorFrom(a) || sel
      addEvent(withMeta({ kind: 'action', type: 'click_popup', selector: aSel, url: href }, 1700))
      return
    }
  } catch {}
  addEvent(withMeta({ kind: 'action', type: 'click', selector: sel }, 1700))
}

function onInput(e) {
  if (isUiEventTarget(e)) return
  if (!window.__DUBBI_RECORDER_ON__) return
  const t = e.target
  if (!t) return
  const tag = (t.tagName || '').toLowerCase()
  if (tag !== 'input' && tag !== 'textarea') return
  const sel = selectorFrom(t)
  if (!sel) return
  addEvent(withMeta({ kind: 'action', type: 'input', selector: sel, value: t.value || '' }, 120))
}

function onNavigate() {
  if (!window.__DUBBI_RECORDER_ON__) return
  addEvent(withMeta({ kind: 'action', type: 'navigate', url: window.location.href }, 0))
}

window.addEventListener('click', onClick, true)
window.addEventListener('input', onInput, true)
window.addEventListener('hashchange', onNavigate, true)
window.addEventListener('popstate', onNavigate, true)
window.addEventListener(
  'keydown',
  (e) => {
    if (e.key === 'Alt') {
      altPressed = true
      if (window.__DUBBI_RECORDER_ON__ && panelMsgEl) panelMsgEl.textContent = 'ALT ON: click to add assertion.'
    }
  },
  true
)
window.addEventListener(
  'keyup',
  (e) => {
    if (e.key === 'Alt') {
      altPressed = false
      if (window.__DUBBI_RECORDER_ON__ && panelMsgEl) panelMsgEl.textContent = ''
    }
  },
  true
)

// Picker overlay for assertions
let pickerMode = null // { assertType: string }
let overlay = null
let pickerCancelKey = null
let pickerActivePickHandler = null
let pickerActiveMoveHandler = null

// Playback (AuTomato-like): persist play state in storage so it can resume after navigation.
let playbackTimer = null
let playingNow = false
let pausedNow = false
let lastMarkedEl = null
let altPressed = false

function markEl(el) {
  try {
    unmarkEl()
    if (!el || !el.getBoundingClientRect) return
    lastMarkedEl = el
    el.__dubbi_prev_outline = el.style.outline
    el.__dubbi_prev_outline_offset = el.style.outlineOffset
    el.style.outline = '3px solid #22c55e'
    el.style.outlineOffset = '2px'
  } catch {}
}

function unmarkEl() {
  try {
    if (lastMarkedEl) {
      lastMarkedEl.style.outline = lastMarkedEl.__dubbi_prev_outline || ''
      lastMarkedEl.style.outlineOffset = lastMarkedEl.__dubbi_prev_outline_offset || ''
    }
  } catch {}
  lastMarkedEl = null
}

async function setPlayState(patch) {
  const r = await chrome.storage.local.get([STATE_KEY])
  const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
  const next = { ...st, ...patch }
  await chrome.storage.local.set({ [STATE_KEY]: next })
  return next
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

function resolveEl(selector) {
  if (!selector) return null
  try {
    return document.querySelector(selector)
  } catch {
    return null
  }
}

function findIframeForFrame(evFrame) {
  if (!evFrame) return null
  const wantHref = String(evFrame.href || '')
  const wantName = String(evFrame.name || '')
  const iframes = Array.from(document.querySelectorAll('iframe'))
  // Prefer src match
  if (wantHref) {
    const hit = iframes.find((f) => {
      const src = String(f.getAttribute('src') || '')
      return src === wantHref || (src && wantHref && (wantHref.startsWith(src) || src.startsWith(wantHref)))
    })
    if (hit) return hit
  }
  // Fallback: name match
  if (wantName) {
    const hit2 = iframes.find((f) => String(f.getAttribute('name') || '') === wantName)
    if (hit2) return hit2
  }
  return null
}

function execInIframe(ev, reqId) {
  return new Promise((resolve, reject) => {
    const frame = findIframeForFrame(ev.frame)
    const cw = frame?.contentWindow
    if (!cw) {
      reject(new Error('iframe not found'))
      return
    }
    const timer = setTimeout(() => {
      window.removeEventListener('message', onMsg)
      reject(new Error('iframe exec timeout'))
    }, 6000)
    function onMsg(mev) {
      const d = mev?.data
      if (!d || typeof d !== 'object') return
      if (d.type !== 'DUBBI_IFRAME_EXEC_RESULT') return
      if (d.reqId !== reqId) return
      clearTimeout(timer)
      window.removeEventListener('message', onMsg)
      if (d.ok) resolve(d)
      else reject(new Error(d.error || 'iframe exec failed'))
    }
    window.addEventListener('message', onMsg)
    cw.postMessage({ type: 'DUBBI_IFRAME_EXEC', reqId, event: ev }, '*')
  })
}

function isVisible(el) {
  try {
    if (!el) return false
    const r = el.getBoundingClientRect()
    if (!r || r.width <= 0 || r.height <= 0) return false
    const st = window.getComputedStyle(el)
    if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false
    return true
  } catch {
    return false
  }
}

async function stopPlayback(msg) {
  playingNow = false
  pausedNow = false
  if (playbackTimer) clearTimeout(playbackTimer)
  playbackTimer = null
  unmarkEl()
  await setPlayState({ playing: false, playIndex: 0 })
  await refreshOverlayFromStorage()
  if (panelMsgEl && msg) panelMsgEl.textContent = msg
}

async function playbackStep() {
  const r = await chrome.storage.local.get([STATE_KEY])
  const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
  if (!st.playing) return
  if (pausedNow) {
    playbackTimer = setTimeout(playbackStep, 250)
    return
  }

  const idx = Math.max(0, Number(st.playIndex || 0))
  const evs = flattenEvents(st.events || [])
  if (idx >= evs.length) {
    await stopPlayback('Play finished.')
    return
  }

  const ev = evs[idx] || {}
  const type = String(ev.type || '')
  const delay = Number.isFinite(ev.delay) ? Number(ev.delay) : 0

  try {
    // Status line update happens via storage refresh anyway, but keep message helpful.
    if (panelMsgEl) panelMsgEl.textContent = `PLAY ${idx + 1}/${evs.length}: ${type}`

    // If this event was recorded in an iframe, execute it in that iframe.
    if (window === window.top && ev?.frame && ev.frame.isTop === false) {
      const reqId = nowId()
      await execInIframe(ev, reqId)
      await setPlayState({ playing: true, playIndex: idx + 1, recording: false })
      await refreshOverlayFromStorage()
      playbackTimer = setTimeout(playbackStep, Math.max(0, delay))
      return
    }

    if (type === 'navigate') {
      // Persist next index, then navigate. Next page load will resume.
      await setPlayState({ playing: true, playIndex: idx + 1, recording: false })
      window.__DUBBI_RECORDER_ON__ = false
      await refreshOverlayFromStorage()
      window.location.href = String(ev.url || '')
      return
    }

    if (type === 'click') {
      const el = resolveEl(ev.selector)
      if (!el) throw new Error(`element not found: ${String(ev.selector || '')}`)
      el.scrollIntoView({ block: 'center', inline: 'center' })
      markEl(el)
      el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    } else if (type === 'input') {
      const el = resolveEl(ev.selector)
      if (!el) throw new Error(`element not found: ${String(ev.selector || '')}`)
      el.scrollIntoView({ block: 'center', inline: 'center' })
      markEl(el)
      el.focus?.()
      el.value = String(ev.value || '')
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    } else if (type === 'assert_visible') {
      const el = resolveEl(ev.selector)
      if (!el) throw new Error(`element not found: ${String(ev.selector || '')}`)
      markEl(el)
      if (!isVisible(el)) throw new Error('assert_visible failed (not visible)')
    } else if (type === 'assert_text') {
      const el = resolveEl(ev.selector)
      if (!el) throw new Error(`element not found: ${String(ev.selector || '')}`)
      markEl(el)
      const actual = String(el.innerText || el.textContent || '').trim()
      const expected = String(ev.text || '').trim()
      if (expected && !actual.includes(expected)) {
        throw new Error(`assert_text failed. expected 포함: "${expected}" actual: "${actual.slice(0, 120)}"`)
      }
    } else if (type === 'assert_url') {
      const expected = String(ev.url || '').trim()
      const actual = String(window.location.href || '')
      if (expected && actual !== expected && !actual.startsWith(expected)) {
        throw new Error(`assert_url failed. expected: "${expected}" actual: "${actual}"`)
      }
    }

    // Move to next
    await setPlayState({ playing: true, playIndex: idx + 1, recording: false })
    window.__DUBBI_RECORDER_ON__ = false
    await refreshOverlayFromStorage()

    playbackTimer = setTimeout(playbackStep, Math.max(0, delay))
  } catch (e) {
    await stopPlayback(`Play failed at #${idx + 1} (${type}): ${String(e?.message || e)}`)
  }
}

async function startPlayback(fromIndex) {
  const r = await chrome.storage.local.get([STATE_KEY])
  const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
  const flat = flattenEvents(st.events || [])
  if (!flat.length) {
    if (panelMsgEl) panelMsgEl.textContent = 'No events to play.'
    return
  }
  playingNow = true
  pausedNow = false
  await setPlayState({ playing: true, playIndex: Math.max(0, Number(fromIndex || 0)), recording: false })
  window.__DUBBI_RECORDER_ON__ = false
  await refreshOverlayFromStorage()
  if (playbackTimer) clearTimeout(playbackTimer)
  playbackTimer = setTimeout(playbackStep, 50)
}

function ensureOverlay() {
  if (overlay) return overlay
  overlay = document.createElement('div')
  overlay.style.position = 'fixed'
  overlay.style.inset = '0'
  overlay.style.zIndex = '2147483647'
  overlay.style.pointerEvents = 'none'

  const box = document.createElement('div')
  box.id = '__dubbi_pick_box'
  box.style.position = 'absolute'
  box.style.border = '2px solid #155EEF'
  box.style.background = 'rgba(21,94,239,0.08)'
  box.style.borderRadius = '6px'
  overlay.appendChild(box)

  document.documentElement.appendChild(overlay)
  return overlay
}

function clearOverlay() {
  if (overlay) overlay.remove()
  overlay = null
}

function setBoxFor(el) {
  const ov = ensureOverlay()
  const box = ov.querySelector('#__dubbi_pick_box')
  if (!box || !el || !el.getBoundingClientRect) return
  const r = el.getBoundingClientRect()
  box.style.left = `${Math.max(0, r.left)}px`
  box.style.top = `${Math.max(0, r.top)}px`
  box.style.width = `${Math.max(0, r.width)}px`
  box.style.height = `${Math.max(0, r.height)}px`
}

function startPicker(assertType) {
  pickerMode = { assertType }
  ensureOverlay()

  const onMove = (e) => {
    const el = e.target
    setBoxFor(el)
  }

  const cleanup = (msg) => {
    try {
      if (pickerActiveMoveHandler) document.removeEventListener('mousemove', pickerActiveMoveHandler, true)
      if (pickerActivePickHandler) document.removeEventListener('click', pickerActivePickHandler, true)
      if (pickerCancelKey) window.removeEventListener('keydown', pickerCancelKey, true)
    } catch {}
    pickerActiveMoveHandler = null
    pickerActivePickHandler = null
    pickerCancelKey = null
    pickerMode = null
    clearOverlay()
    if (panelMsgEl && msg) panelMsgEl.textContent = msg
  }

  const onPick = async (e) => {
    e.preventDefault()
    e.stopPropagation()
    const el = e.target
    // ignore clicks on our own UI while picking
    if (el && (el.closest?.('#__dubbi_rec_badge') || el.closest?.('#__dubbi_rec_panel'))) {
      return
    }
    try {
      const sel = selectorFrom(el)
      const at = pickerMode?.assertType
      if (at === 'assert_text') {
        const txt = (el?.innerText || el?.textContent || '').trim().slice(0, 200)
        await addEvent(withMeta({ kind: 'assert', type: 'assert_text', selector: sel, text: txt || '' }, 0))
      } else if (at === 'assert_visible') {
        await addEvent(withMeta({ kind: 'assert', type: 'assert_visible', selector: sel }, 0))
      } else if (at === 'assert_url') {
        await addEvent(withMeta({ kind: 'assert', type: 'assert_url', url: window.location.href }, 0))
      }
      cleanup('Picker OFF: assertion step added.')
    } catch (err) {
      cleanup(`Picker error: ${String(err?.message || err)}`)
    }
  }

  const onKey = (e) => {
    if (e.key === 'Escape') cleanup('Picker cancelled.')
  }

  pickerActiveMoveHandler = onMove
  pickerActivePickHandler = onPick
  pickerCancelKey = onKey

  document.addEventListener('mousemove', onMove, true)
  document.addEventListener('click', onPick, true)
  window.addEventListener('keydown', onKey, true)
}

async function ensureInitialNavigate() {
  try {
    const r = await chrome.storage.local.get([STATE_KEY])
    const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
    if (!st.recording) return
    const evs = st.events || []
    const already = evs.some((e) => e?.type === 'navigate')
    if (already) return
    await addEvent(withMeta({ kind: 'action', type: 'navigate', url: window.location.href }, 0))
  } catch {}
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === 'PING') {
    sendResponse({ ok: true })
    return
  }
  if (msg?.type === 'RECORDER_ON') {
    window.__DUBBI_RECORDER_ON__ = Boolean(msg.on)
    if (msg.on) {
      ensureInitialNavigate()
    }
    refreshOverlayFromStorage()
    sendResponse({ ok: true })
    return
  }
  if (msg?.type === 'PICK_ASSERT') {
    if (!window.__DUBBI_RECORDER_ON__) {
      sendResponse({ ok: false, error: 'not recording' })
      return
    }
    startPicker(msg.assertType)
    sendResponse({ ok: true })
    return
  }
})

// Initialize recorder flag from storage (best-effort)
;(async () => {
  try {
    const r = await chrome.storage.local.get([STATE_KEY])
    const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
    window.__DUBBI_RECORDER_ON__ = Boolean(st.recording)
    panelOpen = Boolean(st.uiOpen)
    ensureRecBadge(Boolean(st.recording || st.uiOpen || st.playing), Boolean(st.recording))
    if (st.uiOpen) ensurePanel(st)
    if (st.recording) ensureInitialNavigate()
    if (st.playing) {
      // resume after navigation/page reload
      if (st.uiOpen) ensurePanel(st)
      await sleep(250)
      startPlayback(Number(st.playIndex || 0))
    }
  } catch {
    // ignore
  }
})()

// Allow Dubbi E2E web app to detect extension & prefill config / start session.
window.addEventListener('message', async (ev) => {
  const data = ev?.data
  if (!data || typeof data !== 'object') return
  // IFrame exec (playback routing)
  if (data.type === 'DUBBI_IFRAME_EXEC' && window !== window.top) {
    const reqId = data.reqId
    const ev0 = data.event || {}
    const type = String(ev0.type || '')
    try {
      if (type === 'click') {
        const el = resolveEl(ev0.selector)
        if (!el) throw new Error(`element not found: ${String(ev0.selector || '')}`)
        el.scrollIntoView({ block: 'center', inline: 'center' })
        markEl(el)
        el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
      } else if (type === 'input') {
        const el = resolveEl(ev0.selector)
        if (!el) throw new Error(`element not found: ${String(ev0.selector || '')}`)
        el.scrollIntoView({ block: 'center', inline: 'center' })
        markEl(el)
        el.focus?.()
        el.value = String(ev0.value || '')
        el.dispatchEvent(new Event('input', { bubbles: true }))
        el.dispatchEvent(new Event('change', { bubbles: true }))
      } else if (type === 'assert_visible') {
        const el = resolveEl(ev0.selector)
        if (!el) throw new Error(`element not found: ${String(ev0.selector || '')}`)
        markEl(el)
        if (!isVisible(el)) throw new Error('assert_visible failed (not visible)')
      } else if (type === 'assert_text') {
        const el = resolveEl(ev0.selector)
        if (!el) throw new Error(`element not found: ${String(ev0.selector || '')}`)
        markEl(el)
        const actual = String(el.innerText || el.textContent || '').trim()
        const expected = String(ev0.text || '').trim()
        if (expected && !actual.includes(expected)) {
          throw new Error(`assert_text failed. expected 포함: "${expected}"`)
        }
      } else if (type === 'assert_url') {
        const expected = String(ev0.url || '').trim()
        const actual = String(window.location.href || '')
        if (expected && actual !== expected && !actual.startsWith(expected)) {
          throw new Error(`assert_url failed. expected: "${expected}" actual: "${actual}"`)
        }
      } else {
        // navigate/group not supported inside iframe exec
      }
      window.parent.postMessage({ type: 'DUBBI_IFRAME_EXEC_RESULT', reqId, ok: true }, '*')
    } catch (e) {
      window.parent.postMessage(
        { type: 'DUBBI_IFRAME_EXEC_RESULT', reqId, ok: false, error: String(e?.message || e) },
        '*'
      )
    }
    return
  }
  if (data.type === 'DUBBI_EXT_PING') {
    window.postMessage({ type: 'DUBBI_EXT_PONG' }, '*')
    return
  }
  if (data.type === 'DUBBI_EXT_PREFILL') {
    const r = await chrome.storage.local.get([STATE_KEY])
    const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
    const next = {
      ...st,
      config: {
        ...st.config,
        apiBaseUrl: data.apiBaseUrl || st.config.apiBaseUrl,
        token: data.token || st.config.token,
        scenarioName: data.scenarioName || st.config.scenarioName,
      },
    }
    await chrome.storage.local.set({ [STATE_KEY]: next })
    window.postMessage({ type: 'DUBBI_EXT_PREFILL_OK' }, '*')
    return
  }
  if (data.type === 'DUBBI_EXT_START_SESSION') {
    const url = String(data.url || '').trim()
    if (!url) {
      window.postMessage({ type: 'DUBBI_EXT_START_SESSION_ERR', error: 'url is required' }, '*')
      return
    }
    // prefill first (token/apiBaseUrl/scenarioName)
    const r = await chrome.storage.local.get([STATE_KEY])
    const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
    const next = {
      ...st,
      recording: true,
      events: [],
      config: {
        ...st.config,
        apiBaseUrl: data.apiBaseUrl || st.config.apiBaseUrl,
        token: data.token || st.config.token,
        scenarioName: data.scenarioName || st.config.scenarioName,
      },
    }
    await chrome.storage.local.set({ [STATE_KEY]: next })
    // FE will open the new tab via user-gesture (more reliable than extension-driven tab open).
    // We just ack quickly.
    window.postMessage({ type: 'DUBBI_EXT_START_SESSION_OK', tabId: null }, '*')
  }
})

// Keep overlay in sync with storage (event count updates, etc.)
try {
  chrome.storage.onChanged.addListener((_changes, area) => {
    if (area !== 'local') return
    refreshOverlayFromStorage()
  })
} catch {}

// Make badge clickable to toggle panel
document.addEventListener(
  'click',
  (e) => {
    const t = e.target
    if (t && t.id === '__dubbi_rec_badge') {
      chrome.storage.local.get([STATE_KEY]).then(async (r) => {
        const st = normalizeState(r[STATE_KEY] || DEFAULT_STATE)
        const nextOpen = !Boolean(st.uiOpen)
        await chrome.storage.local.set({ [STATE_KEY]: { ...st, uiOpen: nextOpen } })
        panelOpen = nextOpen
        await refreshOverlayFromStorage()
      })
      e.preventDefault()
      e.stopPropagation()
    }
  },
  true
)


