"""Where the data and the generated artefacts live — resolved once, from here.

Before the split every module derived its own paths from `__file__`, and three of
them walked *out* of the repo to find ground truth: `datasets.py` reached into the
parent directory, and `reviewer_rates.py` hardcoded an absolute path under the
author's Downloads folder. Nothing ran on any other machine. Every path below is
anchored to the repo root instead, so a fresh clone is enough.

`OUTPUT_DIR` is overridable via AI4RE_OUTPUT_DIR, for writing a scratch run
somewhere else without disturbing the committed artefacts.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = REPO_ROOT / "data"
GT_DIR = DATA_DIR / "ground_truth"
SPEC_DIR = DATA_DIR / "specs"
FEEDBACK_DIR = DATA_DIR / "sme_feedback"
SAMPLES_DIR = DATA_DIR / "samples"

RUBRIC_DIR = Path(__file__).resolve().parent / "rubrics"

# Rule sets the testbed injects. These are pipeline *products* that later become
# testbed *inputs*, so they are versioned alongside the code rather than treated
# as disposable output.
RULE_SETS_DIR = REPO_ROOT / "icai_v2" / "rule_sets"

# Prediction matrices and raw dumps from the batch runs. Expensive to regenerate
# (100 whole-set LLM calls per config), so they are kept, not rebuilt.
TESTBED_RUNS_DIR = REPO_ROOT / "n8n_testbed" / "runs"
REVIEWER_RUNS_DIR = REPO_ROOT / "reviewer_reliability" / "runs"

DOCS_FIGURE_DIR = REPO_ROOT / "docs" / "figures"

OUTPUT_DIR = Path(os.getenv("AI4RE_OUTPUT_DIR") or (REPO_ROOT / "outputs"))


def output_dir(component: str) -> Path:
    """Scratch/regenerable output for one component, created on demand."""
    path = OUTPUT_DIR / component
    path.mkdir(parents=True, exist_ok=True)
    return path
