"""
Action Transaction: 안정적인 액션 실행을 위한 트랜잭션 규격

각 click/fill 같은 액션은 다음 순서로 실행:
1. 사전 안정화 (DOMContentLoaded + idle, 요소 actionable 확인, scrollIntoView, hover)
2. 액션 수행 (다중 전략: normal click → force click → JS click)
3. 성공 판정 (success_conditions를 top page + 모든 frames + popup pages에서 평가)
4. 재시도 (조건 불충족 시 1~2회 재시도)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Tuple
from playwright.sync_api import Frame, Page, TimeoutError, expect

# #region agent log
def _write_debug_log(location: str, message: str, data: dict, hypothesis_id: str = None):
    """Write debug log in NDJSON format to .cursor/debug.log"""
    log_path = "/Users/gangjong-won/Dubbi/e2e-service/.cursor/debug.log"
    log_entry = {
        "timestamp": time.time() * 1000,
        "location": location,
        "message": message,
        "data": data,
        "sessionId": "debug-session",
        "hypothesisId": hypothesis_id,
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _check_dropdown_state(page: Page, expected_text: str) -> dict:
    """Check if dropdown text exists in DOM"""
    try:
        # Check if text exists anywhere in DOM
        text_count = page.get_by_text(expected_text, exact=False).count()
        
        # Check if visible
        is_visible = False
        if text_count > 0:
            try:
                is_visible = page.get_by_text(expected_text, exact=False).first.is_visible(timeout=100)
            except Exception:
                pass
        
        # Try to get element info
        element_info = {}
        if text_count > 0:
            try:
                locator = page.get_by_text(expected_text, exact=False).first
                element_info = {
                    "text_content": locator.text_content(timeout=100) or "",
                    "inner_html_preview": locator.evaluate("el => el.innerHTML", timeout=100)[:200] if hasattr(locator, 'evaluate') else "",
                }
            except Exception:
                pass
        
        return {
            "text_exists": text_count > 0,
            "text_count": text_count,
            "is_visible": is_visible,
            "element_info": element_info,
        }
    except Exception as e:
        return {"error": str(e)}
# #endregion


class ActionTransaction:
    """
    액션을 트랜잭션으로 실행하는 클래스.
    
    클릭이 성공했는지를 "UI 상태 변화"로 판정하고,
    실패 시 재시도 및 다중 전략을 시도합니다.
    """
    
    def __init__(
        self,
        page: Page,
        run_dir: str,
        step_index: int,
        step_type: str,
    ):
        self.page = page
        self.run_dir = run_dir
        self.step_index = step_index
        self.step_type = step_type
        self.context = page.context
    
    def _log_checkpoint(self, checkpoint_name: str, data: Dict[str, Any]) -> None:
        """디버그 체크포인트 로깅"""
        try:
            from app.runner.debug_utils import log_debug_checkpoint
            log_debug_checkpoint(
                self.run_dir,
                self.step_index,
                self.step_type,
                checkpoint_name,
                data,
            )
        except Exception:
            pass
    
    def _pre_stabilize(self, tgt: Page | Frame, selector: str) -> None:
        """
        1. 사전 안정화
        
        - DOMContentLoaded + 짧은 idle
        - 대상 요소가 actionable(visible/enabled/stable)인지 확인
        - 필요 시 scrollIntoView, hover 수행
        """
        # DOMContentLoaded 대기
        if isinstance(tgt, Page):
            try:
                tgt.wait_for_load_state("domcontentloaded", timeout=1500)
            except Exception:
                pass
            # 짧은 idle 대기
            try:
                tgt.wait_for_timeout(200)
            except Exception:
                pass
        else:
            try:
                tgt.page.wait_for_load_state("domcontentloaded", timeout=1500)
            except Exception:
                pass
            try:
                tgt.page.wait_for_timeout(200)
            except Exception:
                pass
        
        # 요소가 actionable인지 확인
        locator = tgt.locator(selector).first
        
        # 1. 요소가 attached인지 확인
        try:
            locator.wait_for(state="attached", timeout=5000)
        except Exception:
            raise ValueError(f"Element not found: {selector}")
        
        # 2. 요소가 visible인지 확인
        try:
            locator.wait_for(state="visible", timeout=5000)
        except Exception:
            raise ValueError(f"Element not visible: {selector}")
        
        # 3. 요소가 enabled인지 확인
        try:
            locator.evaluate("""
                el => {
                    if (!el) throw new Error('Element not found');
                    if (el.disabled || el.getAttribute('aria-disabled') === 'true') {
                        throw new Error('Element is disabled');
                    }
                    const style = window.getComputedStyle(el);
                    if (style.pointerEvents === 'none') {
                        throw new Error('Element has pointer-events: none');
                    }
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) {
                        throw new Error('Element has zero size');
                    }
                }
            """)
        except Exception as e:
            # React가 아직 렌더링 중일 수 있으므로 조금 더 대기
            try:
                if isinstance(tgt, Page):
                    tgt.wait_for_timeout(300)
                else:
                    tgt.page.wait_for_timeout(300)
                # 다시 확인
                locator.evaluate("""
                    el => {
                        if (el.disabled || el.getAttribute('aria-disabled') === 'true') {
                            throw new Error('Element is disabled');
                        }
                    }
                """)
            except Exception:
                raise ValueError(f"Element not actionable: {selector} - {str(e)}")
        
        # 4. scrollIntoView
        try:
            locator.scroll_into_view_if_needed()
        except Exception:
            pass
        
        # Note: hover는 _execute_click_multi_strategy에서 수행 (드롭다운/토글 UI를 위해)
    
    def _execute_click_multi_strategy(
        self,
        tgt: Page | Frame,
        selector: str,
    ) -> str:
        """
        2. 액션 수행 (다중 전략)
        
        핵심 원칙: Playwright native click을 1순위로, JS click은 마지막 fallback
        드롭다운/헤더 메뉴는 hover를 선행하면 통과율이 크게 올라감
        
        전략 순서:
        1. hover (드롭다운/토글 UI를 위해)
        2. native click (실제 마우스 이벤트)
        3. force click (오버레이/인터셉트 대응)
        4. 좌표 클릭 (DOM은 맞는데 클릭이 안 먹히는 경우)
        5. JS click + pointer 이벤트 (최후의 수단)
        """
        locator = tgt.locator(selector).first
        page = tgt if isinstance(tgt, Page) else tgt.page
        
        # 0. hover 선행 (드롭다운/헤더 메뉴/토글 UI를 위해 필수인 경우가 많음)
        # 드롭다운 메뉴는 hover 후 클릭해야 열리는 경우가 많음
        try:
            locator.hover(timeout=2000)  # hover 시간을 늘림
            # hover 후 짧은 대기 (드롭다운이 hover에 반응할 시간)
            try:
                page.wait_for_timeout(300)
            except Exception:
                pass
            self._log_checkpoint("click_strategy", {"strategy": "hover", "success": True})
        except Exception:
            # hover 실패해도 계속 진행 (모든 요소가 hover를 필요로 하지는 않음)
            self._log_checkpoint("click_strategy", {"strategy": "hover", "skipped": True})
        
        # 1차: native click (Playwright의 실제 마우스 이벤트 - 가장 안정적)
        try:
            locator.click(timeout=8000, force=False)
            self._log_checkpoint("click_strategy", {"strategy": "native_click", "success": True})
            return "native_click"
        except Exception as e1:
            self._log_checkpoint("click_strategy", {"strategy": "native_click", "error": str(e1)})
            
            # 2차: force click (오버레이/인터셉트 대응)
            try:
                locator.click(timeout=8000, force=True)
                self._log_checkpoint("click_strategy", {"strategy": "force_click", "success": True})
                return "force_click"
            except Exception as e2:
                self._log_checkpoint("click_strategy", {"strategy": "force_click", "error": str(e2)})
                
                # 3차: 좌표 클릭 (DOM은 맞는데 클릭이 안 먹히는 경우)
                try:
                    box = locator.bounding_box(timeout=2000)
                    if box:
                        center_x = box["x"] + box["width"] / 2
                        center_y = box["y"] + box["height"] / 2
                        page.mouse.click(center_x, center_y)
                        self._log_checkpoint("click_strategy", {"strategy": "coordinate_click", "success": True})
                        return "coordinate_click"
                except Exception as e3:
                    self._log_checkpoint("click_strategy", {"strategy": "coordinate_click", "error": str(e3)})
                    
                    # 4차: JS click + pointer 이벤트 (최후의 수단)
                    try:
                        locator.evaluate("""
                            (el) => {
                                el.scrollIntoView({ block: 'center', inline: 'center' });
                                if (el.disabled || el.getAttribute('aria-disabled') === 'true') {
                                    throw new Error('Button is disabled');
                                }
                                // pointer 이벤트 체인을 완전히 시뮬레이션
                                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, buttons: 1 }));
                                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, buttons: 1 }));
                                el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, buttons: 1 }));
                                // pointer 이벤트도 추가 (최신 브라우저)
                                if (window.PointerEvent) {
                                    el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, pointerId: 1 }));
                                    el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true, pointerId: 1 }));
                                }
                            }
                        """)
                        self._log_checkpoint("click_strategy", {"strategy": "js_click", "success": True})
                        return "js_click"
                    except Exception as e4:
                        raise RuntimeError(
                            f"All click strategies failed for {selector}. "
                            f"Errors: native={str(e1)}, force={str(e2)}, coordinate={str(e3)}, js={str(e4)}"
                        )
    
    def _get_all_evaluation_scopes(self) -> List[Tuple[Page | Frame, str]]:
        """
        success_conditions 평가 범위: top page + 모든 frames + popup pages
        
        Returns: [(target, scope_name), ...]
        """
        scopes: List[Tuple[Page | Frame, str]] = []
        
        # 1. Top page
        scopes.append((self.page, "top_page"))
        
        # 2. 모든 frames
        try:
            for i, frame in enumerate(self.page.frames):
                if frame != self.page.main_frame:
                    scopes.append((frame, f"frame_{i}_{frame.url[:50] if frame.url else 'unnamed'}"))
        except Exception:
            pass
        
        # 3. Popup pages
        try:
            for i, popup_page in enumerate(self.context.pages):
                if popup_page != self.page:
                    scopes.append((popup_page, f"popup_{i}_{popup_page.url[:50] if popup_page.url else 'unnamed'}"))
        except Exception:
            pass
        
        return scopes
    
    def _evaluate_success_condition(
        self,
        condition: Dict[str, Any],
        scopes: List[Tuple[Page | Frame, str]],
    ) -> Tuple[bool, str | None]:
        """
        success_condition을 모든 scope에서 평가
        
        Returns: (success, matched_scope)
        """
        cond_type = condition.get("type")
        timeout = condition.get("timeout", 15000)
        
        if cond_type == "modal_visible":
            # 모달이 나타나는지 확인
            text = condition.get("text")
            if not text:
                return False, None
            
            for tgt, scope_name in scopes:
                try:
                    # text only면 get_by_text 사용 (더 정확)
                    if isinstance(tgt, Page):
                        locator = tgt.get_by_text(text, exact=False).first
                    else:
                        locator = tgt.locator(f"text={text}").first
                    # visible 상태로 명시적으로 대기 (드롭다운/모달이 나타날 때까지)
                    locator.wait_for(state="visible", timeout=timeout)
                    # 추가 검증: 실제로 보이는지 확인
                    if locator.is_visible(timeout=1000):
                        return True, scope_name
                except Exception:
                    continue
            return False, None
        
        elif cond_type == "url_changed":
            # URL이 변경되는지 확인
            url = condition.get("url")
            if not url:
                return False, None
            
            # URL prefix 매칭 지원
            url_pattern = url if url.endswith("*") else f"{url}*"
            prefix = url_pattern.rstrip("*")
            
            for tgt, scope_name in scopes:
                if isinstance(tgt, Page):
                    try:
                        if prefix:
                            tgt.wait_for_function(
                                f'() => (window.location.href || "").startsWith("{prefix}")',
                                timeout=timeout
                            )
                        else:
                            expect(tgt).to_have_url(url, timeout=timeout)
                        return True, scope_name
                    except Exception:
                        # Fallback: check current URL
                        if prefix and (tgt.url or "").startswith(prefix):
                            return True, scope_name
                        elif not prefix and (tgt.url or "").startswith(url):
                            return True, scope_name
                        continue
            return False, None
        
        elif cond_type == "popup_opened":
            # Popup이 열리는지 확인
            # 이미 popup pages가 scopes에 포함되어 있으므로, 새로운 popup이 있는지 확인
            initial_pages = set(self.context.pages)
            try:
                self.page.wait_for_timeout(min(timeout, 2000))
            except Exception:
                pass
            current_pages = set(self.context.pages)
            if len(current_pages) > len(initial_pages):
                return True, "popup_opened"
            return False, None
        
        elif cond_type == "element_visible":
            # 특정 요소가 보이는지 확인
            selector = condition.get("selector")
            text = condition.get("text")
            if not selector and not text:
                return False, None
            
            for tgt, scope_name in scopes:
                try:
                    if text:
                        # text only면 무조건 get_by_text + visible 기준 대기
                        if isinstance(tgt, Page):
                            locator = tgt.get_by_text(text, exact=False).first
                        else:
                            # Frame의 경우 locator 사용
                            locator = tgt.locator(f"text={text}").first
                    else:
                        locator = tgt.locator(selector).first
                    # visible 상태로 명시적으로 대기 (드롭다운/모달이 나타날 때까지)
                    locator.wait_for(state="visible", timeout=timeout)
                    # 추가 검증: 실제로 보이는지 확인
                    if locator.is_visible(timeout=1000):
                        return True, scope_name
                except Exception:
                    continue
            return False, None
        
        return False, None
    
    def _evaluate_success_conditions(
        self,
        success_conditions: List[Dict[str, Any]],
    ) -> Tuple[bool, str | None]:
        """
        3. 성공 판정 (관측)
        
        success_conditions(OR)을 top page + 모든 frames + popup pages에서 평가
        
        Returns: (success, matched_condition_info)
        """
        if not success_conditions:
            # 조건이 없으면 기본 대기만 수행
            try:
                self.page.wait_for_timeout(1000)
            except Exception:
                pass
            return True, "no_conditions"
        
        scopes = self._get_all_evaluation_scopes()
        
        # OR 조건: 하나라도 만족하면 성공
        for condition in success_conditions:
            success, matched_scope = self._evaluate_success_condition(condition, scopes)
            if success:
                self._log_checkpoint(
                    "success_condition_met",
                    {
                        "condition": condition,
                        "matched_scope": matched_scope,
                    }
                )
                return True, f"{condition.get('type')}_{matched_scope}"
        
        # 모든 조건 실패
        self._log_checkpoint(
            "success_conditions_failed",
            {
                "conditions": success_conditions,
                "scopes_checked": [name for _, name in scopes],
            }
        )
        return False, None
    
    def execute_click_transaction(
        self,
        tgt: Page | Frame,
        selector: str | List[str],
        success_conditions: List[Dict[str, Any]] | None = None,
        max_retries: int = 2,
    ) -> Tuple[bool, str]:
        """
        Click을 트랜잭션으로 실행
        
        Args:
            selector: 단일 selector 문자열 또는 selector 후보 리스트
        
        Returns: (success, method_used)
        """
        success_conditions = success_conditions or []
        
        # selector를 리스트로 정규화
        if isinstance(selector, str):
            selectors = [selector]
        else:
            selectors = selector
        
        # 각 selector 후보를 시도
        last_error = None
        for sel in selectors:
            try:
                for attempt in range(max_retries + 1):
                    try:
                        # 1. 사전 안정화
                        self._pre_stabilize(tgt, sel)
                        
                        # 2. 액션 수행
                        method = self._execute_click_multi_strategy(tgt, sel)
                        
                        # DOM 업데이트 대기 (React/JS 완료)
                        # 드롭다운/모달이 나타나기까지 시간이 필요하므로 충분히 대기
                        # #region agent log
                        _write_debug_log(
                            f"action_transaction.py:{452}",
                            "Before wait after click",
                            {"step_index": self.step_index, "selector": sel, "method": method},
                            "B"
                        )
                        # #endregion
                        try:
                            if isinstance(tgt, Page):
                                tgt.wait_for_timeout(2000)  # 2초 대기 (드롭다운/모달 표시 시간 확보)
                            else:
                                tgt.page.wait_for_timeout(2000)
                        except Exception:
                            pass
                        # #region agent log
                        _write_debug_log(
                            f"action_transaction.py:{456}",
                            "After wait after click",
                            {"step_index": self.step_index, "selector": sel},
                            "B"
                        )
                        # #endregion
                        
                        # 3. 성공 판정 (클릭 후 상태 변화 검증)
                        # success_conditions가 있으면 반드시 만족될 때까지 재시도
                        if success_conditions:
                            # #region agent log
                            # 드롭다운 상태 확인
                            dropdown_state_before = {}
                            for condition in success_conditions:
                                if condition.get("text") == "로그인 하세요!":
                                    page_for_check = tgt if isinstance(tgt, Page) else tgt.page
                                    dropdown_state_before = _check_dropdown_state(page_for_check, "로그인 하세요!")
                                    break
                            _write_debug_log(
                                f"action_transaction.py:{477}",
                                "Before success_condition check",
                                {"step_index": self.step_index, "selector": sel, "conditions": success_conditions, "dropdown_state": dropdown_state_before},
                                "B"
                            )
                            # #endregion
                            success, condition_info = self._evaluate_success_conditions(success_conditions)
                            # #region agent log
                            # 드롭다운 상태 재확인
                            dropdown_state_after = {}
                            for condition in success_conditions:
                                if condition.get("text") == "로그인 하세요!":
                                    page_for_check = tgt if isinstance(tgt, Page) else tgt.page
                                    dropdown_state_after = _check_dropdown_state(page_for_check, "로그인 하세요!")
                                    break
                            _write_debug_log(
                                f"action_transaction.py:{489}",
                                "After success_condition check",
                                {"step_index": self.step_index, "selector": sel, "success": success, "condition_info": condition_info, "dropdown_state": dropdown_state_after},
                                "B"
                            )
                            # #endregion
                            
                            if success:
                                self._log_checkpoint(
                                    "click_transaction_success",
                                    {
                                        "selector": sel,
                                        "attempt": attempt + 1,
                                        "method": method,
                                        "condition_info": condition_info,
                                    }
                                )
                                return True, method
                            else:
                                # 조건 불충족 - 재시도 (드롭다운/모달이 안 열린 경우)
                                if attempt < max_retries:
                                    self._log_checkpoint(
                                        "click_transaction_retry",
                                        {
                                            "selector": sel,
                                            "attempt": attempt + 1,
                                            "max_retries": max_retries,
                                            "condition_info": condition_info,
                                            "reason": "success_condition_not_met",
                                        }
                                    )
                                    # 재시도 전 대기 (DOM 업데이트 시간 확보)
                                    # 드롭다운이 열리지 않았으므로 더 긴 대기 후 재시도
                                    try:
                                        if isinstance(tgt, Page):
                                            tgt.wait_for_timeout(2000)  # 2초 대기
                                        else:
                                            tgt.page.wait_for_timeout(2000)
                                    except Exception:
                                        pass
                                    continue
                                else:
                                    # 최대 재시도 횟수 초과 - 다음 selector 시도
                                    self._log_checkpoint(
                                        "click_transaction_failed",
                                        {
                                            "selector": sel,
                                            "attempt": attempt + 1,
                                            "max_retries": max_retries,
                                            "condition_info": condition_info,
                                            "reason": "max_retries_exceeded",
                                        }
                                    )
                                    break
                        else:
                            # success_conditions가 없으면 클릭만 성공하면 OK
                            # 하지만 DOM 업데이트를 위해 짧은 대기
                            try:
                                if isinstance(tgt, Page):
                                    tgt.wait_for_timeout(500)
                                else:
                                    tgt.page.wait_for_timeout(500)
                            except Exception:
                                pass
                            
                            self._log_checkpoint(
                                "click_transaction_success",
                                {
                                    "selector": sel,
                                    "attempt": attempt + 1,
                                    "method": method,
                                    "condition_info": "no_conditions",
                                }
                            )
                            return True, method
                    
                    except Exception as e:
                        if attempt < max_retries:
                            self._log_checkpoint(
                                "click_transaction_exception_retry",
                                {
                                    "selector": sel,
                                    "attempt": attempt + 1,
                                    "error": str(e),
                                }
                            )
                            try:
                                if isinstance(tgt, Page):
                                    tgt.wait_for_timeout(500)
                                else:
                                    tgt.page.wait_for_timeout(500)
                            except Exception:
                                pass
                            continue
                        else:
                            # 최대 재시도 횟수 초과 - 다음 selector 시도
                            last_error = e
                            break
                
                # 이 selector로 성공하지 못했으면 다음 selector 시도
                continue
                
            except Exception as e:
                last_error = e
                continue
        
        # 모든 selector 실패
        if last_error:
            raise last_error
        return False, "unknown"

