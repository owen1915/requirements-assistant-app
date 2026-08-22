"""One overall (notebook-style) boxplot per rule group.

For each threshold rule group (lenient / default / moderate / strict) this makes
a single boxplot in the AI4RE deck format: one horizontal box per metric
(F1, Precision, Accuracy, FNR, FPR, TNR, TPR), showing the POOLED metric's
distribution across the 15 runs. Saves one PNG per group and a combined PDF.

    python -m n8n_testbed.plots.group_boxplots
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from n8n_testbed import metrics
from .boxplots import _make_boxplot, _METRICS, _METRIC_LABELS

from shared.paths import TESTBED_RUNS_DIR as RUNS_DIR, output_dir

# Matrices, raw dumps and ground-truth workbooks are the RUN STORE: each one
# cost 100 whole-set LLM calls, so they are versioned rather than rebuilt.
# Plots and summary workbooks are regenerable and go to outputs/.
RUNS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = output_dir("n8n_testbed")
PLOT_DIR = OUTPUT_DIR / "plots" / "rule_groups"

DATASET = "PM"
GROUPS = ["lenient", "default", "moderate", "strict"]
GRID_LABEL = {
    "lenient":  "corr>=0.50, acc>=0.40, cov>=0.05",
    "default":  "corr>=0.60, acc>=0.50, cov>=0.10",
    "moderate": "corr>=0.70, acc>=0.55, cov>=0.15",
    "strict":   "corr>=0.80, acc>=0.60, cov>=0.20",
}


def _pooled_distributions(dataset: str, config: str):
    long = metrics.score(dataset, config)
    pooled = long[long["rule"] == "POOLED"]
    n_runs = pooled["execution"].nunique()
    data = [pooled[m].dropna().values for m in _METRICS]
    return data, n_runs


def main() -> None:
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = OUTPUT_DIR / f"{DATASET}_rule_group_boxplots.pdf"
    made = []
    with PdfPages(pdf_path) as pdf:
        for g in GROUPS:
            if not (RUNS_DIR / f"{DATASET}_{g}_matrix.xlsx").exists():
                print(f"  skip {g} (no matrix)")
                continue
            data, n_runs = _pooled_distributions(DATASET, g)
            title = (f"{DATASET} / {g} rules ({GRID_LABEL[g]})\n"
                     f"Metric distribution across {n_runs} runs  |  claude-sonnet-4-6")
            png = PLOT_DIR / f"{DATASET}_{g}_overall_box.png"
            _make_boxplot(data, _METRIC_LABELS, title, png)
            # also drop the same figure into the combined PDF
            fig, ax = plt.subplots(figsize=(8, 6))
            bp = ax.boxplot(data, tick_labels=_METRIC_LABELS, vert=False,
                            patch_artist=True, showfliers=True)
            for box in bp["boxes"]:
                box.set(color="black"); box.set(facecolor="none")
            for med in bp["medians"]:
                med.set(color="maroon", linewidth=1.5)
            for w in bp["whiskers"]:
                w.set(color="black")
            for c in bp["caps"]:
                c.set(color="black")
            import numpy as np
            for i, d in enumerate(data, start=1):
                if len(d):
                    m = float(np.nanmedian(d))
                    ax.text(m, i + 0.2, f"{m:.2f}", va="bottom", ha="center",
                            color="maroon", fontsize=12)
            from matplotlib.ticker import FormatStrFormatter
            ax.set_xlim(0, 1)
            ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
            ax.set_xlabel("Rate", fontsize=13)
            ax.set_ylabel("Metric", fontsize=13)
            ax.set_title(title, fontweight="bold", fontsize=12)
            fig.tight_layout(); pdf.savefig(fig); plt.close(fig)
            made.append(g)
            print(f"  {g}: overall boxplot written ({n_runs} runs)")
    print(f"\nWrote {len(made)} group plots -> {PLOT_DIR}")
    print(f"Combined PDF -> {pdf_path}")


if __name__ == "__main__":
    main()
