"""
Shared pytest configuration for the end-to-end tests.

This configuration introduces a ``--scenario`` command-line option that
pytest will accept. The ``scenario_path`` fixture exposes the value of
that option to test functions.
"""

import pytest


def pytest_addoption(parser):
    """Hook to add custom command-line options to pytest."""
    parser.addoption("--scenario", action="store", default=None)


@pytest.fixture(scope="session")
def scenario_path(pytestconfig):
    """
    Fixture providing the path to the scenario YAML file.

    The scenario is supplied via the ``--scenario`` option when invoking
    pytest. If the option is missing, an error is raised to inform
    callers that they need to specify it.
    """
    path = pytestconfig.getoption("--scenario")
    if not path:
        raise RuntimeError("Missing --scenario")
    return path
