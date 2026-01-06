from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle


@dataclass(frozen=True)
class AllureTestResult:
    name: str
    status: str
    started_epoch_ms: int | None
    stopped_epoch_ms: int | None
    message: str | None


@dataclass(frozen=True)
class FailureContext:
    current_url: str | None
    step_index: int | None
    step_type: str | None
    selector: str | None
    expected_text: str | None
    actual_text: str | None
    raw_step_repr: str | None
    raw_message: str | None


def _pick_korean_font_name() -> str:
    """
    ReportLab 기본 폰트(Times/Helvetica/Courier)는 한글 글리프가 없어 '□'로 깨집니다.
    CID 폰트는 파일(otf/ttf) 없이도 CJK 문자를 렌더링할 수 있어 Docker slim 환경에 유리합니다.

    환경에 따라 특정 CID 폰트가 실패할 수 있어, 여러 후보를 순서대로 시도합니다.
    """
    # 1) 우선: Docker에 설치된 실제 TTF(가독성 좋은 폰트)를 사용 (권장)
    # Debian fonts-nanum 경로를 기준으로 탐색합니다.
    ttf_candidates = [
        ("NanumGothic", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        ("NanumGothic", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        ("NanumGothic", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    ]
    for font_name, path in ttf_candidates:
        try:
            if Path(path).exists():
                pdfmetrics.registerFont(TTFont(font_name, path))
                # bold가 있으면 같이 등록(없어도 무방)
                bold_path = Path(path).with_name("NanumGothicBold.ttf")
                if bold_path.exists():
                    pdfmetrics.registerFont(TTFont("NanumGothicBold", str(bold_path)))
                    try:
                        pdfmetrics.registerFontFamily(
                            "NanumGothic",
                            normal="NanumGothic",
                            bold="NanumGothicBold",
                            italic="NanumGothic",
                            boldItalic="NanumGothicBold",
                        )
                    except Exception:
                        pass
                return font_name
        except Exception:
            continue

    # 2) 폴백: CID 폰트(파일 없이도 동작) — 다만 디자인은 다소 투박할 수 있음
    for font_name in ("HYGothic-Medium", "HYSMyeongJo-Medium"):
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))
            return font_name
        except Exception:
            continue

    # 최후 폴백(이 경우 한글이 깨질 수 있음)
    return "Helvetica"


def _apply_font(styles, font_name: str) -> None:
    # 기본 스타일들(Title/Normal/Heading*/Code)에 폰트를 강제 적용해 한글 깨짐을 방지합니다.
    for key in ("Title", "Normal", "Heading1", "Heading2", "Heading3", "Code"):
        if key in styles:
            styles[key].fontName = font_name
            # Code 스타일은 기본 leading이 낮아 한글이 겹칠 수 있어 약간 키웁니다.
            if key == "Code":
                styles[key].leading = max(styles[key].leading, styles[key].fontSize + 3)
            # CJK 문장 줄바꿈 품질 개선
            styles[key].wordWrap = "CJK"


def _make_kv_table(rows: list[tuple[str, str]], font_name: str):
    data = [["항목", "값"]] + [[k, v] for (k, v) in rows]
    t = Table(data, colWidths=[4.0 * cm, 12.5 * cm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def _make_steps_table(steps: list[dict[str, Any]], font_name: str):
    data: list[list[str]] = [["순서", "type", "주요 필드"]]
    for i, st in enumerate(steps, start=1):
        if not isinstance(st, dict):
            continue
        t = str(st.get("type") or "")
        main = _summarize_step(st).replace(f"type={t} ", "")
        data.append([str(i), t, main])
    table = Table(data, colWidths=[1.2 * cm, 3.0 * cm, 12.3 * cm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _extract_pytest_summary(stdout_text: str) -> str | None:
    # e.g. "1 failed in 7.78s"
    m = re.search(r"^\s*\d+\s+(?:failed|passed|skipped).*$", stdout_text, flags=re.MULTILINE)
    if not m:
        return None
    # 마지막 summary가 더 정확하므로 findall 후 마지막 사용
    allm = re.findall(r"^\s*\d+\s+(?:failed|passed|skipped).*$", stdout_text, flags=re.MULTILINE)
    return allm[-1].strip() if allm else m.group(0).strip()


def _step_detail_lines(step: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    t = step.get("type")
    lines.append(f"type: {t}")
    for k, v in step.items():
        if k == "type":
            continue
        lines.append(f"{k}: {v}")
    return lines


def _is_image_path(p: Path) -> bool:
    return p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def _safe_read_text(path: Path, max_chars: int = 30_000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) <= max_chars:
        return data
    return data[:max_chars] + "\n...\n(truncated)\n"


def _iter_allure_results(allure_dir: Path) -> Iterable[AllureTestResult]:
    if not allure_dir.exists() or not allure_dir.is_dir():
        return []

    results: list[AllureTestResult] = []
    for p in sorted(allure_dir.glob("*-result.json")):
        try:
            obj: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue

        status_details = obj.get("statusDetails") or {}
        msg = status_details.get("message")
        results.append(
            AllureTestResult(
                name=str(obj.get("name") or p.name),
                status=str(obj.get("status") or "unknown"),
                started_epoch_ms=obj.get("start"),
                stopped_epoch_ms=obj.get("stop"),
                message=str(msg) if msg is not None else None,
            )
        )
    return results


def _load_scenario_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    ext = path.suffix.lower()
    try:
        txt = path.read_text(encoding="utf-8")
        if ext == ".json":
            return json.loads(txt)
        # yaml/yml: `app.runner.scenario` uses yaml.safe_load; we mirror that.
        import yaml  # lazy import to avoid hard dependency in report module

        return yaml.safe_load(txt)
    except Exception:
        return None


def _summarize_step(step: dict[str, Any]) -> str:
    t = step.get("type")
    if t == "go":
        return f"type=go url={step.get('url')}"
    if t == "click":
        return f"type=click selector={step.get('selector')}"
    if t == "fill":
        v = step.get("value")
        if v is None:
            v = step.get("text")
        return f"type=fill selector={step.get('selector')} value={v}"
    if t == "expect_text":
        return f"type=expect_text selector={step.get('selector')} text={step.get('text')}"
    if t == "expect_visible":
        return f"type=expect_visible selector={step.get('selector')}"
    if t == "expect_url":
        return f"type=expect_url url={step.get('url')}"
    if t == "screenshot":
        return f"type=screenshot name={step.get('name', 'shot')}"
    return f"type={t} params={ {k: v for k, v in step.items() if k != 'type'} }"


def _load_step_log(run_dir: Path) -> list[dict[str, Any]]:
    p = run_dir / "step_log.jsonl"
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def _load_failure_context(run_dir: Path) -> dict[str, Any] | None:
    p = run_dir / "failure_context.json"
    if not p.exists():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _extract_failure_from_text(*, stdout_text: str, allure_message: str | None) -> FailureContext:
    """
    Try to extract user-facing failure context (URL, failing step, expected/actual)
    from pytest stdout snippet and/or Allure statusDetails.message.
    """
    text = (allure_message or "") + "\n" + (stdout_text or "")

    # URL often appears in pytest stdout as: page = <Page url='https://...'>
    url = None
    m = re.search(r"url='([^']+)'", text)
    if m:
        url = m.group(1)

    # Step repr often appears as: step = {'selector': 'h1', ...}
    raw_step = None
    for m in re.finditer(r"step\s*=\s*(\{.*\})\s*$", text, flags=re.MULTILINE):
        raw_step = m.group(1)

    step_type = selector = expected = actual = None
    if raw_step:
        m = re.search(r"'type'\s*:\s*'([^']+)'", raw_step)
        if m:
            step_type = m.group(1)
        m = re.search(r"'selector'\s*:\s*'([^']+)'", raw_step)
        if m:
            selector = m.group(1)
        m = re.search(r"'text'\s*:\s*'([^']+)'", raw_step)
        if m:
            expected = m.group(1)

    # Allure message usually includes:
    # - Locator expected to contain text 'X'
    # - Actual value: Y
    m = re.search(r"expected to contain text '([^']+)'", text)
    if m and not expected:
        expected = m.group(1)
    m = re.search(r"Actual value:\s*([^\n]+)", text)
    if m:
        actual = m.group(1).strip()

    # Step index: best-effort by matching raw_step against scenario steps later (filled by caller)
    return FailureContext(
        current_url=url,
        step_index=None,
        step_type=step_type,
        selector=selector,
        expected_text=expected,
        actual_text=actual,
        raw_step_repr=raw_step,
        raw_message=allure_message,
    )


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "-"
    # Ensure timezone-aware formatting for consistent display.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _fmt_ms(ms: int | None) -> str:
    if ms is None:
        return "-"
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _duration_ms(start_ms: int | None, stop_ms: int | None) -> str:
    if start_ms is None or stop_ms is None:
        return "-"
    return f"{max(0, stop_ms - start_ms)}ms"


def generate_run_report_pdf(
    *,
    run_id: str,
    status: str,
    scenario_path: str,
    artifact_dir: str,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    exit_code: int | None = None,
    error_message: str | None = None,
    debug: bool = False,
    output_path: str,
) -> str:
    """
    Generate a PDF report for a run by scanning artifacts on disk.

    목표: 시나리오 실행자가 바로 이해할 수 있게
    - "어느 step이, 왜 실패했는지"를 최우선으로 보여주고
    - 내부 로그(서비스 관점)는 debug 옵션에서만 부록으로 제공합니다.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    run_dir = Path(artifact_dir)
    stdout_path = run_dir / "pytest.stdout.log"
    stderr_path = run_dir / "pytest.stderr.log"
    allure_dir = run_dir / "allure-results"

    stdout_text = _safe_read_text(stdout_path)
    stderr_text = _safe_read_text(stderr_path)
    allure_results = list(_iter_allure_results(allure_dir))

    styles = getSampleStyleSheet()
    font_name = _pick_korean_font_name()
    _apply_font(styles, font_name)
    story: list[Any] = []

    story.append(Paragraph("E2E 테스트 실행 리포트", styles["Title"]))
    story.append(Paragraph(f"Run ID: {run_id}", styles["Normal"]))
    story.append(Paragraph(f"생성 시각(UTC): {_fmt_dt(datetime.now(timezone.utc))}", styles["Normal"]))
    story.append(Spacer(1, 0.3 * cm))

    # Scenario overview (user-facing)
    story.append(Spacer(1, 0.4 * cm))

    scenario_obj = _load_scenario_dict(Path(scenario_path))
    steps: list[dict[str, Any]] = []
    base_url = None
    if isinstance(scenario_obj, dict):
        base_url = scenario_obj.get("base_url")
        if isinstance(scenario_obj.get("steps"), list):
            steps = scenario_obj["steps"]  # type: ignore[assignment]

    if base_url or steps:
        # 요약 표(사용자 관점)
        pytest_summary = _extract_pytest_summary(stdout_text) or "-"
        test_name = "-"
        test_start = test_stop = "-"
        duration = "-"
        if allure_results:
            # 첫 result 기준으로 표시(현재는 test_scenario 1개 케이스가 일반적)
            r0 = allure_results[0]
            test_name = r0.name
            test_start = _fmt_ms(r0.started_epoch_ms)
            test_stop = _fmt_ms(r0.stopped_epoch_ms)
            if r0.started_epoch_ms is not None and r0.stopped_epoch_ms is not None:
                duration = f"{(r0.stopped_epoch_ms - r0.started_epoch_ms)/1000.0:.2f}s"

        story.append(
            _make_kv_table(
                [
                    ("상태", status),
                    ("테스트", test_name),
                    ("시작(UTC)", test_start),
                    ("종료(UTC)", test_stop),
                    ("소요시간", duration),
                    ("pytest 요약", pytest_summary),
                    ("base_url", str(base_url or "-")),
                ],
                font_name,
            )
        )
        story.append(Spacer(1, 0.5 * cm))

        story.append(Paragraph("시나리오 단계", styles["Heading2"]))
        story.append(_make_steps_table(steps, font_name))
        story.append(Spacer(1, 0.4 * cm))

        # Execution result table (based on step_log.jsonl)
        step_log = _load_step_log(run_dir)
        if step_log:
            story.append(Paragraph("실행 결과(스텝별 PASS/FAIL + 스크린샷)", styles["Heading2"]))
            items: list[list[Any]] = [["#", "결과", "type", "소요(ms)", "요약", "썸네일(step_*)"]]
            for row in step_log:
                idx = str(row.get("i") or "-")
                st = str(row.get("status") or "-")
                tp = str(row.get("type") or "-")
                dur = str(row.get("duration_ms") or "-")

                summary = "-"
                try:
                    i_int = int(row.get("i") or 0)
                    if 1 <= i_int <= len(steps):
                        summary = _summarize_step(steps[i_int - 1])
                except Exception:
                    pass

                preview: Any = ""
                shot = row.get("screenshot")
                if shot:
                    img_path = run_dir / str(shot)
                    if img_path.exists() and _is_image_path(img_path):
                        try:
                            img = Image(str(img_path))
                            img._restrictSize(3.0 * cm, 3.0 * cm)
                            preview = img
                        except Exception:
                            preview = ""

                items.append([idx, st, tp, dur, summary, preview])

            t = Table(items, colWidths=[1.0 * cm, 2.0 * cm, 2.6 * cm, 2.2 * cm, 8.0 * cm, 3.0 * cm], repeatRows=1)
            t.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), font_name),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("PADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.append(t)
            story.append(Spacer(1, 0.4 * cm))

        # Step-by-step detail (요청: 조합 내 step을 하나하나 자세히)
        story.append(Paragraph("단계 상세(1 step씩)", styles["Heading2"]))
        for i, st in enumerate(steps, start=1):
            if not isinstance(st, dict):
                continue
            story.append(Paragraph(f"Step {i}", styles["Heading3"]))
            story.append(Preformatted("\n".join(_step_detail_lines(st)), styles["Code"]))

            # screenshot step이면 해당 이미지 파일을 inline으로 첨부
            if st.get("type") == "screenshot":
                name = st.get("name", "shot")
                img_path = run_dir / f"{name}.png"
                if img_path.exists():
                    try:
                        img = Image(str(img_path))
                        img._restrictSize(18.5 * cm, 18.0 * cm)
                        story.append(img)
                    except Exception:
                        pass
            story.append(Spacer(1, 0.3 * cm))

    # Failure first (user-facing)
    allure_message = None
    for r in allure_results:
        if r.status.lower() == "failed" and r.message:
            allure_message = r.message
            break
    failure = _extract_failure_from_text(stdout_text=stdout_text, allure_message=allure_message)

    # Prefer runner-generated failure context if available (much more accurate than regex)
    fc = _load_failure_context(run_dir)
    if fc:
        try:
            failure = FailureContext(
                current_url=str(fc.get("url") or failure.current_url or ""),
                step_index=int(fc.get("step_index")) if fc.get("step_index") else None,
                step_type=str((fc.get("step") or {}).get("type") or failure.step_type or ""),
                selector=str((fc.get("step") or {}).get("selector") or failure.selector or ""),
                expected_text=(fc.get("step") or {}).get("text") if isinstance(fc.get("step"), dict) else failure.expected_text,
                actual_text=failure.actual_text,
                raw_step_repr=json.dumps(fc.get("step"), ensure_ascii=False) if fc.get("step") is not None else failure.raw_step_repr,
                raw_message=fc.get("error") or failure.raw_message,
            )
        except Exception:
            pass

    # Try to determine failing step index by matching type/selector/text against scenario steps.
    step_index = None
    if steps and failure.step_type:
        for i, st in enumerate(steps, start=1):
            if not isinstance(st, dict):
                continue
            if st.get("type") != failure.step_type:
                continue
            if failure.selector and st.get("selector") != failure.selector:
                continue
            if failure.expected_text and st.get("text") != failure.expected_text:
                continue
            step_index = i
            break
    failure = FailureContext(
        current_url=failure.current_url,
        step_index=step_index,
        step_type=failure.step_type,
        selector=failure.selector,
        expected_text=failure.expected_text,
        actual_text=failure.actual_text,
        raw_step_repr=failure.raw_step_repr,
        raw_message=failure.raw_message,
    )

    if status.upper() in ("FAILED", "FAIL"):
        story.append(Paragraph("실패 원인(핵심)", styles["Heading2"]))
        core_lines: list[str] = []
        if failure.step_index:
            core_lines.append(f"- 실패한 step: {failure.step_index}번")
        if failure.step_type:
            core_lines.append(f"- step type: {failure.step_type}")
        if failure.current_url:
            core_lines.append(f"- 실패 시점 URL: {failure.current_url}")
        if failure.selector:
            core_lines.append(f"- 대상 selector: {failure.selector}")
        if failure.expected_text is not None or failure.actual_text is not None:
            core_lines.append(f"- 기대값: {failure.expected_text if failure.expected_text is not None else '-'}")
            core_lines.append(f"- 실제값: {failure.actual_text if failure.actual_text is not None else '-'}")
        story.append(Preformatted("\n".join(core_lines) if core_lines else "-", styles["Code"]))
        story.append(Spacer(1, 0.4 * cm))

        # A short excerpt is more useful than dumping everything.
        if failure.raw_message:
            first_block = "\n".join(failure.raw_message.splitlines()[:20])
            story.append(Paragraph("실패 원인 요약(발췌)", styles["Heading3"]))
            story.append(Preformatted(first_block, styles["Code"]))
            story.append(Spacer(1, 0.4 * cm))

    # Screenshots (best-effort)

    for candidate in ("home.png", "FAIL.png"):
        p = run_dir / candidate
        if not p.exists():
            continue
        label = "성공 시점" if candidate.lower().startswith("home") else "실패 시점 자동 캡처"
        story.append(Paragraph(f"스크린샷: {candidate} ({label})", styles["Heading2"]))
        try:
            img = Image(str(p))
            img._restrictSize(18.5 * cm, 24.0 * cm)  # fit within A4 with margins
            story.append(img)
        except Exception:
            story.append(Preformatted(f"(failed to embed image: {candidate})", styles["Code"]))
        story.append(Spacer(1, 0.4 * cm))

    # Artifact list table
    try:
        story.append(Paragraph("아티팩트 목록", styles["Heading2"]))
        items: list[list[Any]] = [["파일명", "크기(bytes)", "미리보기"]]
        for f in sorted(run_dir.iterdir()):
            if not f.is_file():
                continue

            preview: Any = ""
            if _is_image_path(f):
                try:
                    img = Image(str(f))
                    # 표 안에서 한눈에 보이도록 작은 썸네일로 제한
                    img._restrictSize(3.2 * cm, 3.2 * cm)
                    preview = img
                except Exception:
                    preview = ""

            items.append([f.name, str(f.stat().st_size), preview])

        t = Table(items, colWidths=[8.5 * cm, 3.0 * cm, 5.0 * cm], repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (2, 1), (2, -1), "MIDDLE"),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 0.4 * cm))
    except Exception:
        pass

    if debug:
        story.append(Paragraph("부록(디버그)", styles["Heading2"]))
        story.append(Preformatted(f"- Artifact dir: {artifact_dir}", styles["Code"]))
        story.append(Spacer(1, 0.2 * cm))
        if error_message:
            story.append(Paragraph("DB error_message", styles["Heading3"]))
            story.append(Preformatted(error_message, styles["Code"]))
            story.append(Spacer(1, 0.3 * cm))
        if stdout_text:
            story.append(Paragraph("pytest.stdout.log (truncated)", styles["Heading3"]))
            story.append(Preformatted(stdout_text, styles["Code"]))
            story.append(Spacer(1, 0.3 * cm))
        if stderr_text.strip():
            story.append(Paragraph("pytest.stderr.log (truncated)", styles["Heading3"]))
            story.append(Preformatted(stderr_text, styles["Code"]))
            story.append(Spacer(1, 0.3 * cm))

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"Run Report {run_id}",
    )
    doc.build(story)
    return str(out)


