"""Method A x Method B agreement — the most trustworthy rules.

Loads the rules produced by both methods and finds where they independently
agree. A rule that BOTH an anchoring method (B, directed coding onto the INCOSE
codebook) and a discovery+validation method (A, ICAI) produced for the same
criterion is the strongest evidence the corpus supports it.

Output tiers, most trustworthy first:
  1. CORROBORATED   — both methods produced the same rule.
  2. VALIDATED-ONLY — Method A only, but it passed the reconstruction test.
  3. ANCHORED-ONLY  — Method B only (codebook-anchored, but unvalidated).

Run:
    python -m icai_v2.pipeline.merge            # live (uses the API to match)
    python -m icai_v2.pipeline.merge --dry-run  # match by criterion only
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from .contract import ExtractedRule, load_rules, save_rules
from shared import llm

from shared.paths import output_dir, RULE_SETS_DIR

OUTPUT_DIR = output_dir("icai_v2")


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #

def _match_prompt(criterion: str, a_rules: List[ExtractedRule],
                  b_rules: List[ExtractedRule]) -> str:
    a_block = "\n".join(f"  A{i}: \"{r.rule_text}\"" for i, r in enumerate(a_rules))
    b_block = "\n".join(f"  B{i}: \"{r.rule_text}\"" for i, r in enumerate(b_rules))
    return f"""Two rule-extraction methods produced candidate rules for INCOSE criterion {criterion}.

Method A (ICAI) principles:
{a_block}

Method B (directed coding) rules:
{b_block}

For each Method A principle, decide which Method B rule(s), if any, express the SAME underlying rule — the same condition and the same action, not merely the same criterion. If they match, write one clear merged statement.

Return ONLY JSON:
{{"matches": [{{"a": 0, "b": [0], "same": true, "merged_rule": "..."}}]}}
Use the integer indices from the A#/B# labels. If a principle matches nothing, give it "b": [] and "same": false."""


def _match_criterion(criterion: str, a_rules: List[ExtractedRule],
                     b_rules: List[ExtractedRule], dry_run: bool) -> List[Dict]:
    """Return match records: {a_idx, b_idxs, same, merged_rule}."""
    if dry_run:
        # Naive: every A rule "matches" all B rules in the same criterion.
        return [{"a": i, "b": list(range(len(b_rules))),
                 "same": bool(b_rules),
                 "merged_rule": a.rule_text}
                for i, a in enumerate(a_rules)]
    try:
        out = llm.extract_json(llm.call_llm(_match_prompt(criterion, a_rules, b_rules)))
        return out.get("matches", [])
    except Exception as exc:  # noqa: BLE001
        print(f"  ! matching failed for {criterion}: {exc}")
        return [{"a": i, "b": [], "same": False, "merged_rule": a.rule_text}
                for i, a in enumerate(a_rules)]


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #

def merge(a_rules: List[ExtractedRule], b_rules: List[ExtractedRule],
          dry_run: bool = False) -> List[ExtractedRule]:
    a_by_crit: Dict[str, List[ExtractedRule]] = defaultdict(list)
    b_by_crit: Dict[str, List[ExtractedRule]] = defaultdict(list)
    for r in a_rules:
        a_by_crit[r.criterion].append(r)
    for r in b_rules:
        b_by_crit[r.criterion].append(r)

    merged: List[ExtractedRule] = []
    matched_b_ids = set()   # (criterion, idx) of B rules absorbed into a match

    # Criteria where Method A has at least one principle: look for corroboration.
    for criterion, a_list in a_by_crit.items():
        b_list = b_by_crit.get(criterion, [])
        matches = _match_criterion(criterion, a_list, b_list, dry_run) if b_list \
            else [{"a": i, "b": [], "same": False, "merged_rule": a.rule_text}
                  for i, a in enumerate(a_list)]

        matched_a = set()
        for m in matches:
            ai = m.get("a")
            if ai is None or ai >= len(a_list):
                continue
            matched_a.add(ai)
            a_rule = a_list[ai]
            b_hits = [bi for bi in m.get("b", []) if 0 <= bi < len(b_list)] \
                if m.get("same") else []

            if b_hits:
                for bi in b_hits:
                    matched_b_ids.add((criterion, bi))
                b_matched = [b_list[bi] for bi in b_hits]
                evidence = sorted(set(a_rule.evidence) |
                                  {e for b in b_matched for e in b.evidence})
                merged.append(ExtractedRule(
                    criterion=criterion,
                    criterion_name=b_matched[0].criterion_name or a_rule.criterion_name,
                    rule_text=m.get("merged_rule") or a_rule.rule_text,
                    method="corroborated(icai+directed_coding)",
                    evidence=evidence,
                    support_count=len(evidence),
                    sub_rule_id=b_matched[0].sub_rule_id,
                    direction=b_matched[0].direction,
                    extra={
                        "tier": "corroborated",
                        "icai_reconstruction": a_rule.extra.get("reconstruction"),
                        "sources": {"a": a_rule.rule_text,
                                    "b": [b.rule_text for b in b_matched]},
                    },
                ))
            else:
                merged.append(_as_validated_only(a_rule))

        # A principles the matcher skipped entirely -> validated-only
        for i, a_rule in enumerate(a_list):
            if i not in matched_a:
                merged.append(_as_validated_only(a_rule))

    # Method A principles in criteria with no B rules at all
    for criterion, a_list in a_by_crit.items():
        if criterion not in b_by_crit:
            continue  # already handled above (b_list empty path)

    # Every B rule not absorbed into a corroboration -> anchored-only
    for criterion, b_list in b_by_crit.items():
        for i, b_rule in enumerate(b_list):
            if (criterion, i) not in matched_b_ids:
                merged.append(_as_anchored_only(b_rule))

    tier_order = {"corroborated": 0, "validated": 1, "anchored": 2}
    merged.sort(key=lambda r: (tier_order.get(r.extra.get("tier"), 9),
                               -r.support_count))
    return merged


def _as_validated_only(a_rule: ExtractedRule) -> ExtractedRule:
    r = ExtractedRule(**{**a_rule.__dict__})
    r.method = "validated_only(icai)"
    r.extra = {**a_rule.extra, "tier": "validated"}
    return r


def _as_anchored_only(b_rule: ExtractedRule) -> ExtractedRule:
    r = ExtractedRule(**{**b_rule.__dict__})
    r.method = "anchored_only(directed_coding)"
    r.extra = {**b_rule.extra, "tier": "anchored"}
    return r


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

_TIER_LABEL = {
    "corroborated": "CORROBORATED — both methods agree (highest trust)",
    "validated": "VALIDATED-ONLY — ICAI passed the reconstruction test",
    "anchored": "ANCHORED-ONLY — directed coding, not independently validated",
}


def _write_review_markdown(rules: List[ExtractedRule], path: Path) -> None:
    lines = ["# Merged rules — Method A x Method B", ""]
    lines.append("Ranked by trust. A rule both methods produced independently is "
                 "the strongest; approve those first.\n")
    current = None
    for r in rules:
        tier = r.extra.get("tier")
        if tier != current:
            current = tier
            lines.append(f"\n## {_TIER_LABEL.get(tier, tier)}\n")
        anchor = f" · {r.sub_rule_id}" if r.sub_rule_id else ""
        lines.append(f"### [{r.criterion}{anchor}] support {r.support_count}")
        lines.append(f"\n> {r.rule_text}\n")
        if r.extra.get("sources"):
            src = r.extra["sources"]
            lines.append(f"- Method A said: *{src['a']}*")
            for b in src["b"]:
                lines.append(f"- Method B said: *{b}*")
        recon = r.extra.get("icai_reconstruction") or r.extra.get("reconstruction")
        if recon:
            lines.append(f"- ICAI reconstruction: corrective_acc="
                         f"{recon.get('corrective_accuracy')}, accept_acc="
                         f"{recon.get('accept_accuracy')}, coverage="
                         f"{recon.get('coverage')}")
        lines.append(f"- Evidence: {', '.join(r.evidence)}\n")
        lines.append("- [ ] approve  - [ ] edit  - [ ] reject\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge Method A and Method B rules")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    a_path = RULE_SETS_DIR / "rules_method_a.json"
    b_path = RULE_SETS_DIR / "rules_method_b.json"
    if not a_path.exists() or not b_path.exists():
        raise FileNotFoundError(
            "Run method_a_icai and method_b_coding first "
            "(need rules_method_a.json and rules_method_b.json).")

    a_rules = load_rules(a_path)
    b_rules = load_rules(b_path)
    print(f"Loaded {len(a_rules)} Method A + {len(b_rules)} Method B rules. Matching...")

    merged = merge(a_rules, b_rules, dry_run=args.dry_run)

    save_rules(merged, OUTPUT_DIR / "merged_rules.json")
    _write_review_markdown(merged, OUTPUT_DIR / "merged_review.md")

    counts = defaultdict(int)
    for r in merged:
        counts[r.extra.get("tier")] += 1
    print(f"\nMerged {len(merged)} rules:")
    print(f"  corroborated : {counts['corroborated']}")
    print(f"  validated    : {counts['validated']}")
    print(f"  anchored     : {counts['anchored']}")
    print()
    for r in merged:
        tag = r.extra.get("tier", "?").upper()[:4]
        print(f"  [{tag}][{r.criterion} x{r.support_count}] {r.rule_text[:64]}")
    print("\nWrote merged_rules.json and merged_review.md")


if __name__ == "__main__":
    main()
