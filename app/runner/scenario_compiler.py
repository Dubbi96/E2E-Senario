"""
Scenario Compiler: Raw Script를 Executable Scenario로 변환

Extension이 생성한 Raw Script는 환경/렌더링/DOM 구조 변화에 취약합니다.
이 컴파일러는 Raw Script를 받아서 실행 가능한 형태로 보강합니다.

주요 기능:
1. Selector 후보군 생성 (multi-selector)
2. Wait 자동 삽입 (모달/URL 변경 대기)
3. 텍스트 기반 locator 추가
4. Success conditions 자동 부여
"""

from typing import Any, Dict, List


def _generate_selector_candidates(step: Dict[str, Any]) -> List[str]:
    """
    Selector 후보군 생성 (우선순위 재정의)
    
    우선순위:
    1. role/label/text 기반 (getByRole, getByLabel, getByText)
    2. id/class 기반 (짧고 고정적인 것)
    3. CSS path (최후)
    
    Extension이 role/text/aria 정보를 더 수집하도록 개선하면 더 안정적
    """
    candidates = []
    selector = step.get("selector")
    text = step.get("text")
    role = step.get("role")
    label = step.get("label")
    aria_label = step.get("aria_label")
    
    # 1순위: role/label/text 기반 (가장 안정적)
    if role:
        candidates.append(f'role={role}')
    if label:
        candidates.append(f'label={label}')
    if aria_label:
        candidates.append(f'[aria-label="{aria_label}"]')
    if text:
        # 텍스트 기반 locator (exact match 우선, contains는 나중)
        candidates.append(f'text="{text}"')
        candidates.append(f'text=/^{text}$/')  # exact match
    
    # 2순위: id/class 기반 (짧고 고정적인 것)
    if selector:
        # id 기반이면 우선순위 높임
        if selector.startswith("#") and len(selector.split()) == 1:
            candidates.append(selector)
        # class 기반이면 (짧은 경우만)
        elif selector.startswith(".") and len(selector.split()) == 1:
            candidates.append(selector)
        # data-* 속성 기반
        elif selector.startswith("[data-"):
            candidates.append(selector)
        # 기존 selector는 나중에 추가
        else:
            # 3순위: CSS path (nth-of-type 제거한 버전 시도)
            if ":nth-of-type" in selector:
                simplified = selector.replace(":nth-of-type(1)", "").replace(":nth-of-type(2)", "")
                if simplified != selector:
                    candidates.append(simplified)
            # 원본 selector는 최후에
            candidates.append(selector)
    
    # 중복 제거 (순서 유지)
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique_candidates.append(c)
    
    return unique_candidates


def _infer_wait_steps(
    steps: List[Dict[str, Any]],
    current_index: int
) -> List[Dict[str, Any]]:
    """
    현재 step 이후에 필요한 wait step을 추론
    """
    waits = []
    current = steps[current_index]
    current_type = current.get("type")
    
    if current_type != "click":
        return waits
    
    # Click 후 다음 step들을 확인
    if current_index + 1 >= len(steps):
        return waits
    
    next_step = steps[current_index + 1]
    next_type = next_step.get("type")
    
    # Click 후 다음 step이 expect_text인 경우 (모달/드롭다운)
    if next_type == "expect_text":
        next_text = next_step.get("text") or next_step.get("params", {}).get("text")
        if next_text:
            waits.append({
                "type": "wait_visible",
                "text": next_text,
                "timeout": 15000,
                "frame": next_step.get("frame")
            })
    
    # Click 후 다음 step이 다른 click인 경우 (모달 내 버튼)
    elif next_type == "click":
        # 이전 expect_text의 텍스트로 wait
        for i in range(current_index - 1, max(-1, current_index - 3), -1):
            prev_step = steps[i]
            if prev_step.get("type") == "expect_text":
                prev_text = prev_step.get("text") or prev_step.get("params", {}).get("text")
                if prev_text:
                    waits.append({
                        "type": "wait_visible",
                        "text": prev_text,
                        "timeout": 15000,
                        "frame": prev_step.get("frame")
                    })
                    break
    
    # Click 후 URL이 변경되는 경우 (리디렉션)
    # expect_url이나 go step이 있으면 wait_url 추가
    if next_type == "expect_url":
        url = next_step.get("url")
        if url:
            waits.append({
                "type": "wait_url",
                "url": url,
                "timeout": 15000
            })
    elif next_type == "go":
        url = next_step.get("url")
        if url:
            waits.append({
                "type": "wait_url",
                "url": url,
                "timeout": 15000
            })
    
    return waits


def _infer_success_conditions(
    steps: List[Dict[str, Any]],
    current_index: int
) -> List[Dict[str, Any]]:
    """
    Click step의 성공 조건을 추론 (OR 조건)
    모달이 뜨거나 URL이 변경되거나 popup이 열리는 것 중 하나를 만족하면 성공
    """
    conditions = []
    current = steps[current_index]
    
    if current.get("type") != "click":
        return conditions
    
    # 다음 step들을 확인하여 성공 조건 추론
    if current_index + 1 < len(steps):
        next_step = steps[current_index + 1]
        next_type = next_step.get("type")
        
        # 모달/드롭다운이 나타나는 경우
        if next_type == "expect_text":
            next_text = next_step.get("text") or next_step.get("params", {}).get("text")
            if next_text:
                conditions.append({
                    "type": "modal_visible",
                    "text": next_text,
                    "timeout": 15000
                })
        
        # URL이 변경되는 경우 (prefix 매칭 지원)
        if next_type == "expect_url":
            url = next_step.get("url")
            if url:
                # URL prefix 매칭을 위해 * 추가
                url_pattern = url if url.endswith("*") else f"{url}*"
                conditions.append({
                    "type": "url_changed",
                    "url": url_pattern,
                    "timeout": 15000
                })
        elif next_type == "go":
            url = next_step.get("url")
            if url:
                # URL prefix 매칭을 위해 * 추가
                url_pattern = url if url.endswith("*") else f"{url}*"
                conditions.append({
                    "type": "url_changed",
                    "url": url_pattern,
                    "timeout": 15000
                })
    
    return conditions


def compile_scenario(raw_scenario: Dict[str, Any]) -> Dict[str, Any]:
    """
    Raw Scenario를 Executable Scenario로 컴파일
    
    Args:
        raw_scenario: Extension이 생성한 원본 시나리오
            {
                "base_url": "...",
                "steps": [...],
                "_meta": {...}
            }
    
    Returns:
        컴파일된 Executable Scenario
    """
    compiled_steps: List[Dict[str, Any]] = []
    raw_steps = raw_scenario.get("steps", [])
    
    for i, raw_step in enumerate(raw_steps):
        step_type = raw_step.get("type")
        compiled_step: Dict[str, Any] = {}
        
        # 기본 필드 복사
        for key in ["type", "url", "value", "delay_ms", "delay", "frame", "popup_url"]:
            if key in raw_step:
                compiled_step[key] = raw_step[key]
        
        # Step 타입별 보강
        if step_type == "click":
            # Selector 후보군 생성 (우선순위 재정의: role/text 우선)
            selectors = _generate_selector_candidates(raw_step)
            
            # 다음 expect_text/wait_visible step의 정보를 활용
            next_text = None
            next_selector = None
            next_step_type = None
            skip_next = False
            
            if i + 1 < len(raw_steps):
                next_step = raw_steps[i + 1]
                next_step_type = next_step.get("type")
                if next_step_type in ("expect_text", "wait_visible"):
                    next_text = next_step.get("text") or next_step.get("params", {}).get("text")
                    next_selector = next_step.get("selector")
                    # 이 step을 success_condition으로 흡수할 예정
                    skip_next = True
            
            # 텍스트 기반 selector 추가 (다음 step의 텍스트 활용)
            if next_text and not any('text=' in s for s in selectors):
                # 텍스트 기반을 최우선으로
                selectors.insert(0, f'text="{next_text}"')
            
            if len(selectors) > 1:
                compiled_step["selectors"] = selectors
            elif selectors:
                compiled_step["selector"] = selectors[0]
            else:
                compiled_step["selector"] = raw_step.get("selector")
            
            # Success conditions 추가 (OR 조건)
            # click 다음 expect/wait를 success_conditions로 흡수
            success_conditions = _infer_success_conditions(raw_steps, i)
            
            # 다음 step이 expect_text/wait_visible이면 success_condition으로 흡수
            if skip_next and next_step_type:
                if next_step_type == "expect_text" and next_text:
                    # 모달/드롭다운이 나타나는 경우
                    success_conditions.append({
                        "type": "element_visible",
                        "text": next_text,
                        "timeout": 15000
                    })
                elif next_step_type == "wait_visible":
                    if next_text:
                        success_conditions.append({
                            "type": "element_visible",
                            "text": next_text,
                            "timeout": next_step.get("timeout", 15000)
                        })
                    elif next_selector:
                        success_conditions.append({
                            "type": "element_visible",
                            "selector": next_selector,
                            "timeout": next_step.get("timeout", 15000)
                        })
            
            if success_conditions:
                compiled_step["success_conditions"] = success_conditions
            
            # Click step 추가
            compiled_steps.append(compiled_step)
            
            # 다음 step을 건너뛰기 (success_condition으로 흡수했으므로)
            if skip_next:
                continue
        
        elif step_type == "expect_text":
            # 텍스트 기반 locator 우선 사용
            # params 안에 text가 있을 수도 있음
            text = raw_step.get("text") or raw_step.get("params", {}).get("text")
            selector = raw_step.get("selector")
            
            if text:
                # 텍스트를 최상위로 병합
                compiled_step["text"] = text
                if selector:
                    # Selector도 후보로 유지 (텍스트 우선)
                    compiled_step["selectors"] = [
                        f'text="{text}"',  # 텍스트 기반 우선
                        selector
                    ]
                else:
                    # Selector 없으면 텍스트만
                    pass
            else:
                compiled_step["selector"] = selector
        
        elif step_type == "wait_visible":
            # 이미 wait_visible이면 그대로 사용하되, selector 후보군 추가
            # params 안에 text가 있을 수도 있음
            selector = raw_step.get("selector")
            text = raw_step.get("text") or raw_step.get("params", {}).get("text")
            
            if text:
                # 텍스트를 최상위로 병합
                compiled_step["text"] = text
                # 텍스트 기반 selector도 추가
                if selector:
                    compiled_step["selectors"] = [
                        f'text="{text}"',  # 텍스트 우선
                        selector
                    ]
            elif selector:
                # Selector면 후보군 생성 (텍스트 기반 포함)
                selectors = _generate_selector_candidates(raw_step)
                if len(selectors) > 1:
                    compiled_step["selectors"] = selectors
                else:
                    compiled_step["selector"] = selector
            else:
                # Selector도 text도 없으면 에러
                raise ValueError(f"wait_visible step requires 'selector' or 'text' field: {raw_step}")
            
            if "timeout" in raw_step:
                compiled_step["timeout"] = raw_step["timeout"]
            else:
                compiled_step["timeout"] = 15000
        
        elif step_type in ("fill", "go", "expect_visible", "expect_url", "wait_url"):
            # 다른 타입은 그대로 복사
            pass
        
        else:
            # 알 수 없는 타입은 그대로 복사
            # params 안의 text를 최상위로 병합
            if "params" in raw_step and "text" in raw_step["params"]:
                compiled_step["text"] = raw_step["params"]["text"]
        
        compiled_steps.append(compiled_step)
    
    return {
        "base_url": raw_scenario.get("base_url", ""),
        "steps": compiled_steps,
        "_meta": {
            **raw_scenario.get("_meta", {}),
            "compiled": True,
            "compiler_version": "1.0.0"
        }
    }

