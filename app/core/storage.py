"""
Helpers for working with run artifact storage.

In this simple MVP the artifact store is the local filesystem. These
functions abstract over that implementation to make it easy to
substitute a remote store (e.g. S3 or Google Cloud Storage) in a
future iteration without changing the rest of the codebase.
"""

import os
from typing import List

from app.core.config import settings


def get_run_dir(run_id: str) -> str:
    """Return the absolute path to the directory used for a given run."""
    return os.path.join(settings.ARTIFACT_ROOT, run_id)


def list_artifacts(run_id: str) -> List[str]:
    """
    List the filenames of artifacts stored for the specified run.

    :param run_id: Identifier of the run whose artifacts to list
    :return: A list of filenames contained in the run directory
    """
    run_dir = get_run_dir(run_id)
    if not os.path.isdir(run_dir):
        return []
    return [f for f in os.listdir(run_dir) if os.path.isfile(os.path.join(run_dir, f))]


def artifact_path(run_id: str, filename: str) -> str:
    """Construct an absolute path to a specific artifact file."""
    return os.path.join(get_run_dir(run_id), filename)
