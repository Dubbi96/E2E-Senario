import { ButtonLink } from '../components/ButtonLink'

export function WebRecorderInstallPage() {
  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Web Recorder 설치 안내</h2>
        <div style={{ marginLeft: 'auto' }}>
          <ButtonLink to="/recorder">← Web Recorder</ButtonLink>
        </div>
      </div>

      <div style={{ color: 'var(--muted)' }}>
        현재 MVP는 Chrome Web Store 배포가 아니라 “압축해제 확장 로드” 방식입니다. (설치는 로그인 없이도 가능합니다)
      </div>

      <section style={{ border: '1px solid var(--border)', padding: 12, borderRadius: 10, background: 'var(--panel)' }}>
        <h3>설치 방법</h3>
        <ol style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 6 }}>
          <li>
            Chrome에서 <span className="mono">chrome://extensions</span> 접속
          </li>
          <li>우측 상단 “개발자 모드” ON</li>
          <li>
            “압축해제된 확장 프로그램을 로드” 클릭 후 프로젝트의 <span className="mono">extension/</span> 폴더 선택
          </li>
          <li>설치 후 이 페이지로 돌아와서 Web Recorder를 다시 시도</li>
        </ol>
      </section>

      <section style={{ border: '1px solid var(--border)', padding: 12, borderRadius: 10, background: 'var(--panel)' }}>
        <h3>정상 동작 확인</h3>
        <div style={{ color: 'var(--muted)' }}>
          녹화를 시작하면 대상 페이지 우상단에 <b>● REC</b> 배지가 뜹니다. 배지를 클릭하면 Stop/Upload 패널이 열립니다.
        </div>
        <div style={{ marginTop: 10, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <ButtonLink to="/login" variant="primary">
            로그인하고 Recorder 사용하기
          </ButtonLink>
          <ButtonLink to="/">랜딩으로</ButtonLink>
        </div>
      </section>
    </div>
  )
}


