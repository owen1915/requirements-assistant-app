"""Where the app's static assets live — resolved once, from here.

This is the app-repo copy. The research repo carries a fuller version of this
module (ground truth, specs, SME feedback, run stores, figure output). None of
that exists in a deployment, so only the rubric directory is kept here: the
evaluator loads its INCOSE criteria from it, and nothing else in the app reads
a path that is not relative to its own file.

RUBRIC_DIR is anchored to this file rather than to the repo root, so it keeps
working when the package is pip-installed rather than run from a checkout.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

RUBRIC_DIR = Path(__file__).resolve().parent / "rubrics"
