"""How reliable was each SME reviewer vs the ground truth (PM data)?

Each reviewer only saw the violations the AI flagged, and for each said
accept / modify / reject. Treat the reviewer as a classifier of those flags:

    endorsed (accept OR modify)  -> predicts "real issue"  (positive)
    reject                       -> predicts "not an issue" (negative)

Compare to Point_Mass_v5 GT -> per-reviewer confusion, then Agreement,
Precision, Recall, F1 and Cohen's kappa (kappa is the key reliability metric:
it discounts a reviewer who just accepts everything).

Produces reviewer_reliability_PM.pdf: a grouped-metric bar chart, a
per-criterion agreement heatmap, an endorsed-split (accept vs modify) bar, and
a scorecard table. No API — pure scoring of the feedback files + GT.

    python -m reviewer_reliability.reviewer_reliability
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd

from icai_v2.pipeline.corpus import effective_action

from shared.paths import FEEDBACK_DIR, GT_DIR, output_dir

GT_PATH = GT_DIR / "Point_Mass_v5_GroundTruth.xlsx"

OUTPUT_DIR = output_dir("reviewer_reliability")

# The four point-mass sessions, chronological -> SME 1..4.
REVIEWERS = ["cf9c5ba6", "aee204f7", "6e1e38fc", "9dc74a53"]
REVIEWER_LABEL = {"cf9c5ba6": "SME 1", "aee204f7": "SME 2",
                  "6e1e38fc": "SME 3", "9dc74a53": "SME 4"}

# feedback req_id (1..13) -> PM requirement ID (GT columns)
REQ_TO_PM = {1: "FR.1", 2: "FR.2", 3: "PR.1", 4: "PR.2", 5: "PR.3", 6: "PR.4",
             7: "PR.5", 8: "PR.6", 9: "PR.7", 10: "ER.1", 11: "ER.2",
             12: "ER.3", 13: "RR.1"}

CRIT_NAME = {"A2": "Necessary", "A3": "Appropriate", "A4": "Unambiguous",
             "A5": "Complete", "A6": "Singular", "A9": "Correct",
             "A10": "Conforming"}
CRIT_ORDER = ["A2", "A3", "A4", "A5", "A6", "A9", "A10"]


def _load_gt() -> Dict[str, Dict[str, bool]]:
    import json
    df = pd.read_excel(GT_PATH, sheet_name="Sheet1")
    df = df.set_index("Issue ID")
    reqcols = [c for c in df.columns if any(str(c).startswith(p)
               for p in ("FR.", "PR.", "ER.", "RR."))]
    gt: Dict[str, Dict[str, bool]] = {}
    for crit in CRIT_ORDER:
        if crit in df.index:
            gt[crit] = {c: str(df.loc[crit, c]).strip().lower() == "x" for c in reqcols}
    return gt


def _reviewer_records(session: str):
    """Yield (pm_id, criterion, endorsed?, is_modify) for each flag the SME saw."""
    import json
    d = json.loads((FEEDBACK_DIR / f"feedback_{session}.json")
                   .read_text(encoding="utf-8"))
    for req in d["requirement_feedback"]:
        pm = REQ_TO_PM.get(int(req["req_id"]))
        if not pm:
            continue
        rtext = req.get("original_text", "")
        for v in req.get("violation_feedback", []):
            crit = v.get("rule_id", "")
            eff = effective_action(v.get("ai_suggestion", ""), v.get("user_text", ""), rtext)
            endorsed = eff in ("accept", "modify")
            yield pm, crit, endorsed, (eff == "modify")


def score(session: str, gt) -> Dict:
    tp = tn = fp = fn = 0
    endorsed_n = modify_n = reject_n = 0
    # per-criterion agree counts
    per_crit = {c: [0, 0] for c in CRIT_ORDER}   # [agree, total]
    for pm, crit, endorsed, is_mod in _reviewer_records(session):
        if crit not in gt:
            continue
        g = gt[crit].get(pm, False)
        if endorsed:
            endorsed_n += 1
            modify_n += is_mod
            if g:
                tp += 1
            else:
                fp += 1
        else:
            reject_n += 1
            if g:
                fn += 1
            else:
                tn += 1
        agree = (endorsed and g) or ((not endorsed) and (not g))
        per_crit[crit][0] += agree
        per_crit[crit][1] += 1

    n = tp + tn + fp + fn
    po = (tp + tn) / n if n else float("nan")
    # Cohen's kappa (2x2)
    pe = (((tp + fp) / n) * ((tp + fn) / n) + ((fn + tn) / n) * ((fp + tn) / n)) if n else float("nan")
    kappa = (po - pe) / (1 - pe) if (n and (1 - pe) != 0) else 0.0
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if (prec == prec and rec == rec and prec + rec) else float("nan")
    return {
        "session": session, "TP": tp, "TN": tn, "FP": fp, "FN": fn, "n": n,
        "Agreement": po, "Precision": prec, "Recall": rec, "F1": f1, "Kappa": kappa,
        "endorsed": endorsed_n, "modify": modify_n, "reject": reject_n,
        "per_crit": {c: (per_crit[c][0] / per_crit[c][1] if per_crit[c][1] else np.nan)
                     for c in CRIT_ORDER},
    }


# --------------------------------------------------------------------------- #
# Plots
# --------------------------------------------------------------------------- #

def _bar_metrics(pdf, scores):
    metrics = ["Agreement", "Precision", "Recall", "F1"]
    colors = ["#8a1538", "#1f77b4", "#2ca02c", "#ff7f0e"]
    x = np.arange(len(REVIEWERS)); w = 0.2
    fig, ax = plt.subplots(figsize=(11, 6))
    for i, m in enumerate(metrics):
        vals = [scores[s][m] if scores[s][m] == scores[s][m] else 0 for s in REVIEWERS]
        bars = ax.bar(x + i * w, vals, w, label=m, color=colors[i], alpha=0.9)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.015, f"{v:.2f}",
                    ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x + w * 1.5)
    ax.set_xticklabels([REVIEWER_LABEL[s] for s in REVIEWERS])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title("PM reviewer reliability vs ground truth\n"
                 "(endorsed = accept+modify vs reject, scored against Point_Mass_v5)",
                 fontweight="bold", fontsize=13)
    ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.08), frameon=False)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def _heatmap(pdf, scores):
    mat = np.array([[scores[s]["per_crit"][c] for c in CRIT_ORDER] for s in REVIEWERS])
    fig, ax = plt.subplots(figsize=(10, 5))
    im = ax.imshow(mat, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(CRIT_ORDER)))
    ax.set_xticklabels([f"{c}\n{CRIT_NAME[c]}" for c in CRIT_ORDER], fontsize=9)
    ax.set_yticks(range(len(REVIEWERS)))
    ax.set_yticklabels([REVIEWER_LABEL[s] for s in REVIEWERS])
    for i in range(len(REVIEWERS)):
        for j in range(len(CRIT_ORDER)):
            v = mat[i, j]
            ax.text(j, i, "-" if np.isnan(v) else f"{v:.2f}", ha="center", va="center",
                    fontsize=9, color="black")
    ax.set_title("Per-criterion agreement with GT (fraction of flags each reviewer called correctly)",
                 fontweight="bold", fontsize=12)
    fig.colorbar(im, ax=ax, label="agreement", shrink=0.8)
    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def _endorse_split(pdf, scores):
    x = np.arange(len(REVIEWERS)); w = 0.55
    accepts = [scores[s]["endorsed"] - scores[s]["modify"] for s in REVIEWERS]
    modifies = [scores[s]["modify"] for s in REVIEWERS]
    rejects = [scores[s]["reject"] for s in REVIEWERS]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.bar(x, accepts, w, label="accept (trust flag + fix)", color="#2ca02c", alpha=0.85)
    ax.bar(x, modifies, w, bottom=accepts, label="modify (flag ok, fix rewritten)",
           color="#ff7f0e", alpha=0.9)
    ax.bar(x, rejects, w, bottom=np.array(accepts) + np.array(modifies),
           label="reject (dismiss flag)", color="#8a1538", alpha=0.85)
    ax.set_xticks(x); ax.set_xticklabels([REVIEWER_LABEL[s] for s in REVIEWERS])
    ax.set_ylabel("number of AI flags")
    ax.set_title("How each reviewer responded to the AI's flags",
                 fontweight="bold", fontsize=12)
    ax.legend(frameon=False); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def _scorecard(pdf, scores):
    fig = plt.figure(figsize=(11, 3.5)); fig.suptitle(
        "PM reviewer reliability scorecard", fontweight="bold", fontsize=13)
    cols = ["Reviewer", "session", "flags", "TP", "FP", "FN", "TN",
            "Agree", "Prec", "Rec", "F1", "modify"]
    rows = []
    for s in REVIEWERS:
        r = scores[s]
        def f(x): return f"{x:.2f}" if isinstance(x, float) and x == x else str(x)
        rows.append([REVIEWER_LABEL[s], s, r["n"], r["TP"], r["FP"], r["FN"], r["TN"],
                     f(r["Agreement"]), f(r["Precision"]), f(r["Recall"]),
                     f(r["F1"]), r["modify"]])
    ax = fig.add_axes([0.02, 0.05, 0.96, 0.8]); ax.axis("off")
    t = ax.table(cellText=rows, colLabels=cols, loc="center", cellLoc="center")
    t.auto_set_font_size(False); t.set_fontsize(9); t.scale(1, 1.6)
    for j in range(len(cols)):
        t[0, j].set_facecolor("#8a1538"); t[0, j].set_text_props(color="white")
    pdf.savefig(fig); plt.close(fig)


def main() -> None:
    gt = _load_gt()
    scores = {s: score(s, gt) for s in REVIEWERS}
    print("PM reviewer reliability vs Point_Mass_v5 GT:")
    print(f"  {'label':7}{'session':10}{'flags':>6}{'Agree':>7}{'Prec':>7}{'Rec':>7}{'F1':>7}{'modify':>7}")
    for s in REVIEWERS:
        r = scores[s]
        print(f"  {REVIEWER_LABEL[s]:7}{s:10}{r['n']:>6}{r['Agreement']:>7.2f}"
              f"{r['Precision'] if r['Precision']==r['Precision'] else 0:>7.2f}"
              f"{r['Recall'] if r['Recall']==r['Recall'] else 0:>7.2f}"
              f"{r['F1'] if r['F1']==r['F1'] else 0:>7.2f}{r['modify']:>7}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    out = OUTPUT_DIR / "reviewer_reliability_PM.pdf"
    with PdfPages(out) as pdf:
        _bar_metrics(pdf, scores)
        _heatmap(pdf, scores)
        _endorse_split(pdf, scores)
        _scorecard(pdf, scores)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
