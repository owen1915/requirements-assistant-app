"""Rule-injection layer — the core of the testbed.

Runs the same INCOSE per-criterion evaluation the UI prototype runs, but lets us
inject the SME-derived rules into the evaluator prompt so we can compare:

  * baseline — the prototype as shipped (no learned rules)
  * M1       — with Method A (ICAI) validated principles injected
  * M2       — with Method B (directed coding) rules injected

The injected rules are appended under their criterion in the criteria block the
model reads, tagged as expert-learned guidance. Everything else — the criteria
definitions, the output schema, the parsing — is reused from shared.evaluator so the
testbed stays faithful to the live evaluator.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

# Reuse the live evaluator's criteria + call. The offline tool bypasses main.py,
# so load the .env ourselves (same bootstrap the icai_v2 pipeline uses).
from shared.llm import ensure_env
ensure_env()

from shared.evaluator import CRITERIA, CRITERIA_ORDER, CRITERIA_NAMES, _call_ai  # noqa: E402

from shared.paths import RULE_SETS_DIR as _RULES_DIR

CONFIGS = ("baseline", "M1", "M2",
           "lenient", "default", "moderate", "strict", "icai2", "icai4rev",
           "lenient4rev", "lenient5rev")
_RULE_FILE = {"M1": "rules_method_a.json", "M2": "rules_method_b.json",
              "lenient": "rules_group_lenient.json",
              "default": "rules_group_default.json",
              "moderate": "rules_group_moderate.json",
              "strict": "rules_group_strict.json",
              "icai2": "rules_group_icai2.json",
              "icai4rev": "rules_group_icai4rev.json",
              "lenient4rev": "rules_group_lenient4rev.json",
              "lenient5rev": "rules_group_lenient5rev.json",
              "icai_v2": "rules_group_icai_v2.json",
              "lenient_icaiv2": "rules_group_lenient_plus_icaiv2.json",
              "icai_v2_s2": "rules_group_icai_v2_s2.json",
              "icai_v2_s1": "rules_group_icai_v2_s1.json"}

# Evaluator model for the testbed. Configurable so a run can pin a specific
# Sonnet without editing code; defaults to 4-6.
EVAL_MODEL = os.getenv("EVAL_MODEL", "claude-sonnet-4-6")


def available_configs() -> List[str]:
    """Every rule set that can actually be injected right now.

    The union of the historical names in `_RULE_FILE` and whatever
    rules_group_*.json files are on disk — so a set the Studio publishes is
    selectable immediately, without editing a table here.
    """
    on_disk = {p.stem.replace("rules_group_", "")
               for p in _RULES_DIR.glob("rules_group_*.json")}
    known = {c for c in _RULE_FILE if (_RULES_DIR / _RULE_FILE[c]).exists()}
    return sorted({"baseline", *known, *on_disk})


def load_sme_rules(config: str) -> Dict[str, List[str]]:
    """criterion_id -> [rule_text, ...] for the given config ({} for baseline).

    `_RULE_FILE` names the historical configs whose filenames do not follow the
    convention. Anything else is resolved as rules_group_<config>.json, so a rule
    set the ICAIv2 Studio publishes under a new tag is injectable straight away
    rather than needing this table edited first.
    """
    if config == "baseline":
        return {}
    path = _RULES_DIR / _RULE_FILE.get(config, f"rules_group_{config}.json")
    if not path.exists():
        known = ", ".join(sorted({*_RULE_FILE, "baseline"}))
        raise FileNotFoundError(
            f"no rule set for config {config!r} at {path}. Known configs: {known}; "
            f"any other name resolves to rules_group_<name>.json in {_RULES_DIR}")
    rules: Dict[str, List[str]] = {}
    for r in json.loads(path.read_text(encoding="utf-8")):
        rules.setdefault(r["criterion"], []).append(r["rule_text"])
    return rules


def _build_criteria_text(sme_rules: Dict[str, List[str]]) -> str:
    lines = []
    for c in CRITERIA:
        cid = c["criterion_id"]
        lines.append(f"**{cid} - {c['name']}**: {c['description']}")
        for sr in c.get("sub_rules", []):
            lines.append(f"  - {sr}")
        for learned in sme_rules.get(cid, []):
            lines.append(f"  - [Expert-reviewed guidance from prior reviews] {learned}")
    return "\n".join(lines)


# Two prompt framings:
#   "faithful"     — the deployed prototype's behaviour: judge satisfied
#                    true/false for every criterion. Tends to over-flag, which is
#                    exactly what the SME rules are meant to curb (so the M1/M2
#                    effect is visible against this baseline).
#   "conservative" — the mature Thesis prototype's "report only clear violations"
#                    framing, which itself suppresses over-flagging.
FRAMING = "faithful"

# Output mode:
#   "minimal" — return only the violated criterion_ids. ~80% fewer output tokens,
#               which is ~70% of the cost. Use for KPI matrices.
#   "full"    — return per-criterion explanations too (needed for the NLP layer).
OUTPUT_MODE = "minimal"


def _build_system(criteria_text: str, context: str, output_mode: str) -> str:
    """The static, cacheable part: instructions + criteria + context.

    Identical across every requirement in a (dataset, config), so marking it a
    cached prefix makes the repeats cost ~90% less on input tokens."""
    ctx = context.strip() if context else "No additional context provided."
    if output_mode == "minimal":
        out = ('CRITICAL: Your entire response must be ONLY this JSON object and '
               'nothing else — no preamble, no reasoning, no explanation, no '
               'markdown fences. Start your reply with the character { and end '
               'with }. Format: {"violated": ["A2", "A9"]} - the list of '
               "criterion_ids that are VIOLATED. Judge ALL criteria internally "
               "but output only the genuinely violated ones; {\"violated\": []} "
               "if none.")
    else:
        out = ('Output ONLY valid JSON, no markdown:\n'
               '{"criteria_evaluations": [{"criterion_id": "A2", "satisfied": false, '
               '"explanation": "...", "affected_text": "...", "suggested_replacement": "..."}]}\n'
               "Return one entry per criterion.")
    return f"""You are an expert requirements engineer. The user gives one requirement; evaluate it against each INCOSE criterion below.

System Context: {ctx}

Criteria to evaluate:
{criteria_text}

Judge against the System Context: if the context or ConOps supplies the need, traceability, or operating conditions, do not mark a criterion violated on that account. Where expert-reviewed guidance is given under a criterion, weight it — it reflects how expert reviewers judged similar cases.

{out}
Valid criterion_ids: {', '.join(CRITERIA_ORDER)}."""


def _build_user(requirement: Dict) -> str:
    return f"Requirement ID: {requirement['id']}\nText: \"{requirement['text']}\""


_CALL_TIMEOUT = 90   # seconds; a stuck request fails here instead of hanging
TEMPERATURE = 0.7    # raised from 0.1 so repeated runs show real variance


def _call(system: str, user: str, output_mode: str,
          provider: str = None, api_key: str = None) -> str:
    """Provider call with a hard timeout, no SDK retries, and prompt caching.

    The static `system` block is marked as a cached prefix (Anthropic prompt
    caching), so the criteria+context — identical across all requirements in a
    config — is billed at ~10% on repeats. `max_tokens` is small in minimal mode.
    """
    prov = (provider or os.getenv("AI_PROVIDER", "anthropic")).lower()
    max_tok = 500 if output_mode == "minimal" else 1200
    if prov == "anthropic":
        import anthropic
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
        client = anthropic.Anthropic(api_key=key, timeout=_CALL_TIMEOUT, max_retries=0)
        resp = client.messages.create(
            model=EVAL_MODEL, max_tokens=max_tok, temperature=TEMPERATURE,
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}])
        return resp.content[0].text.strip()
    # Non-anthropic fallback: fold system into the prompt (no caching).
    return _call_ai(f"{system}\n\n{user}", provider, api_key)


def _legacy_call(prompt: str, provider: str = None, api_key: str = None) -> str:
    prov = (provider or os.getenv("AI_PROVIDER", "anthropic")).lower()
    if prov == "anthropic":
        import anthropic
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
        client = anthropic.Anthropic(api_key=key, timeout=_CALL_TIMEOUT, max_retries=0)
        resp = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=1200, temperature=0.1,
            messages=[{"role": "user", "content": prompt}])
        return resp.content[0].text.strip()
    return _call_ai(prompt, provider, api_key)


def _strip_to_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner)
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1:
        text = text[s:e + 1]
    return json.loads(text)


def analyze_requirement(requirement: Dict, context: str, sme_rules: Dict[str, List[str]],
                        provider: str = None, api_key: str = None) -> Dict:
    """One requirement -> {criterion_id: violated?} plus raw evaluations for NLP.

    Returns dict with 'violated' (bool per criterion) and 'evaluations' (the full
    parsed list, kept for the comment-similarity analysis)."""
    criteria_text = _build_criteria_text(sme_rules)
    system = _build_system(criteria_text, context, OUTPUT_MODE)
    user = _build_user(requirement)
    raw = _call(system, user, OUTPUT_MODE, provider, api_key)
    data = _strip_to_json(raw)

    violated = {cid: False for cid in CRITERIA_ORDER}
    if OUTPUT_MODE == "minimal":
        evaluations = []  # no explanations in minimal mode
        for cid in data.get("violated", []):
            if cid in violated:
                violated[cid] = True
    else:
        evaluations = data.get("criteria_evaluations", [])
        for ev in evaluations:
            cid = ev.get("criterion_id", "")
            if cid in violated:
                violated[cid] = not bool(ev.get("satisfied", True))
    return {"violated": violated, "evaluations": evaluations}


def _demo() -> None:
    """Show the injected criteria block per config (no API calls)."""
    for config in CONFIGS:
        rules = load_sme_rules(config)
        injected = sum(len(v) for v in rules.values())
        print(f"\n=== config={config}: {injected} SME rules injected "
              f"across {len(rules)} criteria ===")
        for cid, rs in rules.items():
            for r in rs:
                print(f"  {cid}: {r[:80]}")


if __name__ == "__main__":
    _demo()
