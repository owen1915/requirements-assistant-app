"""Baseline vs 4-reviewer rules vs 5-reviewer rules, multishot testbed.

One panel per notebook metric (F1, Precision, Accuracy, TPR, TNR, FPR, FNR);
each panel holds three boxes: baseline, 4-reviewer rules, 5-reviewer rules.
Pooled per-run distributions. Notebook style: black boxes, maroon medians.

    python -m n8n_testbed.plots.tri_compare
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
import numpy as np

from n8n_testbed import metrics

from shared.paths import TESTBED_RUNS_DIR as RUNS_DIR, output_dir

# Matrices, raw dumps and ground-truth workbooks are the RUN STORE: each one
# cost 100 whole-set LLM calls, so they are versioned rather than rebuilt.
# Plots and summary workbooks are regenerable and go to outputs/.
RUNS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = output_dir("n8n_testbed")
PLOT_DIR = OUTPUT_DIR / "plots" / "rule_groups"
COLOR = "maroon"

CONFIGS = [("baseline", "Baseline"),
           ("lenient4rev", "4 reviewers"),
           ("lenient5rev", "5 reviewers")]

# (metric column, panel title) — notebook naming
PANELS = [("f1", "F1"), ("precision", "Precision"), ("accuracy", "Accuracy"),
          ("recall", "TPR"), ("specificity", "TNR"), ("fpr", "FPR"),
          ("fnr", "FNR")]


def _pooled(config: str, metric: str):
    long = metrics.score("PM", config)
    pooled = long[long["rule"] == "POOLED"]
    return pooled[metric].dropna().values, pooled["execution"].nunique()


def _panel(ax, metric, label):
    data, labels = [], []
    for cfg, name in CONFIGS:
        vals, n = _pooled(cfg, metric)
        data.append(vals); labels.append(name)
    bp = ax.boxplot(data, tick_labels=labels, vert=True, patch_artist=True,
                    showfliers=True, widths=0.55)
    for box in bp["boxes"]:
        box.set(color="black"); box.set(facecolor="none")
    for m in bp["medians"]:
        m.set(color=COLOR, linewidth=1.5)
    for part in ("whiskers", "caps"):
        for a in bp[part]:
            a.set(color="black")
    for i, d in enumerate(data, start=1):
        if len(d):
            med = float(np.nanmedian(d))
            ax.text(i + 0.08, med, f"{med:.2f}", va="center", ha="left",
                    color=COLOR, fontsize=10)
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.1f"))
    ax.set_title(label, fontweight="bold", fontsize=13)
    ax.grid(axis="y", alpha=0.25)
    ax.tick_params(axis="x", labelsize=9)


def main() -> None:
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 4, figsize=(16, 8))
    axes = axes.flatten()
    for ax, (m, lbl) in zip(axes, PANELS):
        _panel(ax, m, lbl)
    axes[-1].axis("off")   # 8th slot empty
    ns = {name: _pooled(cfg, "f1")[1] for cfg, name in CONFIGS}
    fig.suptitle("PM multishot: Baseline vs 4-reviewer vs 5-reviewer ICAI rules  |  "
                 "claude-sonnet-4-6  |  " +
                 ", ".join(f"{k} n={v}" for k, v in ns.items()),
                 fontweight="bold", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    png = PLOT_DIR / "PM_tri_baseline_4rev_5rev.png"
    fig.savefig(png, dpi=170, bbox_inches="tight")
    fig.savefig(OUTPUT_DIR / "PM_tri_baseline_4rev_5rev.pdf", bbox_inches="tight")
    plt.close(fig)

    print(f"{'config':14}" + "".join(f"{lbl:>10}" for _, lbl in PANELS))
    for cfg, name in CONFIGS:
        cells = "".join(f"{np.nanmedian(_pooled(cfg, m)[0]):>10.3f}" for m, _ in PANELS)
        print(f"{name:14}{cells}")
    print(f"\nWrote {png.name}")


if __name__ == "__main__":
    main()
