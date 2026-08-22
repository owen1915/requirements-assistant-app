"""Boxplots in the exact format of the AI4RE data-processing notebook.

Replicates colab_R1_R14_evaluation_v2's `_make_boxplot` (overall: one horizontal
box per metric) and `_make_per_rule_boxplot` (one horizontal box per criterion),
with identical styling: black no-fill boxes, maroon medians with the median value
printed, x-axis "Rate" fixed to [0,1] with %.2f ticks, bold title fs15, dpi 300.

Our criteria are A-series, shown in the same canonical order the notebook uses
(Necessary, Appropriate, Unambiguous, Complete, Singular, Correct, Conforming).

    python -m n8n_testbed.plots.boxplots --datasets PM Bookshelf --configs baseline M1 M2
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
import numpy as np
import pandas as pd

from n8n_testbed import metrics
from shared.datasets import CRITERIA_NAMES

from shared.paths import TESTBED_RUNS_DIR as RUNS_DIR, output_dir

# Matrices, raw dumps and ground-truth workbooks are the RUN STORE: each one
# cost 100 whole-set LLM calls, so they are versioned rather than rebuilt.
# Plots and summary workbooks are regenerable and go to outputs/.
RUNS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = output_dir("n8n_testbed")
PLOT_DIR = OUTPUT_DIR / "plots" / "notebook_style"

# Same canonical order the notebook uses, in A-series.
CRITERION_ORDER = ["A2", "A3", "A4", "A5", "A6", "A9", "A10"]

# Overall boxplot metrics + display labels (matches notebook cell 2 exactly).
_METRICS = ["f1", "precision", "accuracy", "fnr", "fpr", "specificity", "recall"]
_METRIC_LABELS = ["F1", "Precision", "Accuracy", "FNR", "FPR", "TNR", "TPR"]

_COLOR = "maroon"


def _make_boxplot(data, labels, title, save_path, color=_COLOR):
    fig, ax = plt.subplots(figsize=(8, 6))
    bp = ax.boxplot(data, tick_labels=labels, vert=False,
                    patch_artist=True, showfliers=True)
    for box in bp["boxes"]:
        box.set(color="black"); box.set(facecolor="none")
    for med in bp["medians"]:
        med.set(color=color, linewidth=1.5)
    for w in bp["whiskers"]:
        w.set(color="black")
    for c in bp["caps"]:
        c.set(color="black")
    medians = [np.nanmedian(d) if len(d) else np.nan for d in data]
    for i, m in enumerate(medians, start=1):
        if not np.isnan(m):
            ax.text(m, i + 0.2, f"{m:.2f}", va="bottom", ha="center",
                    color=color, fontsize=14)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.tick_params(axis="x", labelsize=14)
    ax.tick_params(axis="y", labelsize=14)
    ax.set_xlabel("Rate", fontsize=15)
    ax.set_ylabel("Metric", fontsize=15)
    ax.set_title(title, fontweight="bold", fontsize=15)
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _make_per_rule_boxplot(df_by_rule, title, save_path, color=_COLOR):
    X_PADDING, Y_PADDING, Y_OFFSET = 0.04, 0.3, 0.3
    ordered = [r for r in CRITERION_ORDER if r in df_by_rule.index]
    ordered += [r for r in df_by_rule.index if r not in CRITERION_ORDER]
    df_by_rule = df_by_rule.loc[ordered]
    rules = df_by_rule.index.tolist()
    rule_labels = [CRITERIA_NAMES.get(str(r), str(r)) for r in rules]
    data = [df_by_rule.loc[r].dropna().values for r in rules]

    fig, ax = plt.subplots(figsize=(8, 10))
    bp = ax.boxplot(data, tick_labels=rule_labels, vert=False,
                    patch_artist=True, showfliers=True)
    for box in bp["boxes"]:
        box.set(color="black"); box.set(facecolor="none")
    for med in bp["medians"]:
        med.set(color=color, linewidth=1)
    for w in bp["whiskers"]:
        w.set(color="black")
    for c in bp["caps"]:
        c.set(color="black")
    medians = [np.nanmedian(d) if len(d) else np.nan for d in data]
    for i, m in enumerate(medians, start=1):
        if not np.isnan(m):
            ax.text(m, i - Y_OFFSET, f"{m:.2f}", va="bottom", ha="center",
                    color=color, fontsize=14)
    n = len(data)
    ax.set_ylim(0.5 - Y_PADDING, n + 0.5 + Y_PADDING)
    ax.set_xlim(-X_PADDING, 1 + X_PADDING)
    ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.tick_params(axis="x", labelsize=14)
    ax.tick_params(axis="y", labelsize=14)
    ax.set_xlabel("Rate", fontsize=15)
    ax.set_ylabel("Rule", fontsize=15)
    ax.set_title(title, fontweight="bold", fontsize=15)
    ax.invert_yaxis()
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def generate(dataset: str, config: str) -> None:
    """Both notebook-style boxplots for one (dataset, config)."""
    long = metrics.score(dataset, config)
    per_rule = long[long["rule"] != "POOLED"]
    pooled = long[long["rule"] == "POOLED"]   # one row per run
    n_runs = pooled["execution"].nunique()

    # Overall: one box per metric, distribution of the POOLED metric across the
    # runs (run-to-run variance) — NOT across criteria (where most PM criteria
    # have 0 precision, which made the median misleadingly 0).
    overall = [pooled[m].dropna().values for m in _METRICS]
    _make_boxplot(
        overall, _METRIC_LABELS,
        f"{dataset} / {config}: Metric Distribution across {n_runs} Runs",
        PLOT_DIR / f"{dataset}_{config}_overall_box.png")

    # Per-rule: one box per criterion, distribution of F1 across the runs.
    for metric, mlabel in [("f1", "F1"), ("precision", "Precision"),
                           ("recall", "Recall"), ("fpr", "FPR")]:
        pivot = per_rule.pivot_table(index="rule", columns="execution",
                                     values=metric)
        _make_per_rule_boxplot(
            pivot, f"{dataset} / {config}: {mlabel} by Rule",
            PLOT_DIR / f"{dataset}_{config}_{metric}_by_rule_box.png")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="+", default=["PM", "Bookshelf"])
    ap.add_argument("--configs", nargs="+", default=["baseline", "M1", "M2"])
    args = ap.parse_args()
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    made = 0
    for ds in args.datasets:
        for cfg in args.configs:
            if (RUNS_DIR / f"{ds}_{cfg}_matrix.xlsx").exists():
                generate(ds, cfg)
                made += 1
                print(f"  {ds}/{cfg}: notebook-style boxplots written")
            else:
                print(f"  skip {ds}/{cfg} (no matrix)")
    print(f"\nWrote boxplots for {made} (dataset,config) pairs -> "
          f"outputs/plots/notebook_style/")


if __name__ == "__main__":
    main()
