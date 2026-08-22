"""Do two arms' per-run metric distributions differ? Two-sample, not paired.

Compares the 7 pooled metrics (TPR, TNR, FPR, FNR, Accuracy, Precision, F1) run
by run between two configs.

THREE THINGS THIS DELIBERATELY DOES NOT DO:

  * It does not pair runs. Both arms are independent stochastic draws at
    temperature 0.7; run 7 on one side has no correspondence to run 7 on the
    other, so a paired test would give a different answer if you shuffled the
    sheets. Mann-Whitney U (two-sample) is the primary test. Welch's t is
    reported alongside for readers who expect a t-test, with unequal variances
    assumed — never Student's, and never paired.

  * It does not claim equivalence from a non-significant result. "No evidence of
    difference" is not "evidence of no difference", and at small n that
    distinction is the whole ballgame. To argue two arms agree you need a TOST
    against a declared margin, or cell-level agreement — see `--tost`.

  * It does not treat the 7 metrics as 7 independent questions. FNR = 1 - TPR
    and FPR = 1 - TNR exactly, so those pairs carry identical p-values by
    construction. Holm correction is applied over the 5 non-redundant metrics.

    python -m n8n_testbed.parity_test --a n8nbatch --b n8nreal
"""

from __future__ import annotations

import argparse
from typing import Dict, List, Optional

import numpy as np
from scipy import stats

from . import metrics

METRICS = [("recall", "TPR"), ("specificity", "TNR"), ("fpr", "FPR"),
           ("fnr", "FNR"), ("accuracy", "Accuracy"),
           ("precision", "Precision"), ("f1", "F1")]

# FNR and FPR are exact complements of TPR and TNR, so they add no independent
# evidence. Corrections are computed over these five only.
NON_REDUNDANT = ["recall", "specificity", "accuracy", "precision", "f1"]


def pooled(config: str, dataset: str, criteria) -> Dict[str, np.ndarray]:
    df = metrics.score(dataset, config, criteria=criteria)
    p = df[df["rule"] == "POOLED"]
    return {m: p[m].dropna().values for m, _ in METRICS}


def holm(pvals: Dict[str, float]) -> Dict[str, float]:
    """Holm-Bonferroni over the non-redundant family."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    n = len(items)
    out, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        adj = min(1.0, (n - i) * p)
        running = max(running, adj)      # enforce monotonicity
        out[k] = running
    return out


def compare(a: str, b: str, dataset: str, criteria,
            margin: Optional[float] = None) -> List[Dict]:
    A, B = pooled(a, dataset, criteria), pooled(b, dataset, criteria)
    raw = {}
    rows = []

    for key, label in METRICS:
        x, y = A[key], B[key]
        if len(x) == 0 or len(y) == 0:
            continue
        u, p_mw = stats.mannwhitneyu(x, y, alternative="two-sided")
        t, p_t = stats.ttest_ind(x, y, equal_var=False)     # Welch
        # Common-language effect size: P(a random B run exceeds a random A run).
        cles = float(np.mean([[xi < yi for xi in x] for yi in y]))
        row = {"metric": label, "key": key,
               "a_med": float(np.median(x)), "b_med": float(np.median(y)),
               "delta": float(np.median(y) - np.median(x)),
               "p_mw": float(p_mw), "p_welch": float(p_t), "cles": cles,
               "n_a": len(x), "n_b": len(y)}
        if margin is not None:
            # TOST: is the difference in means inside +/- margin?
            d = np.mean(y) - np.mean(x)
            se = np.sqrt(np.var(x, ddof=1) / len(x) + np.var(y, ddof=1) / len(y))
            dof = len(x) + len(y) - 2
            p_lo = stats.t.sf((d + margin) / se, dof)      # H0: d <= -margin
            p_hi = stats.t.cdf((d - margin) / se, dof)     # H0: d >= +margin
            row["p_tost"] = float(max(p_lo, p_hi))
            row["equivalent"] = row["p_tost"] < 0.05
        rows.append(row)
        if key in NON_REDUNDANT:
            raw[key] = p_mw

    adj = holm(raw)
    for r in rows:
        r["p_holm"] = adj.get(r["key"])       # None for the redundant pair
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--a", default="n8nbatch", help="reference config")
    ap.add_argument("--b", required=True, help="config under test")
    ap.add_argument("--dataset", default="PM")
    ap.add_argument("--criteria", nargs="*", default=None,
                    help="restrict pooling to these criteria (both arms)")
    ap.add_argument("--tost", type=float, default=None, metavar="MARGIN",
                    help="also run TOST equivalence at +/- MARGIN (e.g. 0.10)")
    args = ap.parse_args()

    rows = compare(args.a, args.b, args.dataset, args.criteria, args.tost)
    n_a, n_b = rows[0]["n_a"], rows[0]["n_b"]
    crit = ", ".join(args.criteria) if args.criteria else "all ground-truth rows"
    print(f"{args.dataset}: {args.a} (n={n_a}) vs {args.b} (n={n_b})   criteria: {crit}")
    print("Mann-Whitney U, two-sided, unpaired. Holm over the 5 non-redundant metrics.\n")

    head = f"{'metric':<10}{args.a[:9]:>10}{args.b[:9]:>10}{'delta':>8}{'p (MW)':>10}{'p Holm':>9}{'Welch p':>9}{'P(b>a)':>8}"
    if args.tost:
        head += f"{'TOST':>8}"
    print(head)
    print("-" * len(head))
    for r in rows:
        holm_txt = "-" if r["p_holm"] is None else f"{r['p_holm']:.4f}"
        line = (f"{r['metric']:<10}{r['a_med']:>10.3f}{r['b_med']:>10.3f}"
                f"{r['delta']:>+8.3f}{r['p_mw']:>10.4f}{holm_txt:>9}"
                f"{r['p_welch']:>9.4f}{r['cles']:>8.2f}")
        if args.tost:
            line += f"{('equiv' if r.get('equivalent') else 'no'):>8}"
        print(line)

    print("\nFNR and FPR are exact complements of TPR and TNR - same p by "
          "construction, excluded from the correction.")
    if args.tost:
        print(f"TOST margin +/-{args.tost}: 'equiv' means the mean difference is "
              f"statistically inside that band.")
    else:
        print("No TOST margin given: a large p here means NO EVIDENCE OF "
              "DIFFERENCE, which is not evidence the arms agree. Pass --tost.")


if __name__ == "__main__":
    main()
