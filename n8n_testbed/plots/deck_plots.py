"""Deck-format boxplot report (matches AI4RE Comparative_Analysis slides).

For each dataset, produces a PDF where every page places the versions
(baseline | M1 | M2) side by side:
  * page 1  - "Summary of Metrics": overall boxplot per version (metrics on y)
  * pages 2-8 - one metric each (TPR/TNR/FPR/FNR/Accuracy/Precision/F1),
               per-issue boxplot per version (issues on y)

Sourced from the notebook-scored confusion files
(PM_<cfg>_confusion_notebook.xlsx etc.), so numbers match the notebook exactly.

    python -m n8n_testbed.plots.deck_plots
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd

from shared.paths import TESTBED_RUNS_DIR as RUNS_DIR, output_dir

# Matrices, raw dumps and ground-truth workbooks are the RUN STORE: each one
# cost 100 whole-set LLM calls, so they are versioned rather than rebuilt.
# Plots and summary workbooks are regenerable and go to outputs/.
RUNS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = output_dir("n8n_testbed")
_COLOR = "maroon"

CONFIGS = ["baseline", "M1", "M2"]
CONFIG_TITLE = {"baseline": "Baseline", "M1": "M1 (ICAI)", "M2": "M2 (Directed Coding)"}

# Overall summary: metric column in Summary sheet -> deck label
SUMMARY_METRICS = [("TPR", "Recall"), ("TNR", "Specificity"), ("FPR", "FPR"),
                   ("FNR", "FNR"), ("Accuracy", "Accuracy"),
                   ("Precision", "Precision"), ("F1", "F1")]

# Per-issue: deck metric name -> confusion sheet
ISSUE_METRIC_SHEET = [("TPR", "Recall_by_issue"), ("TNR", "Specificity_by_issue"),
                      ("FPR", "FPR_by_issue"), ("FNR", "FNR_by_issue"),
                      ("Accuracy", "Accuracy_by_issue"),
                      ("Precision", "Precision_by_issue"), ("F1", "F1_by_issue")]

ISSUE_LABEL = {"A1": "No Issues", "A2": "Necessary", "A3": "Appropriate",
               "A4": "Unambiguous", "A5": "Complete", "A6": "Singular",
               "A9": "Correct", "A10": "Conforming", "A11": "Unsure of Category"}
ISSUE_ORDER = ["A1", "A2", "A3", "A4", "A5", "A6", "A9", "A10", "A11"]


def _confusion(dataset: str, cfg: str) -> Path:
    return RUNS_DIR / f"{dataset}_{cfg}_confusion_notebook.xlsx"


def _style(ax, bp):
    for b in bp["boxes"]:
        b.set(color="black"); b.set(facecolor="none")
    for m in bp["medians"]:
        m.set(color=_COLOR, linewidth=1.5)
    for w in bp["whiskers"]:
        w.set(color="black")
    for c in bp["caps"]:
        c.set(color="black")


def _hbox(ax, data, labels, title, med_fs=9):
    bp = ax.boxplot(data, tick_labels=labels, vert=False,
                    patch_artist=True, showfliers=True)
    _style(ax, bp)
    # Median value printed clearly ABOVE each box (not on the median line).
    for i, d in enumerate(data, 1):
        if len(d):
            med = np.nanmedian(d)
            if not np.isnan(med):
                ax.text(med, i + 0.42, f"{med:.2f}", va="bottom", ha="center",
                        color=_COLOR, fontsize=med_fs, fontweight="bold")
    ax.set_xlim(-0.04, 1.04)
    ax.set_ylim(0.4, len(data) + 0.8)   # headroom so the value labels aren't clipped
    ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.set_xlabel("Rate", fontsize=10)
    ax.set_title(title, fontweight="bold", fontsize=11)


def _summary_page(pdf, dataset):
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.5), sharey=True)
    fig.suptitle(f"{dataset}: Summary of Metrics", fontweight="bold", fontsize=15)
    labels = [lbl for _, lbl in SUMMARY_METRICS]
    for ax, cfg in zip(axes, CONFIGS):
        s = pd.read_excel(_confusion(dataset, cfg), sheet_name="Summary")
        colmap = {"TPR": "Recall", "TNR": "Specificity", "FPR": "FPR", "FNR": "FNR",
                  "Accuracy": "Accuracy", "Precision": "Precision", "F1": "F1"}
        data = [pd.to_numeric(s[colmap[m]], errors="coerce").dropna().values
                for m, _ in SUMMARY_METRICS]
        _hbox(ax, data, labels, CONFIG_TITLE[cfg])
    axes[0].invert_yaxis()
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    pdf.savefig(fig); plt.close(fig)


def _issue_page(pdf, dataset, metric_label, sheet):
    fig, axes = plt.subplots(1, 3, figsize=(15, 6), sharey=True)
    fig.suptitle(f"{dataset}: Distribution of {metric_label} by Issue",
                 fontweight="bold", fontsize=15)
    for ax, cfg in zip(axes, CONFIGS):
        df = pd.read_excel(_confusion(dataset, cfg), sheet_name=sheet)
        df = df.set_index(df.columns[0])
        rows = [r for r in ISSUE_ORDER if r in df.index]
        labels = [ISSUE_LABEL[r] for r in rows]
        data = [pd.to_numeric(df.loc[r], errors="coerce").dropna().values for r in rows]
        _hbox(ax, data, labels, CONFIG_TITLE[cfg], med_fs=8)
    axes[0].invert_yaxis()
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    pdf.savefig(fig); plt.close(fig)


def build(dataset: str) -> Path:
    out = OUTPUT_DIR / f"{dataset}_deck_report.pdf"
    with PdfPages(out) as pdf:
        _summary_page(pdf, dataset)
        for metric_label, sheet in ISSUE_METRIC_SHEET:
            _issue_page(pdf, dataset, metric_label, sheet)
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="+", default=["PM", "Bookshelf"])
    args = ap.parse_args()
    for ds in args.datasets:
        if all(_confusion(ds, c).exists() for c in CONFIGS):
            print(f"wrote {build(ds).name}")
        else:
            print(f"skip {ds}: missing confusion files")


if __name__ == "__main__":
    main()
