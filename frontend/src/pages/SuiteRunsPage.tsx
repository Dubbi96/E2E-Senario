import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { StatusChip } from '../components/StatusChip'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { Card, KV } from '../components/Card'
import { ButtonLink } from '../components/ButtonLink'
import { formatKstYmdHms } from '../lib/datetime'
import { useToast } from '../components/ToastProvider'

type Picked = { id: string; label: string }

export function SuiteRunsPage() {
  const qc = useQueryClient()
  const isMobile = useMediaQuery('(max-width: 900px)')
  const toast = useToast()
  const myScenarios = useQuery({ queryKey: ['myScenarios'], queryFn: api.scenarios.myList })
  const myTeams = useQuery({ queryKey: ['myTeams'], queryFn: api.teams.myTeams })
  const authStates = useQuery({ queryKey: ['authStatesMe'], queryFn: api.authStates.myList })
  const [teamId, setTeamId] = useState<string>('') // optional suite scope
  const [authStateId, setAuthStateId] = useState<string>('') // optional auth injection
  const myHistory = useQuery({
    queryKey: ['suiteHistoryMe'],
    queryFn: api.suiteRuns.myHistory,
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  })
  const drafts = useQuery({ queryKey: ['drafts'], queryFn: api.drafts.list })

  const [teamScenarioTeamId, setTeamScenarioTeamId] = useState<string>('') // for listing team scenarios
  const teamScenarios = useQuery({
    queryKey: ['teamScenariosForSuite', teamScenarioTeamId],
    queryFn: () => api.teams.teamScenarios(teamScenarioTeamId),
    enabled: Boolean(teamScenarioTeamId),
  })

  const available: Picked[] = useMemo(() => {
    const mine = (myScenarios.data || []).map((s: any) => ({
      id: s.id,
      label: `[내] ${s.name}`,
    }))
    const team = (teamScenarios.data || []).map((s: any) => ({
      id: s.id,
      label: `[팀] ${s.name}`,
    }))
    return [...mine, ...team]
  }, [myScenarios.data, teamScenarios.data])

  const [currentCombo, setCurrentCombo] = useState<Picked[]>([])
  const [combinations, setCombinations] = useState<string[][]>([])
  const [draftName, setDraftName] = useState<string>('내 조합 초안')

  function addToCurrent(id: string) {
    const found = available.find((a) => a.id === id)
    if (!found) return
    setCurrentCombo((prev) => [...prev, found])
  }

  function moveCurrent(i: number, dir: -1 | 1) {
    setCurrentCombo((prev) => {
      const next = [...prev]
      const j = i + dir
      if (j < 0 || j >= next.length) return prev
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }

  function removeCurrent(i: number) {
    setCurrentCombo((prev) => prev.filter((_, idx) => idx !== i))
  }

  function commitCombo() {
    if (currentCombo.length === 0) return
    setCombinations((prev) => [...prev, currentCombo.map((x) => x.id)])
    setCurrentCombo([])
  }

  function removeCombo(idx: number) {
    setCombinations((prev) => prev.filter((_, i) => i !== idx))
  }

  const create = useMutation({
    mutationFn: () =>
      api.suiteRuns.create({
        team_id: teamId || null,
        combinations,
        auth_state_id: authStateId || null,
      }),
    onSuccess: async () => {
      toast.push({ kind: 'info', title: 'Suite Run 요청', message: '조합 실행을 요청했습니다. 상태가 자동으로 갱신됩니다.' })
      await qc.invalidateQueries({ queryKey: ['suiteHistoryMe'] })
    },
  })

  const saveDraft = useMutation({
    mutationFn: () =>
      api.drafts.create({
        name: draftName,
        team_id: teamId || null,
        combinations,
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['drafts'] })
    },
  })

  const deleteDraft = useMutation({
    mutationFn: (draftId: string) => api.drafts.delete(draftId),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['drafts'] })
    },
  })

  const deleteSuite = useMutation({
    mutationFn: (suiteRunId: string) => api.suiteRuns.delete(suiteRunId),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['suiteHistoryMe'] })
    },
  })

  const err = create.error as ApiError | null

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
    if (!myHistory.isSuccess) return
    const rows: any[] = myHistory.data || []
    const next = new Map<string, string>()
    for (const r of rows) next.set(String(r.id), String(r.status || ''))

    if (!seededRef.current) {
      prevMapRef.current = next
      seededRef.current = true
      return
    }

    for (const [id, st] of next.entries()) {
      if (!prevMapRef.current.has(id)) {
        toast.push({ kind: 'info', title: '새 Suite Run', message: `${shortId(id)} 생성됨 (상태: ${st || '-'})` })
      }
    }

    for (const [id, st] of next.entries()) {
      const prev = prevMapRef.current.get(id)
      if (prev != null && prev !== st) {
        toast.push({
          kind: toastKindFor(st),
          title: 'Suite Run 상태 변경',
          message: `${shortId(id)}: ${prev || '-'} → ${st || '-'}`,
        })
      }
    }

    prevMapRef.current = next
  }, [myHistory.isSuccess, myHistory.data, toast])

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div>
        <h2>조합 실행(Suite Run)</h2>
        <p style={{ color: 'var(--muted)' }}>
          사용자 정의 조합을 제출하면 각 조합이 케이스로 실행됩니다. 케이스 전체가 PASS면 suite PASS.
        </p>
      </div>

      <section className="panelCard">
        <h3>1) (선택) 팀 스코프로 실행</h3>
        <div className="rowEnd">
          <label className="field" style={{ minWidth: 260 }}>
            suite team_id (실행 권한: OWNER/ADMIN)
            <select value={teamId} onChange={(e) => setTeamId(e.target.value)}>
              <option value="">(개인 스코프)</option>
              {(myTeams.data || []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.id})
                </option>
              ))}
            </select>
          </label>
        </div>
        <div style={{ marginTop: 10 }}>
          <label className="field" style={{ minWidth: 260 }}>
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
              선택 시 각 케이스(case_dir)에 storage_state.json이 주입되고 combined.json에 storage_state_path가 자동 설정됩니다.
            </div>
          </label>
        </div>
      </section>

      <section className="panelCard">
        <h3>2) 시나리오 선택(내/팀)</h3>
        <div style={{ display: 'grid', gap: 8 }}>
          <label className="field" style={{ minWidth: 0 }}>
            팀 시나리오 불러올 팀 선택(선택)
            <select value={teamScenarioTeamId} onChange={(e) => setTeamScenarioTeamId(e.target.value)}>
              <option value="">(선택 안 함)</option>
              {(myTeams.data || []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>

          <label className="field" style={{ minWidth: 0 }}>
            시나리오를 현재 조합에 추가
            <select onChange={(e) => addToCurrent(e.target.value)} value="">
              <option value="">선택</option>
              {available.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label} ({a.id})
                </option>
              ))}
            </select>
          </label>
        </div>

        <div style={{ marginTop: 12 }}>
          <h4>현재 조합(순서 중요: A안=step 이어붙이기)</h4>
          {currentCombo.length === 0 ? (
            <div style={{ color: '#6b7280' }}>비어있음</div>
          ) : (
            <ol>
              {currentCombo.map((c, idx) => (
                <li key={`${c.id}-${idx}`} style={{ marginBottom: 6 }}>
                  {c.label} <span style={{ color: '#6b7280' }}>({c.id})</span>{' '}
                  <button onClick={() => moveCurrent(idx, -1)} disabled={idx === 0}>
                    ↑
                  </button>{' '}
                  <button onClick={() => moveCurrent(idx, 1)} disabled={idx === currentCombo.length - 1}>
                    ↓
                  </button>{' '}
                  <button onClick={() => removeCurrent(idx)}>삭제</button>
                </li>
              ))}
            </ol>
          )}
          <button disabled={currentCombo.length === 0} onClick={commitCombo}>
            이 조합 추가
          </button>
        </div>
      </section>

      <section className="panelCard">
        <h3>3) 제출할 조합 목록</h3>
        {combinations.length === 0 ? (
          <div style={{ color: 'var(--muted)' }}>아직 조합이 없습니다.</div>
        ) : (
          <div style={{ display: 'grid', gap: 8 }}>
            {combinations.map((combo, idx) => (
              <div key={idx} className="row" style={{ justifyContent: 'space-between' }}>
                <div className="mono ellipsis" style={{ flex: 1, minWidth: 0 }}>
                  {idx + 1}. [{combo.join(', ')}]
                </div>
                <button className="miniBtn" onClick={() => removeCombo(idx)}>
                  삭제
                </button>
              </div>
            ))}
          </div>
        )}

        <div style={{ marginTop: 12 }}>
          <button disabled={create.isPending || combinations.length === 0} onClick={() => create.mutate()}>
            {create.isPending ? '생성 중...' : 'Suite Run 생성 + 실행'}
          </button>
          <div className="rowEnd" style={{ marginTop: 10 }}>
            <label className="field" style={{ minWidth: 260 }}>
              Draft 이름
              <input value={draftName} onChange={(e) => setDraftName(e.target.value)} />
            </label>
            <button disabled={saveDraft.isPending || combinations.length === 0} onClick={() => saveDraft.mutate()}>
              {saveDraft.isPending ? '저장 중...' : '이 조합 목록 Draft로 저장'}
            </button>
          </div>
          {err ? <div style={{ color: 'crimson', marginTop: 8 }}>에러: {String(err.detail ?? err.message)}</div> : null}
        </div>

        {create.data ? (
          <div style={{ marginTop: 12 }}>
            생성됨: <Link to={`/suite-runs/${create.data.suite_run_id}`}>{create.data.suite_run_id}</Link>
          </div>
        ) : null}
      </section>

      <section className="panelCard">
        <h3>저장된 Draft</h3>
        <p style={{ color: 'var(--muted)' }}>
          개인별로 저장해두었다가 불러오거나 삭제할 수 있습니다. (팀 스코프 team_id도 함께 저장됨)
        </p>
        {drafts.isLoading ? (
          <div>로딩 중...</div>
        ) : (
          <div style={{ display: 'grid', gap: 8 }}>
            {(drafts.data || []).map((d: any) => (
              <div
                key={d.id}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr auto',
                  gap: 8,
                  border: '1px solid var(--border)',
                  borderRadius: 10,
                  padding: 10,
                }}
              >
                <div>
                  <div style={{ fontWeight: 700 }}>{d.name}</div>
                  <div className="mono ellipsis" style={{ color: 'var(--muted)', maxWidth: 560 }}>
                    id: {d.id}
                  </div>
                  <div style={{ color: 'var(--muted)' }}>
                    team_id: <span className="mono ellipsis" style={{ maxWidth: 560 }}>{d.team_id || '-'}</span>
                  </div>
                  <div className="mono preWrap" style={{ marginTop: 6 }}>
                    {JSON.stringify(d.combinations)}
                  </div>
                </div>
                <div style={{ display: 'grid', gap: 6, alignContent: 'start' }}>
                  <button
                    className="miniBtn"
                    onClick={() => {
                      setTeamId(d.team_id || '')
                      setCombinations(d.combinations || [])
                    }}
                  >
                    불러오기
                  </button>
                  <button className="miniBtn" onClick={() => deleteDraft.mutate(d.id)} disabled={deleteDraft.isPending}>
                    삭제
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section style={{ border: '1px solid var(--border)', padding: 12, borderRadius: 10, background: 'var(--panel)' }}>
        <h3>내 실행 이력</h3>
        {myHistory.isLoading ? (
          <div>로딩 중...</div>
        ) : (
          isMobile ? (
            <div style={{ display: 'grid', gap: 10 }}>
              {(myHistory.data || []).map((r: any) => (
                <Card
                  key={r.id}
                  title={<ButtonLink to={`/suite-runs/${r.id}`}>{r.id}</ButtonLink>}
                  right={
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <StatusChip status={r.status} />
                      {!r.team_id ? (
                        <button
                          className="miniBtn"
                          onClick={() => {
                            if (!confirm(`Suite Run ${r.id} 이력을 삭제할까요?`)) return
                            deleteSuite.mutate(r.id)
                          }}
                          disabled={deleteSuite.isPending}
                        >
                          삭제
                        </button>
                      ) : null}
                    </div>
                  }
                >
                  <KV label="team_id" value={<span className="mono">{r.team_id || '-'}</span>} />
                  <KV label="생성(KST)" value={formatKstYmdHms(r.created_at)} />
                </Card>
              ))}
            </div>
          ) : (
            <div className="tableWrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th style={{ width: 110 }}>상태</th>
                    <th style={{ width: 180 }}>team_id</th>
                    <th style={{ width: 170 }}>생성(KST)</th>
                    <th className="actions" style={{ width: 110 }}>
                      작업
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(myHistory.data || []).map((r: any) => (
                    <tr key={r.id}>
                      <td className="mono ellipsis" style={{ maxWidth: 420 }}>
                        <Link to={`/suite-runs/${r.id}`}>{r.id}</Link>
                      </td>
                      <td>
                        <StatusChip status={r.status} />
                      </td>
                      <td className="mono ellipsis" style={{ maxWidth: 180 }}>
                        {r.team_id || '-'}
                      </td>
                      <td className="nowrap">{formatKstYmdHms(r.created_at)}</td>
                      <td className="actions">
                        {!r.team_id ? (
                          <button
                            className="miniBtn"
                            onClick={() => {
                              if (!confirm(`Suite Run ${r.id} 이력을 삭제할까요?`)) return
                              deleteSuite.mutate(r.id)
                            }}
                            disabled={deleteSuite.isPending}
                          >
                            삭제
                          </button>
                        ) : (
                          <span style={{ color: 'var(--muted)' }}>-</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </section>
    </div>
  )
}


