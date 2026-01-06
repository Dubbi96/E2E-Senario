import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ButtonLink } from '../components/ButtonLink'
import { getAccessToken } from '../lib/auth'
import { api } from '../lib/api'

function envStr(key: string, fallback: string) {
  const v = (import.meta as any)?.env?.[key]
  return (typeof v === 'string' && v.trim()) ? v.trim() : fallback
}

export function LandingPage() {
  const loggedIn = Boolean(getAccessToken())
  const serviceName = envStr('VITE_SERVICE_NAME', 'Dubbi E2E')
  const contactEmail = envStr('VITE_CONTACT_EMAIL', 'yrs03001@hanyang.ac.kr')

  const consoleHref = useMemo(() => (loggedIn ? '/dashboard' : '/login'), [loggedIn])

  const me = useQuery({
    queryKey: ['me'],
    queryFn: api.auth.me,
    enabled: loggedIn,
    staleTime: 30_000,
  })

  return (
    <div className="landing">
      <header className="landingTop">
        <div className="landingBrand">
          <div className="landingLogo">{serviceName}</div>
          <div className="landingTag">E2E 테스트 자동화 · 조합 실행 · CI/CD 연동</div>
        </div>
        <div className="landingActions">
          {loggedIn ? (
            <ButtonLink to="/dashboard" variant="primary">
              콘솔 열기
            </ButtonLink>
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

      <main className="landingMain">
        <section className="hero">
          <div className="heroLeft">
            <div className="heroBadge">AWS Activate Founders · Landing</div>
            <h1 className="heroTitle">{serviceName}</h1>
            <p className="heroDesc">
              팀/개인 시나리오를 업로드하고, 선택/조합 기반으로 순차 실행한 뒤, PDF 리포트/웹훅으로 결과를 받아
              배포 게이트로 사용할 수 있는 E2E 실행 서비스입니다.
            </p>
            <div className="heroCtas">
              <ButtonLink to={consoleHref} variant="primary">
                {loggedIn ? '대시보드로 이동' : '로그인하고 시작하기'}
              </ButtonLink>
              <ButtonLink to="/recorder/install">Web Recorder 설치</ButtonLink>
            </div>
            <div className="heroMeta">
              {loggedIn ? (
                <div className="heroMetaItem">
                  <div className="k">내 계정</div>
                  <div className="v mono">
                    {me.isLoading ? '로딩 중...' : (me.data?.email || me.data?.id || '-')}
                  </div>
                </div>
              ) : (
                <div className="heroMetaItem">
                  <div className="k">담당자 이메일</div>
                  <div className="v mono">{contactEmail}</div>
                </div>
              )}
              <div className="heroMetaItem">
                <div className="k">서비스</div>
                <div className="v">{serviceName}</div>
              </div>
            </div>
          </div>

          <div className="heroRight">
            <div className="featureGrid">
              <div className="featureCard">
                <div className="t">조합 실행(Suite)</div>
                <div className="d">선택된 조합이 모두 PASS일 때만 전체 성공으로 판정</div>
              </div>
              <div className="featureCard">
                <div className="t">상세 PDF 리포트</div>
                <div className="d">스텝별 결과/스크린샷/아티팩트 썸네일까지 한 번에</div>
              </div>
              <div className="featureCard">
                <div className="t">Public API + Webhook</div>
                <div className="d">API Key로 비동기 실행 → 폴링/콜백으로 CI/CD에 쉽게 연동</div>
              </div>
              <div className="featureCard">
                <div className="t">Web Recorder</div>
                <div className="d">브라우징하며 액션/검증 포인트를 기록해 시나리오 생성</div>
              </div>
            </div>
          </div>
        </section>

        <section className="landingSection">
          <h2>최소 리소스 운영(권장)</h2>
          <div className="landingPanel">
            <ul className="bullets">
              <li>
                <b>프론트</b>: 정적 호스팅(S3 + CloudFront) 또는 단일 컨테이너로 제공 가능
              </li>
              <li>
                <b>백엔드</b>: FastAPI + Celery(워커) + Redis + Postgres
              </li>
              <li>
                <b>실행</b>: 워커 수를 최소로(예: 1~2) 두고 필요 시 오토스케일
              </li>
            </ul>
          </div>
        </section>

        <section className="landingSection">
          <h2>바로가기</h2>
          <div className="landingPanel linksRow">
            <ButtonLink to={consoleHref} variant="primary">
              콘솔
            </ButtonLink>
            <ButtonLink to="/teams">팀</ButtonLink>
            <ButtonLink to="/suite-runs">조합 실행</ButtonLink>
            <ButtonLink to="/scenarios">내 시나리오</ButtonLink>
          </div>
          {!loggedIn ? <div className="muted" style={{ marginTop: 10 }}>콘솔 기능은 로그인 후 이용 가능합니다.</div> : null}
        </section>
      </main>

      <footer className="landingFooter">
        <div className="muted">
          © {new Date().getFullYear()} {serviceName} · Contact: <span className="mono">{contactEmail}</span>
        </div>
      </footer>
    </div>
  )
}


