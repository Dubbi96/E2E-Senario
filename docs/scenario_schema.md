# 시나리오 스키마 가이드

수동으로 작성한 시나리오가 runner에서 안정적으로 실행될 수 있도록 하는 가이드입니다.

## 기본 구조

```json
{
  "base_url": "https://example.com",
  "requires_auth": false,
  "storage_state_path": "./storage_state.json",
  "steps": [
    {
      "type": "go",
      "url": "https://example.com"
    }
  ]
}
```

### 필수 필드

- `steps`: 배열 (최소 1개 이상의 step 필요)

### 선택 필드

- `base_url`: 문자열 (http:// 또는 https://로 시작)
- `requires_auth`: boolean (로그인 세션 필요 여부. true면 storageState 주입 권장/필수)
- `storage_state_path`: 문자열 (Playwright storageState JSON 파일 경로. 시나리오 파일 기준 상대경로 가능)

## Step 타입

### 1. go - 페이지 이동

```json
{
  "type": "go",
  "url": "https://example.com"
}
```

**필수 필드:**
- `url`: 문자열 (비어있지 않아야 함)

**선택 필드:**
- `delay_ms`: 숫자 (밀리초 단위 대기 시간)

---

### 2. click - 요소 클릭

```json
{
  "type": "click",
  "selector": "#submit-button"
}
```

또는 여러 selector 후보:

```json
{
  "type": "click",
  "selectors": [
    "[data-testid='submit']",
    "#submit-button",
    "button[type='submit']"
  ]
}
```

**필수 필드 (둘 중 하나):**
- `selector`: 문자열
- `selectors`: 문자열 배열 (비어있지 않아야 함)

**선택 필드:**
- `delay_ms`: 숫자 (기본값: 1500ms, click은 200ms 추가되어 1700ms)
- `frame`: 객체 (iframe 내부 클릭 시)

**권장 사항:**
- `selectors` 배열을 사용하여 여러 후보를 제공하면 안정성이 향상됩니다.
- `data-testid` 속성을 사용한 selector가 가장 안정적입니다.

---

### 3. fill - 입력 필드에 값 입력

```json
{
  "type": "fill",
  "selector": "#email",
  "value": "user@example.com"
}
```

**필수 필드:**
- `selector`: 문자열
- `value`: 문자열

**선택 필드:**
- `delay_ms`: 숫자
- `frame`: 객체 (iframe 내부 입력 시)

---

### 4. expect_text - 텍스트 검증

```json
{
  "type": "expect_text",
  "text": "Welcome",
  "selector": "h1"
}
```

또는 텍스트만으로 검증 (가장 안정적):

```json
{
  "type": "expect_text",
  "text": "Welcome"
}
```

**필수 필드:**
- `text`: 문자열

**선택 필드:**
- `selector`: 문자열
- `selectors`: 문자열 배열
- `frame`: 객체

**권장 사항:**
- `text`만 사용하면 DOM 구조 변화에 더 안정적입니다.
- `selector`와 함께 사용하면 더 정확한 검증이 가능합니다.

---

### 5. expect_visible - 요소 존재 검증

```json
{
  "type": "expect_visible",
  "selector": ".modal"
}
```

**필수 필드:**
- `selector`: 문자열

**선택 필드:**
- `frame`: 객체

---

### 6. expect_url - URL 검증

```json
{
  "type": "expect_url",
  "url": "https://example.com/dashboard"
}
```

**필수 필드:**
- `url`: 문자열

---

### 7. wait_visible - 요소가 나타날 때까지 대기

```json
{
  "type": "wait_visible",
  "selector": ".modal",
  "timeout": 5000
}
```

또는 텍스트 기반 (가장 안정적):

```json
{
  "type": "wait_visible",
  "text": "로그인 하세요!",
  "timeout": 15000
}
```

또는 role 기반:

```json
{
  "type": "wait_visible",
  "role": "button",
  "timeout": 5000
}
```

**필수 필드 (하나 이상):**
- `selector`: 문자열
- `selectors`: 문자열 배열
- `text`: 문자열
- `role`: 문자열

**선택 필드:**
- `timeout`: 숫자 (밀리초, 기본값: 15000)
- `frame`: 객체

**권장 사항:**
- `text` 기반이 가장 안정적입니다 (DOM 구조 변화에 강함).
- 모달이나 드롭다운이 나타날 때까지 대기할 때 사용합니다.

---

### 8. wait_url - URL 변경 대기

```json
{
  "type": "wait_url",
  "url": "https://example.com/dashboard",
  "timeout": 15000
}
```

또는 prefix 매칭:

```json
{
  "type": "wait_url",
  "url": "https://example.com/dashboard*",
  "timeout": 15000
}
```

**필수 필드:**
- `url`: 문자열

**선택 필드:**
- `timeout`: 숫자 (밀리초, 기본값: 15000)

---

### 9. screenshot - 스크린샷 촬영

```json
{
  "type": "screenshot",
  "name": "final"
}
```

**선택 필드:**
- `name`: 문자열 (기본값: "shot")

---

### 10. ensure_logged_in - 로그인 상태 확인(로그인 우회용)

Apple 로그인(팝업/2차인증)으로 headless에서 로그인 진행이 어려운 경우,
**사전에 캡처한 Playwright storageState를 주입**하고, 이 step으로 로그인 상태를 보장합니다.

```json
{
  "type": "ensure_logged_in",
  "selector": "#btnUser",
  "logged_out_text": "로그인"
}
```

**선택 필드:**
- `selector` 또는 `selectors`: 로그인 버튼/영역 selector (기본값: `#btnUser`)
- `logged_out_text`: 로그아웃 상태를 나타내는 텍스트 (기본값: `"로그인"`)
- `frame`: 객체

---

### 11. ensure_logged_out - 로그아웃 상태 확인

```json
{
  "type": "ensure_logged_out",
  "selector": "#btnUser",
  "logged_out_text": "로그인"
}
```

---

## 로그인(Apple 등) 우회: storageState 주입

런타임에 Apple 로그인 팝업/2차인증을 수행하지 않기 위해,
Playwright의 `storageState`를 주입할 수 있습니다.

- 환경변수:
  - `E2E_STORAGE_STATE_PATH`: storageState JSON 파일 경로
  - `E2E_STORAGE_STATE_B64`: storageState JSON 파일 내용을 base64로 인코딩한 값 (CI/Secret 주입용)

시나리오 파일에 `requires_auth: true`가 설정되어 있고 storageState가 없으면,
테스트는 즉시 실패하며 주입 방법을 안내합니다.

## 공통 필드

모든 step에서 사용 가능한 필드:

- `delay_ms`: 숫자 (0 이상, step 실행 후 대기 시간)
- `delay`: 숫자 (0 이상, `delay_ms`와 동일)
- `frame`: 객체 (iframe 내부 실행 시)

## 시나리오 작성 가이드

### 1. 안정적인 Selector 사용

**권장:**
- `data-testid` 속성 사용
- `id` 속성 사용 (고유한 경우)
- `role` + `aria-label` 조합

**비권장:**
- `:nth-of-type()` 사용 (DOM 구조 변화에 취약)
- 복잡한 CSS 경로

### 2. wait_visible 활용

동적으로 나타나는 요소(모달, 드롭다운)는 `wait_visible`로 대기:

```json
{
  "type": "click",
  "selector": "#open-modal"
},
{
  "type": "wait_visible",
  "text": "모달 제목",
  "timeout": 15000
},
{
  "type": "click",
  "selector": "#modal-submit"
}
```

### 3. 텍스트 기반 검증

`expect_text`에서 `text`만 사용하면 DOM 구조 변화에 강함:

```json
{
  "type": "expect_text",
  "text": "로그인 성공"
}
```

### 4. 여러 Selector 후보 제공

`selectors` 배열을 사용하여 fallback 제공:

```json
{
  "type": "click",
  "selectors": [
    "[data-testid='submit']",
    "#submit-button",
    "button:has-text('Submit')"
  ]
}
```

### 5. 적절한 delay 사용

- `click` 후: 기본 1700ms (자동 적용)
- `fill` 후: 필요시 500ms 정도
- `go` 후: 필요시 2000ms 정도

## 완전한 예시

```json
{
  "base_url": "https://example.com",
  "steps": [
    {
      "type": "go",
      "url": "https://example.com/login"
    },
    {
      "type": "wait_visible",
      "selector": "#email",
      "timeout": 5000
    },
    {
      "type": "fill",
      "selector": "#email",
      "value": "user@example.com",
      "delay_ms": 500
    },
    {
      "type": "fill",
      "selector": "#password",
      "value": "password123",
      "delay_ms": 500
    },
    {
      "type": "click",
      "selectors": [
        "[data-testid='login-button']",
        "button[type='submit']"
      ]
    },
    {
      "type": "wait_url",
      "url": "https://example.com/dashboard*",
      "timeout": 15000
    },
    {
      "type": "expect_text",
      "text": "Welcome",
      "selector": "h1"
    },
    {
      "type": "screenshot",
      "name": "dashboard"
    }
  ]
}
```

## 검증 규칙

시나리오는 저장/업로드 시 자동으로 검증됩니다:

1. 기본 구조 검증 (steps 필수, 배열 여부)
2. 각 step의 필수 필드 검증
3. 타입 검증 (문자열, 숫자, 배열 등)
4. URL 형식 검증

검증 실패 시 저장/업로드가 거부되며 에러 메시지가 표시됩니다.

