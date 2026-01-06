"""
Celery tasks used by the end-to-end test service.

Currently a single task ``execute_run`` is defined. It spawns a
subprocess to run pytest against a scenario provided by the user and
captures the resulting output into the run's artifact directory.

This design isolates the test execution from the main worker process,
so that any side effects or crashes in the tests do not bring down
Celery itself. It also makes it easy to swap out the test executor
implementation (for example to use pytest programmatically) in the
future.
"""

from __future__ import annotations

import os
import subprocess
import traceback
from typing import Dict

from app.core.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.db.crud import get_run, mark_finished, mark_running


@celery_app.task(name="execute_run")
def execute_run(run_id: str) -> Dict[str, int]:
    """
    Execute a single scenario as identified by ``run_id``.

    The task locates the scenario YAML in the run directory, invokes
    pytest with appropriate arguments to point at the scenario and
    Allure results directory, and writes the subprocess output to
    ``pytest.stdout.log`` and ``pytest.stderr.log`` files in the run
    directory.

    :param run_id: Unique identifier for the run
    :return: A dictionary containing the run_id and the exit code from pytest
    """
    db = SessionLocal()
    try:
        run = get_run(db, run_id)
        if not run:
            return {"run_id": run_id, "exit_code": 99}

        mark_running(db, run_id)

        run_dir = run.artifact_dir
        scenario_path = run.scenario_path
        allure_dir = os.path.join(run_dir, "allure-results")
        os.makedirs(allure_dir, exist_ok=True)

        # Construct the pytest command. The tests are located in the ``tests`` package
        # at the project root. We pass the scenario path and allure directory as
        # command-line options. ``-q`` runs pytest in quiet mode.
        cmd = [
            "pytest",
            "-q",
            "tests/e2e/test_scenario.py",
            f"--scenario={scenario_path}",
            f"--alluredir={allure_dir}",
        ]

        # Determine the working directory for the subprocess. We want pytest to run
        # from the project root so that imports resolve correctly. ``__file__`` is
        # ``app/tasks.py`` so the project root is two directories up.
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Prepare environment variables - ensure PLAYWRIGHT_HEADLESS is set
        # Default to 'true' for headless mode in server environment
        env = os.environ.copy()
        if "PLAYWRIGHT_HEADLESS" not in env:
            env["PLAYWRIGHT_HEADLESS"] = "true"

        proc = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            env=env,
        )

        # Persist stdout and stderr to files for later inspection.
        with open(os.path.join(run_dir, "pytest.stdout.log"), "w", encoding="utf-8") as f:
            f.write(proc.stdout)
        with open(os.path.join(run_dir, "pytest.stderr.log"), "w", encoding="utf-8") as f:
            f.write(proc.stderr)

        passed = proc.returncode == 0
        mark_finished(db, run_id, passed=passed, exit_code=proc.returncode, error_message=None)
        return {"run_id": run_id, "exit_code": proc.returncode}
    except Exception as e:
        err = f"{e}\n{traceback.format_exc()}"
        mark_finished(db, run_id, passed=False, exit_code=None, error_message=err)
        return {"run_id": run_id, "exit_code": 98}
    finally:
        db.close()
