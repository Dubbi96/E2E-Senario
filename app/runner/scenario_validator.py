"""
시나리오 검증 규칙

수동으로 작성한 시나리오가 runner에서 안정적으로 실행될 수 있도록
엄격한 검증 규칙을 적용합니다.
"""

from typing import Any, Dict, List, Tuple


class ScenarioValidationError(Exception):
    """시나리오 검증 실패 시 발생하는 예외"""
    pass


def validate_scenario(scenario: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    시나리오를 검증하고 문제점 목록을 반환합니다.
    
    Args:
        scenario: 시나리오 딕셔너리
        
    Returns:
        (is_valid, errors): 검증 통과 여부와 에러 메시지 목록
    """
    errors: List[str] = []
    
    # 1. 기본 구조 검증
    if not isinstance(scenario, dict):
        errors.append("시나리오는 객체(JSON object)여야 합니다.")
        return False, errors
    
    # 2. base_url 검증 (선택적이지만 있으면 유효한 URL이어야 함)
    base_url = scenario.get("base_url", "")
    if base_url:
        if not isinstance(base_url, str):
            errors.append("base_url은 문자열이어야 합니다.")
        elif not (base_url.startswith("http://") or base_url.startswith("https://")):
            errors.append("base_url은 http:// 또는 https://로 시작해야 합니다.")
    
    # 3. steps 검증 (필수)
    steps = scenario.get("steps")
    if not steps:
        errors.append("steps 필드는 필수이며 비어있을 수 없습니다.")
        return False, errors
    
    if not isinstance(steps, list):
        errors.append("steps는 배열이어야 합니다.")
        return False, errors
    
    if len(steps) == 0:
        errors.append("steps는 최소 1개 이상의 step을 포함해야 합니다.")
        return False, errors
    
    # 4. 각 step 검증
    for i, step in enumerate(steps, start=1):
        step_errors = validate_step(step, i)
        errors.extend(step_errors)
    
    return len(errors) == 0, errors


def validate_step(step: Dict[str, Any], step_index: int) -> List[str]:
    """
    개별 step을 검증합니다.
    
    Args:
        step: step 딕셔너리
        step_index: step 인덱스 (에러 메시지용)
        
    Returns:
        에러 메시지 목록
    """
    errors: List[str] = []
    
    if not isinstance(step, dict):
        errors.append(f"Step {step_index}: step은 객체여야 합니다.")
        return errors
    
    step_type = step.get("type")
    if not step_type:
        errors.append(f"Step {step_index}: 'type' 필드는 필수입니다.")
        return errors
    
    if not isinstance(step_type, str):
        errors.append(f"Step {step_index}: 'type'은 문자열이어야 합니다.")
        return errors
    
    # Step 타입별 검증
    if step_type == "go":
        if "url" not in step:
            errors.append(f"Step {step_index} (go): 'url' 필드는 필수입니다.")
        elif not isinstance(step["url"], str) or not step["url"].strip():
            errors.append(f"Step {step_index} (go): 'url'은 비어있지 않은 문자열이어야 합니다.")
    
    elif step_type == "click":
        # selector 또는 selectors 중 하나는 필수
        selector = step.get("selector")
        selectors = step.get("selectors")
        
        if not selector and not selectors:
            errors.append(f"Step {step_index} (click): 'selector' 또는 'selectors' 필드 중 하나는 필수입니다.")
        elif selector and not isinstance(selector, str):
            errors.append(f"Step {step_index} (click): 'selector'는 문자열이어야 합니다.")
        elif selectors and not isinstance(selectors, list):
            errors.append(f"Step {step_index} (click): 'selectors'는 배열이어야 합니다.")
        elif selectors and len(selectors) == 0:
            errors.append(f"Step {step_index} (click): 'selectors'는 비어있을 수 없습니다.")
        elif selectors:
            for j, sel in enumerate(selectors):
                if not isinstance(sel, str):
                    errors.append(f"Step {step_index} (click): 'selectors[{j}]'는 문자열이어야 합니다.")
    
    elif step_type == "fill":
        if "selector" not in step:
            errors.append(f"Step {step_index} (fill): 'selector' 필드는 필수입니다.")
        elif not isinstance(step["selector"], str):
            errors.append(f"Step {step_index} (fill): 'selector'는 문자열이어야 합니다.")
        
        if "value" not in step:
            errors.append(f"Step {step_index} (fill): 'value' 필드는 필수입니다.")
        elif not isinstance(step["value"], str):
            errors.append(f"Step {step_index} (fill): 'value'는 문자열이어야 합니다.")
    
    elif step_type == "expect_text":
        # text 필드는 필수
        text = step.get("text")
        if not text:
            errors.append(f"Step {step_index} (expect_text): 'text' 필드는 필수입니다.")
        elif not isinstance(text, str):
            errors.append(f"Step {step_index} (expect_text): 'text'는 문자열이어야 합니다.")
        
        # selector 또는 selectors는 선택적이지만, 있으면 유효해야 함
        selector = step.get("selector")
        selectors = step.get("selectors")
        if selector and not isinstance(selector, str):
            errors.append(f"Step {step_index} (expect_text): 'selector'는 문자열이어야 합니다.")
        if selectors and not isinstance(selectors, list):
            errors.append(f"Step {step_index} (expect_text): 'selectors'는 배열이어야 합니다.")
    
    elif step_type == "expect_visible":
        if "selector" not in step:
            errors.append(f"Step {step_index} (expect_visible): 'selector' 필드는 필수입니다.")
        elif not isinstance(step["selector"], str):
            errors.append(f"Step {step_index} (expect_visible): 'selector'는 문자열이어야 합니다.")
    
    elif step_type == "expect_url":
        if "url" not in step:
            errors.append(f"Step {step_index} (expect_url): 'url' 필드는 필수입니다.")
        elif not isinstance(step["url"], str):
            errors.append(f"Step {step_index} (expect_url): 'url'는 문자열이어야 합니다.")
    
    elif step_type == "wait_visible":
        # selector, selectors, text, role 중 하나는 필수
        selector = step.get("selector")
        selectors = step.get("selectors")
        text = step.get("text")
        role = step.get("role")
        
        if not selector and not selectors and not text and not role:
            errors.append(f"Step {step_index} (wait_visible): 'selector', 'selectors', 'text', 또는 'role' 중 하나는 필수입니다.")
        
        if selector and not isinstance(selector, str):
            errors.append(f"Step {step_index} (wait_visible): 'selector'는 문자열이어야 합니다.")
        if selectors and not isinstance(selectors, list):
            errors.append(f"Step {step_index} (wait_visible): 'selectors'는 배열이어야 합니다.")
        if text and not isinstance(text, str):
            errors.append(f"Step {step_index} (wait_visible): 'text'는 문자열이어야 합니다.")
        if role and not isinstance(role, str):
            errors.append(f"Step {step_index} (wait_visible): 'role'는 문자열이어야 합니다.")
    
    elif step_type == "wait_url":
        if "url" not in step:
            errors.append(f"Step {step_index} (wait_url): 'url' 필드는 필수입니다.")
        elif not isinstance(step["url"], str):
            errors.append(f"Step {step_index} (wait_url): 'url'는 문자열이어야 합니다.")
    
    elif step_type == "screenshot":
        # name은 선택적
        pass
    
    elif step_type in ("click_popup", "popup_go", "close_page", "switch_main"):
        # 이 타입들은 특별한 검증 필요 없음 (내부적으로 처리)
        pass
    
    else:
        errors.append(f"Step {step_index}: 알 수 없는 step 타입 '{step_type}'입니다. 지원되는 타입: go, click, fill, expect_text, expect_visible, expect_url, wait_visible, wait_url, screenshot")
    
    # 공통 필드 검증
    delay_ms = step.get("delay_ms")
    if delay_ms is not None:
        if not isinstance(delay_ms, (int, float)) or delay_ms < 0:
            errors.append(f"Step {step_index}: 'delay_ms'는 0 이상의 숫자여야 합니다.")
    
    delay = step.get("delay")
    if delay is not None:
        if not isinstance(delay, (int, float)) or delay < 0:
            errors.append(f"Step {step_index}: 'delay'는 0 이상의 숫자여야 합니다.")
    
    return errors


def get_scenario_schema_example() -> Dict[str, Any]:
    """
    검증된 시나리오 스키마 예시를 반환합니다.
    """
    return {
        "base_url": "https://example.com",
        "steps": [
            {
                "type": "go",
                "url": "https://example.com"
            },
            {
                "type": "wait_visible",
                "selector": "h1",
                "timeout": 5000
            },
            {
                "type": "expect_text",
                "text": "Example Domain",
                "selector": "h1"
            },
            {
                "type": "click",
                "selector": "a",
                "delay_ms": 1500
            },
            {
                "type": "fill",
                "selector": "#email",
                "value": "user@example.com",
                "delay_ms": 500
            },
            {
                "type": "screenshot",
                "name": "final"
            }
        ]
    }

