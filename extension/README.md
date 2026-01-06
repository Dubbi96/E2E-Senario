## Dubbi E2E Recorder (Chrome Extension) - MVP

### 목표
- 브라우저에서 사용자가 수행한 액션(click/input/navigate)을 기록
- 사용자가 지정한 검증 포인트 3종을 기록
  - `expect_text`
  - `expect_visible`
  - `expect_url`
- 녹화 종료 후, 백엔드 `/recordings/to-scenario`로 업로드하여 **개인 시나리오(JSON)** 생성
- 생성된 시나리오는 FE `/scenarios/:id` 에디터에서 수정 가능

### data-testid란?
웹앱의 요소에 안정적인 식별자를 넣는 속성입니다.

예:

```html
<button data-testid="login-submit">로그인</button>
```

Recorder는 셀렉터를 만들 때 `data-testid`가 있으면 최우선으로:

```css
[data-testid="login-submit"]
```

을 사용합니다. (DOM 구조 변화에 덜 깨짐)

### 설치(개발용)
1) Chrome → `chrome://extensions`
2) 우측 상단 “개발자 모드” ON
3) “압축해제된 확장 프로그램을 로드” → `extension/` 폴더 선택

### 사용 흐름(MVP)
1) 확장 팝업에서 API Base URL(예: `http://localhost:8000`)과 JWT 토큰을 입력
2) “녹화 시작” → 클릭/입력/이동 기록
3) “검증 추가” → 타입 선택 후 요소를 클릭(텍스트/보이는지/URL)
4) “녹화 종료”
5) “서버로 업로드(개인 시나리오 생성)”

### Hogak 로그인(Apple/Google) 우회용: storageState Export (원클릭)
Hogak은 Apple 로그인 팝업/2차인증 때문에 headless 서버에서 로그인 재현이 어렵습니다.
이 확장은 확장 권한으로 **쿠키(HttpOnly 포함)+localStorage/sessionStorage**를 수집하여
Playwright `storageState` 포맷(JSON)을 생성할 수 있습니다.

1) Hogak 사이트에서 Google 테스트 계정으로 로그인 완료
2) 로그인된 Hogak 탭을 활성화
3) 확장 팝업 → **“Hogak 로그인 세션(storageState) Export”**
   - “다운로드(.json)”: `*.storage_state.json` 파일 다운로드
   - “Export + 서버 업로드”: Dubbi 서버(`/auth-states`)로 바로 업로드 (JWT 토큰 필요)

> 참고: 웹 페이지 JS에서 storageState를 “원클릭”으로 뽑는 건 HttpOnly 쿠키/SOP 때문에 불가능합니다.
> 확장 프로그램/Playwright 같은 “브라우저 권한 레벨”이 필요합니다.

### 기록이 안 될 때 체크리스트
- `chrome://extensions`에서 확장을 **새로고침(↻)** 한 뒤 다시 시도
- 일부 페이지는 확장 주입이 금지됩니다:
  - `chrome://...`
  - Chrome Web Store
  - 내장 PDF 뷰어 등
- 정상적으로 녹화가 켜지면 페이지 우상단에 **`● REC` 배지**가 표시됩니다.

### 팝업 닫으면 데이터가 사라지나요?
아니요. MVP는 `chrome.storage.local`에 저장하므로 팝업을 닫았다 다시 열어도 이벤트/설정이 유지됩니다.


