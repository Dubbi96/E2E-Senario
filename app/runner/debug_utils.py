"""
Debug utilities for step execution debugging.
Provides detailed logging and checkpoint tracking.
"""
import json
import os
from typing import Any, Dict, Optional
from playwright.sync_api import Page, Frame


def log_debug_checkpoint(
    run_dir: str,
    step_index: int,
    step_type: str,
    checkpoint_name: str,
    data: Dict[str, Any],
) -> None:
    """Log a debug checkpoint to a JSONL file."""
    debug_log_path = os.path.join(run_dir, "debug_checkpoints.jsonl")
    checkpoint = {
        "step_index": step_index,
        "step_type": step_type,
        "checkpoint": checkpoint_name,
        "data": data,
    }
    try:
        with open(debug_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(checkpoint, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Fail silently if logging fails


def check_element_exists(tgt: Page | Frame, selector: str) -> Dict[str, Any]:
    """Check if element exists in DOM and return detailed info."""
    try:
        locator = tgt.locator(selector).first
        count = locator.count()
        if count == 0:
            return {"exists": False, "count": 0, "visible": False}
        
        try:
            is_visible = locator.is_visible(timeout=100)
        except Exception:
            is_visible = False
        
        try:
            text = locator.text_content(timeout=100) or ""
        except Exception:
            text = ""
        
        try:
            inner_html = tgt.locator(selector).first.evaluate("el => el.innerHTML")[:200]
        except Exception:
            inner_html = ""
        
        return {
            "exists": True,
            "count": count,
            "visible": is_visible,
            "text": text[:100],
            "inner_html_preview": inner_html,
        }
    except Exception as e:
        return {"exists": False, "error": str(e)}


def check_dom_state(page: Page, selector: str, description: str) -> Dict[str, Any]:
    """Check DOM state for a selector and return detailed info."""
    try:
        # Check if selector exists
        count = page.locator(selector).count()
        
        # Try to get text content
        text_content = ""
        try:
            if count > 0:
                text_content = page.locator(selector).first.text_content(timeout=100) or ""
        except Exception:
            pass
        
        # Try to check visibility
        is_visible = False
        try:
            if count > 0:
                is_visible = page.locator(selector).first.is_visible(timeout=100)
        except Exception:
            pass
        
        # Get current URL
        current_url = page.url
        
        return {
            "description": description,
            "selector": selector,
            "count": count,
            "visible": is_visible,
            "text_content": text_content[:200],
            "current_url": current_url,
        }
    except Exception as e:
        return {
            "description": description,
            "selector": selector,
            "error": str(e),
            "current_url": page.url,
        }

