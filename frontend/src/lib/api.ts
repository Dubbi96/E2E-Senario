const API_BASE_URL =
  (import.meta as any).env?.VITE_API_BASE_URL?.toString() || 'http://localhost:8000'

function getToken(): string | null {
  return localStorage.getItem('access_token')
}

export function getApiBaseUrl(): string {
  return API_BASE_URL
}

export async function downloadWithAuth(path: string, filename: string) {
  const token = getToken()
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) {
    throw new ApiError(res.status, await res.text().catch(() => 'download failed'))
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export class ApiError extends Error {
  status: number
  detail: any
  constructor(status: number, detail: any) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail))
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const headers = new Headers(init?.headers || {})
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  })

  const contentType = res.headers.get('content-type') || ''
  const isJson = contentType.includes('application/json')
  const body = isJson ? await res.json().catch(() => null) : await res.text().catch(() => '')

  if (!res.ok) {
    throw new ApiError(res.status, (body as any)?.detail ?? body)
  }
  return body as T
}

export const api = {
  auth: {
    register: (email: string, password: string) =>
      request<{ id: string; email: string }>('/auth/register', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ email, password }),
      }),
    token: async (email: string, password: string) => {
      // OAuth2PasswordRequestForm: application/x-www-form-urlencoded
      const form = new URLSearchParams()
      form.set('username', email)
      form.set('password', password)
      return request<{ access_token: string; token_type: string }>('/auth/token', {
        method: 'POST',
        headers: { 'content-type': 'application/x-www-form-urlencoded' },
        body: form,
      })
    },
    me: () => request<{ id: string; email: string }>('/auth/me'),
  },

  scenarios: {
    myList: () => request<any[]>('/scenarios/me'),
    getContent: (scenarioId: string) =>
      request<any>(`/scenarios/${encodeURIComponent(scenarioId)}/content`),
    updateContent: (scenarioId: string, content: any) =>
      request<any>(`/scenarios/${encodeURIComponent(scenarioId)}/content`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ content }),
      }),
    validate: (content: any) =>
      request<{ valid: boolean; errors: string[]; example?: any }>('/scenarios/validate', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ content }),
      }),
    deleteMine: (scenarioId: string) =>
      request<any>(`/scenarios/${encodeURIComponent(scenarioId)}`, {
        method: 'DELETE',
      }),
    uploadMine: async (name: string, file: File) => {
      const fd = new FormData()
      fd.set('scenario', file)
      return request<any>(`/scenarios?name=${encodeURIComponent(name)}`, {
        method: 'POST',
        body: fd,
      })
    },
    publishToTeam: (scenarioId: string, teamId: string, name?: string) =>
      request<any>(`/scenarios/${encodeURIComponent(scenarioId)}/publish`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ team_id: teamId, name: name || null }),
      }),
  },

  recordings: {
    toScenario: (payload: { name: string; base_url?: string | null; events: any[] }) =>
      request<any>('/recordings/to-scenario', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      }),
  },

  runs: {
    myList: () => request<any[]>('/runs/me'),
    create: async (file: File, authStateId?: string | null) => {
      const fd = new FormData()
      fd.set('scenario', file)
      if (authStateId) fd.set('auth_state_id', authStateId)
      return request<any>('/runs', { method: 'POST', body: fd })
    },
    delete: (runId: string) =>
      request<any>(`/runs/${encodeURIComponent(runId)}`, {
        method: 'DELETE',
      }),
    artifacts: (runId: string) => request<any[]>(`/runs/${encodeURIComponent(runId)}/artifacts`),
    reportUrl: (runId: string) => `/runs/${encodeURIComponent(runId)}/report.pdf`,
  },

  teams: {
    myTeams: () => request<{ id: string; name: string }[]>('/teams/me'),
    create: (name: string) =>
      request<{ id: string; name: string }>('/teams', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name }),
      }),
    members: (teamId: string) => request<any[]>(`/teams/${encodeURIComponent(teamId)}/members`),
    addMember: (teamId: string, userId: string, role: string) =>
      request<any>(`/teams/${encodeURIComponent(teamId)}/members`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ user_id: userId, role }),
      }),
    teamScenarios: (teamId: string) =>
      request<any[]>(`/teams/${encodeURIComponent(teamId)}/scenarios`),
    updateTeamScenario: (teamId: string, scenarioId: string, name: string) =>
      request<any>(`/teams/${encodeURIComponent(teamId)}/scenarios/${encodeURIComponent(scenarioId)}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name }),
      }),
    replaceTeamScenarioFile: async (teamId: string, scenarioId: string, file: File) => {
      const fd = new FormData()
      fd.set('scenario', file)
      return request<any>(`/teams/${encodeURIComponent(teamId)}/scenarios/${encodeURIComponent(scenarioId)}/file`, {
        method: 'PUT',
        body: fd,
      })
    },
    deleteTeamScenario: (teamId: string, scenarioId: string) =>
      request<any>(`/teams/${encodeURIComponent(teamId)}/scenarios/${encodeURIComponent(scenarioId)}`, {
        method: 'DELETE',
      }),

    apiKeys: (teamId: string) => request<any[]>(`/teams/${encodeURIComponent(teamId)}/api-keys`),
    createApiKey: (teamId: string, name: string) =>
      request<any>(`/teams/${encodeURIComponent(teamId)}/api-keys`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name }),
      }),
    revokeApiKey: (teamId: string, apiKeyId: string) =>
      request<any>(`/teams/${encodeURIComponent(teamId)}/api-keys/${encodeURIComponent(apiKeyId)}`, {
        method: 'DELETE',
      }),

    externalRequests: (teamId: string) =>
      request<any[]>(`/teams/${encodeURIComponent(teamId)}/integrations/external-requests`),
    webhookDeliveries: (teamId: string) =>
      request<any[]>(`/teams/${encodeURIComponent(teamId)}/integrations/webhook-deliveries`),
  },

  suiteRuns: {
    create: (payload: { team_id?: string | null; combinations: string[][]; auth_state_id?: string | null }) =>
      request<{ suite_run_id: string; status: string; case_ids: string[] }>('/suite-runs', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    myHistory: () => request<any[]>('/suite-runs/me'),
    get: (suiteRunId: string) => request<any>(`/suite-runs/${encodeURIComponent(suiteRunId)}`),
    cases: (suiteRunId: string) => request<any[]>(`/suite-runs/${encodeURIComponent(suiteRunId)}/cases`),
    teamHistory: (teamId: string) => request<any[]>(`/teams/${encodeURIComponent(teamId)}/suite-runs`),
    reportUrl: (suiteRunId: string) => `/suite-runs/${encodeURIComponent(suiteRunId)}/report.pdf`,
    delete: (suiteRunId: string) =>
      request<any>(`/suite-runs/${encodeURIComponent(suiteRunId)}`, {
        method: 'DELETE',
      }),
  },

  drafts: {
    list: () => request<any[]>('/drafts'),
    create: (payload: { name: string; team_id?: string | null; combinations: string[][] }) =>
      request<any>('/drafts', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    delete: (draftId: string) =>
      request<any>(`/drafts/${encodeURIComponent(draftId)}`, {
        method: 'DELETE',
      }),
  },

  authStates: {
    myList: () => request<any[]>('/auth-states/me'),
    upload: async (payload: { name: string; provider: string; file: File }) => {
      const fd = new FormData()
      fd.set('name', payload.name || '')
      fd.set('provider', payload.provider || 'google')
      fd.set('storage_state', payload.file)
      return request<any>('/auth-states', { method: 'POST', body: fd })
    },
    delete: (authStateId: string) =>
      request<any>(`/auth-states/${encodeURIComponent(authStateId)}`, { method: 'DELETE' }),
    b64: (authStateId: string) =>
      request<{ auth_state_id: string; b64: string }>(`/auth-states/${encodeURIComponent(authStateId)}/b64`, {
        method: 'POST',
      }),
    downloadUrl: (authStateId: string) => `/auth-states/${encodeURIComponent(authStateId)}/download`,
  },
}


