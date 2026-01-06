from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def inject_storage_state_path_into_scenario_file(*, scenario_path: str, storage_state_rel_path: str) -> None:
    """
    Mutate scenario file (json/yaml/yml) to include:
      - requires_auth: true
      - storage_state_path: <rel path>
    """
    ext = os.path.splitext(scenario_path)[1].lower()
    raw = Path(scenario_path).read_text(encoding="utf-8")
    if ext == ".json":
        d = json.loads(raw)
    else:
        import yaml

        d = yaml.safe_load(raw)
    if not isinstance(d, dict):
        d = {"steps": []}
    d["requires_auth"] = True
    d["storage_state_path"] = storage_state_rel_path
    # preserve meta hint
    meta = d.get("_meta")
    if isinstance(meta, dict):
        meta.setdefault("auth_note", "storageState injected by server (auth_state_id)")
    else:
        d["_meta"] = {"auth_note": "storageState injected by server (auth_state_id)"}

    if ext == ".json":
        Path(scenario_path).write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        import yaml

        Path(scenario_path).write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")


