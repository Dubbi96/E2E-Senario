from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, KeepInFrame, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.reporting.pdf_report import (
    _apply_font,
    _extract_failure_from_text,
    _extract_pytest_summary,
    _fmt_dt,
    _iter_allure_results,
    _load_scenario_dict,
    _pick_korean_font_name,
)
from app.reporting.pdf_report import generate_run_report_pdf


def _thumb(path: Path, w_cm: float = 2.6, h_cm: float = 2.6) -> Image:
    img = Image(str(path))
    img._restrictSize(w_cm * cm, h_cm * cm)
    return img


def _collect_case_images(case_dir: Path) -> list[Path]:
    # Prefer step_*.png and home/FAIL ordering for quick scan.
    imgs = [p for p in case_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png"]

    def key(p: Path) -> tuple[int, str]:
        name = p.name.lower()
        if name.startswith("fail"):
            return (2, name)
        if name.startswith("home"):
            return (0, name)
        if name.startswith("step_"):
            return (1, name)
        return (3, name)

    return sorted(imgs, key=key)


def _load_failure_context(case_dir: Path) -> dict[str, Any] | None:
    p = case_dir / "failure_context.json"
    if not p.exists():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _thumb_grid(image_paths: list[Path], font_name: str, *, max_images: int = 8, max_h_cm: float = 4.6) -> Any:
    if not image_paths:
        return ""
    # Cover summary must never overflow a page. Limit count + force-fit the grid into a fixed box.
    # (Some runs may produce dozens of step_*.png, which would otherwise create a huge table cell.)
    image_paths = list(image_paths)[: max(0, int(max_images or 0))]
    cols = 4
    rows: list[list[Any]] = []
    row: list[Any] = []
    for p in image_paths:
        try:
            row.append(_thumb(p))
        except Exception:
            row.append("")
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        # pad
        while len(row) < cols:
            row.append("")
        rows.append(row)

    t = Table(rows, colWidths=[2.8 * cm] * cols)
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("PADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    # Force-fit into the cover table cell (prevents reportlab LayoutError).
    return KeepInFrame(7.5 * cm, max_h_cm * cm, [t], mode="shrink")


def generate_suite_report_pdf(
    *,
    suite_id: str,
    status: str,
    created_at: datetime | None,
    started_at: datetime | None,
    finished_at: datetime | None,
    suite_dir: str,
    cases: list[dict],
    output_path: str,
) -> str:
    """
    Generate a suite-level PDF report that summarizes all cases and embeds thumbnails.

    `cases` expects dicts containing:
      - case_index (int), case_id (str), status (str), started_at/finished_at (datetime|None),
        artifact_dir (str), combined_scenario_path (str)
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    font_name = _pick_korean_font_name()
    _apply_font(styles, font_name)

    # 1) Cover PDF (summary + thumbnails table + failure highlight)
    cover_path = Path(suite_dir) / "_suite_cover.pdf"
    story: list[Any] = []
    story.append(Paragraph("E2E Suite 실행 리포트", styles["Title"]))
    story.append(Paragraph(f"Suite Run ID: {suite_id}", styles["Normal"]))
    story.append(Paragraph(f"생성 시각(UTC): {_fmt_dt(datetime.now(timezone.utc))}", styles["Normal"]))
    story.append(Spacer(1, 0.3 * cm))

    # Summary table
    summary_rows = [
        ("상태", status),
        ("생성(UTC)", _fmt_dt(created_at)),
        ("시작(UTC)", _fmt_dt(started_at)),
        ("종료(UTC)", _fmt_dt(finished_at)),
        ("케이스 수", str(len(cases))),
        ("아티팩트 디렉터리", suite_dir),
    ]
    summary = Table([["항목", "값"]] + summary_rows, colWidths=[4.0 * cm, 12.5 * cm])
    summary.setStyle(
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
    story.append(summary)
    story.append(Spacer(1, 0.5 * cm))

    # Case summary table with thumbnails + failure highlight
    story.append(Paragraph("케이스별 요약", styles["Heading2"]))
    header = ["#", "상태", "소요", "실패 step", "미리보기(FAIL/home/step_*)"]
    rows: list[list[Any]] = [header]

    for c in sorted(cases, key=lambda x: x["case_index"]):
        case_dir = Path(c["artifact_dir"])
        stdout = (case_dir / "pytest.stdout.log").read_text(encoding="utf-8", errors="replace") if (case_dir / "pytest.stdout.log").exists() else ""
        allure_dir = case_dir / "allure-results"
        allure_results = list(_iter_allure_results(allure_dir))
        allure_message = None
        for r in allure_results:
            if r.status.lower() == "failed" and r.message:
                allure_message = r.message
                break

        failure = _extract_failure_from_text(stdout_text=stdout, allure_message=allure_message)

        # try match step index against combined scenario
        step_index = None
        scenario_obj = _load_scenario_dict(Path(c["combined_scenario_path"]))
        steps = []
        if isinstance(scenario_obj, dict) and isinstance(scenario_obj.get("steps"), list):
            steps = scenario_obj["steps"]
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

        # Prefer runner-generated failure context (more accurate than regex matching)
        fc = _load_failure_context(case_dir)
        if fc and fc.get("step_index"):
            try:
                step_index = int(fc["step_index"])
            except Exception:
                pass
            try:
                if fc.get("url"):
                    failure = failure.__class__(
                        current_url=str(fc.get("url")),
                        step_index=step_index,
                        step_type=str((fc.get("step") or {}).get("type") or failure.step_type or ""),
                        selector=str((fc.get("step") or {}).get("selector") or failure.selector or ""),
                        expected_text=(fc.get("step") or {}).get("text") if isinstance(fc.get("step"), dict) else failure.expected_text,
                        actual_text=failure.actual_text,
                        raw_step_repr=failure.raw_step_repr,
                        raw_message=fc.get("error") or failure.raw_message,
                    )
            except Exception:
                pass

        dur = "-"
        if c["started_at"] and c["finished_at"]:
            dur = f"{(c['finished_at'] - c['started_at']).total_seconds():.2f}s"

        fail_str = ""
        if c["status"] == "FAILED":
            pieces = []
            if step_index:
                pieces.append(f"{step_index}번")
            if failure.step_type:
                pieces.append(failure.step_type)
            if failure.selector:
                pieces.append(f"sel={failure.selector}")
            fail_str = " / ".join(pieces) if pieces else "(unknown)"

        thumbs = _thumb_grid(_collect_case_images(case_dir), font_name)
        rows.append([str(c["case_index"]), c["status"], dur, fail_str, thumbs])

    t = Table(rows, colWidths=[1.0 * cm, 2.0 * cm, 2.0 * cm, 4.0 * cm, 7.5 * cm], repeatRows=1)
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
    story.append(Spacer(1, 0.5 * cm))

    # Optional per-case failure detail (highlight)
    for c in sorted(cases, key=lambda x: x["case_index"]):
        if c["status"] != "FAILED":
            continue
        case_dir = Path(c["artifact_dir"])
        stdout = (case_dir / "pytest.stdout.log").read_text(encoding="utf-8", errors="replace") if (case_dir / "pytest.stdout.log").exists() else ""
        summary = _extract_pytest_summary(stdout) or "-"
        story.append(Paragraph(f"실패 케이스 상세: {c['case_index']}번", styles["Heading2"]))
        story.append(Paragraph(f"pytest 요약: {summary}", styles["Normal"]))

        allure_dir = case_dir / "allure-results"
        allure_results = list(_iter_allure_results(allure_dir))
        allure_message = None
        for r in allure_results:
            if r.status.lower() == "failed" and r.message:
                allure_message = r.message
                break
        failure = _extract_failure_from_text(stdout_text=stdout, allure_message=allure_message)

        lines = []
        if failure.current_url:
            lines.append(f"- URL: {failure.current_url}")
        if failure.step_type:
            lines.append(f"- step type: {failure.step_type}")
        if failure.selector:
            lines.append(f"- selector: {failure.selector}")
        if failure.expected_text is not None:
            lines.append(f"- 기대값: {failure.expected_text}")
        if failure.actual_text is not None:
            lines.append(f"- 실제값: {failure.actual_text}")
        detail = Table([["항목", "값"]] + [[x.split(": ", 1)[0].lstrip("- "), x.split(": ", 1)[1] if ": " in x else x] for x in lines], colWidths=[4.0 * cm, 12.5 * cm])
        detail.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FCE4E4")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(detail)
        story.append(Spacer(1, 0.3 * cm))

        # include FAIL.png if present
        fail_png = case_dir / "FAIL.png"
        if fail_png.exists():
            story.append(Paragraph("FAIL.png (실패 시점)", styles["Heading3"]))
            try:
                img = Image(str(fail_png))
                img._restrictSize(18.5 * cm, 22.0 * cm)
                story.append(img)
            except Exception:
                pass
            story.append(Spacer(1, 0.5 * cm))

    cover_doc = SimpleDocTemplate(
        str(cover_path),
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"Suite Cover {suite_id}",
    )
    cover_doc.build(story)

    # 2) Per-case detailed reports (reuse the existing run report generator)
    case_report_paths: list[Path] = []
    for c in sorted(cases, key=lambda x: x["case_index"]):
        case_dir = Path(c["artifact_dir"])
        case_pdf = case_dir / "report.pdf"
        # Prefer existing report.pdf produced during execution (fast + avoids re-generation failures)
        if case_pdf.exists():
            case_report_paths.append(case_pdf)
            continue
        try:
            generate_run_report_pdf(
                run_id=f"{suite_id}:{c['case_index']}:{c['case_id']}",
                status=c["status"],
                scenario_path=c["combined_scenario_path"],
                artifact_dir=c["artifact_dir"],
                created_at=None,
                started_at=c.get("started_at"),
                finished_at=c.get("finished_at"),
                exit_code=None,
                error_message=c.get("error_message"),
                debug=True,
                output_path=str(case_pdf),
            )
            if case_pdf.exists():
                case_report_paths.append(case_pdf)
        except Exception as e:
            # If a case report fails to generate, log why and keep going.
            try:
                (case_dir / "_case_report_error.txt").write_text(
                    f"{e}\n\n{traceback.format_exc()}",
                    encoding="utf-8",
                )
            except Exception:
                pass
            continue

    # 3) Merge cover + case reports into suite_report.pdf
    # Use PdfWriter(add_page) instead of PdfMerger for maximum robustness.
    try:
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter()
        for src in [cover_path, *case_report_paths]:
            if not src.exists():
                continue
            reader = PdfReader(str(src))
            for pg in reader.pages:
                writer.add_page(pg)
        with open(out, "wb") as f:
            writer.write(f)
    except Exception as e:
        # Keep cover-only report, but write debug info next to it.
        try:
            (Path(suite_dir) / "_suite_merge_error.txt").write_text(
                f"{e}\n\n{traceback.format_exc()}",
                encoding="utf-8",
            )
        except Exception:
            pass
        try:
            # Keep cover as the output if merge failed.
            cover_path.replace(out)
        except Exception:
            pass

    return str(out)


