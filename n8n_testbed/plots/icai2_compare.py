"""Boxplots: multishot baseline vs an injected ICAI constitution.

Produces one figure per treatment config (F1 / Precision / Accuracy panels),
comparing the pooled per-run metric distribution of the baseline against the
config with rules injected. Notebook-style: black boxes, maroon medians.

    python -m n8n_testbed.plots.icai2_compare
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
METRICS = [("f1", "F1"), ("precision", "Precision"), ("accuracy", "Accuracy")]

# (treatment config, treatment label, figure title, output stem)
COMPARISONS = [
    ("icai4rev", "+ 4-reviewer rules (A9+A10)",
     "PM multishot: baseline vs 4-reviewer ICAI rules",
     "PM_multishot_baseline_vs_icai4rev"),
    ("icai2", "+ 5-SME rules (A10+A2)",
     "PM multishot: baseline vs 5-SME ICAI rules",
     "PM_multishot_baseline_vs_icai2"),
]


def _pooled(config: str, metric: str):
    long = metrics.score("PM", config)
    pooled = long[long["rule"] == "POOLED"]
    return pooled[metric].dropna().values, pooled["execution"].nunique()


def _panel(ax, configs, metric, label):
    data, labels = [], []
    for cfg, name in configs:
        vals, n = _pooled(cfg, metric)
        data.append(vals); labels.append(f"{name}\n(n={n})")
    bp = ax.boxplot(data, tick_labels=labels, vert=True, patch_artist=True,
                    showfliers=True, widths=0.5)
    for box in bp["boxes"]:
        box.set(color="black"); box.set(facecolor="none")
    for med in bp["medians"]:
        med.set(color=COLOR, linewidth=1.6)
    for part in ("whiskers", "caps"):
        for a in bp[part]:
            a.set(color="black")
    for i, d in enumerate(data, start=1):
        if len(d):
            m = float(np.nanmedian(d))
            ax.text(i + 0.07, m, f"{m:.2f}", va="center", ha="left",
                    color=COLOR, fontsize=12)
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.set_title(label, fontweight="bold", fontsize=13)
    ax.grid(axis="y", alpha=0.25)
    ax.tick_params(axis="x", labelsize=10)


def generate(treat_cfg, treat_name, title, stem) -> None:
    configs = [("baseline", "Baseline"), (treat_cfg, treat_name)]
    fig, axes = plt.subplots(1, 3, figsize=(13, 5.5))
    for ax, (m, lbl) in zip(axes, METRICS):
        _panel(ax, configs, m, lbl)
    fig.suptitle(f"{title}  |  claude-sonnet-4-6", fontweight="bold", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    png = PLOT_DIR / f"{stem}.png"
    fig.savefig(png, dpi=200, bbox_inches="tight")
    fig.savefig(OUTPUT_DIR / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)

    print(f"\n{title}")
    print(f"  {'config':30}{'F1':>8}{'Prec':>8}{'Rec':>8}{'Acc':>8}")
    for cfg, name in configs:
        row = {m: np.nanmedian(_pooled(cfg, m)[0]) for m in
               ("f1", "precision", "recall", "accuracy")}
        print(f"  {name:30}{row['f1']:>8.3f}{row['precision']:>8.3f}"
              f"{row['recall']:>8.3f}{row['accuracy']:>8.3f}")
    print(f"  -> {png.name}")


def main() -> None:
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    for cfg, name, title, stem in COMPARISONS:
        if (RUNS_DIR / f"PM_{cfg}_matrix.xlsx").exists():
            generate(cfg, name, title, stem)
        else:
            print(f"skip {cfg} (no matrix yet)")


if __name__ == "__main__":
    main()
