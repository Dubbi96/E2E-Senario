# Scenario Compiler 설계 문서

## 목표
Extension이 생성한 Raw Script를 Executable Scenario로 자동 변환하여 Docker/서버 환경에서도 안정적으로 실행되도록 보강

## 현재 구조 분석

### Extension이 저장하는 데이터 (Raw Event)
```typescript
{
  kind: "action" | "assert",
  type: "click" | "input" | "navigate" | "assert_text" | "assert_visible" | "assert_url",
  selector: string,  // CSS selector (단일)
  url?: string,
  text?: string,
  value?: string,
  delay?: number,
  frame?: { href: string, name: string, isTop: boolean },
  id?: string,
  ts?: number
}
```

### 문제점
1. **Selector 단일화**: 하나의 selector만 저장 (nth-of-type 등 취약한 selector)
2. **의미 정보 부족**: 요소의 textContent, role, aria-label 등이 selector에만 의존
3. **결과 관측 없음**: 클릭 후 모달/URL 변경/popup 생성 등을 기록하지 않음
4. **대기 로직 부족**: 클릭 후 자동 대기(wait)가 없음

## 설계: Scenario Compiler

### Phase 1: Extension 데이터 보강 (최우선)

Extension이 더 많은 메타데이터를 저장하도록 수정:

```typescript
// Enhanced RecordingEvent
{
  // 기존 필드
  kind: "action" | "assert",
  type: "click" | "input" | "navigate" | ...,
  selector: string,
  
  // 추가 필드 (Phase 1)
  element_meta: {
    tagName: string,
    id: string | null,
    className: string | null,
    textContent: string | null,
    innerText: string | null,
    role: string | null,
    ariaLabel: string | null,
    ariaDescribedBy: string | null,
    href: string | null,
    name: string | null,
    dataTestId: string | null,
    boundingBox: { x: number, y: number, width: number, height: number } | null
  },
  
  // Selector 후보군
  selector_candidates: string[],  // [data-testid, id, role+aria, ...]
  
  // 클릭 후 관측 (클릭 이벤트의 경우)
  outcome: {
    url_changed: boolean,
    popup_opened: boolean,
    modal_detected: boolean,
    iframe_added: boolean,
    network_requests: string[]  // 주요 API 호출
  } | null
}
```

### Phase 2: Scenario Compiler 구현

#### 2.1 Selector 보강 (Multi-selector)

```python
def enrich_selectors(raw_event: RecordingEvent) -> list[str]:
    """
    요소 메타데이터를 기반으로 selector 후보군 생성
    우선순위:
    1. data-testid
    2. id (unique)
    3. role + aria-label
    4. name (input)
    5. aria-label alone
    6. text-based locator
    7. CSS path (fallback)
    """
    candidates = []
    meta = raw_event.element_meta
    
    if meta.dataTestId:
        candidates.append(f'[data-testid="{meta.dataTestId}"]')
    
    if meta.id:
        candidates.append(f'#{meta.id}')
    
    if meta.role and meta.ariaLabel:
        candidates.append(f'[role="{meta.role}"][aria-label="{meta.ariaLabel}"]')
    
    if meta.name:
        candidates.append(f'{meta.tagName}[name="{meta.name}"]')
    
    if meta.ariaLabel:
        candidates.append(f'{meta.tagName}[aria-label="{meta.ariaLabel}"]')
    
    # Text-based (가장 안정적)
    if meta.textContent:
        # "로그인 하세요!" 같은 텍스트로 찾기
        candidates.append(f'text="{meta.textContent[:50]}"')
    
    # 기존 selector는 fallback으로
    if raw_event.selector:
        candidates.append(raw_event.selector)
    
    return candidates
```

#### 2.2 Action Outcome 추론 및 Wait 자동 삽입

```python
def infer_outcome_and_add_waits(
    events: list[RecordingEvent],
    current_index: int
) -> list[dict[str, Any]]:
    """
    클릭 액션 직후 결과를 관측하여 자동으로 wait step 추가
    """
    current = events[current_index]
    if current.type != "click":
        return []
    
    waits = []
    outcome = current.outcome
    
    # 모달/드롭다운 감지
    if outcome and outcome.modal_detected:
        # 다음 expect_text step의 텍스트로 wait_visible 추가
        next_text = find_next_text_assertion(events, current_index)
        if next_text:
            waits.append({
                "type": "wait_visible",
                "text": next_text,
                "timeout": 15000
            })
    
    # URL 변경 감지
    if outcome and outcome.url_changed:
        next_url = find_next_url(events, current_index)
        if next_url:
            waits.append({
                "type": "wait_url",
                "url": next_url,
                "timeout": 15000
            })
    
    # Popup 감지
    if outcome and outcome.popup_opened:
        waits.append({
            "type": "wait_popup",
            "timeout": 10000
        })
    
    return waits
```

#### 2.3 Success Conditions 자동 부여

```python
def add_success_conditions(step: dict[str, Any], raw_event: RecordingEvent) -> dict[str, Any]:
    """
    액션의 성공 조건을 OR 조건으로 추가
    예: 로그인 버튼 클릭 → 모달 OR URL 변경 OR popup 모두 성공 조건
    """
    if step["type"] != "click":
        return step
    
    outcome = raw_event.outcome
    if not outcome:
        return step
    
    success_conditions = []
    
    # 모달이 뜨면 성공
    if outcome.modal_detected:
        success_conditions.append({
            "type": "modal_visible",
            "timeout": 15000
        })
    
    # URL이 변경되면 성공
    if outcome.url_changed:
        success_conditions.append({
            "type": "url_changed",
            "timeout": 15000
        })
    
    # Popup이 열리면 성공
    if outcome.popup_opened:
        success_conditions.append({
            "type": "popup_opened",
            "timeout": 10000
        })
    
    if success_conditions:
        step["success_conditions"] = success_conditions
    
    return step
```

### Phase 3: Executable Scenario v2 스키마

```json
{
  "base_url": "https://hogak.live",
  "steps": [
    {
      "type": "click",
      "selectors": [
        "[data-testid='login-btn']",
        "#btnUser",
        "button[aria-label='로그인']",
        "text='로그인'",
        "div.btn_user"
      ],
      "success_conditions": [
        {"type": "modal_visible", "text": "로그인 하세요!", "timeout": 15000},
        {"type": "url_changed", "url": "https://hogak.live/login", "timeout": 15000}
      ],
      "auto_retry": {
        "max_attempts": 3,
        "fallback_strategies": ["text_locator", "role_locator", "js_click"]
      },
      "frame": {"href": "...", "isTop": true}
    },
    {
      "type": "wait_visible",
      "selectors": [
        "text='로그인 하세요!'",
        "div.info-top.flex > div:nth-of-type(1)",
        "[role='dialog']"
      ],
      "timeout": 15000
    }
  ]
}
```

## 구현 계획

### Step 1: Extension 보강 (content.js 수정)
- `onClick` 함수에서 요소 메타데이터 수집
- 클릭 후 결과 관측 (MutationObserver, URL 변경 감지)
- Selector 후보군 생성

### Step 2: RecordingEvent 스키마 확장 (recordings.py)
- `element_meta` 필드 추가
- `selector_candidates` 필드 추가
- `outcome` 필드 추가

### Step 3: Scenario Compiler 모듈 생성
- `app/runner/scenario_compiler.py` 생성
- `compile_raw_to_executable()` 함수 구현

### Step 4: Runner Auto-heal 강화
- 클릭 실패 시 fallback 전략 적용
- Success conditions OR 처리

## 우선순위

1. **즉시 구현 가능**: Scenario Compiler (서버 측만 수정)
   - 기존 selector를 기반으로 후보군 생성
   - 텍스트 기반 locator 추가
   - Wait 자동 삽입

2. **Extension 보강**: 다음 단계
   - 더 많은 메타데이터 수집
   - Outcome 관측

3. **Runner Auto-heal**: 병행 가능
   - Fallback 전략 구현
   - Success conditions OR 처리

