"""Simplified ICAI (Findeis et al., ICLR 2025) principle induction.

The paper's five steps, with the two expensive ones traded down:

  1. GENERATE  - one LLM call per SME decision, 3 candidate principles each.
                 Corrective decisions get the paper's "negative trait" prompt
                 (Listing 1); accepted decisions get the neutral prompt
                 (Listing 2). Two prompt variants matter: the ablation (Table 3)
                 shows single-prompt generation is the worst configuration on
                 unaligned data, which is what our reject records are.
  2/3. DEDUP   - normalise each candidate's text, collapse exact duplicates, and
                 rank by how many decisions independently produced it. Frequency
                 stands in for cluster size. The paper uses k-means over
                 embeddings; ablating dedup entirely was mixed in Table 3
                 (better on 2 of 4 datasets), so this is a documented-loss
                 deviation, not a silent one.
  4. TEST      - one call per decision carrying ALL surviving principles, each
                 voting reject / accept / na. This is the paper's Step 4
                 parallelisation: the case text is the expensive token, so it is
                 sent once per case rather than once per principle.
  5. FILTER    - net = correct - incorrect; drop relevance < 10% or net <= 0;
                 rank by net; keep the top n.

Then the Eq. 1 agreement check: annotate with the constitution vs without, and
report the lift.

DEVIATION FROM THE PAPER'S DATA MODEL. ICAI assumes pairwise preferences (two
responses, one chosen). This corpus only half fits. The 44 corrective records
carry a genuine two-pole contrast (the AI's fragment vs the fragment the SME
kept), but all 159 accepts have user_text == ai_suggestion -- the pre-edit
fragment is never stored, so there is no second pole to compare against. The
unit here is therefore a binary judgement on a proposed edit ("did the expert
take this change?"), not a preference between two texts. Everything downstream
of that -- the A/B/None voting, the relevance and net accounting, the top-n
filter -- follows the paper.

Run:
    python -m icai_v2.pipeline.icai_simple
    python -m icai_v2.pipeline.icai_simple --dry-run
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .corpus import build_corpus, CanonicalRecord
from .contract import ExtractedRule, save_rules
from shared import llm

from shared.paths import output_dir, RULE_SETS_DIR

OUTPUT_DIR = output_dir("icai_v2")

SEED = 7
WORKERS = 12               # parallel API calls; the API is the bottleneck

N_ACCEPT_FOR_GENERATION = 44   # matched to the 44 corrective records
N_CANDIDATES_KEPT = 40         # cap before testing (bounds cost AND output size)
N_TEST_CASES = 100             # stratified: all corrective + accepts to fill
N_CONSTITUTION = 5             # paper default n=5

MIN_RELEVANCE = 0.10           # paper Step 5: drop principles relevant on <10%
AGREEMENT_BATCH = 25


@dataclass
class Case:
    """One SME decision, framed for generation and for testing."""
    record: CanonicalRecord
    label: str                 # "reject" (declined the edit) | "accept" (took it)

    @property
    def is_corrective(self) -> bool:
        return self.label == "reject"


def build_cases(data_dir: Path | None = None) -> List[Case]:
    """Every SME decision as a Case. `data_dir` selects the corpus; the
    default is the checked-in PM sessions, and the Studio passes an
    uploaded directory instead."""
    records, _ = (build_corpus(data_dir) if data_dir else build_corpus())
    return [
        Case(record=r,
             label="reject" if r.effective_action in ("reject", "modify") else "accept")
        for r in records
    ]


# --------------------------------------------------------------------------- #
# Step 1 - generation
# --------------------------------------------------------------------------- #

def _generation_prompt(case: Case) -> str:
    r = case.record
    if case.is_corrective:
        # Paper Listing 1: bias toward naming the bad trait in the rejected text.
        return f"""An AI evaluator flagged an INCOSE requirements criterion ({r.criterion_id} - {r.criterion_name}) and proposed a rewrite. An expert reviewer DECLINED the AI's version and kept their own wording instead.

Requirement: "{r.requirement_text[:400]}"
AI proposed:  "{r.ai_suggestion[:200]}"
Expert kept:  "{r.user_text[:200]}"
Reviewer note: {r.notes[:300] or '(none)'}

Why did the expert decline the AI's version? Reply with the 3 most likely rules that explain the decision, each 12 words or less. Be specific about the difference between the two versions. Each rule must start with "Do not flag" or "Do not replace" and name the bad thing the AI did.

Reply ONLY as JSON: {{"principles": ["...", "...", "..."]}}
DO NOT add markdown formatting around the JSON."""

    # Paper Listing 2: neutral, positive-trait phrasing.
    return f"""An AI evaluator flagged an INCOSE requirements criterion ({r.criterion_id} - {r.criterion_name}) and proposed a rewrite. An expert reviewer ACCEPTED the AI's version.

Requirement: "{r.requirement_text[:400]}"
AI proposed (accepted): "{r.ai_suggestion[:200]}"

Why was the AI right to flag this? Reply with the 3 most likely rules that explain the decision, each 12 words or less. Be specific about what was wrong with the original wording. Each rule must start with "Flag" or "Prefer".

Reply ONLY as JSON: {{"principles": ["...", "...", "..."]}}
DO NOT add markdown formatting around the JSON."""


def generate(cases: List[Case], dry_run: bool) -> List[Dict]:
    if dry_run:
        return [{"principle": f"[dry-run] principle {i}", "criterion": c.record.criterion_id}
                for i, c in enumerate(cases)]

    def one(case: Case) -> List[Dict]:
        try:
            out = llm.extract_json(llm.call_llm(_generation_prompt(case)))
            return [{"principle": p.strip(), "criterion": case.record.criterion_id}
                    for p in out.get("principles", []) if p and p.strip()]
        except Exception as exc:  # noqa: BLE001
            print(f"    ! generation failed ({case.record.record_id}): {exc}")
            return []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(one, cases))
    return [p for group in results for p in group]


# --------------------------------------------------------------------------- #
# Steps 2 + 3 - dedup by frequency (frequency stands in for cluster size)
# --------------------------------------------------------------------------- #

def _norm_principle(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return " ".join(text.split())


def dedup(candidates: List[Dict], keep: int) -> List[Dict]:
    buckets: Dict[str, Dict] = {}
    for c in candidates:
        key = _norm_principle(c["principle"])
        if not key:
            continue
        b = buckets.setdefault(key, {"principle": c["principle"],
                                     "criteria": set(), "count": 0})
        b["count"] += 1
        b["criteria"].add(c["criterion"])

    ranked = sorted(buckets.values(), key=lambda b: -b["count"])
    return [{"principle": b["principle"],
             "criterion": sorted(b["criteria"])[0] if b["criteria"] else "",
             "support": b["count"]}
            for b in ranked[:keep]]


# --------------------------------------------------------------------------- #
# Step 4 - testing (one call per case, every principle votes)
# --------------------------------------------------------------------------- #

def _test_prompt(case: Case, principles: List[Dict]) -> str:
    r = case.record
    rules = "\n".join(f'{i}. {p["principle"]}' for i, p in enumerate(principles))
    return f"""An AI evaluator proposed a change to a requirement:

Requirement: "{r.requirement_text[:350]}"
AI proposed replacing text with: "{r.ai_suggestion[:200]}"

For EACH rule below, decide what the rule implies an expert reviewer should do with the AI's proposed change:
- "reject": the rule implies the AI is wrong here and the change should be declined.
- "accept": the rule implies the AI is right here and the change should be taken.
- "na": the rule is not relevant to this case.

Rules:
{rules}

Answer in JSON, one verdict per rule number, e.g. {{"votes": {{"0": "reject", "1": "na", "2": "accept"}}}}.
Vote on ALL {len(principles)} rules. No ties, only "reject", "accept" or "na".
DO NOT respond with any text apart from the JSON.
DO NOT add markdown formatting around the JSON."""


def test_principles(principles: List[Dict], cases: List[Case],
                    dry_run: bool) -> List[Dict]:
    n = len(principles)
    tally = [{"correct": 0, "incorrect": 0, "relevant": 0} for _ in range(n)]

    if dry_run:
        for t in tally:
            t.update(correct=8, incorrect=2, relevant=10)
    else:
        def one(case: Case) -> Optional[Dict[str, str]]:
            for _ in range(2):
                try:
                    out = llm.extract_json(llm.call_llm(_test_prompt(case, principles)))
                    votes = out.get("votes", {})
                    if isinstance(votes, list):
                        votes = {str(i): v for i, v in enumerate(votes)}
                    return votes
                except Exception:  # noqa: BLE001
                    continue
            return None

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            all_votes = list(pool.map(one, cases))

        failed = sum(1 for v in all_votes if v is None)
        if failed:
            print(f"    ! {failed}/{len(cases)} test calls failed after retries")

        for case, votes in zip(cases, all_votes):
            if not votes:
                continue
            for i in range(n):
                v = str(votes.get(str(i), "na")).strip().lower()
                if v not in ("reject", "accept"):
                    continue
                tally[i]["relevant"] += 1
                if v == case.label:
                    tally[i]["correct"] += 1
                else:
                    tally[i]["incorrect"] += 1

    total = len(cases)
    scored = []
    for p, t in zip(principles, tally):
        scored.append({
            **p,
            "relevance": round(t["relevant"] / total, 3) if total else 0.0,
            "accuracy": round(t["correct"] / t["relevant"], 3) if t["relevant"] else None,
            "correct": t["correct"],
            "incorrect": t["incorrect"],
            "net": t["correct"] - t["incorrect"],
        })
    return scored


# --------------------------------------------------------------------------- #
# Eq. 1 - constitution-level agreement
# --------------------------------------------------------------------------- #

def _agreement_prompt(batch: List[Case], constitution: Optional[str]) -> str:
    cases = "\n".join(
        f'{i}. Requirement: "{c.record.requirement_text[:220]}"\n'
        f'   AI proposed: "{c.record.ai_suggestion[:150]}"'
        for i, c in enumerate(batch)
    )
    guide = (f"\n\nUse ONLY these expert-derived principles to decide. "
             f"If none apply, use your best judgement:\n{constitution}\n"
             if constitution else "")
    return f"""Below are cases where an AI requirements evaluator proposed a change. For each, predict what the expert reviewer decided about the AI's proposed change:
- "reject": the expert declined the change.
- "accept": the expert took the change.{guide}

Cases:
{cases}

Answer in JSON: {{"votes": {{"0": "accept", "1": "reject", ...}}}}
Vote on ALL {len(batch)} cases.
DO NOT respond with any text apart from the JSON."""


def agreement(cases: List[Case], constitution: Optional[str],
              model: str = None) -> float:
    batches = [cases[i:i + AGREEMENT_BATCH]
               for i in range(0, len(cases), AGREEMENT_BATCH)]

    def one(batch: List[Case]) -> List[str]:
        for _ in range(2):
            try:
                out = llm.extract_json(
                    llm.call_llm(_agreement_prompt(batch, constitution), model=model))
                votes = out.get("votes", {})
                if isinstance(votes, list):
                    votes = {str(i): v for i, v in enumerate(votes)}
                return [str(votes.get(str(i), "accept")).strip().lower()
                        for i in range(len(batch))]
            except Exception:  # noqa: BLE001
                continue
        return ["accept"] * len(batch)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        preds = [v for group in pool.map(one, batches) for v in group]

    correct = sum(1 for p, c in zip(preds, cases) if p == c.label)
    return round(correct / len(cases), 3) if cases else 0.0


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def run(dry_run: bool = False) -> List[ExtractedRule]:
    rng = random.Random(SEED)
    cases = build_cases()
    corrective = [c for c in cases if c.is_corrective]
    accepts = [c for c in cases if not c.is_corrective]
    rng.shuffle(accepts)

    gen_cases = corrective + accepts[:N_ACCEPT_FOR_GENERATION]
    test_cases = corrective + accepts[:max(0, N_TEST_CASES - len(corrective))]

    print(f"Corpus: {len(cases)} decisions "
          f"({len(corrective)} corrective, {len(accepts)} accepts)")

    t0 = time.time()
    print(f"\nStep 1  generating from {len(gen_cases)} decisions "
          f"({len(corrective)} corrective + {len(gen_cases)-len(corrective)} accepts)...")
    candidates = generate(gen_cases, dry_run)
    print(f"        -> {len(candidates)} candidate principles "
          f"({time.time()-t0:.0f}s)")

    print(f"\nStep 2/3 dedup by frequency, keep top {N_CANDIDATES_KEPT}...")
    survivors = dedup(candidates, N_CANDIDATES_KEPT)
    print(f"        -> {len(survivors)} distinct principles "
          f"(top support: {survivors[0]['support'] if survivors else 0})")

    if not survivors:
        return []

    t1 = time.time()
    print(f"\nStep 4  testing {len(survivors)} principles against "
          f"{len(test_cases)} decisions (1 call per decision)...")
    scored = test_principles(survivors, test_cases, dry_run)
    print(f"        -> done ({time.time()-t1:.0f}s)")

    print(f"\nStep 5  filtering (relevance >= {MIN_RELEVANCE}, net > 0, top {N_CONSTITUTION})...")
    eligible = [s for s in scored if s["relevance"] >= MIN_RELEVANCE and s["net"] > 0]
    eligible.sort(key=lambda s: -s["net"])
    top = eligible[:N_CONSTITUTION]
    print(f"        -> {len(eligible)} eligible, keeping {len(top)}")

    rules = [
        ExtractedRule(
            criterion=s["criterion"], criterion_name="", rule_text=s["principle"],
            method="icai_simple", evidence=[], support_count=s["support"],
            extra={"rank": rank, "relevance": s["relevance"], "accuracy": s["accuracy"],
                   "correct": s["correct"], "incorrect": s["incorrect"], "net": s["net"]},
        )
        for rank, s in enumerate(top, 1)
    ]

    if rules and not dry_run:
        constitution = "\n".join(f"- {r.rule_text}" for r in rules)
        print(f"\nEq. 1   agreement check over {len(test_cases)} SME decisions...")
        base = agreement(test_cases, None)
        withc = agreement(test_cases, constitution)
        print(f"        default annotator (no rules): {base}")
        print(f"        constitutional annotator:     {withc}")
        print(f"        lift:                         {withc - base:+.3f}")
        for r in rules:
            r.extra["agreement_base"] = base
            r.extra["agreement_with_constitution"] = withc

    (OUTPUT_DIR / "icai_simple_all_scored.json").write_text(
        json.dumps(scored, indent=2, ensure_ascii=False), encoding="utf-8")
    return rules


def _write_review(rules: List[ExtractedRule], path: Path) -> None:
    lines = [
        "# Simplified ICAI - candidate principles for SME review", "",
        "Generated from SME feedback by the ICAI algorithm (Findeis et al., ICLR 2025):",
        "generate -> dedup -> test -> filter. Each principle below survived a",
        "reconstruction test against real accept/reject decisions.", "",
        "**These principles correlate with the decisions; they were not necessarily used",
        "to make them.** Multiple different constitutions can explain the same data",
        "equally well (the Rashomon effect, paper Sec. 6). Absence of a harmful",
        "principle here is not evidence the data is free of one.", "",
    ]
    for i, r in enumerate(rules, 1):
        e = r.extra
        lines += [
            f"## {i}. [{r.criterion}] proposed by {r.support_count} decisions",
            "", f"> {r.rule_text}", "",
            f"Reconstruction: net={e['net']} (correct {e['correct']} - incorrect "
            f"{e['incorrect']}), relevance={e['relevance']}, accuracy={e['accuracy']}",
            "", "- [ ] approve   - [ ] edit   - [ ] reject", "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Simplified ICAI principle induction")
    ap.add_argument("--dry-run", action="store_true", help="no API calls")
    args = ap.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    rules = run(dry_run=args.dry_run)

    suffix = "_dryrun" if args.dry_run else ""
    save_rules(rules, OUTPUT_DIR / f"rules_icai_simple{suffix}.json")
    _write_review(rules, OUTPUT_DIR / f"review_icai_simple{suffix}.md")

    print(f"\n=== CONSTITUTION ({len(rules)} principles) ===")
    for i, r in enumerate(rules, 1):
        print(f"{i}. [{r.criterion}] {r.rule_text}")
        print(f"     net={r.extra['net']}  relevance={r.extra['relevance']}  "
              f"accuracy={r.extra['accuracy']}  proposed_by={r.support_count}")
    print(f"\nWrote rules_icai_simple{suffix}.json and review_icai_simple{suffix}.md")


if __name__ == "__main__":
    main()
