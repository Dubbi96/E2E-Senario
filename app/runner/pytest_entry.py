"""
Entry point functions for running scenario tests via pytest programmatically.

While the MVP invokes pytest via a subprocess in ``app/tasks.py``, this
module sketches an alternative approach where pytest is executed
programmatically using ``pytest.main``. This can be useful for
integrating more tightly with Python code or inspecting results
directly. Currently this module is not used by the service but acts
as a reference for future improvements.
"""

from pathlib import Path
from typing import List
import pytest


def run_scenario_pytest(scenario_path: Path, allure_dir: Path) -> int:
    """
    Execute pytest for the given scenario and allure output directory.

    :param scenario_path: Path to the scenario YAML file
    :param allure_dir: Directory where Allure results should be stored
    :return: Exit code returned by pytest
    """
    args: List[str] = [
        "tests/e2e/test_scenario.py",
        f"--scenario={scenario_path}",
        f"--alluredir={allure_dir}",
        "-q",
    ]
    return pytest.main(args)
