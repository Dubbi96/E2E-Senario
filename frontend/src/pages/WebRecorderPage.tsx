import { useEffect, useMemo, useState } from 'react'
import { ButtonLink } from '../components/ButtonLink'
import { getAccessToken } from '../lib/auth'

function defaultScenarioName(url: string) {
  try {
    const u = new URL(url)
    const host = u.hostname.replace(/\./g, '_')
    const d = new Date()
    const pad = (n: number) => String(n).padStart(2, '0')
    return `recording_${host}_${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(
      d.getMinutes()
    )}${pad(d.getSeconds())}`
  } catch {
    return 'recorded_scenario'
  }
}

function getApiBaseUrl() {
  // Vite env convention used elsewhere
  return (import.meta as any).env?.VITE_API_BASE_URL || 'http://localhost:8000'
}

async function pingExtension(timeoutMs = 600) {
  return await new Promise<boolean>((resolve) => {
    let done = false
    const timer = window.setTimeout(() => {
      if (done) return
      done = true
      resolve(false)
    }, timeoutMs)
    const onMsg = (ev: MessageEvent) => {
      if (ev?.data?.type === 'DUBBI_EXT_PONG') {
        if (done) return
        done = true
        window.clearTimeout(timer)
        window.removeEventListener('message', onMsg)
        resolve(true)
      }
    }
    window.addEventListener('message', onMsg)
    window.postMessage({ type: 'DUBBI_EXT_PING' }, '*')
  })
}

async function startSession({
  url,
  scenarioName,
  apiBaseUrl,
  token,
}: {
  url: string
  scenarioName: string
  apiBaseUrl: string
  token: string
}) {
  return await new Promise<{ ok: boolean; tabId?: any; error?: string }>((resolve) => {
    let done = false
    const timer = window.setTimeout(() => {
      if (done) return
      done = true
      resolve({ ok: false, error: 'timeout waiting extension response' })
    }, 8000)

    const onMsg = (ev: MessageEvent) => {
      if (ev?.data?.type === 'DUBBI_EXT_START_SESSION_OK') {
        if (done) return
        done = true
        window.clearTimeout(timer)
        window.removeEventListener('message', onMsg)
        resolve({ ok: true, tabId: ev.data.tabId })
      }
      if (ev?.data?.type === 'DUBBI_EXT_START_SESSION_ERR') {
        if (done) return
        done = true
        window.clearTimeout(timer)
        window.removeEventListener('message', onMsg)
        resolve({ ok: false, error: ev.data.error || 'failed' })
      }
    }
    window.addEventListener('message', onMsg)
    window.postMessage({ type: 'DUBBI_EXT_START_SESSION', url, scenarioName, apiBaseUrl, token }, '*')
  })
}

export function WebRecorderPage() {
  const apiBaseUrl = getApiBaseUrl()
  const token = getAccessToken() || ''
  const [targetUrl, setTargetUrl] = useState('https://example.com')
  const [installed, setInstalled] = useState<boolean | null>(null)
  const [status, setStatus] = useState<string>('')
  const [scenarioName, setScenarioName] = useState('')

  useEffect(() => {
    setScenarioName(defaultScenarioName(targetUrl))
  }, [targetUrl])

  useEffect(() => {
    ;(async () => {
      const ok = await pingExtension()
      setInstalled(ok)
    })()
  }, [])

  const canStart = useMemo(() => {
    if (!installed) return false
    if (!token) return false
    try {
      // validate URL
      new URL(targetUrl)
      return true
    } catch {
      return false
    }
  }, [installed, token, targetUrl])

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Web Recorder</h2>
        <div style={{ marginLeft: 'auto' }}>
          <ButtonLink to="/scenarios">← 내 시나리오</ButtonLink>
        </div>
      </div>

      <div style={{ color: 'var(--muted)' }}>
        흐름: <b>DubbieE2E → Web Recorder</b>에서 시작하면, 확장이 설치되어 있을 때 자동으로 토큰/서버/시나리오명이
        세팅되고 새 탭에서 녹화가 시작됩니다.
      </div>

      {installed === false ? (
        <div style={{ display: 'grid', gap: 8 }}>
          <div style={{ color: 'crimson' }}>Dubbi Recorder 확장이 감지되지 않았습니다.</div>
          <ButtonLink to="/recorder/install" variant="primary">
            확장 설치 안내 보기
          </ButtonLink>
        </div>
      ) : null}

      <section style={{ border: '1px solid var(--border)', padding: 12, borderRadius: 10, background: 'var(--panel)' }}>
        <h3>녹화 설정</h3>
        <div style={{ display: 'grid', gap: 8, maxWidth: 720 }}>
          <label>
            대상 URL
            <input value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} style={{ width: '100%' }} />
          </label>
          <label>
            시나리오 이름
            <input value={scenarioName} onChange={(e) => setScenarioName(e.target.value)} style={{ width: '100%' }} />
          </label>

          <div style={{ color: 'var(--muted)', fontSize: 12 }}>
            - API Base URL: <span className="mono">{apiBaseUrl}</span>
            <br />
            - Token: {token ? <span>자동 로드됨</span> : <span style={{ color: 'crimson' }}>로그인 필요</span>}
          </div>

          <button
            disabled={!canStart}
            onClick={async () => {
              setStatus('확장으로 세션 시작 요청 중...')
              const res = await startSession({ url: targetUrl, scenarioName, apiBaseUrl, token })
              if (!res.ok) {
                setStatus(`실패: ${res.error}`)
                return
              }
              // Open new tab via user gesture (more reliable than extension-driven tab open)
              try {
                window.open(targetUrl, '_blank', 'noopener,noreferrer')
              } catch {}
              setStatus(
                '새 탭을 열었습니다. 대상 페이지 우상단에 ● REC 가 뜨면 녹화 중입니다. (배지를 클릭하면 Stop/Clear/Upload 패널이 열립니다)'
              )
            }}
          >
            {installed === null ? '확장 확인 중...' : '새 탭 열고 녹화 시작'}
          </button>

          {status ? <div style={{ color: 'var(--muted)', whiteSpace: 'pre-wrap' }}>{status}</div> : null}
        </div>
      </section>
    </div>
  )
}


