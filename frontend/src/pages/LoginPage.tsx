import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { setAccessToken } from '../lib/auth'
import { ButtonLink } from '../components/ButtonLink'

export function LoginPage() {
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const submit = () => {
    if (m.isPending) return
    m.mutate()
  }

  const m = useMutation({
    mutationFn: async () => {
      const tok = await api.auth.token(email, password)
      setAccessToken(tok.access_token)
      await api.auth.me()
    },
    onSuccess: () => nav('/'),
  })

  const err = m.error as ApiError | null

  return (
    <div className="centerPage">
      <div className="authCard">
        <h2 style={{ marginTop: 0 }}>로그인</h2>
        <p style={{ color: '#6b7280' }}>
          백엔드 `POST /auth/token`(OAuth2)로 로그인합니다.
        </p>

        <div style={{ display: 'grid', gap: 8 }}>
          <label>
            이메일
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submit()
              }}
              style={{ width: '100%' }}
            />
          </label>
          <label>
            비밀번호
            <input
              value={password}
              type="password"
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submit()
              }}
              style={{ width: '100%' }}
            />
          </label>
          <button disabled={m.isPending} onClick={submit}>
            {m.isPending ? '로그인 중...' : '로그인'}
          </button>
          {err ? <div style={{ color: 'crimson' }}>에러: {String(err.detail ?? err.message)}</div> : null}
        </div>

        <div style={{ marginTop: 12 }}>
          계정이 없나요? <ButtonLink to="/register">회원가입</ButtonLink>
        </div>
      </div>
    </div>
  )
}


