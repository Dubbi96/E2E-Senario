const STATE_KEY = 'dubbi_recorder_state_v1'

const DEFAULT_STATE = {
  recording: false,
  events: [],
  config: { apiBaseUrl: 'http://localhost:8000', token: '', scenarioName: 'recorded_scenario' },
}

async function loadState() {
  const r = await chrome.storage.local.get([STATE_KEY])
  return r[STATE_KEY] || DEFAULT_STATE
}

async function saveState(next) {
  await chrome.storage.local.set({ [STATE_KEY]: next })
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

async function sendSafe(msg) {
  try {
    return await chrome.runtime.sendMessage(msg)
  } catch (e) {
    return { ok: false, error: String(e?.message || e) }
  }
}

async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true })
  return tabs[0]
}

async function sendToTab(tabId, msg) {
  return await chrome.tabs.sendMessage(tabId, msg)
}

async function ensureContentScript(tabId) {
  try {
    await sendToTab(tabId, { type: 'PING' })
    return true
  } catch (e) {
    // content script not present -> inject it
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] })
      await sendToTab(tabId, { type: 'PING' })
      return true
    } catch (e2) {
      return false
    }
  }
}

function $(id) {
  return document.getElementById(id)
}

function setText(id, v) {
  $(id).textContent = String(v)
}

function setMsg(okText, errText) {
  $('ok').textContent = okText || ''
  $('err').textContent = errText || ''
}

function base64FromUtf8(s) {
  // UTF-8 safe base64 (for data: URL download)
  const bytes = new TextEncoder().encode(String(s))
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
  return btoa(bin)
}

function mapSameSite(ss) {
  const v = String(ss || '').toLowerCase()
  if (v === 'no_restriction' || v === 'none') return 'None'
  if (v === 'strict') return 'Strict'
  if (v === 'lax') return 'Lax'
  // default: Playwright expects Lax/None/Strict; safest fallback is Lax
  return 'Lax'
}

async function captureWebStorages(tabId) {
  const [{ result }] = await chrome.scripting.executeScript({
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
  return result
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

async function buildStorageStateFromActiveTab(tab) {
  if (!tab?.id) throw new Error('no active tab')
  const url = String(tab.url || '').trim()
  if (!/^https?:\/\//i.test(url)) throw new Error('active tab must be http(s)')

  const stor = await captureWebStorages(tab.id)
  if (!stor?.origin) throw new Error('failed to capture storages')

  // cookies: capture for current URL + hogak root (helps when tab is deep path)
  const cookieUrls = Array.from(new Set([url, `${stor.origin}/`]))
  let cookies = []
  for (const cu of cookieUrls) {
    try {
      const part = await captureCookiesForUrl(cu)
      cookies = cookies.concat(part)
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
    _meta: {
      capturedAt: Date.now(),
      tabUrl: url,
      note: 'Exported by Dubbi extension (cookies + localStorage/sessionStorage)',
    },
  }
}

async function downloadJson(filename, obj) {
  const json = JSON.stringify(obj, null, 2)
  const b64 = base64FromUtf8(json)
  const dataUrl = `data:application/json;base64,${b64}`
  await chrome.downloads.download({ url: dataUrl, filename, saveAs: true })
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
  const res = await fetch(`${base}/auth-states`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: fd,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.detail || res.statusText)
  return data
}

async function refresh() {
  // Always trust storage (persists even when popup closes / service worker sleeps)
  const st = await loadState()
  $('apiBaseUrl').value = st.config?.apiBaseUrl || ''
  $('token').value = st.config?.token || ''
  $('scenarioName').value = st.config?.scenarioName || ''
  $('authStateName').value = st.config?.authStateName || 'hogak-google'
  $('authProvider').value = st.config?.authProvider || 'google'
  setText('count', st.events?.length || 0)
  $('msg').textContent = st.recording ? '녹화 중...' : '대기 중'
}

async function saveConfig() {
  const st = await loadState()
  const next = {
    ...st,
    config: {
      ...st.config,
      apiBaseUrl: $('apiBaseUrl').value.trim(),
      token: $('token').value.trim(),
      scenarioName: $('scenarioName').value.trim(),
      authStateName: $('authStateName').value.trim(),
      authProvider: $('authProvider').value,
    },
  }
  await saveState(next)
  // best-effort: also inform background (not required for persistence)
  await sendSafe({ type: 'SET_CONFIG', config: next.config })
}

document.addEventListener('DOMContentLoaded', async () => {
  try {
    await refresh()
  } catch (e) {
    setMsg('', `init failed: ${String(e?.message || e)}`)
  }

  ;['apiBaseUrl', 'token', 'scenarioName', 'authStateName', 'authProvider'].forEach((id) => {
    $(id).addEventListener('change', async () => {
      await saveConfig()
      await refresh()
    })
  })

  $('start').addEventListener('click', async () => {
    setMsg('', '')
    await saveConfig()
    // persist start to storage (so closing popup keeps state)
    const st = await loadState()
    const next = { ...st, recording: true, events: [] }
    await saveState(next)
    // best-effort background
    await sendSafe({ type: 'START' })
    const tab = await activeTab()
    if (tab?.id) {
      const ok = await ensureContentScript(tab.id)
      if (!ok) {
        setMsg('', '이 페이지에서는 content script를 주입할 수 없습니다. (chrome://, webstore 등은 제한)')
        await refresh()
        return
      }
      await sendToTab(tab.id, { type: 'RECORDER_ON', on: true })
    }
    await refresh()
  })

  $('stop').addEventListener('click', async () => {
    setMsg('', '')
    const st = await loadState()
    await saveState({ ...st, recording: false })
    await sendSafe({ type: 'STOP' })
    const tab = await activeTab()
    if (tab?.id) {
      await ensureContentScript(tab.id)
      try {
        await sendToTab(tab.id, { type: 'RECORDER_ON', on: false })
      } catch {}
    }
    await refresh()
  })

  $('clear').addEventListener('click', async () => {
    setMsg('', '')
    const st = await loadState()
    await saveState({ ...st, events: [] })
    await sendSafe({ type: 'CLEAR' })
    await refresh()
  })

  $('pick').addEventListener('click', async () => {
    setMsg('', '')
    const tab = await activeTab()
    if (!tab?.id) {
      setMsg('', 'no active tab')
      return
    }
    const ok = await ensureContentScript(tab.id)
    if (!ok) {
      setMsg('', '이 페이지에서는 content script를 주입할 수 없습니다. (chrome://, webstore 등은 제한)')
      return
    }
    const at = $('assertType').value
    let res = null
    try {
      res = await sendToTab(tab.id, { type: 'PICK_ASSERT', assertType: at })
    } catch (e) {
      setMsg('', 'picker failed: content script not reachable')
      return
    }
    if (!res?.ok) {
      setMsg('', res?.error || 'picker failed (start recording first)')
      return
    }
    setMsg('피커 실행됨: 페이지에서 요소를 클릭하세요.', '')
    await refresh()
  })

  $('upload').addEventListener('click', async () => {
    setMsg('', '')
    await saveConfig()
    const st = await loadState()
    const apiBaseUrl = st.config?.apiBaseUrl?.trim()
    const token = st.config?.token?.trim()
    if (!apiBaseUrl || !token) {
      setMsg('', 'apiBaseUrl / token 을 입력하세요.')
      return
    }
    try {
      const res = await fetch(`${apiBaseUrl.replace(/\\/$/, '')}/recordings/to-scenario`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ name: st.config?.scenarioName || 'recorded_scenario', events: flattenEvents(st.events || []) }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg('', `upload failed: ${data?.detail || res.statusText}`)
        return
      }
      setMsg(`업로드 성공! scenario_id=${data?.id}`, '')
    } catch (e) {
      setMsg('', `upload error: ${String(e?.message || e)}`)
      return
    }
    await refresh()
  })

  $('autoFillToken')?.addEventListener('click', async () => {
    setMsg('', '')
    const tab = await activeTab()
    if (!tab?.id) {
      setMsg('', 'no active tab')
      return
    }
    try {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        world: 'MAIN',
        func: () => {
          try {
            return localStorage.getItem('access_token') || ''
          } catch {
            return ''
          }
        },
      })
      if (!result) {
        setMsg('', '현재 탭에서 access_token을 찾지 못했습니다. (Dubbi FE 로그인 탭에서 실행하세요)')
        return
      }
      $('token').value = String(result)
      await saveConfig()
      await refresh()
      setMsg('token 자동 채움 완료', '')
    } catch (e) {
      setMsg('', `token 자동 채움 실패: ${String(e?.message || e)}`)
    }
  })

  $('exportStorageState')?.addEventListener('click', async () => {
    setMsg('', '')
    await saveConfig()
    const tab = await activeTab()
    if (!tab?.id) return setMsg('', 'no active tab')
    try {
      const st = await loadState()
      const name = (st.config?.authStateName || 'hogak-google').trim() || 'hogak-google'
      const storageState = await buildStorageStateFromActiveTab(tab)
      await downloadJson(`${name}.storage_state.json`, storageState)
      setMsg(`다운로드 준비됨: ${name}.storage_state.json`, '')
    } catch (e) {
      setMsg('', `export 실패: ${String(e?.message || e)}`)
    }
    await refresh()
  })

  $('exportAndUploadStorageState')?.addEventListener('click', async () => {
    setMsg('', '')
    await saveConfig()
    const tab = await activeTab()
    if (!tab?.id) return setMsg('', 'no active tab')
    const st = await loadState()
    const apiBaseUrl = st.config?.apiBaseUrl?.trim()
    const token = st.config?.token?.trim()
    if (!apiBaseUrl || !token) {
      setMsg('', 'apiBaseUrl / token 을 입력(또는 token 자동 채우기)하세요.')
      return
    }
    try {
      const name = (st.config?.authStateName || 'hogak-google').trim() || 'hogak-google'
      const provider = String(st.config?.authProvider || 'google')
      const storageState = await buildStorageStateFromActiveTab(tab)
      const res = await uploadStorageState({ apiBaseUrl, token, name, provider, storageState })
      setMsg(`업로드 성공! auth_state_id=${res?.id}`, '')
    } catch (e) {
      setMsg('', `export+upload 실패: ${String(e?.message || e)}`)
    }
    await refresh()
  })
})


