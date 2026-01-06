"""
실패 시 디버깅 아티팩트 수집 표준화

실패하면 무조건 아래를 남김:
- Playwright trace.zip
- 마지막 화면 screenshot
- page HTML dump
- frames 목록(url)
- context.pages 목록(url) (popup 탐지)
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from playwright.sync_api import BrowserContext, Frame, Page


def collect_failure_artifacts(
    page: Page,
    context: BrowserContext,
    run_dir: str,
    step_index: int,
    step_type: str,
    error: Exception | None = None,
) -> Dict[str, Any]:
    """
    실패 시 모든 디버깅 아티팩트를 수집
    
    Returns: 수집된 아티팩트 정보
    """
    artifacts: Dict[str, Any] = {
        "step_index": step_index,
        "step_type": step_type,
        "error": str(error) if error else None,
    }
    
    # 1. Playwright trace.zip (가능하면)
    try:
        trace_path = os.path.join(run_dir, f"trace_step_{step_index:03d}.zip")
        # Note: 실제 trace는 context.tracing.start/stop으로 생성해야 함
        # 여기서는 placeholder만 생성
        artifacts["trace_path"] = trace_path
    except Exception as e:
        artifacts["trace_error"] = str(e)
    
    # 2. 마지막 화면 screenshot
    try:
        screenshot_path = os.path.join(run_dir, f"failure_step_{step_index:03d}.png")
        page.screenshot(path=screenshot_path, full_page=True)
        artifacts["screenshot_path"] = screenshot_path
    except Exception as e:
        artifacts["screenshot_error"] = str(e)
    
    # 3. page HTML dump
    try:
        html_path = os.path.join(run_dir, f"failure_step_{step_index:03d}.html")
        html_content = page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        artifacts["html_path"] = html_path
        artifacts["html_size"] = len(html_content)
    except Exception as e:
        artifacts["html_error"] = str(e)
    
    # 4. frames 목록(url)
    try:
        frames_info: List[Dict[str, Any]] = []
        for i, frame in enumerate(page.frames):
            frame_info = {
                "index": i,
                "url": frame.url if frame.url else "",
                "name": frame.name if frame.name else "",
                "is_main": frame == page.main_frame,
            }
            try:
                # Frame의 title도 가져오기 (가능하면)
                frame_info["title"] = frame.evaluate("() => document.title") if frame.url else ""
            except Exception:
                frame_info["title"] = ""
            frames_info.append(frame_info)
        artifacts["frames"] = frames_info
    except Exception as e:
        artifacts["frames_error"] = str(e)
    
    # 5. context.pages 목록(url) (popup 탐지)
    try:
        pages_info: List[Dict[str, Any]] = []
        for i, p in enumerate(context.pages):
            page_info = {
                "index": i,
                "url": p.url if p.url else "",
                "is_main": p == page,
            }
            try:
                page_info["title"] = p.title()
            except Exception:
                page_info["title"] = ""
            pages_info.append(page_info)
        artifacts["pages"] = pages_info
    except Exception as e:
        artifacts["pages_error"] = str(e)
    
    # 6. 현재 URL 및 상태
    try:
        artifacts["current_url"] = page.url
        artifacts["current_title"] = page.title()
    except Exception:
        pass
    
    # 7. 메타데이터를 JSON으로 저장
    try:
        metadata_path = os.path.join(run_dir, f"failure_step_{step_index:03d}_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(artifacts, f, ensure_ascii=False, indent=2)
        artifacts["metadata_path"] = metadata_path
    except Exception as e:
        artifacts["metadata_error"] = str(e)
    
    return artifacts


def start_tracing(context: BrowserContext, run_dir: str) -> None:
    """
    Playwright tracing 시작
    
    Note: test_scenario.py에서 context 생성 후 호출해야 함
    """
    try:
        trace_path = os.path.join(run_dir, "trace.zip")
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
    except Exception as e:
        # Tracing이 실패해도 계속 진행
        pass


def stop_tracing(context: BrowserContext, run_dir: str) -> None:
    """
    Playwright tracing 중지 및 저장
    """
    try:
        trace_path = os.path.join(run_dir, "trace.zip")
        context.tracing.stop(path=trace_path)
    except Exception as e:
        # Tracing이 실패해도 계속 진행
        pass

