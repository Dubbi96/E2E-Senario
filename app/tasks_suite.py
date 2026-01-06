from __future__ import annotations

import os
import subprocess
import traceback
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.db.models import SuiteCase, SuiteRun, SuiteStatus
from app.db.session import SessionLocal
from app.reporting.suite_pdf_report import generate_suite_report_pdf
from app.tasks_webhook import send_suite_webhook


@celery_app.task(name="execute_suite_case")
def execute_suite_case(case_id: str) -> dict:
    db: Session = SessionLocal()
    try:
        case = db.get(SuiteCase, case_id)
        if not case:
            return {"case_id": case_id, "error": "case not found"}

        suite = db.get(SuiteRun, case.suite_run_id)
        if suite and suite.started_at is None:
            suite.started_at = datetime.now(timezone.utc)
            suite.status = SuiteStatus.RUNNING.value
            db.commit()

        case.status = SuiteStatus.RUNNING.value
        case.started_at = datetime.now(timezone.utc)
        db.commit()

        run_dir = case.artifact_dir
        scenario_path = case.combined_scenario_path
        allure_dir = os.path.join(run_dir, "allure-results")
        os.makedirs(allure_dir, exist_ok=True)

        cmd = [
            "pytest",
            "-q",
            "tests/e2e/test_scenario.py",
            f"--scenario={scenario_path}",
            f"--alluredir={allure_dir}",
        ]

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Prepare environment variables - ensure PLAYWRIGHT_HEADLESS is set
        env = os.environ.copy()
        if "PLAYWRIGHT_HEADLESS" not in env:
            env["PLAYWRIGHT_HEADLESS"] = "true"
        proc = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, env=env)

        with open(os.path.join(run_dir, "pytest.stdout.log"), "w", encoding="utf-8") as f:
            f.write(proc.stdout)
        with open(os.path.join(run_dir, "pytest.stderr.log"), "w", encoding="utf-8") as f:
            f.write(proc.stderr)

        passed = proc.returncode == 0
        case.status = SuiteStatus.PASSED.value if passed else SuiteStatus.FAILED.value
        case.exit_code = proc.returncode
        case.finished_at = datetime.now(timezone.utc)
        db.commit()
        return {"case_id": case_id, "exit_code": proc.returncode}
    except Exception as e:
        err = f"{e}\n{traceback.format_exc()}"
        case = db.get(SuiteCase, case_id)
        if case:
            case.status = SuiteStatus.FAILED.value
            case.exit_code = None
            case.error_message = err
            case.finished_at = datetime.now(timezone.utc)
            db.commit()
        return {"case_id": case_id, "error": str(e)}
    finally:
        db.close()


@celery_app.task(name="finalize_suite_run")
def finalize_suite_run(suite_run_id: str, results: list[dict] | None = None) -> dict:
    db: Session = SessionLocal()
    try:
        suite = db.get(SuiteRun, suite_run_id)
        if not suite:
            return {"suite_run_id": suite_run_id, "error": "suite not found"}

        cases = db.query(SuiteCase).filter(SuiteCase.suite_run_id == suite.id).all()
        if suite.started_at is None:
            suite.started_at = min((c.started_at for c in cases if c.started_at), default=datetime.now(timezone.utc))

        all_finished = all(c.status in (SuiteStatus.PASSED.value, SuiteStatus.FAILED.value) for c in cases)
        if all_finished:
            suite.finished_at = datetime.now(timezone.utc)
            suite.status = SuiteStatus.PASSED.value if all(c.status == SuiteStatus.PASSED.value for c in cases) else SuiteStatus.FAILED.value
        else:
            suite.status = SuiteStatus.RUNNING.value

        # Auto-generate suite report once fully finished.
        if all_finished:
            pdf_path = os.path.join(suite.artifact_dir, "suite_report.pdf")
            case_dicts = [
                {
                    "case_index": c.case_index,
                    "case_id": c.id,
                    "status": c.status,
                    "started_at": c.started_at,
                    "finished_at": c.finished_at,
                    "error_message": c.error_message,
                    "artifact_dir": c.artifact_dir,
                    "combined_scenario_path": c.combined_scenario_path,
                }
                for c in cases
            ]
            try:
                generate_suite_report_pdf(
                    suite_id=suite.id,
                    status=suite.status,
                    created_at=suite.created_at,
                    started_at=suite.started_at,
                    finished_at=suite.finished_at,
                    suite_dir=suite.artifact_dir,
                    cases=case_dicts,
                    output_path=pdf_path,
                )
                suite.summary_pdf_path = pdf_path
            except Exception:
                # report generation should not break finalize
                pass

            # Webhook callback (best-effort, async)
            try:
                if getattr(suite, "webhook_url", None):
                    send_suite_webhook.delay(suite.id)
            except Exception:
                pass

        db.commit()
        return {"suite_run_id": suite_run_id, "status": suite.status, "case_count": len(cases)}
    finally:
        db.close()


