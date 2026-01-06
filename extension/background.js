const STATE_KEY = 'dubbi_recorder_state_v1'

async function getState() {
  const r = await chrome.storage.local.get([STATE_KEY])
  return (
    r[STATE_KEY] || {
      recording: false,
      events: [],
      config: { apiBaseUrl: 'http://localhost:8000', token: '', scenarioName: 'recorded_scenario' },
    }
  )
}

async function setState(next) {
  await chrome.storage.local.set({ [STATE_KEY]: next })
}

function mapSameSite(ss) {
  const v = String(ss || '').toLowerCase()
  if (v === 'no_restriction' || v === 'none') return 'None'
  if (v === 'strict') return 'Strict'
  if (v === 'lax') return 'Lax'
  return 'Lax'
}

async function captureWebStorages(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    func: () => {
      const pairs = (storage) => {
        const out = []
        try {
          for (let i = 0; i < storage.length; i++) {
            const k = storage.key(i)
            if (!k) continue
            out.push({ name: k, value: String(storage.getItem(k) ?? '') })
          }
        } catch {}
        return out
      }
      return {
        origin: String(window.location.origin || ''),
        href: String(window.location.href || ''),
        localStorage: pairs(window.localStorage),
        sessionStorage: pairs(window.sessionStorage),
      }
    },
  })
  return results?.[0]?.result
}

async function captureCookiesForUrl(url) {
  const cookies = await chrome.cookies.getAll({ url })
  return (cookies || []).map((c) => ({
    name: c.name,
    value: c.value,
    domain: c.domain,
    path: c.path,
    expires: typeof c.expirationDate === 'number' ? c.expirationDate : -1,
    httpOnly: Boolean(c.httpOnly),
    secure: Boolean(c.secure),
    sameSite: mapSameSite(c.sameSite),
  }))
}

function base64FromUtf8(s) {
  const bytes = new TextEncoder().encode(String(s))
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
  return btoa(bin)
}

async function downloadJson(filename, obj) {
  const json = JSON.stringify(obj, null, 2)
  const b64 = base64FromUtf8(json)
  const dataUrl = `data:application/json;base64,${b64}`
  await chrome.downloads.download({ url: dataUrl, filename, saveAs: true })
}

async function buildStorageStateFromTab(tabId, tabUrl) {
  const url = String(tabUrl || '').trim()
  const stor = await captureWebStorages(tabId)
  if (!stor?.origin) throw new Error('failed to capture storages')

  const cookieUrls = Array.from(new Set([url, `${stor.origin}/`]))
  let cookies = []
  for (const cu of cookieUrls) {
    try {
      cookies = cookies.concat(await captureCookiesForUrl(cu))
    } catch {}
  }
  // de-dup by (name,domain,path)
  const seen = new Set()
  const uniq = []
  for (const c of cookies) {
    const k = `${c.name}||${c.domain}||${c.path}`
    if (seen.has(k)) continue
    seen.add(k)
    uniq.push(c)
  }

  return {
    cookies: uniq,
    origins: [
      {
        origin: stor.origin,
        localStorage: Array.isArray(stor.localStorage) ? stor.localStorage : [],
        sessionStorage: Array.isArray(stor.sessionStorage) ? stor.sessionStorage : [],
      },
    ],
    _meta: { capturedAt: Date.now(), tabUrl: url },
  }
}

async function uploadStorageState({ apiBaseUrl, token, name, provider, storageState }) {
  const base = String(apiBaseUrl || '').replace(/\/$/, '')
  if (!base) throw new Error('apiBaseUrl is required')
  if (!token) throw new Error('token is required')
  const blob = new Blob([JSON.stringify(storageState, null, 2)], { type: 'application/json' })
  const fd = new FormData()
  fd.set('name', name || 'hogak-google')
  fd.set('provider', provider || 'google')
  fd.set('storage_state', blob, 'storage_state.json')
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), 12_000)
  const res = await fetch(`${base}/auth-states`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: fd,
    signal: ctrl.signal,
  })
  clearTimeout(t)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.detail || res.statusText)
  return data
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

function openTab(url) {
  return chrome.tabs.create({ url })
}

async function ensureTabRecorderOn(tabId) {
  // content script might not be ready immediately; retry a few times
  for (let i = 0; i < 10; i++) {
    try {
      await chrome.tabs.sendMessage(tabId, { type: 'RECORDER_ON', on: true })
      return true
    } catch (e) {
      await new Promise((r) => setTimeout(r, 300))
    }
  }
  return false
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  ;(async () => {
    try {
      const state = await getState()
      try {
        console.log('[dubbi-recorder-bg] message', msg?.type || msg)
      } catch {}

      if (msg?.type === 'PING_BG') {
        sendResponse({ ok: true })
        return
      }

    if (msg?.type === 'GET_STATE') {
      sendResponse({ ok: true, state })
      return
    }

    if (msg?.type === 'SET_CONFIG') {
      const next = { ...state, config: { ...state.config, ...msg.config } }
      await setState(next)
      sendResponse({ ok: true, state: next })
      return
    }

    if (msg?.type === 'START') {
      const next = { ...state, recording: true, events: [] }
      await setState(next)
      sendResponse({ ok: true, state: next })
      return
    }

    if (msg?.type === 'STOP') {
      const next = { ...state, recording: false }
      await setState(next)
      sendResponse({ ok: true, state: next })
      return
    }

    if (msg?.type === 'ADD_EVENT') {
      if (!state.recording) {
        sendResponse({ ok: false, error: 'not recording' })
        return
      }
      const next = { ...state, events: [...state.events, msg.event] }
      await setState(next)
      sendResponse({ ok: true, state: next })
      return
    }

    if (msg?.type === 'CLEAR') {
      const next = { ...state, events: [] }
      await setState(next)
      sendResponse({ ok: true, state: next })
      return
    }

    if (msg?.type === 'UPLOAD') {
      // Always re-read latest state from storage (content scripts may update storage directly)
      const latest = await getState()
      const { apiBaseUrl, token, scenarioName } = latest.config || {}
      if (!apiBaseUrl || !token) {
        sendResponse({ ok: false, error: 'apiBaseUrl/token is required' })
        return
      }
      const events = flattenEvents(latest.events || [])
      if (!events.length) {
        sendResponse({ ok: false, error: 'no events to upload' })
        return
      }
      try {
        console.log('[dubbi-recorder-bg] uploading', { apiBaseUrl, eventCount: events.length, scenarioName })
      } catch {}
      const payload = {
        name: scenarioName || 'recorded_scenario',
        events,
      }
      try {
        const ctrl = new AbortController()
        const t = setTimeout(() => ctrl.abort(), 12_000)
        const res = await fetch(`${apiBaseUrl.replace(/\\/$/, '')}/recordings/to-scenario`, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          signal: ctrl.signal,
          body: JSON.stringify(payload),
        })
        clearTimeout(t)
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          // On failure: keep events so user can retry.
          await setState({ ...latest, recording: false })
          try {
            console.warn('[dubbi-recorder-bg] upload failed', res.status, data)
          } catch {}
          sendResponse({ ok: false, error: data?.detail || res.statusText, data })
          return
        }
        // On success: stop + clear events (best UX)
        await setState({ ...latest, recording: false, events: [] })
        try {
          console.log('[dubbi-recorder-bg] upload OK', data)
        } catch {}
        sendResponse({ ok: true, data })
        return
      } catch (e) {
        await setState({ ...latest, recording: false })
        const msg = String(e?.name === 'AbortError' ? 'timeout uploading to api' : e?.message || e)
        try {
          console.error('[dubbi-recorder-bg] upload exception', msg)
        } catch {}
        sendResponse({ ok: false, error: msg })
        return
      }
    }

    if (msg?.type === 'OPEN_SESSION') {
      const url = String(msg.url || '').trim()
      if (!url) {
        sendResponse({ ok: false, error: 'url is required' })
        return
      }
      // start recording + clear events (persist in storage)
      const next = { ...state, recording: true, events: [] }
      await setState(next)

      const tab = await openTab(url)
      if (!tab?.id) {
        sendResponse({ ok: false, error: 'failed to create tab' })
        return
      }
      // best-effort toggle on (fire-and-forget). Recording flag is already persisted in storage,
      // so the content script will show REC badge even if this message fails.
      ensureTabRecorderOn(tab.id)
      sendResponse({ ok: true, tabId: tab.id, note: 'tab opened, recorder will attach shortly' })
      return
    }

    if (msg?.type === 'CAPTURE_STORAGE_STATE') {
      const tabId = _sender?.tab?.id
      const tabUrl = _sender?.tab?.url
      if (!tabId || !tabUrl) {
        sendResponse({ ok: false, error: 'no sender tab context' })
        return
      }
      try {
        const storageState = await buildStorageStateFromTab(tabId, tabUrl)
        sendResponse({ ok: true, storageState })
      } catch (e) {
        sendResponse({ ok: false, error: String(e?.message || e) })
      }
      return
    }

    if (msg?.type === 'DOWNLOAD_STORAGE_STATE') {
      try {
        await downloadJson(String(msg.filename || 'storage_state.json'), msg.storageState || {})
        sendResponse({ ok: true })
      } catch (e) {
        sendResponse({ ok: false, error: String(e?.message || e) })
      }
      return
    }

    if (msg?.type === 'UPLOAD_AUTH_STATE') {
      try {
        const data = await uploadStorageState({
          apiBaseUrl: msg.apiBaseUrl,
          token: msg.token,
          name: msg.name,
          provider: msg.provider,
          storageState: msg.storageState,
        })
        sendResponse({ ok: true, data })
      } catch (e) {
        sendResponse({ ok: false, error: String(e?.name === 'AbortError' ? 'timeout uploading to api' : e?.message || e) })
      }
      return
    }

      sendResponse({ ok: false, error: 'unknown message' })
    } catch (e) {
      // Never leave caller hanging
      sendResponse({ ok: false, error: String(e?.message || e) })
    }
  })()

  return true
})


