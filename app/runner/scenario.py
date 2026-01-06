"""
Loading of scenario definitions from YAML.

A scenario describes an end-to-end workflow to exercise via the
Playwright browser. Scenarios consist of a base URL and a list of
steps. Each step declares a type (e.g. ``go``, ``click``, ``fill``,
``expect_text``, ``screenshot``) and the parameters required for that
action.
"""

from dataclasses import dataclass
from typing import Any, Dict, List
import json
import os
import yaml

@dataclass
class Scenario:
    # MVP: allow scenarios without base_url (recorder may produce only absolute URLs)
    base_url: str
    steps: List[Dict[str, Any]]
    # Optional top-level config fields (e.g., auth/session injection hints)
    config: Dict[str, Any]

def load_scenario(path: str) -> Scenario:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    ext = os.path.splitext(path)[1].lower()

    if ext == ".json":
        data = json.loads(content)
    else:
        # 기본은 yaml/yml로 처리
        data = yaml.safe_load(content)

    base_url = ""
    steps: list[dict[str, Any]] = []
    config: dict[str, Any] = {}
    if isinstance(data, dict):
        # allow missing base_url for recorder-generated scenarios
        base_url = str(data.get("base_url") or data.get("baseUrl") or "")
        steps = data.get("steps") or []
        # preserve any extra top-level keys for runner configuration
        config = {
            k: v
            for k, v in data.items()
            if k not in ("base_url", "baseUrl", "steps")
        }
    return Scenario(base_url=base_url, steps=list(steps), config=dict(config))