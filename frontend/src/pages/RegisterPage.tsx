import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { ButtonLink } from '../components/ButtonLink'

export function RegisterPage() {
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [clientError, setClientError] = useState<string | null>(null)
  const submit = () => {
    if (m.isPending) return
    m.mutate()
  }

  const m = useMutation({
    mutationFn: async () => {
      setClientError(null)
      if (password.length < 12) {
        setClientError('비밀번호는 최소 12자 이상이어야 합니다.')
        throw new Error('client_validation')
      }
      if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
        setClientError('비밀번호는 영문과 숫자를 각각 1개 이상 포함해야 합니다.')
        throw new Error('client_validation')
      }
      return api.auth.register(email, password)
    },
    onSuccess: () => nav('/login'),
  })

  const err = m.error as ApiError | null

  return (
    <div className="centerPage">
      <div className="authCard">
        <h2 style={{ marginTop: 0 }}>회원가입</h2>
        <p style={{ color: '#6b7280' }}>
          백엔드 `POST /auth/register`로 계정을 생성합니다. (비밀번호: 최소 12자 + 영문/숫자 포함)
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
            {m.isPending ? '생성 중...' : '계정 생성'}
          </button>
          {clientError ? <div style={{ color: 'crimson' }}>{clientError}</div> : null}
          {err ? <div style={{ color: 'crimson' }}>에러: {String(err.detail ?? err.message)}</div> : null}
        </div>
        <div style={{ marginTop: 12 }}>
          이미 계정이 있나요? <ButtonLink to="/login">로그인</ButtonLink>
        </div>
      </div>
    </div>
  )
}


