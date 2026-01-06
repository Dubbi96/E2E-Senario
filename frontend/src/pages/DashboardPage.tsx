import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export function DashboardPage() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.auth.me })
  const myScenarios = useQuery({ queryKey: ['myScenarios'], queryFn: api.scenarios.myList })
  const myTeams = useQuery({ queryKey: ['myTeams'], queryFn: api.teams.myTeams })

  return (
    <div>
      <h2>대시보드</h2>
      <div style={{ display: 'grid', gap: 8 }}>
        <div>
          <b>로그인 사용자</b>: {me.data?.email ?? '(loading...)'}
        </div>
        <div>
          <b>내 시나리오</b>: {myScenarios.data?.length ?? 0}개
        </div>
        <div>
          <b>내 팀</b>: {myTeams.data?.length ?? 0}개
        </div>
      </div>
    </div>
  )
}


