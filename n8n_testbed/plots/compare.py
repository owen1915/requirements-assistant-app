"""Comparison layer — the headline result: baseline vs M1 vs M2.

Consumes the scored matrices from metrics.py and answers: does injecting the
SME-derived rules move the prototype's agreement with ground truth, and does M1
(ICAI) or M2 (directed coding) do it better? Produces a comparison table
(pooled + per-rule, mean +/- std with deltas vs baseline) and grouped bar plots.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from n8n_testbed import metrics

from shared.paths import TESTBED_RUNS_DIR as RUNS_DIR, output_dir

# Matrices, raw dumps and ground-truth workbooks are the RUN STORE: each one
# cost 100 whole-set LLM calls, so they are versioned rather than rebuilt.
# Plots and summary workbooks are regenerable and go to outputs/.
RUNS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = output_dir("n8n_testbed")
PLOT_DIR = OUTPUT_DIR / "plots"

HEADLINE = ["accuracy", "precision", "recall", "f1", "fpr"]
CONFIG_COLOR = {"baseline": "#6c757d", "M1": "#1f77b4", "M2": "#8a1538"}


def _pooled_summary(long_df: pd.DataFrame) -> pd.DataFrame:
    """Per (dataset, config): mean+/-std of the pooled metrics across runs."""
    pooled = long_df[long_df["rule"] == "POOLED"]
    rows = []
    for (ds, cfg), g in pooled.groupby(["dataset", "config"]):
        row = {"dataset": ds, "config": cfg, "runs": g["execution"].nunique()}
        for m in ["accuracy", "precision", "recall", "specificity", "f1", "fpr", "fnr"]:
            row[f"{m}_mean"] = g[m].mean()
            row[f"{m}_std"] = g[m].std()
        rows.append(row)
    return pd.DataFrame(rows)


def _add_deltas(pooled: pd.DataFrame) -> pd.DataFrame:
    out = []
    for ds, g in pooled.groupby("dataset"):
        base = g[g["config"] == "baseline"]
        for _, r in g.iterrows():
            row = r.to_dict()
            for m in HEADLINE:
                if len(base):
                    row[f"{m}_delta_vs_base"] = r[f"{m}_mean"] - base[f"{m}_mean"].values[0]
            out.append(row)
    return pd.DataFrame(out)


def _grouped_bar(pooled: pd.DataFrame, dataset: str, path: Path) -> None:
    g = pooled[pooled["dataset"] == dataset]
    configs = [c for c in ["baseline", "M1", "M2"] if c in g["config"].values]
    x = np.arange(len(HEADLINE))
    w = 0.8 / max(len(configs), 1)
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, cfg in enumerate(configs):
        row = g[g["config"] == cfg].iloc[0]
        means = [row[f"{m}_mean"] for m in HEADLINE]
        errs = [row[f"{m}_std"] for m in HEADLINE]
        ax.bar(x + i * w, means, w, yerr=errs, capsize=3,
               label=cfg, color=CONFIG_COLOR.get(cfg, None), alpha=0.85)
    ax.set_xticks(x + w * (len(configs) - 1) / 2)
    ax.set_xticklabels(HEADLINE)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("score")
    ax.set_title(f"{dataset}: pooled KPIs by config (mean +/- std over runs)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _per_rule_metric_bar(long_df: pd.DataFrame, dataset: str, metric: str,
                         path: Path) -> None:
    g = long_df[(long_df["dataset"] == dataset) & (long_df["rule"] != "POOLED")]
    rules = sorted(g["rule"].unique())
    configs = [c for c in ["baseline", "M1", "M2"] if c in g["config"].values]
    x = np.arange(len(rules))
    w = 0.8 / max(len(configs), 1)
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, cfg in enumerate(configs):
        means = [g[(g["config"] == cfg) & (g["rule"] == r)][metric].mean() for r in rules]
        ax.bar(x + i * w, means, w, label=cfg, color=CONFIG_COLOR.get(cfg), alpha=0.85)
    ax.set_xticks(x + w * (len(configs) - 1) / 2)
    ax.set_xticklabels(rules)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel(metric)
    ax.set_title(f"{dataset}: {metric} by rule and config")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run(datasets: List[str], configs: List[str]) -> pd.DataFrame:
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    long = pd.concat(
        [metrics.score(ds, cfg) for ds in datasets for cfg in configs
         if (RUNS_DIR / f"{ds}_{cfg}_matrix.xlsx").exists()],
        ignore_index=True)

    pooled = _pooled_summary(long)
    pooled_deltas = _add_deltas(pooled)

    for ds in datasets:
        if ds not in long["dataset"].values:
            continue
        _grouped_bar(pooled, ds, PLOT_DIR / f"compare_{ds}_pooled.png")
        _per_rule_metric_bar(long, ds, "precision", PLOT_DIR / f"compare_{ds}_precision_by_rule.png")
        _per_rule_metric_bar(long, ds, "fpr", PLOT_DIR / f"compare_{ds}_fpr_by_rule.png")

    with pd.ExcelWriter(OUTPUT_DIR / "comparison_summary.xlsx") as xl:
        pooled_deltas.to_excel(xl, sheet_name="pooled_by_config", index=False)
        metrics.summarize(long).to_excel(xl, sheet_name="per_rule", index=False)

    # Console headline
    print("\n=== POOLED KPIs (mean over runs) ===")
    for ds in datasets:
        sub = pooled[pooled["dataset"] == ds]
        if not len(sub):
            continue
        print(f"\n{ds}:")
        print(f"  {'config':<9}{'acc':>7}{'prec':>7}{'rec':>7}{'f1':>7}{'fpr':>7}")
        for cfg in ["baseline", "M1", "M2"]:
            r = sub[sub["config"] == cfg]
            if not len(r):
                continue
            r = r.iloc[0]
            print(f"  {cfg:<9}{r['accuracy_mean']:>7.3f}{r['precision_mean']:>7.3f}"
                  f"{r['recall_mean']:>7.3f}{r['f1_mean']:>7.3f}{r['fpr_mean']:>7.3f}")
    return pooled_deltas


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="+", default=["PM", "Bookshelf"])
    ap.add_argument("--configs", nargs="+", default=["baseline", "M1", "M2"])
    args = ap.parse_args()
    run(args.datasets, args.configs)
    print("\nWrote comparison_summary.xlsx and compare_*.png in outputs/plots/")


if __name__ == "__main__":
    main()
