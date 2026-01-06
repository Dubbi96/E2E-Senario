import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { StatusChip } from '../components/StatusChip'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { Card, KV } from '../components/Card'
import { ButtonLink } from '../components/ButtonLink'
import { formatKstYmdHms } from '../lib/datetime'
import { useToast } from '../components/ToastProvider'

export function TeamDetailPage() {
  const { teamId } = useParams()
  const tid = teamId || ''
  const qc = useQueryClient()
  const isMobile = useMediaQuery('(max-width: 900px)')
  const toast = useToast()

  const members = useQuery({
    queryKey: ['teamMembers', tid],
    queryFn: () => api.teams.members(tid),
    enabled: Boolean(tid),
  })
  const me = useQuery({ queryKey: ['me'], queryFn: api.auth.me })
  const scenarios = useQuery({
    queryKey: ['teamScenarios', tid],
    queryFn: () => api.teams.teamScenarios(tid),
    enabled: Boolean(tid),
  })

  const myRole = useMemo(() => {
    const uid = me.data?.id
    const ms = members.data || []
    const found = ms.find((m: any) => m.user_id === uid)
    return found?.role || null
  }, [me.data, members.data])
  const isOwner = myRole === 'OWNER'

  const apiKeys = useQuery({
    queryKey: ['teamApiKeys', tid],
    queryFn: () => api.teams.apiKeys(tid),
    enabled: Boolean(tid) && isOwner,
  })

  const externalReqs = useQuery({
    queryKey: ['teamExternalReqs', tid],
    queryFn: () => api.teams.externalRequests(tid),
    enabled: Boolean(tid) && isOwner,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })

  const webhookDeliveries = useQuery({
    queryKey: ['teamWebhookDeliveries', tid],
    queryFn: () => api.teams.webhookDeliveries(tid),
    enabled: Boolean(tid) && isOwner,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })

  const [newKeyName, setNewKeyName] = useState('github-actions')
  const createKey = useMutation({
    mutationFn: () => api.teams.createApiKey(tid, newKeyName),
    onSuccess: async (data: any) => {
      await qc.invalidateQueries({ queryKey: ['teamApiKeys', tid] })
      // show only once
      const token = data?.api_key
      if (token) {
        try {
          await navigator.clipboard.writeText(String(token))
          toast.push({ kind: 'success', title: 'API Key 발급', message: 'API Key를 발급했고 클립보드에 복사했습니다.' })
        } catch {
          toast.push({ kind: 'success', title: 'API Key 발급', message: 'API Key를 발급했습니다. 아래 토큰을 복사해두세요.' })
        }
        alert(`API Key(1회 노출):\n\n${token}\n\n※ 이 토큰은 다시 조회할 수 없습니다. 안전한 곳에 보관하세요.`)
      } else {
        toast.push({ kind: 'success', title: 'API Key 발급', message: 'API Key를 발급했습니다.' })
      }
    },
  })

  const revokeKey = useMutation({
    mutationFn: (apiKeyId: string) => api.teams.revokeApiKey(tid, apiKeyId),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['teamApiKeys', tid] })
      toast.push({ kind: 'success', title: 'API Key 폐기', message: 'API Key를 폐기했습니다.' })
    },
  })

  const teamSuiteRuns = useQuery({
    queryKey: ['teamSuiteRuns', tid],
    queryFn: () => api.suiteRuns.teamHistory(tid),
    enabled: Boolean(tid),
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  })

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
    if (!teamSuiteRuns.isSuccess) return
    const rows: any[] = teamSuiteRuns.data || []
    const next = new Map<string, string>()
    for (const r of rows) next.set(String(r.id), String(r.status || ''))

    if (!seededRef.current) {
      prevMapRef.current = next
      seededRef.current = true
      return
    }

    for (const [id, st] of next.entries()) {
      if (!prevMapRef.current.has(id)) {
        toast.push({
          kind: 'info',
          title: '팀 Suite Run',
          message: `${shortId(id)} 생성됨 (상태: ${st || '-'})`,
        })
      }
    }

    for (const [id, st] of next.entries()) {
      const prev = prevMapRef.current.get(id)
      if (prev != null && prev !== st) {
        toast.push({
          kind: toastKindFor(st),
          title: '팀 Suite Run 상태 변경',
          message: `${shortId(id)}: ${prev || '-'} → ${st || '-'}`,
        })
      }
    }

    prevMapRef.current = next
  }, [teamSuiteRuns.isSuccess, teamSuiteRuns.data, toast])

  const [newMemberUserId, setNewMemberUserId] = useState('')
  const [newMemberRole, setNewMemberRole] = useState('MEMBER')
  const addMember = useMutation({
    mutationFn: () => api.teams.addMember(tid, newMemberUserId, newMemberRole),
    onSuccess: async () => {
      setNewMemberUserId('')
      await qc.invalidateQueries({ queryKey: ['teamMembers', tid] })
    },
  })

  const [renameScenarioId, setRenameScenarioId] = useState('')
  const [renameValue, setRenameValue] = useState('')
  const rename = useMutation({
    mutationFn: () => api.teams.updateTeamScenario(tid, renameScenarioId, renameValue),
    onSuccess: async () => {
      setRenameScenarioId('')
      setRenameValue('')
      await qc.invalidateQueries({ queryKey: ['teamScenarios', tid] })
    },
  })

  const [replaceScenarioId, setReplaceScenarioId] = useState('')
  const [replaceFile, setReplaceFile] = useState<File | null>(null)
  const replace = useMutation({
    mutationFn: async () => {
      if (!replaceFile) throw new Error('파일을 선택하세요.')
      return api.teams.replaceTeamScenarioFile(tid, replaceScenarioId, replaceFile)
    },
    onSuccess: async () => {
      setReplaceScenarioId('')
      setReplaceFile(null)
      await qc.invalidateQueries({ queryKey: ['teamScenarios', tid] })
    },
  })

  const del = useMutation({
    mutationFn: (scenarioId: string) => api.teams.deleteTeamScenario(tid, scenarioId),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['teamScenarios', tid] })
    },
  })

  const deleteSuite = useMutation({
    mutationFn: (suiteRunId: string) => api.suiteRuns.delete(suiteRunId),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['teamSuiteRuns', tid] })
    },
  })

  const err = (addMember.error || rename.error || replace.error || del.error) as ApiError | null
  const scenarioRows = useMemo(() => scenarios.data || [], [scenarios.data])

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div>
        <h2>팀 상세</h2>
        <div style={{ color: '#6b7280' }}>team_id: <span style={{ fontFamily: 'monospace' }}>{tid}</span></div>
      </div>

      {err ? <div style={{ color: 'crimson' }}>에러: {String(err.detail ?? err.message)}</div> : null}

      <section className="panelCard">
        <h3>멤버</h3>
        <div style={{ display: 'grid', gap: 12 }}>
          <div>
            {members.isLoading ? (
              <div>로딩 중...</div>
            ) : (
              isMobile ? (
                <div style={{ display: 'grid', gap: 10 }}>
                  {(members.data || []).map((m: any) => (
                    <Card key={m.user_id} title={<span className="mono">{m.user_id}</span>} right={m.role}>
                      <KV label="role" value={m.role} />
                    </Card>
                  ))}
                </div>
              ) : (
                <div className="tableWrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>user_id</th>
                        <th style={{ width: 120 }}>role</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(members.data || []).map((m: any) => (
                        <tr key={m.user_id}>
                          <td className="mono ellipsis" style={{ maxWidth: 420 }}>
                            {m.user_id}
                          </td>
                          <td>{m.role}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            )}
          </div>

          <div className="rowEnd">
            <label className="field" style={{ minWidth: 220 }}>
              user_id
              <input value={newMemberUserId} onChange={(e) => setNewMemberUserId(e.target.value)} />
            </label>
            <label className="field" style={{ minWidth: 180, flex: '0 0 auto' }}>
              role
              <select value={newMemberRole} onChange={(e) => setNewMemberRole(e.target.value)}>
                <option value="MEMBER">MEMBER</option>
                <option value="ADMIN">ADMIN</option>
                <option value="OWNER">OWNER</option>
              </select>
            </label>
            <button disabled={addMember.isPending || !newMemberUserId} onClick={() => addMember.mutate()}>
              {addMember.isPending ? '추가 중...' : '멤버 추가(OWNER만)'}
            </button>
          </div>
        </div>
      </section>

      <section className="panelCard">
        <h3>팀 시나리오</h3>
        <div style={{ color: 'var(--muted)', marginBottom: 8 }}>
          수정/삭제/파일교체는 OWNER만 동작합니다(권한 없으면 403).
        </div>

        {scenarios.isLoading ? (
          <div>로딩 중...</div>
        ) : (
          isMobile ? (
            <div style={{ display: 'grid', gap: 10 }}>
              {scenarioRows.map((s: any) => (
                <Card
                  key={s.id}
                  title={s.name}
                  right={
                    <button onClick={() => del.mutate(s.id)} disabled={del.isPending}>
                      삭제
                    </button>
                  }
                >
                  <KV label="id" value={<span className="mono">{s.id}</span>} />
                  <KV label="created" value={s.created_at} />
                </Card>
              ))}
            </div>
          ) : (
            <div className="tableWrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>name</th>
                    <th>id</th>
                    <th style={{ width: 160 }}>created_at</th>
                    <th className="actions" style={{ width: 110 }}>
                      actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {scenarioRows.map((s: any) => (
                    <tr key={s.id}>
                      <td className="ellipsis" style={{ maxWidth: 240 }}>
                        {s.name}
                      </td>
                      <td className="mono ellipsis" style={{ maxWidth: 360 }}>
                        {s.id}
                      </td>
                      <td>{s.created_at}</td>
                      <td className="actions">
                        <button className="miniBtn" onClick={() => del.mutate(s.id)} disabled={del.isPending}>
                          삭제(OWNER)
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}

        <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
          <div className="rowEnd">
            <label className="field" style={{ minWidth: 260 }}>
              scenario_id
              <input value={renameScenarioId} onChange={(e) => setRenameScenarioId(e.target.value)} />
            </label>
            <label className="field" style={{ minWidth: 260 }}>
              새 이름
              <input value={renameValue} onChange={(e) => setRenameValue(e.target.value)} />
            </label>
            <button disabled={rename.isPending || !renameScenarioId || !renameValue} onClick={() => rename.mutate()}>
              {rename.isPending ? '변경 중...' : '이름 변경(OWNER)'}
            </button>
          </div>

          <div className="rowEnd">
            <label className="field" style={{ minWidth: 260 }}>
              scenario_id
              <input value={replaceScenarioId} onChange={(e) => setReplaceScenarioId(e.target.value)} />
            </label>
            <label className="field" style={{ minWidth: 260 }}>
              새 파일
              <input type="file" onChange={(e) => setReplaceFile(e.target.files?.[0] || null)} />
            </label>
            <button
              disabled={replace.isPending || !replaceScenarioId || !replaceFile}
              onClick={() => replace.mutate()}
            >
              {replace.isPending ? '교체 중...' : '파일 교체(OWNER)'}
            </button>
          </div>
        </div>
      </section>

      <section className="panelCard">
        <h3>외부 연동(API / Webhook)</h3>
        <p style={{ color: 'var(--muted)' }}>
          CI/CD에서 <span className="mono">X-Api-Key</span>로 실행 요청을 보내고, 완료 시 <span className="mono">webhook_url</span>로 콜백을 받을 수 있습니다.
        </p>
        {!isOwner ? (
          <div style={{ color: 'var(--muted)' }}>
            이 섹션은 팀 <b>OWNER</b>만 API Key 발급/로그 조회가 가능합니다. (현재 권한: {myRole || '-'})
          </div>
        ) : null}

        {isOwner ? (
          <div style={{ display: 'grid', gap: 12 }}>
            <div>
              <h4 style={{ margin: '8px 0' }}>1) 팀 API Key</h4>
              <div className="rowEnd">
                <label className="field" style={{ minWidth: 260 }}>
                  Key 이름
                  <input value={newKeyName} onChange={(e) => setNewKeyName(e.target.value)} />
                </label>
                <button disabled={createKey.isPending || !newKeyName.trim()} onClick={() => createKey.mutate()}>
                  {createKey.isPending ? '발급 중...' : '새 API Key 발급'}
                </button>
              </div>
              {apiKeys.isLoading ? <div>로딩 중...</div> : null}
              {apiKeys.error ? (
                <div style={{ color: 'crimson' }}>에러: {String((apiKeys.error as any)?.detail ?? (apiKeys.error as any)?.message ?? apiKeys.error)}</div>
              ) : null}
              <div className="tableWrap" style={{ marginTop: 8 }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>name</th>
                      <th style={{ width: 140 }}>prefix</th>
                      <th style={{ width: 190 }}>created</th>
                      <th style={{ width: 190 }}>revoked</th>
                      <th className="actions" style={{ width: 120 }}>
                        actions
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(apiKeys.data || []).map((k: any) => (
                      <tr key={k.id}>
                        <td className="ellipsis" style={{ maxWidth: 240 }}>
                          {k.name}
                        </td>
                        <td className="mono">{k.prefix}</td>
                        <td className="nowrap">{k.created_at}</td>
                        <td className="nowrap">{k.revoked_at || '-'}</td>
                        <td className="actions">
                          {k.revoked_at ? (
                            <span style={{ color: 'var(--muted)' }}>-</span>
                          ) : (
                            <button
                              className="miniBtn"
                              onClick={() => {
                                if (!confirm(`API Key '${k.name}'을(를) 폐기할까요?`)) return
                                revokeKey.mutate(k.id)
                              }}
                              disabled={revokeKey.isPending}
                            >
                              폐기
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {(apiKeys.data || []).length === 0 ? (
                      <tr>
                        <td colSpan={5} style={{ color: 'var(--muted)' }}>
                          아직 발급된 API Key가 없습니다.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <h4 style={{ margin: '8px 0' }}>2) 실행 요청 예제(복붙용)</h4>
              <div className="mono preWrap" style={{ border: '1px solid var(--border)', borderRadius: 12, padding: 10, background: 'var(--panel2)' }}>
{`# 1) Suite Run 실행 요청(비동기)\n# - Idempotency-Key는 build_id 등으로 넣어두면 재시도 시 중복 실행이 생기지 않습니다.\n\ncurl -X POST \"${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/public/v1/suite-runs\" \\\n  -H \"X-Api-Key: <YOUR_TEAM_API_KEY>\" \\\n  -H \"Idempotency-Key: <YOUR_BUILD_ID>\" \\\n  -H \"Content-Type: application/json\" \\\n  -d '{\n    \"team_id\": \"${tid}\",\n    \"combinations\": [[\"<scenario_id_1>\", \"<scenario_id_2>\"]],\n    \"context\": {\"git_sha\": \"<sha>\", \"branch\": \"<branch>\", \"build_id\": \"<id>\"},\n    \"webhook_url\": \"https://your-ci.example.com/webhooks/dubbi\",\n    \"webhook_secret\": \"optional-secret\"\n  }'\n\n# 2) 상태 조회(폴링)\ncurl -H \"X-Api-Key: <YOUR_TEAM_API_KEY>\" \"${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/public/v1/suite-runs/<suite_run_id>\"\n\n# 3) 리포트 다운로드\ncurl -L -H \"X-Api-Key: <YOUR_TEAM_API_KEY>\" \"${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/public/v1/suite-runs/<suite_run_id>/report.pdf\" -o suite_report.pdf\n`}
              </div>
              <div style={{ marginTop: 8, color: 'var(--muted)' }}>
                webhook은 <span className="mono">event=suite_run.completed</span> payload로 호출되며, secret 지정 시 <span className="mono">x-dubbi-signature</span> 헤더(HMAC)가 함께 전송됩니다.
              </div>
            </div>

            <div>
              <h4 style={{ margin: '8px 0' }}>3) 외부 실행 요청 로그</h4>
              {externalReqs.isLoading ? <div>로딩 중...</div> : null}
              <div className="tableWrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th style={{ width: 170 }}>created</th>
                      <th>suite_run_id</th>
                      <th style={{ width: 160 }}>idempotency</th>
                      <th style={{ width: 160 }}>remote</th>
                      <th className="actions" style={{ width: 120 }}>
                        webhook
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(externalReqs.data || []).map((r: any) => (
                      <tr key={r.id}>
                        <td className="nowrap">{r.created_at}</td>
                        <td className="mono ellipsis" style={{ maxWidth: 420 }}>
                          {r.suite_run_id}
                        </td>
                        <td className="mono ellipsis" style={{ maxWidth: 160 }}>
                          {r.idempotency_key || '-'}
                        </td>
                        <td className="ellipsis" style={{ maxWidth: 160 }}>
                          {r.remote_addr || '-'}
                        </td>
                        <td className="actions">
                          <span className="ellipsis" style={{ maxWidth: 220, color: 'var(--muted)' }}>
                            {r.webhook_url || '-'}
                          </span>
                        </td>
                      </tr>
                    ))}
                    {(externalReqs.data || []).length === 0 ? (
                      <tr>
                        <td colSpan={5} style={{ color: 'var(--muted)' }}>
                          아직 외부 실행 요청 로그가 없습니다.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>

            <div>
              <h4 style={{ margin: '8px 0' }}>4) Webhook delivery 로그</h4>
              {webhookDeliveries.isLoading ? <div>로딩 중...</div> : null}
              <div className="tableWrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th style={{ width: 170 }}>created</th>
                      <th>suite_run_id</th>
                      <th style={{ width: 80 }}>attempt</th>
                      <th style={{ width: 90 }}>status</th>
                      <th className="actions">url / error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(webhookDeliveries.data || []).map((w: any) => (
                      <tr key={w.id}>
                        <td className="nowrap">{w.created_at}</td>
                        <td className="mono ellipsis" style={{ maxWidth: 360 }}>
                          {w.suite_run_id}
                        </td>
                        <td>{w.attempt}</td>
                        <td className="mono">{w.status_code ?? '-'}</td>
                        <td className="actions">
                          <div className="ellipsis" style={{ maxWidth: 520, color: 'var(--muted)' }}>
                            {w.url}
                            {w.error_message ? ` | ${String(w.error_message).slice(0, 140)}` : ''}
                          </div>
                        </td>
                      </tr>
                    ))}
                    {(webhookDeliveries.data || []).length === 0 ? (
                      <tr>
                        <td colSpan={5} style={{ color: 'var(--muted)' }}>
                          아직 webhook delivery 로그가 없습니다.
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        ) : null}
      </section>

      <section style={{ border: '1px solid var(--border)', padding: 12, borderRadius: 10, background: 'var(--panel)' }}>
        <h3>팀 실행 이력(Suite Runs)</h3>
        <p style={{ color: 'var(--muted)' }}>
          팀 멤버라면(OWNER/ADMIN/MEMBER) 팀 실행 이력을 조회할 수 있습니다. 삭제는 <b>OWNER만</b> 가능합니다.
        </p>
        {teamSuiteRuns.isLoading ? (
          <div>로딩 중...</div>
        ) : (
          isMobile ? (
            <div style={{ display: 'grid', gap: 10 }}>
              {(teamSuiteRuns.data || []).map((r: any) => (
                <Card
                  key={r.id}
                  title={<ButtonLink to={`/suite-runs/${r.id}`} size="sm">{r.id}</ButtonLink>}
                  right={
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <StatusChip status={r.status} />
                      {isOwner ? (
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
                    <th style={{ width: 170 }}>생성(KST)</th>
                    <th className="actions" style={{ width: 110 }}>
                      작업
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(teamSuiteRuns.data || []).map((r: any) => (
                    <tr key={r.id}>
                      <td className="mono ellipsis" style={{ maxWidth: 420 }}>
                        <ButtonLink to={`/suite-runs/${r.id}`} size="sm">{r.id}</ButtonLink>
                      </td>
                      <td>
                        <StatusChip status={r.status} />
                      </td>
                      <td className="nowrap">{formatKstYmdHms(r.created_at)}</td>
                      <td className="actions">
                        {isOwner ? (
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


