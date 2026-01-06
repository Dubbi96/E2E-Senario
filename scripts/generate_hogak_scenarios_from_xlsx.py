"""
Generate scenario JSON skeletons from the xlsx spec (no external deps).

This script reads `호각_E2E_테스트_시나리오.xlsx` (sheet1 table: A1:M50) and emits
scenario JSON files with `_meta` populated from the spreadsheet.

Note:
- Many rows describe flows that require product-specific selectors and/or real test data.
- For now, we generate runnable templates for search/smoke flows and leave the rest as
  navigation + screenshot (so you can iteratively enrich step selectors).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict


NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _col_to_idx(col: str) -> int:
    n = 0
    for ch in col:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _split_cell_ref(r: str) -> tuple[int, int]:
    col = "".join([c for c in r if c.isalpha()])
    row = "".join([c for c in r if c.isdigit()])
    return _col_to_idx(col), int(row) - 1


def _read_inline_or_shared(z: zipfile.ZipFile, sheet_path: str) -> list[list[str]]:
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in ss.findall("x:si", NS):
            t = si.find("x:t", NS)
            if t is not None:
                shared.append(t.text or "")
            else:
                shared.append("".join((rt.text or "") for rt in si.findall(".//x:t", NS)))

    def cell_text(c: ET.Element) -> str:
        t = c.attrib.get("t")
        if t == "s":
            v = c.find("x:v", NS)
            if v is None:
                return ""
            try:
                return shared[int(v.text or "0")]
            except Exception:
                return v.text or ""
        if t == "inlineStr":
            it = c.find(".//x:t", NS)
            return (it.text or "") if it is not None else ""
        v = c.find("x:v", NS)
        return (v.text or "") if v is not None else ""

    root = ET.fromstring(z.read(sheet_path))
    grid: dict[tuple[int, int], str] = defaultdict(lambda: "")
    max_r = 0
    max_c = 0
    for c in root.findall(".//x:c", NS):
        r = c.attrib.get("r")
        if not r:
            continue
        ci, ri = _split_cell_ref(r)
        grid[(ri, ci)] = cell_text(c)
        max_r = max(max_r, ri)
        max_c = max(max_c, ci)

    rows: list[list[str]] = []
    for ri in range(max_r + 1):
        row = [grid[(ri, ci)] for ci in range(max_c + 1)]
        while row and row[-1] == "":
            row = row[:-1]
        rows.append(row)
    return rows


def _slugify(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^0-9A-Za-z_\\-]+", "", s)
    return s[:80] or "scenario"


def _requires_auth(precond: str, category: str) -> bool:
    if "로그인 상태" in (precond or ""):
        return True
    # heuristic: playback/live often gated
    if category in ("재생", "포인트/결제", "촬영/스트리밍", "설정", "운영자"):
        return True
    return False


def _steps_for_row(scenario_id: str, category: str, name: str) -> list[dict]:
    # Minimal runnable defaults
    base = [
        {"type": "go", "url": "https://hogak.live/main", "delay_ms": 1200},
        {"type": "wait_visible", "text": "경기일정", "timeout": 15000},
    ]
    if category == "검색":
        q = "K리그"
        return base + [
            {"type": "go", "url": "https://hogak.live/search", "delay_ms": 1200},
            {"type": "wait_visible", "text": "검색", "timeout": 15000},
            {"type": "fill", "selector": "input[type='search'], input[placeholder*='검색'], #searchInput", "value": q, "delay_ms": 300},
            {"type": "click", "selectors": ["#btnSearch", "button:has-text('검색')", "button[type='submit']", ".btn_search"]},
            {"type": "wait_visible", "text": "검색결과", "timeout": 15000},
            {"type": "screenshot", "name": f"{scenario_id}_final"},
        ]
    # default template: just screenshot the landing
    return base + [{"type": "screenshot", "name": f"{scenario_id}_final"}]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default="호각_E2E_테스트_시나리오.xlsx")
    ap.add_argument("--out-dir", default="scenarios/hogak_generated_from_xlsx")
    ap.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = ap.parse_args()

    xlsx_path = os.path.abspath(args.xlsx)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    with zipfile.ZipFile(xlsx_path) as z:
        rows = _read_inline_or_shared(z, "xl/worksheets/sheet1.xml")

    if not rows or len(rows) < 2:
        raise RuntimeError("xlsx rows not found")

    header = rows[0]
    col_idx = {name: i for i, name in enumerate(header)}

    def get(row: list[str], key: str) -> str:
        i = col_idx.get(key)
        if i is None or i >= len(row):
            return ""
        return row[i] or ""

    emitted = 0
    for row in rows[1:]:
        scenario_id = get(row, "ScenarioID").strip()
        if not scenario_id:
            continue
        auto = get(row, "자동화 우선(Y/N)").strip().upper()
        if auto != "Y":
            continue

        category = get(row, "구분").strip()
        priority = get(row, "우선순위").strip()
        name = get(row, "시나리오명").strip()
        precond = get(row, "사전조건").strip()

        data = {
            "base_url": "https://hogak.live",
            "requires_auth": _requires_auth(precond, category),
            "_meta": {
                "ScenarioID": scenario_id,
                "구분": category,
                "우선순위": priority,
                "시나리오명": name,
                "목적/범위": get(row, "목적/범위").strip(),
                "사전조건": precond,
                "테스트데이터": get(row, "테스트데이터").strip(),
                "Steps(원문)": get(row, "Steps"),
                "기대결과": get(row, "기대결과").strip(),
                "연동시스템": get(row, "연동시스템").strip(),
                "검증/로그 포인트": get(row, "검증/로그 포인트").strip(),
                "TODO/확인필요": get(row, "TODO/확인필요").strip(),
            },
            "steps": _steps_for_row(scenario_id, category, name),
        }

        fname = f"{scenario_id}__{_slugify(name)}.json"
        out_path = os.path.join(out_dir, fname)
        if (not args.force) and os.path.exists(out_path):
            continue
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        emitted += 1

    print(f"Emitted {emitted} scenario files into: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


