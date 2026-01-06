"""
Implementation of step execution for Playwright.

Each supported step type is mapped to a concrete action on the
Playwright ``Page`` object. Additional step types can be added here
to extend the language understood by the runner.

This implementation mirrors the behavior of the browser extension
(content.js) to ensure test runs behave identically to extension playback.
"""

import json
import os
import time
from typing import Any, Dict, List, Tuple, cast

from playwright.sync_api import Frame, Page, TimeoutError, expect

from app.runner.debug_utils import log_debug_checkpoint, check_element_exists, check_dom_state
from app.runner.action_transaction import ActionTransaction

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


def _get_delay_ms(step: Dict[str, Any]) -> int:
    v = step.get("delay_ms", step.get("delay", 0))
    try:
        return max(0, int(v or 0))
    except Exception:
        return 0


def _smart_wait(page: Page) -> None:
    # Best-effort stabilization. Keep timeouts short to avoid slowing down the suite.
    # Note: Do NOT use wait_for_load_state("networkidle") after clicks as it can cause
    # page reloads or unexpected navigation that closes dropdowns/popups.
    # Only wait for DOM to be ready, not network idle.
    try:
        page.wait_for_load_state("domcontentloaded", timeout=1500)
    except Exception:
        pass
    # Removed networkidle wait - it can cause issues with dropdowns/popups that are open
    # Network idle waits can trigger page reloads or navigation in some environments


def _wait_after_interaction(page: Page, tgt: Page | Frame) -> None:
    """
    Wait after user interaction (click/fill) to allow DOM updates, animations, and dropdowns to appear.
    
    CRITICAL: Do NOT use wait_for_load_state as it can cause page reloads
    that close dropdowns/popups. Only use simple timeout wait.
    
    Simple approach matching crawlHogak_lima.py:
    - Simple timeout wait for JavaScript/DOM updates only
    - NO wait_for_load_state (can cause page reloads)
    - NO MutationObserver (can trigger page reloads in some cases)
    """
    # CRITICAL: Do NOT use wait_for_load_state or MutationObserver
    # They can trigger page reloads that close dropdowns/popups.
    # Use simple timeout wait only - this is the most reliable approach.
    
    # Simple timeout wait for React/JavaScript to complete updates
    # React apps and dropdowns need time, especially in headless/Docker environments
    # Increased timeout for Docker environment stability
    try:
        page.wait_for_timeout(3000)  # Increased from 2000ms for Docker stability
    except Exception:
        pass


def _resolve_frame(page: Page, frame_meta: dict[str, Any] | None, wait_for_frame: bool = False, timeout: int = 5000) -> Frame | None:
    """
    Resolve frame from metadata, matching extension's findIframeForFrame logic.
    Extension prefers href/src match, then falls back to name match.
    
    :param wait_for_frame: If True, wait for frame to appear (for dynamically loaded iframes)
    :param timeout: Timeout for waiting for frame to appear
    """
    if not frame_meta:
        return None
    if bool(frame_meta.get("isTop", True)):
        return None
    name = str(frame_meta.get("name") or "").strip()
    href = str(frame_meta.get("href") or "").strip()
    
    # Extension logic: prefer href/src match, then name match
    if href:
        # If wait_for_frame is True, poll for frame to appear
        if wait_for_frame:
            import time
            start_time = time.time()
            while time.time() - start_time < timeout / 1000:
                try:
                    # Check all frames for matching URL
                    for f in page.frames:
                        if not f.url:
                            continue
                        # Extension uses: src === wantHref || (startsWith in both directions)
                        if f.url == href or href.startswith(f.url) or f.url.startswith(href):
                            return f
                except Exception:
                    pass
                # Wait a bit before retrying
                try:
                    page.wait_for_timeout(200)
                except Exception:
                    break
        
        try:
            # Try exact URL match first
            for f in page.frames:
                if not f.url:
                    continue
                # Extension uses: src === wantHref || (startsWith in both directions)
                if f.url == href:
                    return f
                # Bidirectional prefix matching (extension behavior)
                if href.startswith(f.url) or f.url.startswith(href):
                    return f
        except Exception:
            pass
    
    # Fallback: name match (extension's second choice)
    if name:
        # If wait_for_frame is True, poll for frame to appear
        if wait_for_frame:
            import time
            start_time = time.time()
            while time.time() - start_time < timeout / 1000:
                try:
                    f = page.frame(name=name)
                    if f:
                        return f
                except Exception:
                    pass
                # Wait a bit before retrying
                try:
                    page.wait_for_timeout(200)
                except Exception:
                    break
        
        try:
            f = page.frame(name=name)
            if f:
                return f
        except Exception:
            pass
    
    return None


def _target(page: Page, step: Dict[str, Any], wait_for_frame: bool = False) -> Page | Frame:
    """
    Get target (Page or Frame) for step execution.
    
    :param wait_for_frame: If True, wait for frame to appear (for dynamically loaded iframes)
    """
    fm = cast(dict[str, Any] | None, step.get("frame"))
    f = _resolve_frame(page, fm, wait_for_frame=wait_for_frame)
    return f or page


def _wait_for_element_visible(tgt: Page | Frame, selector: str, timeout: int = 8000) -> None:
    """
    Wait for element to be visible, matching extension behavior.
    Extension waits for element to appear before interacting with it.
    
    This function waits for the element to be both attached to DOM and visible.
    For dynamically rendered content (dropdowns, modals), this ensures they have
    time to appear after previous interactions.
    
    CRITICAL: Do NOT use wait_for_load_state during this wait as it can cause
    page reloads that close dropdowns/popups.
    """
    locator = tgt.locator(selector).first
    # First wait for element to be attached to DOM
    try:
        locator.wait_for(state="attached", timeout=timeout)
    except Exception:
        pass
    # Then wait for it to be visible (handles CSS transitions, animations)
    # Use longer timeout for popups/dropdowns in Docker environments
    locator.wait_for(state="visible", timeout=timeout)


def _wait_for_element_actionable(tgt: Page | Frame, selector: str, timeout: int = 5000) -> None:
    """
    Wait for element to be actionable (not disabled, not covered, pointer-events enabled).
    This is critical for React apps where elements might be in the DOM but not yet interactive.
    """
    locator = tgt.locator(selector).first
    try:
        # Wait for element to be enabled (not disabled)
        locator.wait_for(state="visible", timeout=timeout)
        # Check if element is actually actionable
        locator.evaluate("""
            el => {
                if (!el) throw new Error('Element not found');
                // Check if element or its parent is disabled
                if (el.disabled || el.getAttribute('aria-disabled') === 'true') {
                    throw new Error('Element is disabled');
                }
                // Check pointer-events
                const style = window.getComputedStyle(el);
                if (style.pointerEvents === 'none') {
                    throw new Error('Element has pointer-events: none');
                }
                // Check if element is in viewport and not covered (basic check)
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) {
                    throw new Error('Element has zero size');
                }
            }
        """)
    except Exception:
        # If check fails, wait a bit more and try again (React might still be rendering)
        try:
            if isinstance(tgt, Page):
                tgt.wait_for_timeout(300)
            else:
                tgt.page.wait_for_timeout(300)
        except Exception:
            pass


def _scroll_into_view(tgt: Page | Frame, selector: str) -> None:
    """
    Scroll element into view (center), matching extension's scrollIntoView behavior.
    Extension uses: el.scrollIntoView({ block: 'center', inline: 'center' })
    """
    locator = tgt.locator(selector).first
    locator.scroll_into_view_if_needed()


def _click_via_javascript(tgt: Page | Frame, selector: str) -> None:
    """
    Click element using JavaScript event dispatch (exactly like extension).
    Extension uses: el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    
    This matches the extension's click behavior exactly, which works in React apps.
    Since extension works reliably, we use the same approach.
    
    Handles cases where button text is split across multiple child elements.
    """
    locator = tgt.locator(selector).first
    # Extension's exact approach: scrollIntoView then dispatchEvent
    # Also handle cases where button has nested elements (e.g., "로그인" and "∨" are separate)
    locator.evaluate("""
        el => {
            // Scroll button into view
            el.scrollIntoView({ block: 'center', inline: 'center' });
            
            // Ensure button is visible and enabled
            if (el.disabled || el.getAttribute('aria-disabled') === 'true') {
                throw new Error('Button is disabled');
            }
            
            // Try multiple click methods for reliability
            // Method 1: Direct click event (most reliable for React apps)
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            
            // Method 2: Also trigger mousedown/mouseup for better compatibility
            el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
            el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
        }
    """)


def _wait_for_js_completion(page: Page, selector: str = None, expected_text: str = None, timeout: int = 10000) -> None:
    """
    Wait for JavaScript handlers to complete after click.
    
    This function waits for:
    1. DOM to stabilize (no mutations for a period)
    2. Optionally, an element to appear with expected text
    
    This is critical for headless environments where DOM updates may be delayed.
    """
    # Option 1: Wait for element to appear with expected text (if provided)
    if selector and expected_text:
        try:
            # Use json.dumps for safe JavaScript string escaping
            sel_json = json.dumps(selector)
            text_json = json.dumps(expected_text)
            page.wait_for_function(
                f"""
                () => {{
                    const el = document.querySelector({sel_json});
                    if (!el) return false;
                    const text = String(el.innerText || el.textContent || '').trim();
                    return text.includes({text_json});
                }}
                """,
                timeout=timeout
            )
        except Exception:
            pass
    
    # Option 2: Wait for DOM to stabilize (no mutations for a period)
    # Also wait for React to finish any batched updates
    try:
        page.wait_for_function(
            """
            () => {
                return new Promise(resolve => {
                    // Check if React is present and wait for it to be ready
                    let reactReady = false;
                    try {
                        // React 18+ uses concurrent rendering, check for React DevTools hook
                        // or wait for any pending updates
                        if (window.__REACT_DEVTOOLS_GLOBAL_HOOK__) {
                            reactReady = true;
                        }
                    } catch (e) {
                        // React might not be present, that's okay
                    }
                    
                    // Wait longer for React apps as they may have batched updates
                    let waitTime = reactReady ? 400 : 200;
                    let timeout = setTimeout(resolve, waitTime);
                    const observer = new MutationObserver(() => {
                        clearTimeout(timeout);
                        timeout = setTimeout(resolve, waitTime);
                    });
                    observer.observe(document.body, { 
                        childList: true, 
                        subtree: true,
                        attributes: true,
                        attributeOldValue: false
                    });
                });
            }
            """,
            timeout=5000
        )
    except Exception:
        # Fallback: just wait a short time for DOM updates
        try:
            page.wait_for_timeout(400)  # Increased for React apps
        except Exception:
            pass


def _get_element_text(tgt: Page | Frame, selector: str) -> str:
    """
    Get element text using innerText or textContent, matching extension behavior.
    Extension uses: String(el.innerText || el.textContent || '').trim()
    """
    try:
        # Try innerText first (extension's preference)
        text = tgt.locator(selector).first.evaluate(
            "el => String(el.innerText || el.textContent || '').trim()"
        )
        return str(text) if text else ""
    except Exception:
        # Fallback to Playwright's text_content if evaluate fails
        try:
            text = tgt.locator(selector).first.text_content(timeout=2000)
            return str(text).strip() if text else ""
        except Exception:
            return ""


def _is_element_visible(tgt: Page | Frame, selector: str) -> bool:
    """
    Check if element is visible, matching extension's isVisible logic.
    Extension checks: getBoundingClientRect, display, visibility, opacity
    """
    try:
        return tgt.locator(selector).first.evaluate(
            """el => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                if (!r || r.width <= 0 || r.height <= 0) return false;
                const st = window.getComputedStyle(el);
                if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
                return true;
            }"""
        )
    except Exception:
        # Fallback to Playwright's visibility check
        try:
            return tgt.locator(selector).first.is_visible(timeout=2000)
        except Exception:
            return False


def run_step(page: Page, step: Dict[str, Any], run_dir: str, ctx: Dict[str, Any] | None = None, next_step: Dict[str, Any] | None = None) -> Page:
    """
    Execute a single step against a Playwright page.

    :param page: Playwright ``Page`` object on which to perform actions
    :param step: Dictionary describing the action to perform
    :param run_dir: Directory where screenshots should be stored
    :return: Possibly updated Page (e.g., switched to popup)
    :raises ValueError: If the step type is unknown
    """
    t = step.get("type")
    if not t:
        raise ValueError("Step missing 'type' field")

    if t == "go":
        # Navigate to a URL. Use domcontentloaded (not networkidle) to avoid page reloads.
        page.goto(step["url"], wait_until="domcontentloaded")
        _smart_wait(page)
    elif t == "click":
        # CRITICAL: Extension 방식으로 단순화
        # Extension 재생 방식: scrollIntoView + dispatchEvent (매우 단순하고 안정적)
        # Extension에서는 문제 없이 재생되므로 동일한 방식 사용
        tgt = _target(page, step)
        
        # Support selectors array (from compiler) or single selector
        selectors = step.get("selectors")
        if not selectors or not isinstance(selectors, list):
            # Single selector를 배열로 변환
            sel = step.get("selector")
            if not sel:
                raise ValueError("click step requires 'selector' or 'selectors' field")
            selectors = [sel]
        
        # selectors에서 실제 클릭 가능한 selector만 필터링
        # text="..." 형태는 클릭할 요소가 아니라 나타날 텍스트이므로 제외
        clickable_selectors = []
        for sel in selectors:
            # text="..." 형태는 제외 (이건 success_condition에서 사용)
            if not (sel.startswith('text=') or sel.startswith('text="')):
                clickable_selectors.append(sel)
        
        # 클릭 가능한 selector가 없으면 원본 selectors 사용 (fallback)
        if not clickable_selectors:
            clickable_selectors = selectors
        
        # Extension 방식: 각 selector 시도 (첫 번째 성공하면 종료)
        last_error = None
        for sel in clickable_selectors:
            try:
                # Extension 방식: resolveEl (querySelector)
                locator = tgt.locator(sel).first
                
                # Extension 방식: scrollIntoView({ block: 'center', inline: 'center' })
                locator.scroll_into_view_if_needed()
                
                # Extension 방식: dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
                locator.evaluate("""
                    el => {
                        el.scrollIntoView({ block: 'center', inline: 'center' });
                        el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                    }
                """)
                
                # Extension에서는 delay_ms만큼 대기 (success_conditions 없음)
                # success_conditions가 있으면 옵션으로 체크 (Extension 기록 시에는 없음)
                success_conditions = step.get("success_conditions", [])
                if success_conditions:
                    # success_conditions가 있으면 Extension에서 컴파일러가 추가한 것
                    # 이 경우에만 체크 (하지만 Extension 재생 방식 유지)
                    # 간단히 대기만 하고 체크는 생략 (Extension에서는 체크하지 않음)
                    try:
                        page.wait_for_timeout(500)  # 짧은 대기만
                    except Exception:
                        pass
                
                # 성공하면 다음 selector 시도하지 않음
                break
            except Exception as e:
                last_error = e
                continue
        
        # 모든 selector 실패
        if last_error:
            raise RuntimeError(f"Click failed for all selectors: {clickable_selectors}. Last error: {str(last_error)}")
    elif t == "fill":
        # CRITICAL: Extension 방식으로 단순화
        # Extension 재생 방식: scrollIntoView, focus, set value, dispatch input/change events
        v = step.get("value")
        if v is None:
            v = step.get("text")
        tgt = _target(page, step)
        sel = step["selector"]
        
        # Extension 방식: resolveEl (querySelector)
        locator = tgt.locator(sel).first
        
        # Extension 방식: scrollIntoView({ block: 'center', inline: 'center' })
        locator.scroll_into_view_if_needed()
        
        # Extension 방식: focus, set value, dispatch input/change events
        locator.evaluate("""
            (el, value) => {
                el.scrollIntoView({ block: 'center', inline: 'center' });
                el.focus();
                el.value = value;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
        """, str(v) if v is not None else "")
    elif t == "click_popup":
        # Click and switch to a newly opened page (target=_blank, window.open).
        # Extension behavior: scrollIntoView before click
        if ctx is None:
            ctx = {}
        stack: List[Page] = ctx.setdefault("page_stack", [page])
        sel = step["selector"]
        popup_url = str(step.get("popup_url") or "").strip()
        _wait_for_element_visible(page, sel, timeout=8000)
        _scroll_into_view(page, sel)
        try:
            with page.context.expect_page(timeout=8000) as pinfo:
                page.locator(sel).first.click(timeout=8000)
            new_page = pinfo.value
            _wait_after_interaction(page, page)
        except TimeoutError as e:
            raise RuntimeError(f"click_popup: no new page opened for selector={sel}") from e
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        if popup_url:
            try:
                expect(new_page).to_have_url(popup_url, timeout=8000)
            except Exception:
                # fallback: allow prefix match
                if not (new_page.url or "").startswith(popup_url):
                    raise
        stack.append(new_page)
        page = new_page
        _smart_wait(page)
    elif t == "popup_go":
        # Open a new page and goto url (used for programmatic window.open cases).
        if ctx is None:
            ctx = {}
        stack: List[Page] = ctx.setdefault("page_stack", [page])
        url = step["url"]
        new_page = page.context.new_page()
        new_page.goto(url, wait_until="domcontentloaded")
        _smart_wait(new_page)
        stack.append(new_page)
        page = new_page
    elif t == "close_page":
        if ctx is None:
            ctx = {}
        stack = cast(List[Page], ctx.setdefault("page_stack", [page]))
        if len(stack) > 1:
            try:
                stack[-1].close()
            except Exception:
                pass
            stack.pop()
            page = stack[-1]
    elif t == "switch_main":
        if ctx and ctx.get("main_page") is not None:
            page = cast(Page, ctx["main_page"])
    elif t == "ensure_logged_in":
        # Assert that user is logged-in (i.e., login button does NOT show logged-out text).
        # Useful when using storageState injection to avoid Apple login popups/2FA in headless.
        tgt = _target(page, step, wait_for_frame=True)
        selectors = step.get("selectors")
        if not selectors or not isinstance(selectors, list):
            sel = step.get("selector") or "#btnUser"
            selectors = [sel]
        logged_out_text = str(step.get("logged_out_text") or step.get("loggedOutText") or "로그인").strip()
        last_err = None
        for sel in selectors:
            try:
                loc = tgt.locator(sel).first
                loc.wait_for(state="attached", timeout=5000)
                txt = (loc.inner_text(timeout=2000) or "").strip()
                if logged_out_text and logged_out_text in txt:
                    raise AssertionError(f"로그인 상태가 아닙니다: selector={sel}, text={txt!r}")
                last_err = None
                break
            except Exception as e:
                last_err = e
                continue
        if last_err:
            raise last_err
    elif t == "ensure_logged_out":
        # Assert that user is logged-out (i.e., login button shows logged-out text).
        tgt = _target(page, step, wait_for_frame=True)
        selectors = step.get("selectors")
        if not selectors or not isinstance(selectors, list):
            sel = step.get("selector") or "#btnUser"
            selectors = [sel]
        logged_out_text = str(step.get("logged_out_text") or step.get("loggedOutText") or "로그인").strip()
        last_err = None
        for sel in selectors:
            try:
                loc = tgt.locator(sel).first
                loc.wait_for(state="attached", timeout=5000)
                txt = (loc.inner_text(timeout=2000) or "").strip()
                if logged_out_text and logged_out_text not in txt:
                    raise AssertionError(f"로그아웃 상태가 아닙니다: selector={sel}, text={txt!r}")
                last_err = None
                break
            except Exception as e:
                last_err = e
                continue
        if last_err:
            raise last_err
    elif t == "expect_text":
        # Assert that the element matching the selector contains the expected text.
        # Extension behavior: scrollIntoView, get innerText/textContent, check includes()
        # For dynamically appearing elements (modals), wait for frame if needed
        # Supports multiple strategies:
        # 1. text only (text-based locator - most reliable for dynamic DOM)
        # 2. selectors array (try multiple selectors until one works)
        # 3. selector + text (CSS selector with expected text - original behavior)
        tgt = _target(page, step, wait_for_frame=True)
        expected_text = str(step.get("text", "")).strip()
        
        # #region agent log
        step_index = step.get("_step_index", 0)
        # 드롭다운 상태 확인 (특히 "로그인 하세요!" 텍스트)
        dropdown_state = {}
        if expected_text == "로그인 하세요!":
            page_for_check = page if isinstance(tgt, Page) else tgt.page
            dropdown_state = _check_dropdown_state(page_for_check, expected_text)
        _write_debug_log(
            f"playwright_steps.py:{563}",
            "expect_text start",
            {"step_index": step_index, "expected_text": expected_text, "dropdown_state": dropdown_state},
            "C"
        )
        # #endregion
        
        if not expected_text:
            raise ValueError("expect_text requires 'text' field")
        
        # Strategy 1: Text-based locator only (most reliable - no selector needed)
        if not step.get("selector") and not step.get("selectors"):
            try:
                locator = tgt.locator(f"text={expected_text}").first
                locator.wait_for(state="visible", timeout=15000)
                # Text is already found, so assertion passes
                return page
            except Exception as e:
                # Log failure for debugging
                try:
                    count = tgt.locator(f"text={expected_text}").count()
                    log_debug_checkpoint(
                        run_dir,
                        step.get("_step_index", 0),
                        "expect_text",
                        "text_locator_failed",
                        {
                            "expected_text": expected_text,
                            "text_count": count,
                            "error": str(e),
                        }
                    )
                except Exception:
                    pass
                raise AssertionError(
                    f'expect_text failed. 텍스트 "{expected_text}"를 찾을 수 없습니다.'
                )
        
        # Strategy 2: Multiple selectors (try each until one works)
        selectors = step.get("selectors")
        if selectors and isinstance(selectors, list):
            last_error = None
            for sel in selectors:
                try:
                    _wait_for_element_visible(tgt, sel, timeout=15000)
                    actual_text = _get_element_text(tgt, sel)
                    if expected_text and expected_text not in actual_text:
                        continue  # Try next selector
                    # Found matching text
                    return page
                except Exception as e:
                    last_error = e
                    continue
            # All selectors failed
            if last_error:
                raise AssertionError(
                    f'expect_text failed. 모든 selector 후보에서 실패. expected: "{expected_text}"'
                )
        
        # Strategy 3: Single selector (Extension 방식으로 단순화)
        sel = step.get("selector")
        if not sel:
            # Fallback to text-based if no selector provided
            try:
                # Page의 경우 get_by_text 사용 (더 정확)
                if isinstance(tgt, Page):
                    locator = tgt.get_by_text(expected_text, exact=False).first
                else:
                    # Frame의 경우 locator 사용
                    locator = tgt.locator(f"text={expected_text}").first
                locator.wait_for(state="visible", timeout=15000)
                return page
            except Exception:
                raise ValueError("expect_text requires at least one of: selector, selectors, or text")
        
        # CRITICAL: Extension 방식으로 단순화
        # Extension: resolveEl(selector)로 요소 찾고 바로 innerText/textContent 체크 (wait_for 없음)
        # Extension에서는 wait_for 없이 바로 체크하므로 서버 Runner도 동일하게
        try:
            locator = tgt.locator(sel).first
            # Extension 방식: String(el.innerText || el.textContent || '').trim()
            actual_text = locator.evaluate(
                "el => String(el.innerText || el.textContent || '').trim()"
            )
            actual_text = str(actual_text) if actual_text else ""
            
            # Extension uses: if (expected && !actual.includes(expected)) throw error
            if expected_text and expected_text not in actual_text:
                raise AssertionError(
                    f'expect_text failed. expected 포함: "{expected_text}" actual: "{actual_text[:120]}"'
                )
        except AssertionError:
            raise
        except Exception as e:
            # Element not found or other error
            raise AssertionError(
                f'expect_text failed. selector="{sel}" expected="{expected_text}" error: {str(e)}'
            )
    elif t == "expect_visible":
        # Assert that the element is visible.
        # Extension behavior: scrollIntoView, then check isVisible (getBoundingClientRect, display, visibility, opacity)
        tgt = _target(page, step)
        sel = step["selector"]
        
        # Wait for element to exist first
        locator = tgt.locator(sel).first
        locator.wait_for(state="attached", timeout=8000)
        _scroll_into_view(tgt, sel)
        
        # Use extension's visibility check logic
        if not _is_element_visible(tgt, sel):
            raise AssertionError(f'expect_visible failed (not visible): selector="{sel}"')
    elif t == "expect_url":
        # Exact match (MVP). Can be extended to regex/contains later.
        expect(page).to_have_url(step["url"], timeout=8000)
    elif t == "wait_visible":
        # Wait for element to become visible (for modals/popups that appear after clicks)
        # This is critical for Docker environments where modals may take longer to appear
        # Supports multiple selector strategies:
        # 1. selector (CSS selector)
        # 2. selectors (array of CSS selectors - try each until one works)
        # 3. text (text-based locator - most reliable for dynamic DOM)
        # 4. role (accessibility role-based locator)
        tgt = _target(page, step, wait_for_frame=True)
        timeout = step.get("timeout", 15000)  # Default 15s for modals
        
        # Strategy 1: Text-based locator (most reliable)
        # text only면 무조건 get_by_text + visible 기준 대기 (우선순위 1)
        text = step.get("text")
        if text:
            try:
                # Page의 경우 get_by_text 사용 (더 정확)
                if isinstance(tgt, Page):
                    locator = tgt.get_by_text(text, exact=False).first
                else:
                    # Frame의 경우 locator 사용
                    locator = tgt.locator(f"text={text}").first
                # visible 상태로 명시적으로 대기
                locator.wait_for(state="visible", timeout=timeout)
                return page
            except Exception as e:
                # Log failure but continue to try other strategies
                try:
                    log_debug_checkpoint(
                        run_dir,
                        step.get("_step_index", 0),
                        "wait_visible",
                        "text_failed",
                        {
                            "text": text,
                            "timeout": timeout,
                            "error": str(e),
                        }
                    )
                except Exception:
                    pass
        
        # Strategy 2: Role-based locator
        role = step.get("role")
        if role:
            try:
                locator = tgt.locator(f"role={role}").first
                locator.wait_for(state="visible", timeout=timeout)
                return page
            except Exception as e:
                try:
                    log_debug_checkpoint(
                        run_dir,
                        step.get("_step_index", 0),
                        "wait_visible",
                        "role_failed",
                        {
                            "role": role,
                            "timeout": timeout,
                            "error": str(e),
                        }
                    )
                except Exception:
                    pass
        
        # Strategy 3: Multiple selectors (try each until one works)
        selectors = step.get("selectors")
        if selectors and isinstance(selectors, list):
            last_error = None
            for sel in selectors:
                try:
                    _wait_for_element_visible(tgt, sel, timeout=timeout)
                    return page
                except Exception as e:
                    last_error = e
                    continue
            # All selectors failed - log diagnostic info
            try:
                diagnostic_info = {}
                for sel in selectors:
                    try:
                        count = tgt.locator(sel).count()
                        diagnostic_info[sel] = {"count": count}
                    except Exception:
                        diagnostic_info[sel] = {"count": "error"}
                log_debug_checkpoint(
                    run_dir,
                    step.get("_step_index", 0),
                    "wait_visible",
                    "all_selectors_failed",
                    {
                        "selectors": selectors,
                        "timeout": timeout,
                        "diagnostic": diagnostic_info,
                        "error": str(last_error) if last_error else "unknown",
                    }
                )
            except Exception:
                pass
            if last_error:
                raise last_error
        
        # Strategy 4: Single selector (fallback)
        sel = step.get("selector")
        if sel:
            # Enhanced debugging before failure
            try:
                count = tgt.locator(sel).count()
                # Also check if text exists anywhere
                text_check = None
                if text:
                    if isinstance(tgt, Page):
                        text_count = tgt.get_by_text(text, exact=False).count()
                    else:
                        text_count = tgt.locator(f"text={text}").count()
                    text_check = {"count": text_count}
                log_debug_checkpoint(
                    run_dir,
                    step.get("_step_index", 0),
                    "wait_visible",
                    "before_wait",
                    {
                        "selector": sel,
                        "selector_count": count,
                        "text_check": text_check,
                        "timeout": timeout,
                    }
                )
            except Exception:
                pass
            
            try:
                _wait_for_element_visible(tgt, sel, timeout=timeout)
            except Exception as e:
                # Final diagnostic on failure
                try:
                    final_count = tgt.locator(sel).count()
                    log_debug_checkpoint(
                        run_dir,
                        step.get("_step_index", 0),
                        "wait_visible",
                        "failed",
                        {
                            "selector": sel,
                            "selector_count": final_count,
                            "timeout": timeout,
                            "error": str(e),
                        }
                    )
                except Exception:
                    pass
                raise
        
        # No valid strategy found
        raise ValueError("wait_visible requires at least one of: selector, selectors, text, or role")
    elif t == "wait_url":
        # Wait for URL to match (for page navigation after login/submit)
        # Supports prefix matching (URL ending with *)
        expected_url = step.get("url") or step.get("url_pattern", "")
        timeout = step.get("timeout", 15000)  # Default 15s for navigation
        if expected_url:
            # Prefix matching 지원
            if expected_url.endswith("*"):
                prefix = expected_url[:-1]
                try:
                    page.wait_for_function(
                        f'() => (window.location.href || "").startsWith("{prefix}")',
                        timeout=timeout
                    )
                except Exception:
                    # Fallback: check current URL
                    if not (page.url or "").startswith(prefix):
                        raise
            else:
                try:
                    expect(page).to_have_url(expected_url, timeout=timeout)
                except Exception:
                    # Fallback: allow prefix match
                    if not (page.url or "").startswith(expected_url):
                        raise
    elif t == "screenshot":
        # Take a screenshot and save it in the run directory. The name of the screenshot
        # can be specified with the ``name`` parameter; otherwise a default is used.
        name = step.get("name", "shot")
        path = os.path.join(run_dir, f"{name}.png")
        page.screenshot(path=path, full_page=True)
    else:
        raise ValueError(f"Unknown step type: {t}")

    # Apply post-step delay (ms) to emulate recorder playback timing.
    delay_ms = _get_delay_ms(step)
    if delay_ms > 0:
        try:
            page.wait_for_timeout(delay_ms)
        except Exception:
            pass
    return page
