"""A simple visual explainer of the ICAI rule-extraction process (PDF).

Walks through, with the real records and results:
  1. the 3-stage pipeline (generate -> dedup -> validate)
  2. a worked example for the A9 rule
  3. why the stratified reconstruction test matters (keeps vs drops)
  4. the final extracted rules

    python -m icai_v2.icai_explainer
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib.backends.backend_pdf import PdfPages

from shared.paths import output_dir, RULE_SETS_DIR

OUTPUT_DIR = output_dir("icai_v2")

C_INPUT = "#eceff1"; C_STAGE = "#d6e4f0"; C_VALID = "#e6dcf0"
C_OUT = "#d9ead3"; C_DROP = "#f4cccc"; C_KEEP = "#d9ead3"


def _box(ax, cx, cy, w, h, text, fc, fs=10, weight="normal", wrapw=60, ec="black"):
    ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                 boxstyle="round,pad=0.006,rounding_size=0.015",
                 fc=fc, ec=ec, lw=1.2))
    wrapped = "\n".join(textwrap.fill(line, wrapw) for line in text.split("\n"))
    ax.text(cx, cy, wrapped, ha="center", va="center", fontsize=fs, fontweight=weight)


def _arrow(ax, x, y_top, y_bot, label=None):
    ax.annotate("", xy=(x, y_bot), xytext=(x, y_top),
                arrowprops=dict(arrowstyle="-|>", lw=1.8, color="#444"))
    if label:
        ax.text(x + 0.02, (y_top + y_bot) / 2, label, ha="left", va="center",
                fontsize=8, style="italic", color="#444")


def _page(pdf):
    fig = plt.figure(figsize=(8.5, 11)); ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    return fig, ax


# --------------------------------------------------------------------------- #

def page_overview(pdf):
    fig, ax = _page(pdf)
    ax.text(0.5, 0.95, "How ICAI Extracts Rules from SME Feedback",
            ha="center", fontsize=17, fontweight="bold")
    ax.text(0.5, 0.915, "Inverse Constitutional AI  —  running the evaluator backwards",
            ha="center", fontsize=11, style="italic", color="#555")
    ax.text(0.5, 0.87,
            "Instead of using rules to judge requirements, ICAI uses the experts'\n"
            "accept / reject decisions to reconstruct the rules that would produce them\n"
            "— then keeps only rules that actually predict those decisions.",
            ha="center", va="center", fontsize=10.5)

    cx = 0.5
    steps = [
        (0.775, C_INPUT, "SME FEEDBACK  (4 point-mass sessions)",
         "~154 accept / reject / modify decisions on the AI's flagged issues"),
        (0.635, C_INPUT, "KEEP ONLY DISAGREEMENTS",
         "reject + modify = the corrective signal  (≈ 23 records)\n"
         "where an expert actually overruled the AI"),
        (0.495, C_STAGE, "STAGE 1 — GENERATE",
         "per criterion, an LLM reads the overruled cases and proposes\n"
         "1–3 candidate principles  (\"Do not flag … when …\")"),
        (0.375, C_STAGE, "STAGE 2 — DEDUPLICATE",
         "merge near-duplicate principles into one set"),
        (0.235, C_VALID, "STAGE 3 — VALIDATE  (reconstruction test)",
         "does each principle PREDICT the experts' real decisions?\n"
         "tested on rejections + accepts, scored SEPARATELY (stratified)"),
        (0.09, C_OUT, "OUTPUT — surviving rules",
         "only principles that predict rejections without mis-firing on\n"
         "accepts are kept   →   2 rules (A9, A2)"),
    ]
    for i, (cy, fc, title, body) in enumerate(steps):
        _box(ax, cx, cy, 0.82, 0.10, f"{title}\n{body}", fc, fs=9.5, wrapw=70)
        if i:
            _arrow(ax, cx, steps[i - 1][0] - 0.05, cy + 0.05)
    pdf.savefig(fig); plt.close(fig)


def page_example(pdf):
    fig, ax = _page(pdf)
    ax.text(0.5, 0.95, "Worked example: the A9 (Correct) rule",
            ha="center", fontsize=15, fontweight="bold")

    ax.text(0.5, 0.90, "Three real expert decisions that were overruled (rejections):",
            ha="center", fontsize=10.5, style="italic")
    recs = [
        ("\"... accuracy of +/- 2.5mm [0.1 in] ...\"",
         "AI wanted:  +/- [value traceable to stakeholder need]",
         "Expert kept:  +/- 2.5mm [0.1 in]"),
        ("\"... execute FR2 with +/- 2.5mm accuracy\"",
         "AI wanted:  +/- [value TBD based on stakeholder need]",
         "Expert kept:  +/- 2.5mm [0.1 in]"),
        ("\"... execute FR1 in no more than 30 seconds\"",
         "AI wanted:  [value derived from stakeholder need]",
         "Expert kept:  30 seconds"),
    ]
    y = 0.85
    for req, ai, kept in recs:
        _box(ax, 0.5, y, 0.86, 0.075,
             f"Requirement {req}\n{ai}      |      {kept}", "#fff8e1", fs=8.5, wrapw=92)
        y -= 0.09
    _arrow(ax, 0.5, y + 0.02, y - 0.03, "the AI keeps replacing real values with placeholders")

    _box(ax, 0.5, y - 0.11, 0.86, 0.12,
         "STAGE 1 generates the principle:\n\n"
         "\"Do not flag requirements for lacking traceability to stakeholder "
         "needs when specific, measurable values are already provided.\"",
         C_STAGE, fs=10, weight="normal", wrapw=74)
    _arrow(ax, 0.5, y - 0.17, y - 0.235)

    _box(ax, 0.5, y - 0.315, 0.86, 0.13,
         "STAGE 3 validates it:\n\n"
         "Tested on 23 rejections + 20 accepts.\n"
         "Predicts 80% of the rejections it covers, and does NOT mis-fire on "
         "accepts.\n\n✓  KEPT  (corrective acc 0.80, coverage 0.35)",
         C_KEEP, fs=10, wrapw=74, ec="#2e7d32")
    pdf.savefig(fig); plt.close(fig)


def page_validation(pdf):
    fig, ax = _page(pdf)
    ax.text(0.5, 0.95, "Why the validation step matters",
            ha="center", fontsize=15, fontweight="bold")
    ax.text(0.5, 0.90,
            "Two candidate principles both explain the rejections —\n"
            "only the reconstruction test tells them apart.",
            ha="center", fontsize=10.5, style="italic")

    _box(ax, 0.5, 0.72, 0.86, 0.16,
         "CANDIDATE A  (over-broad)\n\n"
         "\"Prefer the requirement that maintains specific quantitative values.\"\n\n"
         "Predicts 100% of rejections  —  looks perfect!\n"
         "BUT also fires on ACCEPTS (where experts DID accept added detail)\n"
         "→ accept-accuracy 0.00\n\n"
         "✗  DROPPED", C_DROP, fs=10, wrapw=78, ec="#c0392b")

    _box(ax, 0.5, 0.44, 0.86, 0.16,
         "CANDIDATE B  (correctly scoped)\n\n"
         "\"Do not flag ... when specific, measurable values are already provided.\"\n\n"
         "Predicts 80% of rejections\n"
         "Does NOT mis-fire on accepts\n\n"
         "✓  KEPT", C_KEEP, fs=10, wrapw=78, ec="#2e7d32")

    ax.text(0.5, 0.235,
            "The stratified test (scoring rejections and accepts SEPARATELY) is what\n"
            "catches an over-broad rule that would otherwise look flawless.\n"
            "A rule must predict the rejections AND stay silent on the accepts.",
            ha="center", va="center", fontsize=10.5, fontweight="bold", color="#333")
    pdf.savefig(fig); plt.close(fig)


def page_output(pdf):
    import json
    rules_path = RULE_SETS_DIR / "rules_method_a.json"
    rules = json.load(open(rules_path, encoding="utf-8"))
    fig, ax = _page(pdf)
    ax.text(0.5, 0.95, "The rules ICAI extracted", ha="center",
            fontsize=15, fontweight="bold")
    ax.text(0.5, 0.905, "Both survived the reconstruction test.",
            ha="center", fontsize=10.5, style="italic")
    y = 0.78
    for r in rules:
        s = r["extra"]["reconstruction"]
        _box(ax, 0.5, y, 0.86, 0.18,
             f"[{r['criterion']}]   backed by {r['support_count']} expert decisions\n\n"
             f"\"{r['rule_text']}\"\n\n"
             f"reconstruction: predicts {s['corrective_accuracy']} of covered "
             f"rejections | coverage {s['coverage']}",
             C_OUT, fs=10.5, wrapw=74, ec="#2e7d32")
        y -= 0.24
    ax.text(0.5, 0.20,
            "These are injected into the evaluator's prompt as expert-learned\n"
            "guidance (config \"M1\") and tested in the deck-format evaluation.",
            ha="center", va="center", fontsize=10, color="#444")
    pdf.savefig(fig); plt.close(fig)


def _ltext(ax, x, y, s, fs=9, weight="normal", color="black"):
    ax.text(x, y, s, ha="left", va="top", fontsize=fs, fontweight=weight, color=color)


def page_single(pdf):
    import json
    rules_path = RULE_SETS_DIR / "rules_method_a.json"
    rules = json.load(open(rules_path, encoding="utf-8"))

    fig, ax = _page(pdf)
    ax.text(0.5, 0.975, "How ICAI Extracts — and Validates — Rules from SME Feedback",
            ha="center", fontsize=15, fontweight="bold")
    ax.text(0.5, 0.948, "Inverse Constitutional AI: use the experts' accept/reject "
            "decisions to reconstruct the rules that explain them, then keep only "
            "rules that predict those decisions.",
            ha="center", va="top", fontsize=8.8, style="italic", color="#555", wrap=True)

    # compact pipeline strip
    strip = [("SME feedback\n(4 sessions)", C_INPUT),
             ("keep DIS-\nAGREEMENTS\n(~23 records)", C_INPUT),
             ("STAGE 1\nGENERATE\nprinciples", C_STAGE),
             ("STAGE 2\nDEDUPLICATE", C_STAGE),
             ("STAGE 3\nVALIDATE", C_VALID),
             ("keep\nsurvivors\n(2 rules)", C_OUT)]
    xs = np.linspace(0.10, 0.90, len(strip))
    for k, (txt, fc) in enumerate(strip):
        _box(ax, xs[k], 0.885, 0.135, 0.055, txt, fc, fs=7.2, wrapw=16)
        if k:
            ax.annotate("", xy=(xs[k] - 0.067, 0.885), xytext=(xs[k-1] + 0.067, 0.885),
                        arrowprops=dict(arrowstyle="-|>", lw=1.3, color="#555"))

    # ---- THE VALIDATION TEST (the focus) ----
    ax.text(0.5, 0.815, "THE VALIDATION TEST  —  \"reconstruction\"",
            ha="center", fontsize=13, fontweight="bold", color="#4a148c")
    ax.add_patch(FancyBboxPatch((0.06, 0.44), 0.88, 0.35,
                 boxstyle="round,pad=0.008,rounding_size=0.01",
                 fc="#f6f1fb", ec="#4a148c", lw=1.4))
    x0 = 0.09
    _ltext(ax, 0.5, 0.775, "Idea: a good rule should let you REPLAY the experts' decisions "
           "— so we test whether the rule can PREDICT them.", fs=9.2, weight="bold")
    ax.texts[-1].set_ha("center"); ax.texts[-1].set_x(0.5)
    _ltext(ax, x0, 0.735,
           "1.  Build a test set with KNOWN answers:  the ~23 rejections (truth = \"reject\")  +  "
           "20 accepts (truth = \"accept\").\n     Each case's truth = what the expert actually did.", fs=8.8)
    _ltext(ax, x0, 0.685,
           "2.  Predict BLIND:  give an LLM ONLY the rule + the requirement + the AI's proposed "
           "change  (never the real\n     decision)  and ask, per case:  reject / accept / na "
           "(not relevant).", fs=8.8)
    _ltext(ax, x0, 0.635,
           "3.  Score STRATIFIED  (the key step):", fs=8.8, weight="bold")
    _ltext(ax, x0 + 0.03, 0.605,
           "•  corrective accuracy = of the rejections it covers, how many it correctly predicted \"reject\"\n"
           "•  accept accuracy      = of the accepts it covers, how many it correctly predicted \"accept\"\n"
           "•  coverage                 = fraction of cases the rule is relevant to (verdict ≠ \"na\")", fs=8.6)
    _ltext(ax, x0, 0.505, "4.  KEEP the rule only if:   coverage ≥ 0.10   AND   "
           "corrective ≥ 0.60   AND   accept ≥ 0.50.", fs=8.8, weight="bold")
    _ltext(ax, x0, 0.468, "Why split them?  A lazy rule that says \"reject everything\" scores "
           "corrective = 1.00 (looks flawless) but\naccept = 0.00 (it also rejects the accepts) — so the "
           "accept gate catches and drops it.", fs=8.4, color="#7b1fa2")

    # ---- keep vs drop, concrete ----
    _box(ax, 0.28, 0.345, 0.40, 0.13,
         "DROPPED  ✗\n\n\"Prefer requirements that keep\nquantitative values\"\n\n"
         "corrective 1.00  (perfect!)\nBUT accept 0.00  → over-broad",
         C_DROP, fs=8.6, wrapw=40, ec="#c0392b")
    _box(ax, 0.72, 0.345, 0.40, 0.13,
         "KEPT  ✓\n\n\"Do not flag ... when specific,\nmeasurable values are present\"\n\n"
         "corrective 0.80,  silent on accepts",
         C_KEEP, fs=8.6, wrapw=40, ec="#2e7d32")

    # ---- final rules ----
    ax.text(0.5, 0.255, "The 2 rules that survived:", ha="center",
            fontsize=10.5, fontweight="bold")
    y = 0.225
    for r in rules:
        s = r["extra"]["reconstruction"]
        _box(ax, 0.5, y, 0.88, 0.075,
             f"[{r['criterion']}]  (backed by {r['support_count']} expert decisions,  "
             f"corrective {s['corrective_accuracy']}, coverage {s['coverage']})\n"
             f"\"{r['rule_text']}\"", C_OUT, fs=8.6, wrapw=95, ec="#2e7d32")
        y -= 0.09
    ax.text(0.5, 0.045, "Caveat: within-sample test (tiny corpus, no held-out split) — it checks a rule "
            "coherently explains its own decisions\nwithout over-generalizing to accepts; a fresh reviewer "
            "(SME 4) would test true out-of-sample generalization.",
            ha="center", va="top", fontsize=7.6, style="italic", color="#666")
    pdf.savefig(fig); plt.close(fig)


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    out = OUTPUT_DIR / "ICAI_process_explainer.pdf"
    with PdfPages(out) as pdf:
        page_single(pdf)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
