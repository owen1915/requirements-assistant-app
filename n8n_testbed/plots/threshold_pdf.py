"""One PDF: the PM baseline beside the four ICAI threshold rule groups.

A single landscape page, five panels side by side, same AI4RE deck boxplot
format in each — one horizontal box per metric (F1, Precision, Accuracy, FNR,
FPR, TNR, TPR) showing the POOLED metric's distribution across that config's
runs.

The baseline sits leftmost so the four threshold panels read against it. Panels
2-5 are the ICAI rule-selection thresholds from
icai_v2/pipeline/threshold_sensitivity.py, each headed with its actual gate.
All panels share the 0-1 x-axis, so box positions are directly comparable.

NOTE ON THE MODEL LABEL. The evaluator model is not recorded in the *_raw.json
run data, so MODEL_LABEL below is inherited from inject.EVAL_MODEL's default
rather than read back from the runs. It is an assertion, not a measurement.

    python -m n8n_testbed.plots.threshold_pdf
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FormatStrFormatter

from n8n_testbed import metrics
from .boxplots import _METRICS, _METRIC_LABELS

from shared.paths import TESTBED_RUNS_DIR as RUNS_DIR, output_dir

# Matrices, raw dumps and ground-truth workbooks are the RUN STORE: each one
# cost 100 whole-set LLM calls, so they are versioned rather than rebuilt.
# Plots and summary workbooks are regenerable and go to outputs/.
RUNS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = output_dir("n8n_testbed")
PLOT_DIR = OUTPUT_DIR / "plots" / "rule_groups"

DATASET = "PM"
MODEL_LABEL = "claude-sonnet-4-6"

# Left-to-right order: baseline first so the threshold panels read against it.
PANELS = [
    ("baseline", "PM baseline", "no injected rules"),
    ("lenient",  "PM rules - lenient",  "corr >= 0.50, acc >= 0.40, cov >= 0.05"),
    ("default",  "PM rules - default",  "corr >= 0.60, acc >= 0.50, cov >= 0.10"),
    ("moderate", "PM rules - moderate", "corr >= 0.70, acc >= 0.55, cov >= 0.15"),
    ("strict",   "PM rules - strict",   "corr >= 0.80, acc >= 0.60, cov >= 0.20"),
]


def _pooled(dataset: str, config: str):
    long = metrics.score(dataset, config)
    pooled = long[long["rule"] == "POOLED"]
    return [pooled[m].dropna().values for m in _METRICS], pooled["execution"].nunique()


def _panel(ax, data, heading: str, gate: str, show_ylabels: bool):
    """Draw one deck-format boxplot into `ax`. Black boxes, maroon medians."""
    labels = _METRIC_LABELS if show_ylabels else [""] * len(_METRIC_LABELS)
    bp = ax.boxplot(data, tick_labels=labels, vert=False,
                    patch_artist=True, showfliers=True)
    for box in bp["boxes"]:
        box.set(color="black")
        box.set(facecolor="none")
    for med in bp["medians"]:
        med.set(color="maroon", linewidth=1.5)
    for w in bp["whiskers"]:
        w.set(color="black")
    for c in bp["caps"]:
        c.set(color="black")

    for i, d in enumerate(data, start=1):
        if len(d):
            m = float(np.nanmedian(d))
            ax.text(m, i + 0.22, f"{m:.2f}", va="bottom", ha="center",
                    color="maroon", fontsize=10)

    ax.set_xlim(0, 1)
    ax.set_xticks([0.0, 0.25, 0.50, 0.75, 1.0])
    ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.set_xlabel("Rate", fontsize=11)
    if show_ylabels:
        ax.set_ylabel("Metric", fontsize=11)
    ax.set_title(f"{heading}\n{gate}", fontweight="bold", fontsize=10)


def main() -> None:
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = OUTPUT_DIR / f"{DATASET}_thresholds_with_baseline.pdf"

    available = [(c, h, g) for c, h, g in PANELS
                 if (RUNS_DIR / f"{DATASET}_{c}_matrix.xlsx").exists()]
    for c, _, _ in PANELS:
        if c not in {a[0] for a in available}:
            print(f"  skip {c}: no {DATASET}_{c}_matrix.xlsx")

    fig, axes = plt.subplots(1, len(available), figsize=(4.2 * len(available), 5.6),
                             sharey=True)
    if len(available) == 1:
        axes = [axes]

    for i, ((config, heading, gate), ax) in enumerate(zip(available, axes)):
        data, n_runs = _pooled(DATASET, config)
        _panel(ax, data, heading, gate, show_ylabels=(i == 0))
        print(f"  {config:9s} panel drawn ({n_runs} runs)")

    fig.suptitle(f"{DATASET} - pooled metric distributions  |  {MODEL_LABEL}",
                 fontweight="bold", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.95))

    # PNG first: it is never held open by a viewer, so the figure always lands
    # somewhere even if the PDF is locked.
    png_path = PLOT_DIR / f"{DATASET}_thresholds_with_baseline.png"
    fig.savefig(png_path, dpi=150)

    # A PDF open in a reader is locked on Windows. Fall back to a numbered name
    # rather than losing the render.
    target = pdf_path
    for n in range(1, 20):
        try:
            with PdfPages(target) as pdf:
                pdf.savefig(fig)
            break
        except PermissionError:
            target = pdf_path.with_name(f"{pdf_path.stem}_v{n}.pdf")
    else:
        target = None
    plt.close(fig)

    print(f"\n{len(available)} panels side by side")
    print(f"PNG -> {png_path}")
    if target == pdf_path:
        print(f"PDF -> {target}")
    elif target:
        print(f"PDF -> {target}   (original was locked by an open viewer)")
    else:
        print("PDF -> not written; close the open viewer and re-run")


if __name__ == "__main__":
    main()
