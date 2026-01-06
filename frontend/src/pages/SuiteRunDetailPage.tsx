import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { api, downloadWithAuth } from '../lib/api'
import { StatusChip } from '../components/StatusChip'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { Card, KV } from '../components/Card'
import { ButtonLink } from '../components/ButtonLink'
import { useToast } from '../components/ToastProvider'

export function SuiteRunDetailPage() {
  const { suiteRunId } = useParams()
  const id = suiteRunId || ''
  const isMobile = useMediaQuery('(max-width: 900px)')
  const toast = useToast()

  const suite = useQuery({
    queryKey: ['suiteRun', id],
    queryFn: () => api.suiteRuns.get(id),
    enabled: Boolean(id),
    refetchInterval: 1500,
  })
  const cases = useQuery({
    queryKey: ['suiteCases', id],
    queryFn: () => api.suiteRuns.cases(id),
    enabled: Boolean(id),
    refetchInterval: 1500,
    refetchIntervalInBackground: true,
  })

  const dl = useMutation({
    mutationFn: () => downloadWithAuth(api.suiteRuns.reportUrl(id), 'suite_report.pdf'),
  })

  const seededSuiteRef = useRef(false)
  const prevSuiteStatusRef = useRef<string | null>(null)
  useEffect(() => {
    const st = suite.data?.status ? String(suite.data.status) : null
    if (!seededSuiteRef.current) {
      seededSuiteRef.current = true
      prevSuiteStatusRef.current = st
      return
    }
    const prev = prevSuiteStatusRef.current
    if (prev != null && st != null && prev !== st) {
      toast.push({ kind: 'info', title: 'Suite Run 상태', message: `${prev} → ${st}` })
    }
    prevSuiteStatusRef.current = st
  }, [suite.data?.status, toast])

  const seededCasesRef = useRef(false)
  const prevCaseMapRef = useRef<Map<string, string>>(new Map())
  useEffect(() => {
    const rows: any[] = cases.data || []
    const next = new Map<string, string>()
    for (const c of rows) next.set(String(c.id), String(c.status || ''))
    if (!seededCasesRef.current) {
      seededCasesRef.current = true
      prevCaseMapRef.current = next
      return
    }
    for (const [cid, st] of next.entries()) {
      const prev = prevCaseMapRef.current.get(cid)
      if (prev != null && prev !== st) {
        toast.push({ kind: 'info', title: '케이스 상태 변경', message: `${cid.slice(0, 8)}…: ${prev} → ${st}` })
      }
    }
    prevCaseMapRef.current = next
  }, [cases.data, toast])

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div>
        <h2>Suite Run 상세</h2>
        <div style={{ color: '#6b7280' }}>
          suite_run_id: <span style={{ fontFamily: 'monospace' }}>{id}</span>
        </div>
      </div>

      <section style={{ border: '1px solid #e5e7eb', padding: 12, borderRadius: 8 }}>
        <h3>상태</h3>
        {suite.isLoading ? (
          <div>로딩 중...</div>
        ) : (
          <div style={{ display: 'grid', gap: 6 }}>
            <div>
              상태: <StatusChip status={suite.data?.status} />
            </div>
            <div style={{ color: '#6b7280', fontFamily: 'monospace' }}>team_id: {suite.data?.team_id || '-'}</div>
            <div style={{ color: '#6b7280' }}>
              케이스: {suite.data?.passed_cases ?? 0} PASS / {suite.data?.failed_cases ?? 0} FAIL (총{' '}
              {suite.data?.case_count ?? 0})
            </div>
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={() => dl.mutate()} disabled={dl.isPending}>
            {dl.isPending ? '다운로드 중...' : 'suite_report.pdf 다운로드(권한 포함)'}
          </button>
          <span style={{ color: '#6b7280' }}>
            (완료되면 워커가 자동 생성합니다. 필요하면 API에 `?refresh=true`로 강제 재생성)
          </span>
        </div>
      </section>

      <section style={{ border: '1px solid #e5e7eb', padding: 12, borderRadius: 8 }}>
        <h3>케이스 목록</h3>
        {cases.isLoading ? (
          <div>로딩 중...</div>
        ) : (
          isMobile ? (
            <div style={{ display: 'grid', gap: 10 }}>
              {(cases.data || []).map((c: any) => (
                <Card
                  key={c.id}
                  title={`케이스 ${c.case_index}`}
                  right={<StatusChip status={c.status} />}
                >
                  <KV label="case_id" value={<span className="mono">{c.id}</span>} />
                  <KV label="started" value={c.started_at || '-'} />
                  <KV label="finished" value={c.finished_at || '-'} />
                  <KV label="exit_code" value={c.exit_code ?? '-'} />
                </Card>
              ))}
            </div>
          ) : (
            <div className="tableWrap">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 90 }}>case_index</th>
                    <th style={{ width: 110 }}>status</th>
                    <th style={{ width: 190 }}>started_at</th>
                    <th style={{ width: 190 }}>finished_at</th>
                    <th style={{ width: 90 }}>exit_code</th>
                  </tr>
                </thead>
                <tbody>
                  {(cases.data || []).map((c: any) => (
                    <tr key={c.id}>
                      <td>{c.case_index}</td>
                      <td>
                        <StatusChip status={c.status} />
                      </td>
                      <td>{c.started_at || '-'}</td>
                      <td>{c.finished_at || '-'}</td>
                      <td>{c.exit_code ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
        <div style={{ marginTop: 8 }}>
          <ButtonLink to="/suite-runs">← 조합 실행으로</ButtonLink>
        </div>
      </section>
    </div>
  )
}


