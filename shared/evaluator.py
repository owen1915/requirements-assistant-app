"""
INCOSE Requirements Analyzer — A-Criteria Edition
Evaluates each requirement against A2–A10 criteria from incose_rules.json.

Structural design:
- AI only identifies: which criteria are violated + the exact affected_text substring.
- Recommendations are generated PROGRAMMATICALLY per criterion (no AI free-text generation).
- Parallel execution via ThreadPoolExecutor for speed.
"""

import anthropic
import openai as openai_lib
import urllib.request
import json
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Load A-criteria definitions from incose_rules.json
# ---------------------------------------------------------------------------

from shared.paths import RUBRIC_DIR

_CRITERIA_PATH = RUBRIC_DIR / 'incose_rules.json'


def _load_criteria() -> List[Dict]:
    with open(_CRITERIA_PATH, 'r') as f:
        data = json.load(f)
    return [
        c for c in data['individual_criteria']
        if c['criterion_id'] not in ('A1', 'A11')
    ]


CRITERIA = _load_criteria()
CRITERIA_ORDER = [c['criterion_id'] for c in CRITERIA]
CRITERIA_NAMES = {c['criterion_id']: c['name'] for c in CRITERIA}


# ---------------------------------------------------------------------------
# Prompt — AI only classifies violations and identifies affected_text
# ---------------------------------------------------------------------------

def _build_criteria_text() -> str:
    lines = []
    for c in CRITERIA:
        lines.append(f"**{c['criterion_id']} – {c['name']}**: {c['description']}")
        for sr in c.get('sub_rules', []):
            lines.append(f"  - {sr}")
    return "\n".join(lines)


CRITERIA_TEXT = _build_criteria_text()


def _build_prompt(requirement: Dict, context: str) -> str:
    return f"""You are an expert requirements engineer. Evaluate the requirement below against each INCOSE criterion.

System Context: {context.strip() if context else "No additional context provided."}

Requirement:
ID: {requirement['id']}
Text: "{requirement['text']}"

Criteria to evaluate:
{CRITERIA_TEXT}

Your job — for each criterion:
1. Decide: satisfied (true/false).
2. Write a 1–2 sentence explanation of why.
3. If violated: identify the EXACT verbatim substring from the requirement that is the problem (affected_text), and provide a concise improved replacement for ONLY that substring (suggested_replacement). Do not rewrite the whole requirement. Both affected_text and suggested_replacement are REQUIRED when satisfied is false — never leave them null on a violation.
4. If satisfied: affected_text and suggested_replacement are null.

Output ONLY valid JSON — no markdown, no preamble:
{{
  "criteria_evaluations": [
    {{
      "criterion_id": "A2",
      "satisfied": false,
      "explanation": "The requirement cannot be traced to any stakeholder need or ConOps in the provided context.",
      "affected_text": "should be user-friendly and easy to use by all operators",
      "suggested_replacement": "shall provide an interface conforming to [stakeholder need reference]"
    }},
    {{
      "criterion_id": "A3",
      "satisfied": true,
      "explanation": "The requirement refers to the system of interest and expresses a system-level capability.",
      "affected_text": null,
      "suggested_replacement": null
    }}
  ],
  "suggested_full_text": "Improved version of the full requirement with all problems resolved"
}}

Return one entry per criterion in order: {', '.join(CRITERIA_ORDER)}."""


# ---------------------------------------------------------------------------
# Single-requirement analysis
# ---------------------------------------------------------------------------

def get_provider() -> str:
    """Read AI_PROVIDER from env. Defaults to anthropic."""
    return os.getenv("AI_PROVIDER", "anthropic").strip().lower()


# Sampling parameters were removed on Opus 4.7+ and Sonnet 5+ — sending
# temperature to those models is a 400. Older models keep the pinned 0.1, so
# the shipped prototype's behaviour is unchanged.
_NO_SAMPLING = ('claude-opus-4-7', 'claude-opus-4-8', 'claude-opus-5',
                'claude-sonnet-5', 'claude-fable-5', 'claude-mythos-5')

DEFAULT_MODEL = 'claude-sonnet-4-5'


def resolve_model(model: str = None) -> str:
    """Explicit argument wins, then ANTHROPIC_MODEL, then the pinned default."""
    return (model or os.getenv('ANTHROPIC_MODEL') or DEFAULT_MODEL).strip()


def _call_ai(prompt: str, provider: str = None, api_key: str = None,
             model: str = None, max_tokens: int = 1200) -> str:
    """Route to Anthropic, OpenAI, or Ollama. Uses env vars by default."""
    provider = (provider or get_provider()).lower()

    if provider == "anthropic":
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise ValueError("ANTHROPIC_API_KEY is not set in .env")
        client = anthropic.Anthropic(api_key=key)
        model_id = resolve_model(model)
        if model_id.startswith(_NO_SAMPLING):
            # These models think adaptively by default. This workload is
            # structured JSON extraction, not reasoning, and every rule set
            # already in the repo was induced without thinking — leaving it on
            # would multiply output tokens and make new runs incomparable.
            kwargs = {'thinking': {'type': 'disabled'}}
        else:
            kwargs = {'temperature': 0.1}
        response = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        return response.content[0].text.strip()

    elif provider == "openai":
        key = api_key or os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            raise ValueError("OPENAI_API_KEY is not set in .env")
        client = openai_lib.OpenAI(api_key=key)
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=1200,
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()

    elif provider == "ollama":
        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
        payload = json.dumps({
            "model": ollama_model,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["response"].strip()

    else:
        raise ValueError(f"Unknown AI_PROVIDER: '{provider}'. Must be anthropic, openai, or ollama.")


def analyze_requirement(requirement: Dict, context: str, provider: str = None, api_key: str = None) -> Dict:
    prompt = _build_prompt(requirement, context)

    try:
        result_text = _call_ai(prompt, provider, api_key)
        if result_text.startswith("```"):
            lines = result_text.split("\n")
            inner = lines[1:]
            if inner and inner[-1].strip() == "```":
                inner = inner[:-1]
            result_text = "\n".join(inner)

        result = json.loads(result_text)
        evals = result.get("criteria_evaluations", [])

        cleaned = []
        present = set()
        for ev in evals:
            cid = ev.get("criterion_id", "")
            if cid not in CRITERIA_ORDER:
                continue
            present.add(cid)
            satisfied = bool(ev.get("satisfied", True))
            affected_text = ev.get("affected_text") or None

            suggested = ev.get("suggested_replacement") or None
            # Fallback: if violated but no suggestion, flag it clearly
            if not satisfied and not suggested:
                suggested = "[No suggestion provided — review manually]"

            cleaned.append({
                "criterion_id": cid,
                "criterion_name": CRITERIA_NAMES.get(cid, ""),
                "satisfied": satisfied,
                "explanation": ev.get("explanation", ""),
                "affected_text": affected_text,
                "suggested_replacement": suggested,
            })

        # Nothing the model returned matched a criterion we know about. That is
        # a response-shape failure, not a clean requirement — but the fill-in
        # below would turn it into seven satisfied criteria and report it as a
        # pass. This is the path that made ten requirements come back "0
        # criteria violated" with no error anywhere.
        if not present:
            return _error_result(
                requirement,
                "The model returned no recognised criteria. Expected "
                f"criterion_id values from {CRITERIA_ORDER}; got "
                f"{[e.get('criterion_id') for e in evals] or 'an empty list'}. "
                f"Raw response began: {result_text[:200]!r}",
            )

        # Fill in any criteria the AI skipped. Flagged, because "the model did
        # not mention this" is not the same claim as "the model checked it and
        # it passed", and only the second one justifies showing a green row.
        for cid in CRITERIA_ORDER:
            if cid not in present:
                cleaned.append({
                    "criterion_id": cid,
                    "criterion_name": CRITERIA_NAMES.get(cid, ""),
                    "satisfied": True,
                    "not_evaluated": True,
                    "explanation": "Not evaluated — the model did not return this criterion.",
                    "affected_text": None,
                    "suggested_replacement": None,
                })

        cleaned.sort(key=lambda e: CRITERIA_ORDER.index(e["criterion_id"]))

        return {
            "req_id": requirement["id"],
            "original_text": requirement["text"],
            "criteria_evaluations": cleaned,
            "suggested_full_text": result.get("suggested_full_text", requirement["text"]),
        }

    except json.JSONDecodeError as e:
        return _error_result(requirement, f"Failed to parse AI response: {e}")
    except Exception as e:
        return _error_result(requirement, f"Analysis failed: {e}")


def _error_result(requirement: Dict, error_msg: str) -> Dict:
    # Log it. A failed requirement is recorded as "every criterion satisfied"
    # so the review UI still has a complete row to render, which means a total
    # failure is indistinguishable from a clean pass by looking at the counts
    # alone — the caller has to check `error`. Printing here is what makes the
    # cause visible in the server log instead of only in the stored analysis.
    print(f"ANALYSIS ERROR [{requirement.get('id', '?')}]: {error_msg}")
    return {
        "req_id": requirement["id"],
        "original_text": requirement["text"],
        "error": error_msg,
        "criteria_evaluations": [
            {
                "criterion_id": cid,
                "criterion_name": CRITERIA_NAMES.get(cid, ""),
                "satisfied": True,
                "explanation": "Could not evaluate — analysis failed.",
                "affected_text": None,
                "suggested_replacement": None,
            }
            for cid in CRITERIA_ORDER
        ],
        "suggested_full_text": requirement["text"],
    }


# ---------------------------------------------------------------------------
# Parallel batch analysis
# ---------------------------------------------------------------------------

def analyze_all_requirements(
    requirements: List[Dict],
    context: str,
    session_id: str = None,
    provider: str = None,
    api_key: str = None,
) -> Dict:
    if not session_id:
        session_id = str(uuid.uuid4())[:8]

    analyzed: List[Optional[Dict]] = [None] * len(requirements)

    with ThreadPoolExecutor(max_workers=min(10, len(requirements))) as executor:
        future_to_index = {
            executor.submit(analyze_requirement, req, context, provider, api_key): i
            for i, req in enumerate(requirements)
        }
        for future in as_completed(future_to_index):
            i = future_to_index[future]
            req = requirements[i]
            try:
                result = future.result()
            except Exception as e:
                result = _error_result(req, str(e))
            analyzed[i] = result
            evs = result.get("criteria_evaluations", [])
            n = sum(1 for ev in evs if not ev["satisfied"])
            # Say how many criteria were actually judged. "0 criteria violated"
            # alone reads as a pass whether the model examined seven criteria
            # and cleared them or returned nothing usable.
            skipped = sum(1 for ev in evs if ev.get("not_evaluated"))
            note = f", {skipped} not evaluated" if skipped else ""
            print(f"  [{result['req_id']}] done — {n} criteria violated"
                  f" of {len(evs) - skipped} judged{note}")

    return {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": context,
        "rag_enhanced": False,
        "requirements": analyzed,
    }
