"""Method B — Directed (deductive) coding onto the INCOSE codebook.

For each disagreement record, an LLM routes the decision onto the sub-rule of
its criterion that it pushes against, and tags a direction (suppress / tighten /
remediate). Records that hit the same (criterion, sub-rule, direction) are
collapsed into one anchored rule, articulated by a second LLM call.

Two adaptations grounded in this corpus:

  * The router may set `misfiled_criterion` when the expert's reasoning actually
    concerns a different criterion than the one the AI flagged. On this data the
    A2 bucket is polluted with A9/verifiability rationale, so trusting the AI's
    label blindly would mis-anchor rules. We route to the reasoning, not the tag.

  * Every rule carries its evidence record_ids, so a human reviewer (the
    mandated checkpoint) can trace each rule back to the exact decisions.

Run:
    python -m icai_v2.pipeline.method_b_coding            # live (uses the API)
    python -m icai_v2.pipeline.method_b_coding --dry-run  # no API, stub routing
    python -m icai_v2.pipeline.method_b_coding --limit 5  # first 5 records only
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from .corpus import build_corpus, disagreements, CanonicalRecord
from .contract import ExtractedRule, save_rules

from shared.paths import output_dir, RULE_SETS_DIR

OUTPUT_DIR = output_dir("icai_v2")
from shared.paths import RUBRIC_DIR

CODEBOOK_PATH = RUBRIC_DIR / "incose_rules.json"

DIRECTIONS = ("suppress", "tighten", "remediate")


# --------------------------------------------------------------------------- #
# Codebook
# --------------------------------------------------------------------------- #

def load_codebook() -> Dict[str, Dict]:
    """criterion_id -> {name, description, sub_rules[]} from incose_rules.json."""
    data = json.loads(CODEBOOK_PATH.read_text(encoding="utf-8"))
    return {
        c["criterion_id"]: {
            "name": c.get("name", ""),
            "description": c.get("description", ""),
            "sub_rules": c.get("sub_rules", []),
        }
        for c in data["individual_criteria"]
    }


# --------------------------------------------------------------------------- #
# LLM plumbing (reuses the app's provider routing)
# --------------------------------------------------------------------------- #

_ENV_LOADED = False


def _ensure_env() -> None:
    """Load backend/.env ourselves.

    ai_analyzer relies on main.py (the FastAPI app) to call load_dotenv at
    startup; this offline tool bypasses main.py, so we must load it here or the
    provider keys are never set.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    from dotenv import load_dotenv
    from shared.llm import ensure_env
    ensure_env()
    _ENV_LOADED = True


def _call_llm(prompt: str) -> str:
    # Imported lazily so --dry-run needs neither the SDK nor an API key.
    _ensure_env()
    from shared.evaluator import _call_ai
    return _call_ai(prompt)


def _extract_json(text: str) -> dict:
    """Parse a JSON object from a model reply, tolerating ``` fences / prose."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


# --------------------------------------------------------------------------- #
# Stage 1 — route each record onto a sub-rule + direction
# --------------------------------------------------------------------------- #

def _routing_prompt(rec: CanonicalRecord, codebook: Dict[str, Dict]) -> str:
    crit = codebook.get(rec.criterion_id, {"name": rec.criterion_name, "sub_rules": []})
    sub_rules = "\n".join(f"  - {sr}" for sr in crit["sub_rules"]) or "  (none listed)"
    return f"""You are coding one reviewer decision onto the INCOSE requirement-quality codebook.

The AI evaluator flagged criterion {rec.criterion_id} ({crit['name']}) on this requirement and proposed a fix. A subject-matter expert then responded.

Requirement:
"{rec.requirement_text}"

AI's proposed fix (for {rec.criterion_id}):
"{rec.ai_suggestion}"

What the expert kept / wrote instead:
"{rec.user_text}"

Expert action: {rec.effective_action}
Expert note: {rec.notes or "(none)"}

Sub-rules of {rec.criterion_id}:
{sub_rules}

Decide:
1. sub_rule_id — which single sub-rule of {rec.criterion_id} this decision pushes against (e.g. "{rec.criterion_id}.1").
2. direction — one of:
   - "suppress": the flag was a false positive; the criterion should not fire in cases like this.
   - "tighten": the flag was right but the criterion/fix should be stricter or more specific.
   - "remediate": the flag was right but the FIX should differ from what the AI proposed.
3. misfiled_criterion — if the expert's reasoning actually concerns a DIFFERENT criterion, give its id (e.g. "A8"); otherwise null.

Return ONLY JSON:
{{"sub_rule_id": "...", "direction": "suppress|tighten|remediate", "misfiled_criterion": null, "rationale": "<= 20 words"}}"""


def _route_record(rec: CanonicalRecord, codebook: Dict[str, Dict],
                  dry_run: bool) -> Optional[dict]:
    if dry_run:
        return {
            "sub_rule_id": f"{rec.criterion_id}.1",
            "direction": "suppress" if rec.effective_action == "reject" else "remediate",
            "misfiled_criterion": None,
            "rationale": "[dry-run stub]",
        }
    try:
        routed = _extract_json(_call_llm(_routing_prompt(rec, codebook)))
    except Exception as exc:  # noqa: BLE001 — one bad record must not kill the run
        print(f"  ! routing failed for {rec.record_id}: {exc}")
        return None

    if routed.get("direction") not in DIRECTIONS:
        routed["direction"] = "remediate"
    return routed


# --------------------------------------------------------------------------- #
# Stage 2 — collapse and articulate
# --------------------------------------------------------------------------- #

def _articulation_prompt(criterion: str, name: str, sub_rule_id: str,
                         direction: str, members: List[dict]) -> str:
    examples = "\n".join(
        f"  - requirement: \"{m['rec'].requirement_text[:140]}\"\n"
        f"    AI proposed: \"{m['rec'].ai_suggestion[:120]}\"\n"
        f"    expert kept/wrote: \"{m['rec'].user_text[:120]}\"\n"
        f"    note: {m['rec'].notes or '(none)'}"
        for m in members
    )
    return f"""You are writing ONE reusable rule for an INCOSE requirements evaluator.

Anchor: sub-rule {sub_rule_id} of criterion {criterion} ({name}). Direction: {direction}.

It must generalise the following expert decisions (do NOT restate them one by one):
{examples}

Write a single short, testable rule telling the evaluator what to do, in the form
"When <condition>, <do / do not> <action>." Maximum 30 words.

Return ONLY JSON: {{"rule_text": "..."}}"""


def _articulate(criterion: str, name: str, sub_rule_id: str, direction: str,
                members: List[dict], dry_run: bool) -> str:
    if dry_run:
        return (f"[DRY RUN] {direction} rule for {sub_rule_id} "
                f"from {len(members)} record(s)")
    try:
        out = _extract_json(_call_llm(
            _articulation_prompt(criterion, name, sub_rule_id, direction, members)))
        return out.get("rule_text", "").strip() or "[articulation returned empty]"
    except Exception as exc:  # noqa: BLE001
        return f"[articulation failed: {exc}]"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def run(dry_run: bool = False, limit: Optional[int] = None) -> List[ExtractedRule]:
    codebook = load_codebook()
    records, _ = build_corpus()
    recs = disagreements(records, engaged_only=True)
    if limit:
        recs = recs[:limit]

    print(f"Routing {len(recs)} disagreement records"
          f"{' (dry run)' if dry_run else ''}...")

    # Stage 1: route. Group by the criterion the reasoning implicates (which may
    # differ from the flagged one), the sub-rule, and the direction.
    groups: Dict[tuple, List[dict]] = defaultdict(list)
    routed_count = 0
    for rec in recs:
        routed = _route_record(rec, codebook, dry_run)
        if not routed:
            continue
        routed_count += 1
        effective_criterion = routed.get("misfiled_criterion") or rec.criterion_id
        key = (effective_criterion, routed["sub_rule_id"], routed["direction"])
        groups[key].append({"rec": rec, "routed": routed})

    print(f"Routed {routed_count}/{len(recs)} records into {len(groups)} groups. "
          f"Articulating...")

    # Stage 2: one rule per group.
    rules: List[ExtractedRule] = []
    for (criterion, sub_rule_id, direction), members in sorted(
        groups.items(), key=lambda kv: -len(kv[1])
    ):
        name = codebook.get(criterion, {}).get("name", "")
        rule_text = _articulate(criterion, name, sub_rule_id, direction, members, dry_run)
        misfiled = any(m["routed"].get("misfiled_criterion") for m in members)
        rules.append(ExtractedRule(
            criterion=criterion,
            criterion_name=name,
            rule_text=rule_text,
            method="directed_coding",
            evidence=[m["rec"].record_id for m in members],
            support_count=len(members),
            direction=direction,
            sub_rule_id=sub_rule_id,
            extra={
                "rationales": [m["routed"].get("rationale", "") for m in members],
                "reanchored_from_ai_label": misfiled,
            },
        ))
    return rules


def _write_review_markdown(rules: List[ExtractedRule], path: Path) -> None:
    lines = ["# Method B — Directed Coding: candidate rules for review", ""]
    lines.append("Each rule is anchored to an INCOSE sub-rule and backed by the "
                 "listed evidence records. Approve / edit / reject each before it "
                 "enters the knowledge base.\n")
    for i, r in enumerate(rules, 1):
        flag = "  ⚑ re-anchored from AI's label" if r.extra.get(
            "reanchored_from_ai_label") else ""
        lines.append(f"## {i}. [{r.criterion} {r.criterion_name}] "
                     f"{r.sub_rule_id} · {r.direction} · support {r.support_count}{flag}")
        lines.append(f"\n> {r.rule_text}\n")
        lines.append(f"Evidence: {', '.join(r.evidence)}\n")
        lines.append("- [ ] approve  - [ ] edit  - [ ] reject\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Method B — directed coding")
    ap.add_argument("--dry-run", action="store_true",
                    help="skip the API; stub the routing to test plumbing")
    ap.add_argument("--limit", type=int, default=None,
                    help="only process the first N records")
    args = ap.parse_args()

    rules = run(dry_run=args.dry_run, limit=args.limit)

    OUTPUT_DIR.mkdir(exist_ok=True)
    suffix = "_dryrun" if args.dry_run else ""
    dest = OUTPUT_DIR if args.dry_run else RULE_SETS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    save_rules(rules, dest / f"rules_method_b{suffix}.json")
    _write_review_markdown(rules, OUTPUT_DIR / f"review_method_b{suffix}.md")

    print(f"\nProduced {len(rules)} candidate rules:")
    for r in rules:
        print(f"  [{r.criterion} {r.sub_rule_id} {r.direction} x{r.support_count}] "
              f"{r.rule_text[:70]}")
    print(f"\nWrote rules_method_b{suffix}.json and review_method_b{suffix}.md")


if __name__ == "__main__":
    main()
