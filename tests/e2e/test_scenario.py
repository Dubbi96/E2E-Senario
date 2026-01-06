"""
Test runner that executes a YAML-defined scenario using Playwright.

This test expects a ``--scenario`` option pointing at a YAML file. The
scenario is loaded and then each step is executed against a headless
Chromium browser. If any step raises an exception, a failure
screenshot is captured. Any exceptions propagate to pytest which
records the failure.
"""

import json
import os
import time
import base64
from pathlib import Path
from playwright.sync_api import sync_playwright

from app.runner.scenario import load_scenario
from app.runner.playwright_steps import run_step
from app.runner.artifact_collector import start_tracing, stop_tracing, collect_failure_artifacts

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
# #endregion


def _infer_run_dir(scenario_path: str) -> str:
    """Infer the run directory from the scenario path."""
    # For the MVP we assume scenarios live inside a run directory under ``artifacts/<run_id>``.
    return os.path.dirname(scenario_path)

def _maybe_decode_b64_to_file(b64_value: str, out_path: str) -> str:
    data = base64.b64decode(b64_value.encode("utf-8"))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


def _resolve_storage_state(scenario_path: str, run_dir: str, scenario_config: dict) -> str | dict | None:
    """
    Resolve Playwright storage_state source (path or dict).

    Priority:
    1) E2E_STORAGE_STATE_B64 (base64-encoded JSON file contents)
    2) E2E_STORAGE_STATE_PATH
    3) scenario.config.storage_state_path (relative to scenario file dir allowed)
    4) scenario.config.storage_state (inline dict)
    """
    b64 = os.getenv("E2E_STORAGE_STATE_B64", "").strip()
    if b64:
        return _maybe_decode_b64_to_file(b64, os.path.join(run_dir, "storage_state.from_b64.json"))

    env_path = os.getenv("E2E_STORAGE_STATE_PATH", "").strip()
    if env_path:
        return env_path

    cfg_path = str(scenario_config.get("storage_state_path") or scenario_config.get("storageStatePath") or "").strip()
    if cfg_path:
        # allow relative path from scenario directory
        if not os.path.isabs(cfg_path):
            cfg_path = os.path.abspath(os.path.join(os.path.dirname(scenario_path), cfg_path))
        return cfg_path

    cfg_state = scenario_config.get("storage_state") or scenario_config.get("storageState")
    if isinstance(cfg_state, dict):
        return cfg_state

    return None


def test_scenario(scenario_path: str) -> None:
    """
    Playwright-based test that exercises an entire scenario.

    :param scenario_path: Path to the YAML file describing the scenario
    :raises AssertionError: Propagated from any failing step
    """
    scenario = load_scenario(scenario_path)
    run_dir = _infer_run_dir(scenario_path)
    os.makedirs(run_dir, exist_ok=True)

    with sync_playwright() as p:
        # Use simple browser launch matching crawlHogak_lima.py (proven to work reliably)
        headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower()
        headless_mode = headless_env in ("1", "true", "yes", "y")
        browser = p.chromium.launch(headless=headless_mode)
        
        # Simple context setup matching crawlHogak_lima.py
        # CRITICAL: Fix environment to match local/Docker consistency
        context_options = {
            "viewport": {"width": 1440, "height": 900},  # Match crawlHogak_lima.py
            "locale": "ko-KR",  # Korean locale for consistent rendering
            "timezone_id": "Asia/Seoul",  # Korean timezone
            # Use consistent user agent (Chrome on macOS for consistency)
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        requires_auth = bool(scenario.config.get("requires_auth") or scenario.config.get("requiresAuth"))
        storage_state = _resolve_storage_state(scenario_path, run_dir, scenario.config)
        if requires_auth and not storage_state:
            raise RuntimeError(
                "이 시나리오는 로그인 세션이 필요합니다(requires_auth=true). "
                "Apple 2FA/팝업 로그인을 런타임에 수행하지 않기 위해, "
                "Playwright storageState를 주입해주세요. "
                "방법: (1) E2E_STORAGE_STATE_PATH=/abs/path/to/storage_state.json 또는 "
                "(2) E2E_STORAGE_STATE_B64=<base64(json)> 를 설정하세요."
            )
        if storage_state:
            context_options["storage_state"] = storage_state
        # base_url is optional for recorder-generated scenarios (absolute URLs in steps)
        if scenario.base_url:
            context_options["base_url"] = scenario.base_url
        context = browser.new_context(**context_options)
        page = context.new_page()
        ctx = {"main_page": page, "page_stack": [page]}
        
        # Tracing 시작 (실패 시 디버깅용)
        start_tracing(context, run_dir)

        # ---- Network burst screenshot (xhr/fetch): per-page debounce ----
        def setup_network_burst_screenshot(target_page):
            quiet_s = 0.8  # "burst" quiet window (seconds). Tune if needed.
            last_req_ts = 0.0
            net_pending = False
            net_seq = 0

            def _on_request(req) -> None:
                nonlocal last_req_ts, net_pending
                try:
                    if req.resource_type not in ("xhr", "fetch"):
                        return
                except Exception:
                    return
                net_pending = True
                last_req_ts = time.monotonic()

            target_page.on("request", _on_request)

            def flush() -> None:
                nonlocal net_pending, net_seq
                if not net_pending:
                    return
                while True:
                    delta = time.monotonic() - last_req_ts
                    if delta >= quiet_s:
                        break
                    ms = max(50, int((quiet_s - delta) * 1000))
                    try:
                        target_page.wait_for_timeout(ms)
                    except Exception:
                        break
                net_seq += 1
                try:
                    target_page.screenshot(
                        path=os.path.join(run_dir, f"net_burst_{net_seq:03d}.png"),
                        full_page=True,
                    )
                except Exception:
                    pass
                net_pending = False

            return flush

        flush_network_burst_screenshot = setup_network_burst_screenshot(page)

        try:
            for i, step in enumerate(scenario.steps, start=1):
                started = time.monotonic()
                stype = str(step.get("type") or "step")
                shot_name = None
                # #region agent log
                _write_debug_log(
                    f"test_scenario.py:{111}",
                    f"Step {i} start",
                    {"step_index": i, "step_type": stype, "headless_mode": headless_mode},
                    "A"
                )
                # #endregion
                # Add step index to step dict for debug logging
                step_with_index = dict(step)
                step_with_index["_step_index"] = i
                # Get next step for click operations (to wait for popup to appear)
                next_step = scenario.steps[i] if i < len(scenario.steps) else None
                try:
                    # #region agent log
                    step_start_time = time.monotonic()
                    _write_debug_log(
                        f"test_scenario.py:{121}",
                        f"Step {i} run_step before",
                        {"step_index": i, "step_type": stype, "next_step_type": next_step.get("type") if next_step else None},
                        "A"
                    )
                    # #endregion
                    new_page = run_step(page, step_with_index, run_dir, ctx=ctx, next_step=next_step)
                    # #region agent log
                    step_end_time = time.monotonic()
                    step_duration = step_end_time - step_start_time
                    _write_debug_log(
                        f"test_scenario.py:{127}",
                        f"Step {i} run_step after",
                        {"step_index": i, "step_type": stype, "duration_ms": step_duration * 1000},
                        "A"
                    )
                    # #endregion
                    if new_page is not page:
                        # Switch current page; re-init per-page network burst tracker.
                        page = new_page
                        flush_network_burst_screenshot = setup_network_burst_screenshot(page)
                    status = "PASSED"
                    
                    # CRITICAL: Extension 방식으로 변경
                    # Extension은 각 step의 delay_ms만큼만 대기 (추가 대기 없음)
                    # run_step 내부에서 delay_ms를 처리하므로 여기서는 추가 대기 불필요
                    # Extension 재생 방식을 그대로 따르므로 추가 대기 제거
                except Exception as e:
                    status = "FAILED"
                    
                    # 실패 시 디버깅 아티팩트 수집 (표준화)
                    try:
                        artifacts = collect_failure_artifacts(
                            page=page,
                            context=context,
                            run_dir=run_dir,
                            step_index=i,
                            step_type=stype,
                            error=e,
                        )
                        # best-effort failure context for reporting
                        Path(os.path.join(run_dir, "failure_context.json")).write_text(
                            json.dumps(
                                {
                                    "step_index": i,
                                    "step": step,
                                    "url": getattr(page, "url", None),
                                    "error": str(e),
                                    "artifacts": artifacts,
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    except Exception:
                        pass
                    
                    # On failure capture a full-page screenshot for debugging
                    try:
                        page.screenshot(path=os.path.join(run_dir, "FAIL.png"), full_page=True)
                    except Exception:
                        pass
                    # Also capture the failing-step screenshot (if possible)
                    try:
                        page.screenshot(path=os.path.join(run_dir, f"step_{i:03d}_{stype}_FAIL.png"), full_page=True)
                        shot_name = f"step_{i:03d}_{stype}_FAIL.png"
                    except Exception:
                        pass
                    # write step log then re-raise
                    dur_ms = int((time.monotonic() - started) * 1000)
                    try:
                        with open(os.path.join(run_dir, "step_log.jsonl"), "a", encoding="utf-8") as f:
                            f.write(
                                json.dumps(
                                    {
                                        "i": i,
                                        "type": stype,
                                        "status": status,
                                        "duration_ms": dur_ms,
                                        "screenshot": shot_name,
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                    except Exception:
                        pass
                    raise

                # Auto-screenshot after each step (enter page / action / click / assertions)
                if stype != "screenshot":
                    # Use domcontentloaded only - networkidle can cause page reloads that close dropdowns
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=1500)
                    except Exception:
                        pass
                    shot_name = f"step_{i:03d}_{stype}.png"
                    try:
                        page.screenshot(path=os.path.join(run_dir, shot_name), full_page=True)
                    except Exception:
                        shot_name = None

                dur_ms = int((time.monotonic() - started) * 1000)
                try:
                    with open(os.path.join(run_dir, "step_log.jsonl"), "a", encoding="utf-8") as f:
                        f.write(
                            json.dumps(
                                {
                                    "i": i,
                                    "type": stype,
                                    "status": status,
                                    "duration_ms": dur_ms,
                                    "screenshot": shot_name,
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                except Exception:
                    pass

                # Additionally, if there was an API request burst, capture 1 screenshot per burst.
                flush_network_burst_screenshot()
        except Exception:
            raise
        finally:
            # Final flush (in case last burst happens at the end)
            flush_network_burst_screenshot()
            # Tracing 중지 및 저장
            stop_tracing(context, run_dir)
            try:
                context.close()
            except Exception:
                pass
            browser.close()
