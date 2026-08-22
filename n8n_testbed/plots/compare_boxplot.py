"""Grouped boxplot: two configs across the seven pooled metrics, on one axis.

Extends the notebook/deck house style (thin no-fill boxes, value-labelled
medians, "Rate" on [0,1]) to two series. The single-config charts in
boxplots.py stay as they are; this is for A/B reading, where putting both
distributions on the same row is the whole point.

Palette validated with the dataviz validator (light surface, categorical):
lightness band, chroma floor, CVD separation (worst adjacent dE 30.0 deutan),
normal-vision floor and contrast all pass.

    python -m n8n_testbed.plots.compare_boxplot --configs n8nbatch n8nlenient \
        --labels "Baseline" "Baseline + 5 ICAI rules"
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FormatStrFormatter
import numpy as np

from n8n_testbed import metrics

from shared.paths import output_dir

PLOT_DIR = output_dir("n8n_testbed") / "plots" / "notebook_style"

# Deck order, read top-to-bottom.
METRICS = ["recall", "specificity", "fpr", "fnr", "accuracy", "precision", "f1"]
LABELS = ["TPR", "TNR", "FPR", "FNR", "Accuracy", "Precision", "F1"]

# Categorical palette in fixed order — never cycled. Validated all-pairs on the
# light surface: worst CVD separation dE 14.2 (deutan), normal-vision floor 20.1.
# Rejected candidates: green (dE 7.7 deutan vs the maroon), teal (reads gray,
# chroma 0.094), crimson (dE 8.1 normal vision vs the maroon).
SERIES = ["#B22222", "#1F6FEB", "#B8860B", "#7B3294"]
INK = "#1a1a1a"
MUTED = "#6b7280"


def _pooled(dataset: str, config: str) -> dict:
    df = metrics.score(dataset, config)
    p = df[df["rule"] == "POOLED"]
    return {m: p[m].dropna().values for m in METRICS}


def _style(bp, color: str) -> None:
    for box in bp["boxes"]:
        box.set(color=color, facecolor="none", linewidth=1.3)
    for med in bp["medians"]:
        med.set(color=color, linewidth=2.0)
    for part in ("whiskers", "caps"):
        for art in bp[part]:
            art.set(color=color, linewidth=1.0)
    for fl in bp["fliers"]:
        fl.set(marker="o", markersize=3.5, markerfacecolor="none",
               markeredgecolor=color, alpha=0.55)


def generate(dataset: str, configs: List[str], labels: List[str],
             out_name: str | None = None) -> Path:
    series = [_pooled(dataset, c) for c in configs]
    n_runs = [len(s[METRICS[0]]) for s in series]

    n_series = len(series)
    if n_series > len(SERIES):
        raise ValueError(f"palette has {len(SERIES)} validated slots, "
                         f"got {n_series} configs")
    fig, ax = plt.subplots(figsize=(9.5, 7.5 + 0.7 * max(0, n_series - 2)))
    # Spread the group evenly about each metric row.
    span = 0.52
    offsets = ([0.0] if n_series == 1
               else [-span / 2 + i * span / (n_series - 1) for i in range(n_series)])
    width = span / n_series * 0.78

    for si, (data, color) in enumerate(zip(series, SERIES)):
        positions = [i + 1 + offsets[si] for i in range(len(METRICS))]
        bp = ax.boxplot([data[m] for m in METRICS], positions=positions,
                        widths=width, vert=False, patch_artist=True,
                        showfliers=True, manage_ticks=False)
        _style(bp, color)
        # One label per box — the median — placed just outside the box so the
        # two series' numbers never sit on top of each other.
        # Direct labels only while they fit. Past three series the rows are too
        # tight and the numbers land on neighbouring boxes — the printed table
        # below carries every value, so the chart shows shape instead.
        if n_series <= 3:
            for pos, m in zip(positions, METRICS):
                med = float(np.median(data[m]))
                dy = -0.20 if si == 0 else 0.20
                ax.text(med, pos + dy, f"{med:.2f}",
                        va="center", ha="center", color=color, fontsize=10.5)

    ax.set_yticks(range(1, len(METRICS) + 1))
    ax.set_yticklabels(LABELS, fontsize=13, color=INK)
    ax.set_ylim(0.4, len(METRICS) + 0.6)
    ax.invert_yaxis()                       # TPR at the top, as in the deck
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.tick_params(axis="x", labelsize=12, colors=INK)
    ax.set_xlabel("Rate", fontsize=13, color=INK)
    ax.set_ylabel("Metric", fontsize=13, color=INK)

    ax.xaxis.grid(True, color="#e5e7eb", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#d1d5db")

    # n_runs[0] was asserted to apply to every arm. With unequal run counts that
    # silently contradicted the legend, which labels each series with its own n.
    spread = (f"{n_runs[0]} runs per config" if len(set(n_runs)) == 1
              else f"{min(n_runs)}-{max(n_runs)} runs per config")
    ax.set_title(f"{dataset}: pooled metric distributions, {spread}",
                 fontweight="bold", fontsize=14, color=INK, pad=34)
    # Legend sits outside the data area: at n=100 the whiskers reach far enough
    # that any in-plot corner collides with a box.
    ax.legend(handles=[Line2D([0], [0], color=c, lw=2.4,
                              label=f"{l}  (n={n})")
                       for c, l, n in zip(SERIES, labels, n_runs)],
              loc="lower center", bbox_to_anchor=(0.5, 1.005), ncol=min(4, n_series),
              frameon=False, fontsize=12, labelcolor=INK,
              handlelength=1.6, columnspacing=2.4)
    fig.text(0.5, -0.01,
             "Box = IQR across runs, whiskers 1.5xIQR, points are outlier runs. "
             "Higher is better for TPR/TNR/Accuracy/Precision/F1; lower for FPR/FNR.",
             ha="center", fontsize=9.5, color=MUTED)

    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    out = PLOT_DIR / (out_name or f"{dataset}_{'_vs_'.join(configs)}_overall_box.png")
    plt.tight_layout(rect=(0, 0.02, 1, 1))
    plt.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # Table view — identity must never be colour-alone.
    print(f"{'metric':<10}" + "".join(f"{l[:22]:>24}" for l in labels))
    print("-" * (10 + 24 * len(labels)))
    for m, lab in zip(METRICS, LABELS):
        cells = []
        for s in series:
            v = s[m]
            cells.append(f"{np.median(v):.2f} (mean {np.mean(v):.2f})")
        print(f"{lab:<10}" + "".join(f"{c:>24}" for c in cells))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="PM")
    ap.add_argument("--configs", nargs="+", default=["n8nbatch", "n8nlenient"])
    ap.add_argument("--labels", nargs="+",
                    default=["Baseline", "Baseline + 5 ICAI rules"])
    ap.add_argument("--out")
    a = ap.parse_args()
    path = generate(a.dataset, a.configs, a.labels, a.out)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------- #
# Small multiples — one panel per metric, every box directly labelled.
# --------------------------------------------------------------------------- #

HIGHER_BETTER = {"recall": True, "specificity": True, "fpr": False,
                 "fnr": False, "accuracy": True, "precision": True, "f1": True}


def small_multiples(dataset: str, configs: List[str], labels: List[str],
                    out_name: str) -> Path:
    """A grouped boxplot across 4 configs x 7 metrics makes the reader trace
    colours back to a legend for every comparison. One panel per metric, with
    the config named on its own row, removes that work entirely — colour
    becomes redundant reinforcement rather than the only key."""
    series = [_pooled(dataset, c) for c in configs]
    n_runs = len(series[0][METRICS[0]])
    n = len(series)

    fig, axes = plt.subplots(2, 4, figsize=(16.5, 7.6))
    axes = axes.ravel()

    for ax, m, mlabel in zip(axes, METRICS, LABELS):
        data = [s[m] for s in series]
        bp = ax.boxplot(data, vert=False, patch_artist=True, widths=0.55,
                        showfliers=False, positions=range(1, n + 1))
        for i, color in enumerate(SERIES[:n]):
            bp["boxes"][i].set(color=color, facecolor="none", linewidth=1.4)
            bp["medians"][i].set(color=color, linewidth=2.4)
            for art in (bp["whiskers"][2 * i], bp["whiskers"][2 * i + 1],
                        bp["caps"][2 * i], bp["caps"][2 * i + 1]):
                art.set(color=color, linewidth=1.0)

        best = (max if HIGHER_BETTER[m] else min)(
            range(n), key=lambda i: float(np.median(data[i])))
        for i in range(n):
            med = float(np.median(data[i]))
            ax.text(1.02, i + 1, f"{med:.2f}", transform=ax.get_yaxis_transform(),
                    va="center", ha="left", fontsize=11, color=SERIES[i],
                    fontweight="bold" if i == best else "normal")

        arrow = "higher is better" if HIGHER_BETTER[m] else "lower is better"
        ax.set_title(f"{mlabel}   ({arrow})", fontsize=12, fontweight="bold",
                     color=INK, pad=7)
        ax.set_yticks(range(1, n + 1))
        ax.set_yticklabels(labels, fontsize=10.5, color=INK)
        ax.set_ylim(0.4, n + 0.6)
        ax.invert_yaxis()
        ax.set_xlim(0, 1)
        ax.set_xticks([0, 0.5, 1.0])
        ax.xaxis.set_major_formatter(FormatStrFormatter("%.1f"))
        ax.tick_params(axis="x", labelsize=10, colors=INK)
        ax.xaxis.grid(True, color="#e5e7eb", linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color("#d1d5db")

    axes[-1].axis("off")
    fig.suptitle(f"{dataset}: pooled metrics by rule set, {n_runs} runs per config",
                 fontweight="bold", fontsize=15, color=INK, y=0.99)
    fig.text(0.5, 0.005, "Box = IQR across runs, whiskers 1.5xIQR. "
             "Bold value = best arm on that metric.",
             ha="center", fontsize=10, color=MUTED)

    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    out = PLOT_DIR / out_name
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    return out
