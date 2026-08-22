"""Threshold sensitivity for ICAI rule selection.

The three survival gates (corrective accuracy, accept accuracy, coverage) are
judgment-call defaults. This asks: which principles survive as we tighten them?

To keep the comparison honest, candidates are GENERATED and SCORED exactly once
(generation is non-deterministic, so re-generating per threshold would confound
the threshold effect with generation noise). We then apply several threshold
GRIDS to the same fixed, scored candidate set.

    python -m icai_v2.pipeline.threshold_sensitivity
    python -m icai_v2.pipeline.threshold_sensitivity --dry-run
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from shared import llm
from .corpus import build_corpus, disagreements, CanonicalRecord
from .method_a_icai import (
    generate_candidates, dedup, _reconstruction_prompt, SEED,
)

from shared.paths import output_dir, RULE_SETS_DIR

OUTPUT_DIR = output_dir("icai_v2")

# The shared _call_ai hardcodes max_tokens=1200, so a long verdict array gets
# truncated into invalid JSON. Score in small batches so every call stays well
# under that ceiling and no candidate is silently dropped to a parse failure.
BATCH = 30

# corr = min corrective accuracy, acc = min accept accuracy, cov = min coverage
GRIDS = {
    "lenient":  {"corr": 0.50, "acc": 0.40, "cov": 0.05},
    "default":  {"corr": 0.60, "acc": 0.50, "cov": 0.10},
    "moderate": {"corr": 0.70, "acc": 0.55, "cov": 0.15},
    "strict":   {"corr": 0.80, "acc": 0.60, "cov": 0.20},
}


def batched_validate(principle: str, val_records: List[CanonicalRecord],
                     dry_run: bool) -> Dict:
    """Reconstruction test, scored in small batches so no call is truncated.

    Mirrors method_a_icai.validate's stratified scoring, but chunks the cases.
    """
    truth = ["reject" if r.effective_action in ("reject", "modify") else "accept"
             for r in val_records]

    verdicts: List[str] = []
    for i in range(0, len(val_records), BATCH):
        chunk = val_records[i:i + BATCH]
        if dry_run:
            verdicts += ["reject" if t == "reject" else "accept"
                         for t in truth[i:i + BATCH]]
            continue
        got = None
        for attempt in range(3):
            try:
                out = llm.extract_json(llm.call_llm(_reconstruction_prompt(principle, chunk)))
                got = out.get("verdicts", [])
                break
            except Exception as exc:  # noqa: BLE001
                print(f"    ! batch {i//BATCH} attempt {attempt+1} failed: {exc}")
        if got is None:
            got = ["na"] * len(chunk)
        verdicts += (got + ["na"] * len(chunk))[:len(chunk)]

    covered = corr_cov = corr_ok = acc_cov = acc_ok = 0
    for v, t in zip(verdicts, truth):
        if v == "na":
            continue
        covered += 1
        if t == "reject":
            corr_cov += 1
            corr_ok += (v == "reject")
        else:
            acc_cov += 1
            acc_ok += (v == "accept")
    n = len(val_records)
    return {
        "coverage": round(covered / n, 3) if n else 0.0,
        "corrective_accuracy": round(corr_ok / corr_cov, 3) if corr_cov else None,
        "accept_accuracy": round(acc_ok / acc_cov, 3) if acc_cov else None,
        "corrective_covered": corr_cov,
        "accept_covered": acc_cov,
    }


def _passes(scores: Dict, g: Dict) -> bool:
    ca, aa = scores["corrective_accuracy"], scores["accept_accuracy"]
    return (
        scores["coverage"] >= g["cov"]
        and ca is not None and ca >= g["corr"]
        and (aa is None or aa >= g["acc"])
    )


def build_scored_candidates(dry_run: bool) -> List[Dict]:
    records, _ = build_corpus()
    corrective = disagreements(records, engaged_only=False)

    by_criterion: Dict[str, List[CanonicalRecord]] = defaultdict(list)
    for r in corrective:
        by_criterion[r.criterion_id].append(r)

    all_accepts = [r for r in records if r.effective_action == "accept"]
    random.Random(SEED).shuffle(all_accepts)
    val_records = corrective + all_accepts

    print(f"Generating candidates from {len(corrective)} corrective records "
          f"across {len(by_criterion)} criteria{' (dry run)' if dry_run else ''}...")
    candidates = generate_candidates(by_criterion, dry_run)
    print(f"  -> {len(candidates)} candidates")
    deduped = dedup(candidates, dry_run)
    print(f"  -> {len(deduped)} after dedup")
    print(f"Scoring each over {len(val_records)} records "
          f"({len(corrective)} corrective + {len(all_accepts)} accepts)...")

    scored: List[Dict] = []
    for c in deduped:
        s = batched_validate(c["principle"], val_records, dry_run)
        scored.append({
            "criterion": c["criterion"],
            "principle": c["principle"],
            "support": len(c["evidence"]),
            "corr": s["corrective_accuracy"],
            "acc": s["accept_accuracy"],
            "cov": s["coverage"],
        })
        print(f"  {c['criterion']:4} corr={s['corrective_accuracy']} "
              f"acc={s['accept_accuracy']} cov={s['coverage']}  "
              f"\"{c['principle'][:55]}\"")
    return scored


def sweep(scored: List[Dict]) -> Dict[str, List[Dict]]:
    return {name: [c for c in scored if _passes(
                {"corrective_accuracy": c["corr"], "accept_accuracy": c["acc"],
                 "coverage": c["cov"]}, g)]
            for name, g in GRIDS.items()}


def _fmt(v) -> str:
    return "-" if v is None else f"{v:.2f}"


def report(scored: List[Dict], survivors: Dict[str, List[Dict]]) -> str:
    lines: List[str] = []
    lines.append("# ICAI threshold sensitivity\n")
    lines.append("Same fixed candidate set (generated + scored once); thresholds swept.\n")

    # Grid legend
    lines.append("| grid | min corrective | min accept | min coverage | # rules kept |")
    lines.append("|---|---|---|---|---|")
    for name, g in GRIDS.items():
        lines.append(f"| {name} | {g['corr']:.2f} | {g['acc']:.2f} | {g['cov']:.2f} "
                     f"| {len(survivors[name])} |")
    lines.append("")

    # Per-candidate: scores + which grids keep it
    lines.append("## Candidates and which grids keep them\n")
    lines.append("| criterion | corr | acc | cov | " +
                 " | ".join(GRIDS) + " | principle |")
    lines.append("|---|---|---|---|" + "|".join(["---"] * len(GRIDS)) + "|---|")
    # order: most permissive survival first
    def kept_count(c):
        return sum(c in survivors[name] for name in GRIDS)
    for c in sorted(scored, key=lambda x: (-kept_count(x), x["criterion"])):
        marks = " | ".join("Y" if c in survivors[name] else "." for name in GRIDS)
        lines.append(f"| {c['criterion']} | {_fmt(c['corr'])} | {_fmt(c['acc'])} "
                     f"| {_fmt(c['cov'])} | {marks} | {c['principle']} |")
    lines.append("")

    # Rules kept per grid
    lines.append("## Surviving rules by grid\n")
    for name in GRIDS:
        lines.append(f"### {name} "
                     f"(corr≥{GRIDS[name]['corr']}, acc≥{GRIDS[name]['acc']}, "
                     f"cov≥{GRIDS[name]['cov']})")
        if not survivors[name]:
            lines.append("- (none)\n")
            continue
        for c in survivors[name]:
            lines.append(f"- **[{c['criterion']}]** {c['principle']}  "
                         f"_(corr {_fmt(c['corr'])}, acc {_fmt(c['acc'])}, "
                         f"cov {_fmt(c['cov'])}, support {c['support']})_")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    scored = build_scored_candidates(args.dry_run)
    survivors = sweep(scored)

    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "threshold_sensitivity.json").write_text(
        json.dumps({"grids": GRIDS, "scored": scored,
                    "survivors": {k: [c["principle"] for c in v]
                                  for k, v in survivors.items()}},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    md = report(scored, survivors)
    (OUTPUT_DIR / "threshold_sensitivity.md").write_text(md, encoding="utf-8")

    print("\n" + "=" * 70)
    for name, g in GRIDS.items():
        print(f"{name:9} corr>={g['corr']} acc>={g['acc']} cov>={g['cov']} "
              f"-> {len(survivors[name])} rules")
    print("=" * 70)
    print("\nWrote outputs/threshold_sensitivity.md and .json")


if __name__ == "__main__":
    main()
