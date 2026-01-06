import { useEffect, useState } from 'react'
import { Link, Outlet, NavLink } from 'react-router-dom'
import { clearAccessToken, getAccessToken } from '../lib/auth'
import { ButtonLink } from './ButtonLink'

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) => `lnbLink ${isActive ? 'active' : ''}`}
    >
      {label}
    </NavLink>
  )
}

export function AppShell() {
  const loggedIn = Boolean(getAccessToken())
  const [navOpen, setNavOpen] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setNavOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="appShell">
      {/* GNB */}
      <header className="gnb">
        <button className="hamburger" onClick={() => setNavOpen((v) => !v)} aria-label="toggle navigation">
          ☰
        </button>
        <Link to="/" style={{ fontWeight: 800, textDecoration: 'none', color: 'var(--text)' }}>
          Dubbi E2E
        </Link>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center' }}>
          {loggedIn ? (
            <button
              onClick={() => {
                clearAccessToken()
                window.location.href = '/login'
              }}
            >
              로그아웃
            </button>
          ) : (
            <>
              <ButtonLink to="/login">로그인</ButtonLink>
              <ButtonLink to="/register" variant="primary">
                회원가입
              </ButtonLink>
            </>
          )}
        </div>
      </header>

      {/* LNB + content */}
      <div className="shell">
        <aside className={`lnb ${navOpen ? 'open' : ''}`} onClick={() => setNavOpen(false)}>
          <div className="lnbInner" onClick={(e) => e.stopPropagation()}>
            <div className="lnbTitle">NAVIGATION</div>
            <nav className="lnbNav">
              <NavItem to="/dashboard" label="대시보드" />
              <NavItem to="/scenarios" label="내 시나리오" />
              <NavItem to="/recorder" label="Web Recorder" />
              <NavItem to="/auth-states" label="인증 세션" />
              <NavItem to="/runs" label="단일 실행" />
              <NavItem to="/teams" label="팀" />
              <NavItem to="/suite-runs" label="조합 실행" />
            </nav>
          </div>
        </aside>

        <main className="content">
          <div className="contentInner">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}


