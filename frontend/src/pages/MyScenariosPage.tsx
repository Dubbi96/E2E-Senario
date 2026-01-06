import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { Card, KV } from '../components/Card'
import { ButtonLink } from '../components/ButtonLink'
import { formatKstYmdHms } from '../lib/datetime'

export function MyScenariosPage() {
  const qc = useQueryClient()
  const myScenarios = useQuery({ queryKey: ['myScenarios'], queryFn: api.scenarios.myList })
  const myTeams = useQuery({ queryKey: ['myTeams'], queryFn: api.teams.myTeams })
  const isMobile = useMediaQuery('(max-width: 900px)')

  const [name, setName] = useState('passing_example_domain')
  const [file, setFile] = useState<File | null>(null)

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('파일을 선택하세요.')
      return api.scenarios.uploadMine(name, file)
    },
    onSuccess: async () => {
      setFile(null)
      await qc.invalidateQueries({ queryKey: ['myScenarios'] })
    },
  })

  const del = useMutation({
    mutationFn: async (scenarioId: string) => api.scenarios.deleteMine(scenarioId),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['myScenarios'] })
    },
  })

  const [publishScenarioId, setPublishScenarioId] = useState<string>('')
  const [publishTeamId, setPublishTeamId] = useState<string>('')
  const [publishName, setPublishName] = useState<string>('')

  const publish = useMutation({
    mutationFn: () => api.scenarios.publishToTeam(publishScenarioId, publishTeamId, publishName || undefined),
  })

  const rows = useMemo(() => myScenarios.data || [], [myScenarios.data])
  const err = (upload.error || publish.error) as ApiError | null

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div>
        <h2>내 시나리오</h2>
        <p style={{ color: 'var(--muted)' }}>업로드한 시나리오는 본인만 조회 가능합니다.</p>
        <div style={{ marginTop: 8 }}>
          <ButtonLink to="/recorder" variant="primary" size="sm">
            시나리오 생성 &gt; Web Recorder
          </ButtonLink>
        </div>
      </div>

      <section style={{ border: '1px solid var(--border)', padding: 12, borderRadius: 10, background: 'var(--panel)' }}>
        <h3>시나리오 업로드</h3>
        <div style={{ display: 'grid', gap: 8, maxWidth: 700 }}>
          <label>
            이름
            <input value={name} onChange={(e) => setName(e.target.value)} style={{ width: '100%' }} />
          </label>
          <label>
            파일(.yaml/.json)
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
          <button disabled={upload.isPending} onClick={() => upload.mutate()}>
            {upload.isPending ? '업로드 중...' : '업로드'}
          </button>
          {err ? <div style={{ color: 'crimson' }}>에러: {String(err.detail ?? err.message)}</div> : null}
        </div>
      </section>

      <section>
        <h3>목록</h3>
        <div style={{ color: 'var(--muted)', marginBottom: 8 }}>
          {myScenarios.isLoading ? '로딩 중...' : `총 ${rows.length}개`}
        </div>
        {isMobile ? (
          <div style={{ display: 'grid', gap: 10 }}>
            {rows.map((s: any) => (
              <Card
                key={s.id}
                title={s.name}
                right={
                  <div style={{ display: 'flex', gap: 8 }}>
                    <ButtonLink to={`/scenarios/${s.id}`} size="sm">
                      편집
                    </ButtonLink>
                    <button
                      className="miniBtn"
                      onClick={() => {
                        if (!confirm(`시나리오 '${s.name}'을(를) 삭제할까요?`)) return
                        del.mutate(s.id)
                      }}
                      disabled={del.isPending}
                    >
                      삭제
                    </button>
                  </div>
                }
              >
                <KV label="ID" value={<span className="mono">{s.id}</span>} />
                <KV label="생성" value={formatKstYmdHms(s.created_at)} />
              </Card>
            ))}
          </div>
        ) : (
          <div className="tableWrap">
            <table className="table">
              <thead>
                <tr>
                  <th>이름</th>
                  <th>ID</th>
                  <th>생성(KST)</th>
                  <th className="actions">작업</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s: any) => (
                  <tr key={s.id}>
                    <td className="ellipsis" style={{ maxWidth: 240 }}>
                      {s.name}
                    </td>
                    <td className="mono ellipsis" style={{ maxWidth: 360 }}>
                      {s.id}
                    </td>
                    <td className="nowrap">{formatKstYmdHms(s.created_at)}</td>
                    <td className="actions">
                      <div className="btnGroup">
                        <ButtonLink to={`/scenarios/${s.id}`} size="sm">
                          편집
                        </ButtonLink>
                        <button
                          className="miniBtn"
                          onClick={() => {
                            if (!confirm(`시나리오 '${s.name}'을(를) 삭제할까요?`)) return
                            del.mutate(s.id)
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

      <section style={{ border: '1px solid var(--border)', padding: 12, borderRadius: 10, background: 'var(--panel)' }}>
        <h3>팀 시나리오로 발행(publish)</h3>
        <p style={{ color: 'var(--muted)' }}>
          현재 백엔드 정책: 팀 멤버(OWNER/ADMIN/MEMBER)면 발행 가능. 실행은 ADMIN/OWNER.
        </p>
        <div style={{ display: 'grid', gap: 8, maxWidth: 700 }}>
          <label>
            내 시나리오 선택
            <select value={publishScenarioId} onChange={(e) => setPublishScenarioId(e.target.value)}>
              <option value="">선택</option>
              {rows.map((s: any) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.id})
                </option>
              ))}
            </select>
          </label>
          <label>
            팀 선택
            <select value={publishTeamId} onChange={(e) => setPublishTeamId(e.target.value)}>
              <option value="">선택</option>
              {(myTeams.data || []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.id})
                </option>
              ))}
            </select>
          </label>
          <label>
            팀 시나리오 이름(선택)
            <input value={publishName} onChange={(e) => setPublishName(e.target.value)} style={{ width: '100%' }} />
          </label>
          <button
            disabled={publish.isPending || !publishScenarioId || !publishTeamId}
            onClick={() => publish.mutate()}
          >
            {publish.isPending ? '발행 중...' : '팀으로 발행'}
          </button>
        </div>
      </section>
    </div>
  )
}


