import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, ApiError, downloadWithAuth } from '../lib/api'
import { Card, KV } from '../components/Card'
import { useToast } from '../components/ToastProvider'

export function AuthStatesPage() {
  const qc = useQueryClient()
  const toast = useToast()

  const q = useQuery({ queryKey: ['authStatesMe'], queryFn: api.authStates.myList })

  const [name, setName] = useState('hogak-google')
  const [provider, setProvider] = useState('google')
  const [file, setFile] = useState<File | null>(null)

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('storage_state.json 파일을 선택하세요.')
      return api.authStates.upload({ name, provider, file })
    },
    onSuccess: async () => {
      setFile(null)
      toast.push({ kind: 'success', title: '업로드 완료', message: '세션(storageState)이 저장되었습니다.' })
      await qc.invalidateQueries({ queryKey: ['authStatesMe'] })
    },
  })

  const del = useMutation({
    mutationFn: (id: string) => api.authStates.delete(id),
    onSuccess: async () => {
      toast.push({ kind: 'success', title: '삭제 완료', message: '세션이 삭제되었습니다.' })
      await qc.invalidateQueries({ queryKey: ['authStatesMe'] })
    },
  })

  const toB64 = useMutation({
    mutationFn: (id: string) => api.authStates.b64(id),
    onSuccess: async (res) => {
      try {
        await navigator.clipboard.writeText(res.b64)
        toast.push({ kind: 'success', title: '복사 완료', message: 'E2E_STORAGE_STATE_B64 값이 클립보드에 복사되었습니다.' })
      } catch {
        toast.push({ kind: 'info', title: '생성됨', message: 'base64 문자열을 생성했습니다. (클립보드 접근 실패)' })
      }
    },
  })

  const rows = useMemo(() => q.data || [], [q.data])
  const err = (q.error || upload.error || del.error || toB64.error) as ApiError | null

  const verificationScenario = useMemo(() => {
    const content = {
      base_url: 'https://hogak.live',
      requires_auth: true,
      steps: [
        { type: 'go', url: 'https://hogak.live/main', delay_ms: 1200 },
        { type: 'wait_visible', text: '경기일정', timeout: 15000 },
        { type: 'ensure_logged_in', selector: '#btnUser', logged_out_text: '로그인' },
        { type: 'screenshot', name: 'auth_state_verified' },
      ],
    }
    return new File([JSON.stringify(content, null, 2)], 'hogak_auth_state_verify.json', { type: 'application/json' })
  }, [])

  const runVerify = useMutation({
    mutationFn: async (authStateId: string) => api.runs.create(verificationScenario, authStateId),
    onSuccess: (res) => {
      toast.push({
        kind: 'info',
        title: '검증 Run 요청',
        message: `run_id=${res.run_id} (Runs 페이지에서 상태를 확인하세요)`,
      })
    },
  })

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div>
        <h2>인증 세션(로그인 우회) 관리</h2>
        <p style={{ color: 'var(--muted)' }}>
          Hogak은 Apple 로그인 팝업/2차인증 때문에 headless 서버에서 로그인 재현이 어렵습니다. 그래서{' '}
          <b>Google 테스트 계정으로 1회 수동 로그인</b> 후 Playwright <b>storageState</b>를 업로드하고, 서버/CI에서는 이를{' '}
          <b>주입</b>해서 실행합니다.
        </p>
      </div>

      <section className="panelCard">
        <h3>1) storageState 캡처(로컬, headed)</h3>
        <div style={{ display: 'grid', gap: 8 }}>
          <div style={{ color: 'var(--muted)' }}>
            브라우저 보안상 “웹 페이지”에서 다른 도메인(hogak.live)의 쿠키/로컬스토리지를 직접 추출할 수 없어서,
            로컬에서 Playwright를 한 번 실행해 storageState를 저장해야 합니다.
          </div>
          <div style={{ color: 'var(--muted)' }}>
            또는(권장 UX): 이 레포의 <b>Chrome 확장</b>에서 <b>원클릭 Export</b>로 storageState를 다운로드/업로드할 수 있습니다.
            (확장 권한으로 HttpOnly 쿠키까지 포함 가능)
          </div>
          <div className="mono preWrap" style={{ border: '1px solid var(--border)', padding: 10, borderRadius: 10 }}>
            cd /Users/gangjong-won/Dubbi/e2e-service{'\n'}
            python3 scripts/capture_storage_state.py --url https://hogak.live/login_t --out ./hogak.storage_state.json
          </div>
          <div style={{ color: 'var(--muted)' }}>
            위 커맨드 실행 → 뜬 브라우저에서 Google 테스트 계정 로그인 완료 → 터미널에서 ENTER →{' '}
            <span className="mono">hogak.storage_state.json</span> 생성
          </div>
        </div>
      </section>

      <section className="panelCard">
        <h3>2) storageState 업로드</h3>
        <div style={{ display: 'grid', gap: 10, maxWidth: 760 }}>
          <label className="field" style={{ minWidth: 0 }}>
            이름(권장: hogak-google)
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field" style={{ minWidth: 0 }}>
            Provider
            <select value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="google">google</option>
              <option value="kakao">kakao</option>
              <option value="naver">naver</option>
              <option value="apple">apple</option>
              <option value="unknown">unknown</option>
            </select>
          </label>
          <label className="field" style={{ minWidth: 0 }}>
            storage_state.json
            <input type="file" accept="application/json,.json" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
          <button disabled={upload.isPending} onClick={() => upload.mutate()}>
            {upload.isPending ? '업로드 중...' : '업로드'}
          </button>
          {err ? <div style={{ color: 'crimson' }}>에러: {String(err.detail ?? err.message)}</div> : null}
        </div>
      </section>

      <section className="panelCard">
        <h3>3) 저장된 세션 목록</h3>
        {q.isLoading ? <div>로딩 중...</div> : null}
        <div style={{ display: 'grid', gap: 10 }}>
          {rows.length === 0 ? <div style={{ color: 'var(--muted)' }}>아직 저장된 세션이 없습니다.</div> : null}
          {rows.map((r: any) => (
            <Card
              key={r.id}
              title={<span style={{ fontWeight: 800 }}>{r.name}</span>}
              right={<span className="mono" style={{ color: 'var(--muted)' }}>{r.provider}</span>}
            >
              <KV label="auth_state_id" value={<span className="mono">{r.id}</span>} />
              <KV label="created_at" value={<span className="mono">{r.created_at}</span>} />
              <KV label="size" value={`${r.size_bytes ?? 0} bytes`} />
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                <button
                  className="miniBtn"
                  onClick={() => downloadWithAuth(api.authStates.downloadUrl(r.id), `${r.name || r.id}.storage_state.json`)}
                >
                  다운로드
                </button>
                <button className="miniBtn" onClick={() => toB64.mutate(r.id)} disabled={toB64.isPending}>
                  {toB64.isPending ? '생성 중...' : 'CI용 B64 복사'}
                </button>
                <button className="miniBtn" onClick={() => runVerify.mutate(r.id)} disabled={runVerify.isPending}>
                  {runVerify.isPending ? '요청 중...' : '세션 검증 Run 실행'}
                </button>
                <button
                  className="miniBtn"
                  onClick={() => {
                    if (!confirm(`세션 ${r.name || r.id} 를 삭제할까요?`)) return
                    del.mutate(r.id)
                  }}
                  disabled={del.isPending}
                >
                  삭제
                </button>
              </div>
            </Card>
          ))}
        </div>
        <div style={{ marginTop: 10, color: 'var(--muted)' }}>
          CI에서는 아래 환경변수로 주입할 수 있습니다:
          <div className="mono preWrap" style={{ border: '1px solid var(--border)', padding: 10, borderRadius: 10, marginTop: 6 }}>
            export E2E_STORAGE_STATE_B64='(위 버튼으로 복사한 값)'{'\n'}
            export PLAYWRIGHT_HEADLESS=true
          </div>
        </div>
      </section>

      <section className="panelCard">
        <h3>4) 실행 화면에서의 사용</h3>
        <div style={{ color: 'var(--muted)' }}>
          - 단일 실행(Runs): 시나리오 업로드 시 <b>auth_state_id</b>를 함께 선택하면 서버가 자동으로{' '}
          <span className="mono">storage_state.json</span>을 run 디렉터리에 넣고 <span className="mono">storage_state_path</span>를
          주입합니다.
          <br />- 조합 실행(Suite Run): 생성 시 선택한 <b>auth_state_id</b>가 각 case에 동일하게 주입됩니다.
        </div>
      </section>
    </div>
  )
}


