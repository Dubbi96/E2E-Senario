import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../lib/api'
import { ButtonLink } from '../components/ButtonLink'

export function TeamsPage() {
  const qc = useQueryClient()
  const myTeams = useQuery({ queryKey: ['myTeams'], queryFn: api.teams.myTeams })
  const [name, setName] = useState('my-team')

  const create = useMutation({
    mutationFn: () => api.teams.create(name),
    onSuccess: async () => {
      setName('my-team')
      await qc.invalidateQueries({ queryKey: ['myTeams'] })
    },
  })

  const err = create.error as ApiError | null

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div>
        <h2>팀</h2>
        <p style={{ color: 'var(--muted)' }}>팀을 만들고 멤버/팀 시나리오/조합 실행을 관리합니다.</p>
      </div>

      <section className="panelCard" style={{ maxWidth: 760 }}>
        <h3>팀 생성</h3>
        <div className="rowEnd">
          <label className="field" style={{ minWidth: 260 }}>
            팀 이름
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <button disabled={create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? '생성 중...' : '생성'}
          </button>
        </div>
        {err ? <div style={{ color: 'crimson', marginTop: 8 }}>에러: {String(err.detail ?? err.message)}</div> : null}
      </section>

      <section>
        <h3>내 팀 목록</h3>
        {myTeams.isLoading ? (
          <div>로딩 중...</div>
        ) : (
          <ul style={{ paddingLeft: 18, margin: 0, display: 'grid', gap: 10 }}>
            {(myTeams.data || []).map((t) => (
              <li key={t.id}>
                <span className="btnGroup">
                  <ButtonLink to={`/teams/${t.id}`}>{t.name}</ButtonLink>
                  <span className="mono ellipsis" style={{ color: 'var(--muted)', maxWidth: 520 }}>
                    ({t.id})
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}


