"""Method A — Inverse Constitutional AI (ICAI)-style principle induction.

Findeis et al., ICLR 2025. ICAI runs an LLM "backwards": instead of using
principles to make judgements, it uses judgements to reconstruct the principles
that would have produced them, then keeps only principles that actually predict
the held-out judgements.

Adapted to this corpus, the published 5 stages collapse to 3:

  1. GENERATE  — per criterion, read the reject/modify decisions and propose
                 candidate principles ("Prefer / do not flag ... when ...").
  2. DEDUP     — merge near-duplicate principles into one set. (Published ICAI
                 clusters embeddings; at this scale we do an LLM merge pass, and
                 note the deviation.)
  3. VALIDATE  — reconstruction test: does the principle predict the SME's real
                 accept/reject decisions? Run over a MIX of corrective and accept
                 records and report accuracy STRATIFIED by action. This is the
                 fix the ICAI follow-up literature calls for: without it, a lazy
                 "reject everything" principle scores perfectly on the 23
                 corrective records while being wrong on every accept.

A principle survives only if it predicts corrective decisions well, does NOT
mis-fire on accepts, and covers a non-trivial share of the data.

Run:
    python -m icai_v2.pipeline.method_a_icai            # live (uses the API)
    python -m icai_v2.pipeline.method_a_icai --dry-run  # no API, stubbed
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from .corpus import build_corpus, disagreements, CanonicalRecord
from .contract import ExtractedRule, save_rules
from shared import llm

from shared.paths import output_dir, RULE_SETS_DIR

OUTPUT_DIR = output_dir("icai_v2")

# A principle survives validation only if it clears all three.
MIN_CORRECTIVE_ACC = 0.60   # predicts reject/modify decisions it covers
MIN_ACCEPT_ACC = 0.50       # does not systematically mis-fire on accepts
MIN_COVERAGE = 0.10         # fires on at least this share of validation records

N_ACCEPT_SAMPLES = 20       # accept "negatives" in the validation set
SEED = 7
BATCH = 30                  # validation cases per reconstruction call (reliable)

# Paper-faithful filtering (Findeis et al. Step 5): rank principles by net
# contribution (#correct - #incorrect), drop those relevant on < MIN_COVERAGE of
# the data or that don't improve reconstruction (net <= 0), keep the top n.
N_CONSTITUTION = 5          # size of the returned constitution (paper default n=5)


# --------------------------------------------------------------------------- #
# Stage 1 — generate candidate principles, per criterion
# --------------------------------------------------------------------------- #

def _generation_prompt(criterion: str, records: List[CanonicalRecord]) -> str:
    cases = "\n".join(
        f"  - requirement: \"{r.requirement_text[:160]}\"\n"
        f"    AI proposed: \"{r.ai_suggestion[:130]}\"\n"
        f"    expert kept/wrote instead: \"{r.user_text[:130]}\"\n"
        f"    note: {r.notes or '(none)'}"
        for r in records
    )
    return f"""You are compressing expert reviewer decisions into reusable PRINCIPLES for an INCOSE requirements evaluator, for criterion {criterion}.

Below are cases where the AI evaluator proposed a change under {criterion} and the expert REJECTED or MODIFIED it — meaning the AI's flag or its fix was wrong:

{cases}

Write 1 to 3 short PRINCIPLES that explain and generalise these decisions. Each must be a single testable statement in the form "Do not flag ... when ..." or "Prefer the requirement that ...". Do not restate individual cases; capture the pattern.

Return ONLY JSON: {{"principles": ["...", "..."]}}"""


def generate_candidates(by_criterion: Dict[str, List[CanonicalRecord]],
                        dry_run: bool) -> List[Dict]:
    candidates: List[Dict] = []
    for criterion, records in sorted(by_criterion.items(), key=lambda kv: -len(kv[1])):
        if dry_run:
            principles = [f"[dry-run] principle for {criterion} ({len(records)} recs)"]
        else:
            try:
                out = llm.extract_json(llm.call_llm(_generation_prompt(criterion, records)))
                principles = [p.strip() for p in out.get("principles", []) if p.strip()]
            except Exception as exc:  # noqa: BLE001
                print(f"  ! generation failed for {criterion}: {exc}")
                principles = []
        for p in principles:
            candidates.append({
                "criterion": criterion,
                "principle": p,
                "evidence": [r.record_id for r in records],
            })
    return candidates


# --------------------------------------------------------------------------- #
# Stage 2 — dedup
# --------------------------------------------------------------------------- #

def dedup(candidates: List[Dict], dry_run: bool) -> List[Dict]:
    if dry_run or len(candidates) <= 1:
        return candidates
    payload = [{"id": i, "criterion": c["criterion"], "principle": c["principle"]}
               for i, c in enumerate(candidates)]
    prompt = f"""Here are candidate principles for an INCOSE evaluator, each tagged with a criterion.
Merge duplicates and near-duplicates (same underlying rule) into one entry, keeping the clearest wording and the criterion. Keep genuinely distinct principles separate.

Input: {json.dumps(payload, ensure_ascii=False)}

Return ONLY JSON: {{"principles": [{{"criterion": "A9", "principle": "...", "merged_ids": [0,3]}}]}}"""
    try:
        out = llm.extract_json(llm.call_llm(prompt))
        merged: List[Dict] = []
        for m in out.get("principles", []):
            ids = m.get("merged_ids", [])
            evidence = sorted({e for i in ids if 0 <= i < len(candidates)
                               for e in candidates[i]["evidence"]})
            merged.append({
                "criterion": m.get("criterion", ""),
                "principle": m.get("principle", "").strip(),
                "evidence": evidence or (candidates[ids[0]]["evidence"] if ids else []),
            })
        return [m for m in merged if m["principle"]]
    except Exception as exc:  # noqa: BLE001
        print(f"  ! dedup failed, keeping raw candidates: {exc}")
        return candidates


# --------------------------------------------------------------------------- #
# Stage 3 — reconstruction test, stratified by action
# --------------------------------------------------------------------------- #

def _reconstruction_prompt(principle: str, val_records: List[CanonicalRecord]) -> str:
    cases = "\n".join(
        f"{i+1}. requirement: \"{r.requirement_text[:150]}\"\n"
        f"   AI proposed change: \"{r.ai_suggestion[:130]}\""
        for i, r in enumerate(val_records)
    )
    return f"""A reviewer principle is being tested:

PRINCIPLE: "{principle}"

For each case, the AI evaluator proposed a change to a requirement. Using ONLY the principle, predict what the expert reviewer would do with the AI's proposed change:
- "reject": the principle implies the AI is wrong here / the requirement should not be changed this way.
- "accept": the principle does not object to the AI's change.
- "na": the principle is not relevant to this case.

Cases:
{cases}

Return ONLY JSON with one verdict per case, in order:
{{"verdicts": ["reject"|"accept"|"na", ...]}}"""


def validate(principle: Dict, val_records: List[CanonicalRecord],
             dry_run: bool) -> Dict:
    truth = ["reject" if r.effective_action in ("reject", "modify") else "accept"
             for r in val_records]

    if dry_run:
        verdicts = ["reject" if t == "reject" else "accept" for t in truth]
    else:
        # Score in small BATCHES. One giant call makes the model blanket-reject
        # numeric rules (accept accuracy collapses to 0) and can overflow the
        # output cap into truncated JSON. Chunking keeps each call honest.
        verdicts = []
        for i in range(0, len(val_records), BATCH):
            chunk = val_records[i:i + BATCH]
            got = None
            for attempt in range(3):
                try:
                    out = llm.extract_json(llm.call_llm(
                        _reconstruction_prompt(principle["principle"], chunk)))
                    got = out.get("verdicts", [])
                    break
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! validation batch {i//BATCH} attempt {attempt+1} "
                          f"failed: {exc}")
            if got is None:
                got = ["na"] * len(chunk)
            verdicts += (got + ["na"] * len(chunk))[: len(chunk)]
    # pad/truncate defensively
    verdicts = (verdicts + ["na"] * len(val_records))[: len(val_records)]

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
    correct = corr_ok + acc_ok                     # relevant cases predicted right
    incorrect = (corr_cov - corr_ok) + (acc_cov - acc_ok)
    return {
        "coverage": round(covered / n, 3) if n else 0.0,
        "relevance": round(covered / n, 3) if n else 0.0,   # paper term for coverage
        "corrective_accuracy": round(corr_ok / corr_cov, 3) if corr_cov else None,
        "accept_accuracy": round(acc_ok / acc_cov, 3) if acc_cov else None,
        "corrective_covered": corr_cov,
        "accept_covered": acc_cov,
        "correct": correct,
        "incorrect": incorrect,
        "net": correct - incorrect,                # paper's ranking signal
    }


def _passes(scores: Dict) -> bool:
    ca = scores["corrective_accuracy"]
    aa = scores["accept_accuracy"]
    return (
        scores["coverage"] >= MIN_COVERAGE
        and ca is not None and ca >= MIN_CORRECTIVE_ACC
        and (aa is None or aa >= MIN_ACCEPT_ACC)
    )


# --------------------------------------------------------------------------- #
# Constitution-level agreement test (ICAI Eq. 1) — does the whole constitution
# help an annotator reconstruct the SME decisions better than no rules at all?
# --------------------------------------------------------------------------- #

def _agreement_prompt(records: List[CanonicalRecord], constitution: str = None) -> str:
    cases = "\n".join(
        f"{i+1}. requirement: \"{r.requirement_text[:150]}\"\n"
        f"   AI proposed change: \"{r.ai_suggestion[:130]}\""
        for i, r in enumerate(records)
    )
    guide = ("\n\nUse ONLY these expert-derived principles to decide; if none apply "
             "to a case, use your best judgement:\n" + constitution) if constitution else ""
    return f"""Below are cases where an AI evaluator proposed a change to a requirement. For each, predict what an expert requirements reviewer decided about the AI's proposed change:
- "reject": the expert declined the change (kept the original).
- "accept": the expert took the change.{guide}

Cases:
{cases}

Return ONLY JSON with one verdict per case, in order:
{{"verdicts": ["reject"|"accept", ...]}}"""


def agreement(records: List[CanonicalRecord], constitution: str,
              dry_run: bool) -> float:
    """Fraction of SME decisions an annotator reconstructs (with/without rules)."""
    truth = ["reject" if r.effective_action in ("reject", "modify") else "accept"
             for r in records]
    if dry_run:
        return 0.0
    preds: List[str] = []
    for i in range(0, len(records), BATCH):
        chunk = records[i:i + BATCH]
        got = None
        for _ in range(3):
            try:
                out = llm.extract_json(llm.call_llm(_agreement_prompt(chunk, constitution)))
                got = out.get("verdicts", [])
                break
            except Exception:  # noqa: BLE001
                pass
        if got is None:
            got = ["accept"] * len(chunk)          # neutral fallback
        preds += (got + ["accept"] * len(chunk))[: len(chunk)]
    correct = sum(1 for p, t in zip(preds, truth) if p == t)
    return round(correct / len(records), 3) if records else 0.0


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def run(dry_run: bool = False) -> List[ExtractedRule]:
    records, _ = build_corpus()
    # Generation uses corrective (reject/modify) records from every session. The
    # rubber-stamp session contributes none of these, so it is naturally absent
    # here — but it is NOT excluded from the corpus.
    corrective = disagreements(records, engaged_only=False)

    by_criterion: Dict[str, List[CanonicalRecord]] = defaultdict(list)
    for r in corrective:
        by_criterion[r.criterion_id].append(r)

    # Validation set: all corrective (positives) + accepts from ALL sessions,
    # including the rubber-stamp session (negatives). Those accepts are exactly
    # the test that stops a "reject-everything" principle passing — a lenient
    # reviewer's accepts are the hardest negatives, so they must be included.
    all_accepts = [r for r in records if r.effective_action == "accept"]
    random.Random(SEED).shuffle(all_accepts)
    val_records = corrective + all_accepts

    print(f"Stage 1: generating principles from {len(corrective)} corrective "
          f"records across {len(by_criterion)} criteria"
          f"{' (dry run)' if dry_run else ''}...")
    candidates = generate_candidates(by_criterion, dry_run)
    print(f"  -> {len(candidates)} candidate principles")

    print("Stage 2: deduplicating...")
    deduped = dedup(candidates, dry_run)
    print(f"  -> {len(deduped)} after dedup")

    print(f"Stage 3: reconstruction test over {len(val_records)} records "
          f"({len(corrective)} corrective + {len(val_records)-len(corrective)} accepts)...")

    # Score every candidate, then rank by net contribution and keep the top n
    # (paper Step 5) — drop those below the relevance floor or that don't help.
    scored = [{"cand": p, "scores": validate(p, val_records, dry_run)} for p in deduped]
    eligible = [x for x in scored
                if x["scores"]["relevance"] >= MIN_COVERAGE and x["scores"]["net"] > 0]
    eligible.sort(key=lambda x: -x["scores"]["net"])
    top = eligible[:N_CONSTITUTION]
    top_ids = {id(x) for x in top}

    for x in scored:
        s, p = x["scores"], x["cand"]
        mark = "KEEP" if id(x) in top_ids else "drop"
        print(f"  [{mark}] {p['criterion']}: net={s['net']} "
              f"(correct {s['correct']} - incorrect {s['incorrect']}), "
              f"rel={s['relevance']}  \"{p['principle'][:55]}\"")

    rules: List[ExtractedRule] = []
    for rank, x in enumerate(top, 1):
        p, s = x["cand"], x["scores"]
        rules.append(ExtractedRule(
            criterion=p["criterion"], criterion_name="", rule_text=p["principle"],
            method="icai", evidence=p["evidence"], support_count=len(p["evidence"]),
            extra={"reconstruction": s, "rank": rank}))

    # Constitution-level agreement test (ICAI Eq. 1): does the top-n constitution
    # help reconstruct the SME decisions better than no constitution at all?
    if rules and not dry_run:
        constitution = "\n".join(f"- {r.rule_text}" for r in rules)
        base = agreement(val_records, None, dry_run)
        withc = agreement(val_records, constitution, dry_run)
        print(f"\nConstitution agreement test ({len(val_records)} SME decisions):")
        print(f"  default annotator (no rules): {base}")
        print(f"  constitutional annotator:     {withc}")
        print(f"  agreement lift:               {withc - base:+.3f}")

    return rules


def _write_review_markdown(rules: List[ExtractedRule], path: Path) -> None:
    lines = ["# Method A — ICAI: validated principles for review", ""]
    lines.append("Each principle survived a reconstruction test — it predicts the "
                 "SME's real accept/reject decisions, scored separately on "
                 "corrective vs accept records. Approve / edit / reject before use.\n")
    for i, r in enumerate(rules, 1):
        s = r.extra["reconstruction"]
        lines.append(f"## {i}. [{r.criterion}] support {r.support_count}")
        lines.append(f"\n> {r.rule_text}\n")
        lines.append(f"Reconstruction: corrective acc={s['corrective_accuracy']} "
                     f"(n={s['corrective_covered']}), accept acc={s['accept_accuracy']} "
                     f"(n={s['accept_covered']}), coverage={s['coverage']}\n")
        lines.append(f"Evidence: {', '.join(r.evidence)}\n")
        lines.append("- [ ] approve  - [ ] edit  - [ ] reject\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Method A — ICAI principle induction")
    ap.add_argument("--dry-run", action="store_true",
                    help="skip the API; stub generation/validation to test plumbing")
    args = ap.parse_args()

    rules = run(dry_run=args.dry_run)

    OUTPUT_DIR.mkdir(exist_ok=True)
    suffix = "_dryrun" if args.dry_run else ""
    dest = OUTPUT_DIR if args.dry_run else RULE_SETS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    save_rules(rules, dest / f"rules_method_a{suffix}.json")
    _write_review_markdown(rules, OUTPUT_DIR / f"review_method_a{suffix}.md")

    print(f"\n{len(rules)} principles survived validation:")
    for r in rules:
        print(f"  [{r.criterion} x{r.support_count}] {r.rule_text[:72]}")
    print(f"\nWrote rules_method_a{suffix}.json and review_method_a{suffix}.md")


if __name__ == "__main__":
    main()
