import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError, downloadWithAuth } from '../lib/api'
import { Card, KV } from '../components/Card'
import { StatusChip } from '../components/StatusChip'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { formatKstYmdHms } from '../lib/datetime'
import { useToast } from '../components/ToastProvider'

export function RunsPage() {
  const qc = useQueryClient()
  const isMobile = useMediaQuery('(max-width: 900px)')
  const toast = useToast()
  const q = useQuery({
    queryKey: ['myRuns'],
    queryFn: api.runs.myList,
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  })

  const [file, setFile] = useState<File | null>(null)
  const authStates = useQuery({ queryKey: ['authStatesMe'], queryFn: api.authStates.myList })
  const [authStateId, setAuthStateId] = useState<string>('')

  const prevMapRef = useRef<Map<string, string>>(new Map())
  const seededRef = useRef(false)

  function shortId(id: string) {
    return id ? `${id.slice(0, 8)}…` : '-'
  }
  function toastKindFor(status: string) {
    const s = String(status || '').toUpperCase()
    if (s === 'PASSED') return 'success'
    if (s === 'FAILED') return 'error'
    return 'info'
  }

  useEffect(() => {
    // Don't emit toasts on page entry/initial load; only after first successful fetch.
    if (!q.isSuccess) return
    const rows: any[] = q.data || []
    const next = new Map<string, string>()
    for (const r of rows) next.set(String(r.id), String(r.status || ''))

    if (!seededRef.current) {
      prevMapRef.current = next
      seededRef.current = true
      return
    }

    // New runs
    for (const [id, st] of next.entries()) {
      if (!prevMapRef.current.has(id)) {
        toast.push({
          kind: 'info',
          title: '새 Run',
          message: `${shortId(id)} 생성됨 (상태: ${st || '-'})`,
        })
      }
    }

    // Status changes
    for (const [id, st] of next.entries()) {
      const prev = prevMapRef.current.get(id)
      if (prev != null && prev !== st) {
        toast.push({
          kind: toastKindFor(st),
          title: 'Run 상태 변경',
          message: `${shortId(id)}: ${prev || '-'} → ${st || '-'}`,
        })
      }
    }

    prevMapRef.current = next
  }, [q.isSuccess, q.data, toast])

  const create = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('파일을 선택하세요.')
      return api.runs.create(file, authStateId || null)
    },
    onSuccess: async () => {
      setFile(null)
      toast.push({ kind: 'info', title: 'Run 요청', message: '실행 요청을 보냈습니다. 상태가 자동으로 갱신됩니다.' })
      await qc.invalidateQueries({ queryKey: ['myRuns'] })
    },
  })

  const del = useMutation({
    mutationFn: async (runId: string) => api.runs.delete(runId),
    onSuccess: async () => {
      toast.push({ kind: 'success', title: '삭제', message: 'Run이 삭제되었습니다. (soft delete)' })
      await qc.invalidateQueries({ queryKey: ['myRuns'] })
    },
  })

  const rows = useMemo(() => q.data || [], [q.data])
  const err = (q.error || create.error || del.error) as ApiError | null

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div>
        <h2>단일 실행(Runs)</h2>
        <p style={{ color: 'var(--muted)' }}>
          내가 실행한 단일 Run 목록입니다. 삭제하면 DB는 soft-delete되고, 아티팩트는 pending_delete로 이관됩니다.
        </p>
      </div>

      <section style={{ border: '1px solid var(--border)', padding: 12, borderRadius: 10, background: 'var(--panel)' }}>
        <h3>새 Run 실행(업로드)</h3>
        <div style={{ display: 'grid', gap: 10, maxWidth: 720 }}>
          <label className="field" style={{ minWidth: 0 }}>
            시나리오 파일(.yaml/.json)
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
          <label className="field" style={{ minWidth: 0 }}>
            (선택) 인증 세션(auth_state_id) — Apple 2FA 우회용
            <select value={authStateId} onChange={(e) => setAuthStateId(e.target.value)}>
              <option value="">(선택 안 함)</option>
              {(authStates.data || []).map((a: any) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.provider})
                </option>
              ))}
            </select>
            <div style={{ color: 'var(--muted)', marginTop: 6 }}>
              로그인 필요한 시나리오(requires_auth=true)는 여기를 선택하는 것을 권장합니다. 없으면 런이 즉시 실패하며 주입 방법을 안내합니다.
            </div>
          </label>
          <button disabled={create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? '실행 요청 중...' : '실행 요청'}
          </button>
          {err ? <div style={{ color: 'crimson' }}>에러: {String(err.detail ?? err.message)}</div> : null}
        </div>
      </section>

      <section>
        <h3>내 실행 이력(단일 Run)</h3>
        {q.isLoading ? <div>로딩 중...</div> : null}

        {isMobile ? (
          <div style={{ display: 'grid', gap: 10 }}>
            {rows.map((r: any) => (
              <Card
                key={r.id}
                title={<span className="mono">{r.id}</span>}
                right={<StatusChip status={r.status} />}
              >
                <KV label="생성(KST)" value={formatKstYmdHms(r.created_at)} />
                <KV label="종료(KST)" value={r.finished_at ? formatKstYmdHms(r.finished_at) : '-'} />
                <KV label="exit_code" value={r.exit_code ?? '-'} />
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                  <button
                    className="miniBtn"
                    onClick={() => downloadWithAuth(api.runs.reportUrl(r.id), `run_report_${r.id}.pdf`)}
                    disabled={String(r.status).toUpperCase() === 'RUNNING' || String(r.status).toUpperCase() === 'QUEUED'}
                  >
                    PDF
                  </button>
                  <button
                    className="miniBtn"
                    onClick={() => {
                      if (!confirm(`Run ${r.id}를 삭제할까요? (아티팩트는 pending_delete로 이동)`)) return
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
        ) : (
          <div className="tableWrap">
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>상태</th>
                  <th>생성(KST)</th>
                  <th>종료(KST)</th>
                  <th>exit_code</th>
                  <th className="actions">작업</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r: any) => (
                  <tr key={r.id}>
                    <td className="mono ellipsis" style={{ maxWidth: 360 }}>
                      {r.id}
                    </td>
                    <td>
                      <StatusChip status={r.status} />
                    </td>
                    <td className="nowrap">{formatKstYmdHms(r.created_at)}</td>
                    <td className="nowrap">{r.finished_at ? formatKstYmdHms(r.finished_at) : '-'}</td>
                    <td>{r.exit_code ?? '-'}</td>
                    <td className="actions">
                      <div className="btnGroup">
                        <button
                          className="miniBtn"
                          onClick={() => downloadWithAuth(api.runs.reportUrl(r.id), `run_report_${r.id}.pdf`)}
                          disabled={String(r.status).toUpperCase() === 'RUNNING' || String(r.status).toUpperCase() === 'QUEUED'}
                        >
                          PDF
                        </button>
                        <button
                          className="miniBtn"
                          onClick={() => {
                            if (!confirm(`Run ${r.id}를 삭제할까요? (아티팩트는 pending_delete로 이동)`)) return
                            del.mutate(r.id)
                          }}
                          disabled={del.isPending}
                        >
                          삭제
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}


