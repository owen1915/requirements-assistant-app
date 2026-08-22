"""Compare the testbed's n8n replica against the real n8n run, per rule.

Pooled F1 hides compensating errors, and the two sides do not pool the same
rows anyway (n8n scores 9 rows including A1/A11; the testbed scores 7). So the
parity test is per-rule flag behaviour, judged against the n8n run's own
run-to-run spread rather than against a single number.

Reference values are the medians read off the "Comparative Analysis" deck for
Beta 1 (n8n + manually crafted sub-rules, Claude Sonnet 4.6, temperature 0.7,
100 runs). Beta 1 is the configuration the GR_subrules workflow implements.

    python -m n8n_testbed.n8n_parity --dataset PM --config n8nreplica
"""

from __future__ import annotations

import argparse
from typing import Dict, Optional

import numpy as np

from . import metrics
from shared.datasets import CRITERIA_NAMES

# --- Beta 1 reference medians (n8n, Sonnet 4.6, 100 runs) --------------------
BETA1_POOLED = {"recall": 0.60, "specificity": 0.87, "fpr": 0.13,
                "fnr": 0.40, "accuracy": 0.80, "precision": 0.63, "f1": 0.61}

# Per-issue medians. None = the deck shows no box for that rule/metric.
BETA1_BY_RULE = {
    "A2":  {"recall": 1.00, "fpr": 0.08, "precision": 0.50, "f1": 0.67},
    "A3":  {"recall": 0.00, "fpr": 0.09, "precision": 0.00, "f1": 0.50},
    "A4":  {"recall": 0.50, "fpr": 0.33, "precision": 0.43, "f1": 0.44},
    "A5":  {"recall": 0.50, "fpr": 0.09, "precision": 0.50, "f1": 0.57},
    "A6":  {"recall": 0.50, "fpr": 0.18, "precision": 0.25, "f1": 0.40},
    "A9":  {"recall": 0.44, "fpr": 0.25, "precision": 0.89, "f1": 0.57},
    "A10": {"recall": 0.80, "fpr": 0.50, "precision": 0.84, "f1": 0.82},
}

_POOLED_LABELS = [("recall", "TPR"), ("specificity", "TNR"), ("fpr", "FPR"),
                  ("fnr", "FNR"), ("accuracy", "Accuracy"),
                  ("precision", "Precision"), ("f1", "F1")]


def _med(series) -> Optional[float]:
    vals = series.dropna().values if hasattr(series, "dropna") else series
    return float(np.median(vals)) if len(vals) else None


def _fmt(v: Optional[float]) -> str:
    return " n/a " if v is None else f"{v:5.2f}"


def _delta(ours: Optional[float], theirs: Optional[float]) -> str:
    if ours is None or theirs is None:
        return "  -  "
    return f"{ours - theirs:+5.2f}"


def report(dataset: str, config: str) -> Dict:
    long = metrics.score(dataset, config)
    pooled = long[long["rule"] == "POOLED"]
    per_rule = long[long["rule"] != "POOLED"]
    n_runs = pooled["execution"].nunique()

    print(f"\n{'=' * 66}")
    print(f"  {dataset} / {config}: {n_runs} runs   vs   n8n Beta 1 (100 runs)")
    print(f"{'=' * 66}\n")

    print(f"  POOLED (7 rows, A2-A10)")
    print(f"  {'metric':<10} {'replica':>8} {'n8n B1':>8} {'delta':>7}")
    print(f"  {'-' * 36}")
    for key, label in _POOLED_LABELS:
        ours = _med(pooled[key])
        theirs = BETA1_POOLED.get(key)
        print(f"  {label:<10} {_fmt(ours):>8} {_fmt(theirs):>8} {_delta(ours, theirs):>7}")

    print(f"\n  PER RULE (recall / FPR — the parity-relevant pair)")
    print(f"  {'rule':<22} {'TPR':>6} {'B1':>6} {'d':>6}   {'FPR':>6} {'B1':>6} {'d':>6}")
    print(f"  {'-' * 62}")
    verdicts = {}
    for rule in ["A2", "A3", "A4", "A5", "A6", "A9", "A10"]:
        sub = per_rule[per_rule["rule"] == rule]
        if sub.empty:
            continue
        name = f"{rule} {CRITERIA_NAMES.get(rule, '')}"
        r_ours, f_ours = _med(sub["recall"]), _med(sub["fpr"])
        r_ref = BETA1_BY_RULE[rule]["recall"]
        f_ref = BETA1_BY_RULE[rule]["fpr"]
        print(f"  {name:<22} {_fmt(r_ours)} {_fmt(r_ref)} {_delta(r_ours, r_ref)}   "
              f"{_fmt(f_ours)} {_fmt(f_ref)} {_delta(f_ours, f_ref)}")
        verdicts[rule] = {"recall": (r_ours, r_ref), "fpr": (f_ours, f_ref)}

    # Parity call: a rule passes when both medians land within 0.15 of Beta 1's
    # (roughly one requirement's worth of movement on a 13-requirement set).
    print(f"\n  PARITY (|delta| <= 0.15 on both TPR and FPR)")
    print(f"  {'-' * 62}")
    passed, failed, skipped = [], [], []
    for rule, v in verdicts.items():
        # A rule with no ground-truth positives has undefined recall on our side
        # (metrics.py returns None by design). That is missing GT signal, not a
        # parity failure — scoring it either way would be meaningless.
        if v["recall"][0] is None:
            skipped.append(rule)
            print(f"  {rule:<5} {CRITERIA_NAMES.get(rule, ''):<16} N/A "
                  f"(no ground-truth positives on this dataset)")
            continue
        ok = all(v[m][1] is not None and abs(v[m][0] - v[m][1]) <= 0.15
                 for m in ("recall", "fpr"))
        (passed if ok else failed).append(rule)
        print(f"  {rule:<5} {CRITERIA_NAMES.get(rule, ''):<16} "
              f"{'PASS' if ok else 'FAIL'}")
    scored = len(passed) + len(failed)
    print(f"\n  {len(passed)}/{scored} scorable rules within tolerance."
          f"  Divergent: {', '.join(failed) if failed else 'none'}."
          f"  Unscorable: {', '.join(skipped) if skipped else 'none'}")
    return {"passed": passed, "failed": failed, "skipped": skipped,
            "runs": n_runs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="PM")
    ap.add_argument("--config", default="n8nreplica")
    args = ap.parse_args()
    report(args.dataset, args.config)


if __name__ == "__main__":
    main()
