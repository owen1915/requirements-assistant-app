"""Named recipes for the reviewer-reliability figures.

Same motivation as n8n_testbed/figures.py: the published charts came from CLI calls
whose flags were not written down anywhere, and the `--modify` policy is exactly the
kind of flag that silently changes the result. `adjudicated` is the published one —
every `modify` decision labelled by hand against the criterion, the AI's suggestion,
the SME's final text and their note (the table lives in reviewer_rates.ADJUDICATED).

All of these read the SME feedback exports and the v5 ground truth. No API calls.

    python -m reviewer_reliability.figures
    python -m reviewer_reliability.figures reviewer_rates --modify split
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from shared.paths import DOCS_FIGURE_DIR

from . import reviewer_rates


def reviewer_rate_figure(modify: str = "adjudicated",
                         out_dir: Path = DOCS_FIGURE_DIR) -> Path:
    """Per-reviewer TPR/TNR/FPR/FNR against ground truth, one box per metric."""
    df = reviewer_rates.score(modify)
    print(df[["reviewer", "n", "n_accept", "n_modify", "n_reject",
              "tp", "tn", "fp", "fn", "tpr", "tnr", "fpr", "fnr"]].to_string(index=False))
    print("\nmedian across reviewers: " + "  ".join(
        f"{reviewer_rates.MLABEL[m]}={df[m].median():.2f}" for m in reviewer_rates.METRICS))

    produced = reviewer_rates.plot(df, modify)
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / produced.name
    shutil.copyfile(produced, final)
    print(f"\nwrote {final}")
    return final


def reliability_pdf() -> None:
    """Per-reviewer reliability report (PDF) — stays in outputs/, not docs/."""
    from . import reviewer_reliability
    reviewer_reliability.main()


def consistency_pdf() -> None:
    """AI flagging consistency across the SME sessions (PDF)."""
    from . import ai_consistency
    ai_consistency.main()


RECIPES = {
    "reviewer_rates": "PM_reviewer_rates_<policy>.png - SME agreement with ground truth",
    "reliability": "reviewer_reliability_PM.pdf - per-reviewer reliability report",
    "consistency": "ai_flagging_consistency_PM.pdf - AI flag stability across sessions",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("recipes", nargs="*", default=[],
                    help=f"default: all. One or more of: {', '.join(RECIPES)}")
    ap.add_argument("--modify", default="adjudicated",
                    choices=["adjudicated", "endorse", "reject", "split"],
                    help="how a 'modify' decision is scored (default: the published one)")
    ap.add_argument("--out-dir", type=Path, default=DOCS_FIGURE_DIR)
    a = ap.parse_args()
    unknown = [r for r in a.recipes if r not in RECIPES]
    if unknown:
        ap.error(f"unknown recipe(s) {', '.join(unknown)}; "
                 f"choose from {', '.join(RECIPES)}")

    for name in (a.recipes or list(RECIPES)):
        print(f"\n=== {name} ===")
        if name == "reviewer_rates":
            reviewer_rate_figure(a.modify, a.out_dir)
        elif name == "reliability":
            reliability_pdf()
        else:
            consistency_pdf()


if __name__ == "__main__":
    main()
