"""How consistently does the AI flag each PM requirement across the 4 SME sessions?

Each of the 4 point-mass SME sessions carries an independent AI evaluation of the
same 13 requirements. For every (requirement x criterion) cell we count how many
of the 4 sessions the AI flagged it (0-4) = the AI's flagging consistency, and
overlay the GT (Point_Mass_v5) so you can see consistency AND correctness:

  4/4 + GT-positive  -> reliably catches a real issue
  4/4 + GT-negative  -> consistent false positive
  1-3                -> flaky / non-deterministic
  0/4 + GT-positive  -> reliably missed

Produces ai_flagging_consistency_PM.pdf: the count heatmap with GT cells outlined,
plus a per-requirement stability bar. No API - reconstructed from the feedback.

    python -m reviewer_reliability.ai_consistency
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Set, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.colors import BoundaryNorm
import numpy as np

from .reviewer_reliability import (
    FEEDBACK_DIR, REVIEWERS, REVIEWER_LABEL, REQ_TO_PM, CRIT_ORDER, CRIT_NAME,
    _load_gt,
)

from shared.paths import output_dir

OUTPUT_DIR = output_dir("reviewer_reliability")
N = len(REVIEWERS)                                   # 4 sessions
PM_ORDER = [REQ_TO_PM[i] for i in range(1, 14)]      # FR.1 .. RR.1


def _ai_flags(session: str) -> Set[Tuple[str, str]]:
    """{(pm_id, criterion)} the AI flagged in this session."""
    d = json.loads((FEEDBACK_DIR / f"feedback_{session}.json")
                   .read_text(encoding="utf-8"))
    flags: Set[Tuple[str, str]] = set()
    for req in d["requirement_feedback"]:
        pm = REQ_TO_PM.get(int(req["req_id"]))
        if not pm:
            continue
        for v in req.get("violation_feedback", []):
            flags.add((pm, v.get("rule_id")))
    return flags


def build_matrix():
    per_session = [_ai_flags(s) for s in REVIEWERS]
    # count[pm][crit] = how many of the 4 sessions flagged it
    count = np.zeros((len(PM_ORDER), len(CRIT_ORDER)), dtype=int)
    for i, pm in enumerate(PM_ORDER):
        for j, crit in enumerate(CRIT_ORDER):
            count[i, j] = sum((pm, crit) in fl for fl in per_session)
    gt = _load_gt()
    gtmat = np.zeros_like(count, dtype=bool)
    for i, pm in enumerate(PM_ORDER):
        for j, crit in enumerate(CRIT_ORDER):
            gtmat[i, j] = crit in gt and gt[crit].get(pm, False)
    return count, gtmat


def _heatmap(ax, count, gtmat):
    cmap = plt.cm.get_cmap("YlOrRd", N + 1)
    norm = BoundaryNorm(range(N + 2), cmap.N)
    im = ax.imshow(count, cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(len(CRIT_ORDER)))
    ax.set_xticklabels([f"{c}\n{CRIT_NAME[c]}" for c in CRIT_ORDER], fontsize=9)
    ax.set_yticks(range(len(PM_ORDER)))
    ax.set_yticklabels(PM_ORDER, fontsize=9)
    for i in range(len(PM_ORDER)):
        for j in range(len(CRIT_ORDER)):
            v = count[i, j]
            ax.text(j, i, str(v), ha="center", va="center", fontsize=9,
                    color="white" if v >= 3 else "black")
            if gtmat[i, j]:                            # GT-positive -> bold outline
                ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False,
                                       edgecolor="#0d47a1", linewidth=2.5))
    ax.set_title("AI flagging consistency across the 4 SME sessions\n"
                 "cell = # sessions (0-4) the AI flagged it | blue outline = GT real issue",
                 fontweight="bold", fontsize=12)
    cbar = plt.colorbar(im, ax=ax, ticks=range(N + 1), shrink=0.7)
    cbar.set_label("# sessions flagged")


def _stability_bar(ax, count):
    # per-requirement stability = fraction of criteria where the AI was unanimous
    unanim = ((count == 0) | (count == N)).sum(axis=1) / len(CRIT_ORDER)
    y = np.arange(len(PM_ORDER))
    ax.barh(y, unanim, color="#2ca02c", alpha=0.85)
    for i, v in enumerate(unanim):
        ax.text(v + 0.01, i, f"{v:.2f}", va="center", fontsize=8)
    ax.set_yticks(y); ax.set_yticklabels(PM_ORDER, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.08); ax.set_xlabel("stability (fraction unanimous 0/4 or 4/4)")
    ax.set_title("Per-requirement AI stability\n(higher = AI treats it the same every run)",
                 fontweight="bold", fontsize=11)
    ax.grid(axis="x", alpha=0.3)


def main() -> None:
    count, gtmat = build_matrix()

    # console summary
    total = count.size
    unanimous = int(((count == 0) | (count == N)).sum())
    flaky = total - unanimous
    gt_cells = gtmat.sum()
    gt_catch = count[gtmat].mean() / N if gt_cells else float("nan")
    print(f"cells: {total} | unanimous(0 or 4): {unanimous} | flaky(1-3): {flaky}")
    print(f"GT real-issue cells: {gt_cells} | avg AI catch rate on them: {gt_catch:.2f} of 4")
    print(f"\nSessions -> {', '.join(f'{REVIEWER_LABEL[s]}={s}' for s in REVIEWERS)}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    out = OUTPUT_DIR / "ai_flagging_consistency_PM.pdf"
    from matplotlib.backends.backend_pdf import PdfPages
    with PdfPages(out) as pdf:
        fig, ax = plt.subplots(figsize=(9, 8)); _heatmap(ax, count, gtmat)
        fig.tight_layout(); pdf.savefig(fig); plt.close(fig)
        fig, ax = plt.subplots(figsize=(7, 7)); _stability_bar(ax, count)
        fig.tight_layout(); pdf.savefig(fig); plt.close(fig)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
