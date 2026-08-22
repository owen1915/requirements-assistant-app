"""Formatted PDF built from the ACTUAL notebook (colab) evaluation output.

Sources every number from the confusion workbook that
colab_R1_R14_evaluation_v2.run_metrics produced (via n8n_testbed.eval_colab):
  * Summary_Individual        -> overall "Detection Rate Distribution" (per run)
  * <Metric>_by_rule_indiv    -> per-criterion boxplots (per run)

Run eval_colab first, then:
    python -m n8n_testbed.plots.pdf_report --configs M1 M2
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

from n8n_testbed import inject

from shared.paths import TESTBED_RUNS_DIR as RUNS_DIR, output_dir

# Matrices, raw dumps and ground-truth workbooks are the RUN STORE: each one
# cost 100 whole-set LLM calls, so they are versioned rather than rebuilt.
# Plots and summary workbooks are regenerable and go to outputs/.
RUNS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = output_dir("n8n_testbed")
_COLOR = "maroon"

# Overall boxplot: same metric set/order the notebook uses.
_OVERALL = [("F1", "F1"), ("Precision", "Precision"), ("Accuracy", "Accuracy"),
            ("FNR", "FNR"), ("FPR", "FPR"), ("Specificity", "TNR"),
            ("Sensitivity", "TPR")]

# R-series -> criterion name, and the notebook's display order.
R_LABEL = {"R1": "Necessary", "R2": "Singular", "R3": "Unambiguous",
           "R4": "Complete", "R5": "Correct", "R11": "Conforming",
           "R12": "Appropriate"}
R_ORDER = ["R1", "R12", "R3", "R4", "R2", "R5", "R11"]
_PER_RULE = [("Precision_by_rule_indiv", "Precision"),
             ("Recall_by_rule_indiv", "Recall"),
             ("F1_by_rule_indiv", "F1"),
             ("FPR_by_rule_indiv", "FPR")]


def _confusion_path(config: str) -> Path:
    return RUNS_DIR / f"PM_{config}_confusion.xlsx"


def _style(ax, bp, med_lw):
    for b in bp["boxes"]:
        b.set(color="black"); b.set(facecolor="none")
    for m in bp["medians"]:
        m.set(color=_COLOR, linewidth=med_lw)
    for w in bp["whiskers"]:
        w.set(color="black")
    for c in bp["caps"]:
        c.set(color="black")


def _draw_overall(ax, si: pd.DataFrame, title: str):
    data = [si[col].dropna().values for col, _ in _OVERALL]
    labels = [lbl for _, lbl in _OVERALL]
    bp = ax.boxplot(data, tick_labels=labels, vert=False,
                    patch_artist=True, showfliers=True)
    _style(ax, bp, 1.5)
    for i, d in enumerate(data, 1):
        m = np.nanmedian(d) if len(d) else np.nan
        if not np.isnan(m):
            ax.text(m, i + 0.2, f"{m:.2f}", va="bottom", ha="center",
                    color=_COLOR, fontsize=11)
    ax.set_xlim(0, 1); ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.set_xlabel("Rate", fontsize=12); ax.set_ylabel("Metric", fontsize=12)
    ax.set_title(title, fontweight="bold", fontsize=13)


def _scoreable_rules(xls) -> set:
    """Criteria with >=1 ground-truth positive (TP+FN>0). Precision/recall/F1 are
    only defined for these; a criterion with no true violations cannot be scored
    on detection quality and must be excluded from those panels."""
    tp = pd.read_excel(xls, sheet_name="TP_by_rule_indiv")
    fn = pd.read_excel(xls, sheet_name="FN_by_rule_indiv")
    tp = tp.set_index(tp.columns[0]); fn = fn.set_index(fn.columns[0])
    out = set()
    for r in tp.index:
        s = pd.to_numeric(tp.loc[r], errors="coerce").fillna(0).sum() + \
            pd.to_numeric(fn.loc[r], errors="coerce").fillna(0).sum()
        if s > 0:
            out.add(r)
    return out


def _draw_per_rule(ax, sheet: pd.DataFrame, title: str, only_rules: set = None):
    sheet = sheet.set_index(sheet.columns[0])
    rules = [r for r in R_ORDER if r in sheet.index
             and (only_rules is None or r in only_rules)]
    labels, data = [], []
    for r in rules:
        vals = pd.to_numeric(sheet.loc[r], errors="coerce").dropna().values
        if len(vals):                       # skip criteria with no defined values
            labels.append(R_LABEL.get(r, r)); data.append(vals)
    if not data:
        ax.set_axis_off(); ax.set_title(f"{title} (no data)", fontsize=11); return
    bp = ax.boxplot(data, tick_labels=labels, vert=False,
                    patch_artist=True, showfliers=True)
    _style(ax, bp, 1)
    for i, d in enumerate(data, 1):
        m = np.nanmedian(d)
        ax.text(m, i - 0.32, f"{m:.2f}", va="bottom", ha="center",
                color=_COLOR, fontsize=9)
    ax.set_xlim(-0.04, 1.04); ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.set_xlabel("Rate", fontsize=10); ax.set_title(title, fontweight="bold", fontsize=12)
    ax.invert_yaxis()


def _title_page(pdf, configs, summaries):
    fig = plt.figure(figsize=(8.5, 11))
    fig.text(0.5, 0.90, "PM Requirements", ha="center", fontsize=22, fontweight="bold")
    fig.text(0.5, 0.855, "SME-Rule Evaluation - Notebook (AI4RE) Scoring",
             ha="center", fontsize=13)
    n = len(summaries[configs[0]])
    meta = [f"Model: claude-sonnet-4-5   Temperature: {inject.TEMPERATURE}",
            f"Runs per config: {n}",
            "Scoring: colab_R1_R14_evaluation_v2 (pooled per execution)",
            "Ground truth: R1_R14_GroundTruth.xlsx (directly-annotated criteria)"]
    fig.text(0.5, 0.80, "\n".join(meta), ha="center", fontsize=11, va="top")

    cols = ["Config", "Accuracy", "Precision", "Recall", "F1", "FPR"]
    keys = ["Accuracy", "Precision", "Recall", "F1", "FPR"]
    rows = [[c] + [f"{summaries[c][k].mean():.3f} ± {summaries[c][k].std():.3f}"
                   for k in keys] for c in configs]
    ax = fig.add_axes([0.08, 0.5, 0.84, 0.16]); ax.axis("off")
    t = ax.table(cellText=rows, colLabels=cols, loc="center", cellLoc="center")
    t.auto_set_font_size(False); t.set_fontsize(10); t.scale(1, 1.7)
    for j in range(len(cols)):
        t[0, j].set_facecolor("#8a1538"); t[0, j].set_text_props(color="white")
    fig.text(0.5, 0.45, "Overall KPIs, pooled per execution (mean ± std over runs)",
             ha="center", fontsize=11, style="italic")
    pdf.savefig(fig); plt.close(fig)


def build_pdf(configs: List[str], out_path: Path) -> Path:
    summaries = {c: pd.read_excel(_confusion_path(c), sheet_name="Summary_Individual")
                 for c in configs}
    with PdfPages(out_path) as pdf:
        _title_page(pdf, configs, summaries)
        for c in configs:
            xls = pd.ExcelFile(_confusion_path(c))
            # Overall
            fig, ax = plt.subplots(figsize=(8.5, 6))
            _draw_overall(ax, summaries[c],
                          f"PM / {c}: Detection Rate Distribution (100 runs)")
            fig.tight_layout(); pdf.savefig(fig); plt.close(fig)
            # Per-rule: show ALL criteria (as the notebook does). Where a
            # criterion has no GT positives (e.g. PM Necessary/Appropriate),
            # precision is 0 because every model flag is a false positive by
            # definition - shown, not hidden.
            fig, axes = plt.subplots(2, 2, figsize=(11, 11))
            fig.suptitle(f"PM / {c}: Metrics by Criterion",
                         fontweight="bold", fontsize=14)
            for ax, (sheet, label) in zip(axes.flat, _PER_RULE):
                df = pd.read_excel(xls, sheet_name=sheet)
                _draw_per_rule(ax, df, label)
            fig.tight_layout(rect=[0, 0, 1, 0.97]); pdf.savefig(fig); plt.close(fig)
    return out_path


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs="+", default=["M1", "M2"])
    ap.add_argument("--out", default=str(OUTPUT_DIR / "PM_boxplot_report.pdf"))
    args = ap.parse_args()
    build_pdf(args.configs, Path(args.out))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
