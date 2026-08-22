"""Per-reviewer TPR / TNR / FPR / FNR vs ground truth, in one boxplot.

Each SME saw only the violations the AI flagged and said accept / modify /
reject on each. That makes the reviewer a binary classifier over the flagged
set: endorse = "this really is a violation", reject = "it is not". Scored
against the Point_Mass v5 ground truth:

    TP  endorsed & GT violation      FP  endorsed & GT clean
    FN  rejected & GT violation      TN  rejected & GT clean

Note the universe is the AI's flags, not all 91 (requirement x criterion)
cells - a reviewer is never asked about a defect the AI missed, so these rates
describe reviewing behaviour, not independent detection.

`modify` is the awkward case; --modify selects the policy:

    endorse  every modify counts as endorsing the flag (the old behaviour)
    reject   every modify counts as rejecting it
    split    classify each modify by whether the reviewer carried the AI's
             proposed change into their final text (see modify_polarity)

    python -m reviewer_reliability.reviewer_rates --modify split
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
import numpy as np
import pandas as pd

from shared.paths import FEEDBACK_DIR as DATA_DIR, GT_DIR, output_dir, REVIEWER_RUNS_DIR

GT_PATH = GT_DIR / "Point_Mass_v5_GroundTruth.xlsx"
OUTPUT_DIR = output_dir("reviewer_reliability")
PLOT_DIR = OUTPUT_DIR / "plots" / "notebook_style"

REVIEWERS = ["cf9c5ba6", "aee204f7", "6e1e38fc", "9dc74a53", "ffd92981"]
LABEL = {r: f"SME {i}" for i, r in enumerate(REVIEWERS, start=1)}

REQ_TO_PM = {1: "FR.1", 2: "FR.2", 3: "PR.1", 4: "PR.2", 5: "PR.3", 6: "PR.4",
             7: "PR.5", 8: "PR.6", 9: "PR.7", 10: "ER.1", 11: "ER.2",
             12: "ER.3", 13: "RR.1"}
CRITERIA = ["A2", "A3", "A4", "A5", "A6", "A9", "A10"]

METRICS = ["tpr", "tnr", "fpr", "fnr"]
MLABEL = {"tpr": "TPR", "tnr": "TNR", "fpr": "FPR", "fnr": "FNR"}
SERIES = "#B22222"
INK = "#1a1a1a"
MUTED = "#6b7280"

# Human adjudication of every `modify`, decided case by case against the
# criterion, the AI's suggestion, the SME's final text and their note.
# Keyed (session, violation_id). This is the authoritative labelling; the
# mechanical rule below exists for reproducibility and agreed with 7 of these 9.
#
# The two rejects are worth reading:
#   6e1e38fc 10-A2  the SME's fix ("less than [x]% relative humidity") addresses
#                   ambiguity, not necessity - the flag was miscategorised, so
#                   adopting the rewrite is not endorsement of A2.
#   ffd92981 12-A5  the SME deleted content rather than supplying the missing
#                   detail; their note is a style objection to "to prevent",
#                   not agreement that the requirement was incomplete.
ADJUDICATED = {
    ("aee204f7", "9-A4"): "endorse",
    ("aee204f7", "10-A2"): "endorse",
    ("6e1e38fc", "1-A10"): "endorse",
    ("6e1e38fc", "2-A10"): "endorse",
    ("6e1e38fc", "10-A2"): "reject",
    ("6e1e38fc", "12-A5"): "endorse",
    ("ffd92981", "6-A2"): "endorse",
    ("ffd92981", "9-A5"): "endorse",
    ("ffd92981", "12-A5"): "reject",
}

_PUNCT = re.compile(r"[^a-z0-9\[\]% ]+")
_STOP = set("the a an of to in on and or for with is are be shall system it "
            "that this as from by at all".split())


def _norm(t: str) -> str:
    return " ".join(_PUNCT.sub(" ", (t or "").lower()).split())


def _content(t: str) -> set:
    return {w for w in _norm(t).split() if w not in _STOP and len(w) > 1}


def modify_polarity(ai: str, user: str, orig: str) -> Tuple[str, str]:
    """Did a `modify` endorse the flag or decline it?

    The discriminator is whether the reviewer carried the AI's *proposed change*
    into their final text — not text similarity. Similarity fails here because
    `ai_suggestion` is sometimes a replacement span ("shall move") and sometimes
    a whole rewritten sentence, so a reviewer who applies a span edit still
    looks 95% similar to the original and 4% similar to the suggestion.

    Comparing against the tokens the AI ADDED relative to the original isolates
    the actual proposal. Known weakness: when those additions are dominated by
    specific values (coordinates, thresholds) a reviewer who adopts the AI's
    structure but declines its numbers scores low and is called a reject. Audit
    the printed classifications rather than trusting this blind.
    """
    na, nu, no = _norm(ai), _norm(user), _norm(orig)
    if not nu:
        return "reject", "empty"
    if nu == na:
        return "endorse", "verbatim AI text"
    if nu in no:
        return "reject", "slice of the original"
    added = _content(ai) - _content(orig)
    if not added:
        return ("endorse", "no novel AI tokens") if nu != no else ("reject", "unchanged")
    carried = len(added & _content(user)) / len(added)
    verdict = "endorse" if carried >= 0.5 else "reject"
    return verdict, f"carried {carried:.0%} of the AI's additions"


def load_gt() -> Dict[str, Dict[str, bool]]:
    df = pd.read_excel(GT_PATH, sheet_name="Sheet1").set_index("Issue ID")
    cols = [c for c in df.columns
            if any(str(c).startswith(p) for p in ("FR.", "PR.", "ER.", "RR."))]
    return {crit: {c: str(df.loc[crit, c]).strip().lower() == "x" for c in cols}
            for crit in CRITERIA if crit in df.index}


def score(modify: str = "split", verbose: bool = True) -> pd.DataFrame:
    gt = load_gt()
    rows, audit = [], []
    for rid in REVIEWERS:
        data = json.loads((DATA_DIR / f"feedback_{rid}.json").read_text(encoding="utf-8"))
        tp = tn = fp = fn = 0
        counts = {"accept": 0, "reject": 0, "modify": 0}
        for rq in data["requirement_feedback"]:
            req = REQ_TO_PM.get(int(rq["req_id"]))
            orig = rq.get("original_text", "")
            for v in rq.get("violation_feedback", []):
                crit = v.get("rule_id")
                if req is None or crit not in gt:
                    continue
                action = v.get("user_action", "")
                counts[action] = counts.get(action, 0) + 1
                if action == "modify":
                    vid = v.get("violation_id")
                    if modify == "endorse":
                        endorsed, why = True, "policy: endorse"
                    elif modify == "reject":
                        endorsed, why = False, "policy: reject"
                    elif modify == "adjudicated":
                        lab = ADJUDICATED.get((rid, vid))
                        if lab is None:
                            raise KeyError(f"no human label for {rid} {vid}; "
                                           "add it to ADJUDICATED or use --modify split")
                        endorsed, why = lab == "endorse", "human adjudication"
                    else:
                        pol, why = modify_polarity(v.get("ai_suggestion", ""),
                                                   v.get("user_text", ""), orig)
                        endorsed = pol == "endorse"
                    audit.append({"reviewer": LABEL[rid], "id": vid,
                                  "criterion": crit,
                                  "verdict": "endorse" if endorsed else "reject",
                                  "why": why})
                else:
                    endorsed = action == "accept"

                truth = gt[crit].get(req, False)
                if endorsed and truth:
                    tp += 1
                elif endorsed and not truth:
                    fp += 1
                elif not endorsed and truth:
                    fn += 1
                else:
                    tn += 1

        rows.append({
            "reviewer": LABEL[rid], "session": rid,
            "tp": tp, "tn": tn, "fp": fp, "fn": fn, "n": tp + tn + fp + fn,
            "tpr": tp / (tp + fn) if tp + fn else np.nan,
            "tnr": tn / (tn + fp) if tn + fp else np.nan,
            "fpr": fp / (fp + tn) if fp + tn else np.nan,
            "fnr": fn / (fn + tp) if fn + tp else np.nan,
            **{f"n_{k}": v for k, v in counts.items()},
        })

    df = pd.DataFrame(rows)
    if verbose and audit:
        print(f"modify decisions under policy '{modify}':")
        for a in audit:
            print(f"  {a['reviewer']:<7} {a['id']:<8} {a['criterion']:<4} "
                  f"-> {a['verdict']:<8} ({a['why']})")
        print()
    return df


def plot(df: pd.DataFrame, modify: str) -> Path:
    fig, ax = plt.subplots(figsize=(8.5, 5.6))
    data = [df[m].dropna().values for m in METRICS]
    bp = ax.boxplot(data, tick_labels=[MLABEL[m] for m in METRICS], vert=False,
                    patch_artist=True, widths=0.45, showfliers=False)
    for box in bp["boxes"]:
        box.set(color=SERIES, facecolor="none", linewidth=1.3)
    for med in bp["medians"]:
        med.set(color=SERIES, linewidth=2.2)
    for part in ("whiskers", "caps"):
        for art in bp[part]:
            art.set(color=SERIES, linewidth=1.0)

    # Every reviewer shown as a point: with n=5 the box alone hides who is who.
    rng = np.random.default_rng(0)
    for i, m in enumerate(METRICS, start=1):
        vals = df[m].values
        jitter = rng.uniform(-0.13, 0.13, len(vals))
        ax.scatter(vals, i + jitter, s=42, facecolors="none",
                   edgecolors=INK, linewidths=1.1, zorder=3)
        ax.text(float(np.nanmedian(vals)), i - 0.34,
                f"{np.nanmedian(vals):.2f}", ha="center", va="center",
                color=SERIES, fontsize=12)

    # Slight overhang: reviewers sitting at exactly 0.00 or 1.00 (SME 1 does on
    # every metric) get their marker clipped in half by a hard [0,1] limit.
    ax.set_xlim(-0.035, 1.035)
    ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.tick_params(labelsize=12, colors=INK)
    ax.set_xlabel("Rate", fontsize=13, color=INK)
    ax.set_ylabel("Metric", fontsize=13, color=INK)
    ax.invert_yaxis()
    ax.xaxis.grid(True, color="#e5e7eb", linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#d1d5db")
    ax.set_title(f"SME reviewer agreement with ground truth  (n={len(df)} reviewers)",
                 fontweight="bold", fontsize=14, color=INK, pad=12)
    # Caption is anchored to the AXES, not the figure, and pre-wrapped. Anchored
    # to the figure and left on one line it is wider than the plot, and
    # bbox_inches="tight" then expands the canvas to fit the text — which is what
    # made this chart run off the page.
    ax.text(0.5, -0.155,
            f"Each ring is one reviewer; box = spread across reviewers. "
            f"'modify' policy: {modify}.\n"
            f"Universe is the AI-flagged violations each reviewer saw, "
            f"not all requirement x criterion cells.",
            transform=ax.transAxes, ha="center", va="top",
            fontsize=9, color=MUTED, linespacing=1.5)

    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    out = PLOT_DIR / f"PM_reviewer_rates_{modify}.png"
    fig.subplots_adjust(left=0.12, right=0.98, top=0.90, bottom=0.26)
    plt.savefig(out, dpi=200, facecolor="white")
    plt.close(fig)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modify",
                    choices=["adjudicated", "endorse", "reject", "split"],
                    default="adjudicated")
    ap.add_argument("--compare", action="store_true",
                    help="print all three policies side by side")
    a = ap.parse_args()

    if a.compare:
        for pol in ("endorse", "reject", "split", "adjudicated"):
            d = score(pol, verbose=(pol == "adjudicated"))
            print(f"--- modify = {pol} ---")
            print(d[["reviewer", "n", "tp", "tn", "fp", "fn",
                     "tpr", "tnr", "fpr", "fnr"]].to_string(index=False))
            print(f"    median: " + "  ".join(
                f"{MLABEL[m]}={d[m].median():.2f}" for m in METRICS))
            print()
        return

    df = score(a.modify)
    print(df[["reviewer", "n", "n_accept", "n_modify", "n_reject",
              "tp", "tn", "fp", "fn", "tpr", "tnr", "fpr", "fnr"]].to_string(index=False))
    print("\nmedian across reviewers: " + "  ".join(
        f"{MLABEL[m]}={df[m].median():.2f}" for m in METRICS))
    REVIEWER_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(REVIEWER_RUNS_DIR / f"PM_reviewer_rates_{a.modify}.csv", index=False)
    print(f"\nwrote {plot(df, a.modify)}")


if __name__ == "__main__":
    main()
