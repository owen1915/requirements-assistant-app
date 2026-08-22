import json


def create_set_analysis_prompt(requirements, context, glossary, programmatic_findings):
    """
    Build a prompt asking Claude to analyze the requirement SET holistically.

    Args:
        requirements: list of {id, text}
        context: system context string
        glossary: extracted terms from set_analyzer
        programmatic_findings: dict with terminology_issues and conflicts from set_analyzer
    """
    # Number all requirements
    req_lines = []
    for r in requirements:
        req_lines.append(f"  {r['id']}: \"{r['text']}\"")
    req_block = "\n".join(req_lines)

    # Format glossary
    glossary_lines = []
    for entry in glossary:
        ids = ", ".join(entry.get("requirement_ids", []))
        glossary_lines.append(f"  - {entry['term']} (used {entry['frequency']}x in {ids})")
    glossary_block = "\n".join(glossary_lines) if glossary_lines else "  (none extracted)"

    # Format programmatic findings so Claude knows what's already been caught
    prog_lines = []
    for issue in programmatic_findings.get("terminology_issues", []):
        terms = ", ".join(issue.get("terms", []))
        prog_lines.append(f"  - {issue.get('issue_type', 'unknown')}: {terms}")
    for conflict in programmatic_findings.get("conflicts", []):
        ids = ", ".join(conflict.get("requirement_ids", []))
        prog_lines.append(f"  - conflict ({conflict.get('type', 'unknown')}): {ids} -- {conflict.get('description', '')}")
    prog_block = "\n".join(prog_lines) if prog_lines else "  (none found)"

    prompt = f"""You are an expert requirements engineer. Analyze the following requirement SET holistically against INCOSE Guide v4 set-level quality characteristics (C10-C14).

**System Context:**
{context if context else "No additional context provided."}

**Requirements ({len(requirements)} total):**
{req_block}

**Extracted Glossary:**
{glossary_block}

**Already-Detected Issues (programmatic checks -- do NOT repeat these):**
{prog_block}

**Task:**
Assess this requirement set on five dimensions. For each, give an assessment (complete, partial, poor), a confidence score (0-1), specific findings, and actionable recommendations.

1. **C10 - Coverage**: Are there obvious missing requirements for the stated system context? Are failure modes, edge cases, or operational scenarios unaddressed?
2. **C11 - Logical Consistency**: Do any requirements contradict each other semantically (beyond the numeric/terminology conflicts already detected above)?
3. **C12 - Feasibility**: Can the full set of requirements be satisfied simultaneously? Are there implicit resource or physics constraints that make the set infeasible?
4. **C13 - Organization**: Is the set well-structured? Are requirements at a consistent level of abstraction? Is there unnecessary overlap?
5. **C14 - Validation Strategy**: Can this set be validated end-to-end? Are acceptance criteria clear enough to design a test plan?

**Output Format (JSON only, no other text):**
{{
  "set_findings": [
    {{
      "characteristic": "C10",
      "assessment": "partial",
      "confidence": 0.7,
      "findings": ["finding 1", "finding 2"],
      "recommendations": ["recommendation 1"]
    }}
  ],
  "cross_requirement_issues": [
    {{
      "type": "semantic_conflict",
      "requirements": ["REQ-1", "REQ-4"],
      "description": "description of the issue",
      "severity": "medium"
    }}
  ]
}}

Return ONLY valid JSON. Do not include any preamble or explanation outside the JSON."""

    return prompt


def analyze_set(requirements, context, glossary, programmatic_findings, api_key):
    """
    Call Claude with the set analysis prompt.
    Uses same model/params as individual analysis.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    prompt = create_set_analysis_prompt(requirements, context, glossary, programmatic_findings)

    message = client.messages.create(
        # Kept in step with ai_analyzer._call_ai — the previous pinned snapshot
        # (claude-sonnet-4-20250514) no longer resolves and 404s.
        model="claude-sonnet-4-5",
        # Set-level analysis covers every requirement at once, so the response
        # is far larger than a single-requirement evaluation. At 3000 it was
        # truncated mid-object and the JSON parse below failed.
        max_tokens=16000,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )

    if message.stop_reason == "max_tokens":
        raise ValueError(
            "Set analysis response was truncated at max_tokens. Reduce the "
            "number of requirements analysed together, or raise max_tokens."
        )

    response_text = message.content[0].text.strip()

    # Strip a ```json fence if one is present, without assuming the closing
    # fence is the final line.
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1] if "\n" in response_text else ""
        if "```" in response_text:
            response_text = response_text.rsplit("```", 1)[0]
        response_text = response_text.strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Set analysis returned text that is not valid JSON: {exc}"
        ) from exc
