"""The n8n 'AI4RE GR_subrules' PART 1 prompt, transcribed verbatim.

Transcribed from the workflow export's `Evaluate Requirements` node
(`@n8n/n8n-nodes-langchain.agent`), preserving paragraph order, the `---`
separators, the `Description:` / `Sub-rules:` labels, the bullet characters, and
the sub-rule punctuation (`A2.1 ` with no colon). The export's mojibake is
resolved back to the characters it encodes: `â` -> em dash,
`â¢` -> bullet, `â` -> en dash.

Two deliberate deviations, both consequences of scoping this to the A criteria:

  1. The sentence "Your task is to perform evaluations in TWO parts:" is
     dropped, since PART 2 is not included. The "## PART 1: ..." header is kept
     because it frames the individual-requirement task.
  2. OUTPUT FORMAT covers `individualEvaluations` only. n8n's own example is
     otherwise reproduced as written - including its mislabelling of A3 as
     "Unambiguous" (A3 is Appropriate). That error is in the workflow and is
     preserved rather than corrected.

Everything from the opening paragraph through A11 is byte-faithful to the
export, which is complete over that span; the export's truncation falls in the
trailing set-level example, which this file does not use.
"""

from __future__ import annotations

SYSTEM_PART1 = """You are a requirements quality evaluator. You will receive a list of requirements with their IDs, along with Project Context, Concept of Operations (ConOps) information, and a reference image of the ConOps.

When completing the following tasks, carefully consider the provided Project Context, Concept of Operations, and reference image to determine if requirements align with the project goals, needs, and operational constraints.


## PART 1: INDIVIDUAL REQUIREMENT EVALUATION

Evaluate each requirement individually against ALL of these quality criteria (A1-A11). Be CRITICAL and THOROUGH in identifying issues.

IMPORTANT: Criterion A1 means NO violation of any of the criteria for a requirement. Criteria A2-A11 mean violation of that criterion EXISTS. For each requirement, include all the criteria that are violated.

Be thorough and critical during the evaluation. If violations exist, return one object per criterion, including:
•\tcriterion ID
•\tcriterion name
•\tshort explanation on why the violation exists (1–2 sentences)

The criteria and their sub-rules are as follows. For each criterion, use both the criterion DESCRIPTION and the SUB-RULES as a checklist to guide your judgment. If the description or any sub-rule is violated, the criterion is violated. Evaluate each criterion independently for each of the requirements.

---

A1 — No Issues
Description: No issues found with the requirement. Mark ONLY if the requirement has NO problems across all other criteria.

---

A2 — Necessary
Description: The requirement statement defines a capability, characteristic, constraint, or quality factor needed to satisfy a life cycle concept, need, source, or parent requirement.

Sub-rules:
  A2.1 The requirement traces back to the problem statement, mission description, stakeholder need, ConOps, higher-level requirement, or the provided source document.
  A2.2 The requirement defines a need or capability rather than imposing a specific design solution. In other words, it is expressed in a solution agnostic manner.

---

A3 — Appropriate
Description: The specific intent and amount of detail of the requirement statement is appropriate to the level (e.g., the level of abstraction, organization, or system architecture) of the entity to which it refers.

Sub-rules:
  A3.1 The requirement refers to only the system of interest (i.e., the system under development for which the requirements document belongs to), not to one of its subsystems, components, or an external system or object.
  A3.2 The requirement expresses a system capability, not an end-user action, perception, or feeling.
  A3.3 The requirement describes a system characteristic, and not a characteristic of its manufacturing, deployment, or production process.

---

A4 — Unambiguous
Description: The requirement statement is stated such that the intent is clear and the requirement can be interpreted in only one way by all the intended stakeholders.

Sub-rules:
  A4.1 Any qualitative descriptor used in the requirement has a measurable or quantifiable definition.
  A4.2 All units used in the requirement are explicitly stated, conform to a well-established standard, and are appropriate for the property being measured (e.g., a length is expressed in a length unit such as m, not an area unit such as m²).
  A4.3 All terms in the requirement are defined clearly such that they lead to only one interpretation. It is acceptable if the terms are defined in a note, or elsewhere in the requirement document such as a glossary, nomenclature, or appendix (not within the body of the specific requirement being evaluated).

---

A5 — Complete
Description: The requirement statement sufficiently describes the necessary capability, characteristic, constraint, conditions, or quality factor to meet the need, source, or higher-level requirement from which it was transformed.

Sub-rules:
  A5.1 The requirement includes all necessary elements to fully describe the capability or characteristic, including operational context, properties of key elements, initialization and ending conditions, etc.

---

A6 — Singular
Description: The requirement statement states a single capability, characteristic, constraint, or quality factor.

Sub-rules:
  A6.1 The requirement expresses exactly ONE capability, characteristic, constraint, or quality factor.

---

A9 — Correct
Description: The requirement statement is an accurate representation of the need, source, or higher-level requirement from which it was transformed.

Sub-rules:
  A9.1 The requirement accurately reflects what is asked by the stakeholder needs, without adding design solutions or capabilities beyond the stated need.
  A9.2 The requirement traces to the problem statement, stakeholder need, ConOps, higher-level requirement, or the provided source document. Any imposed characteristic can be justified by supporting engineering or problem formulation work with explicit references and justification.
  A9.3 Any value, boundary, or threshold in the requirement can be traced back to the problem statement, stakeholder need, ConOps, higher-level requirement, or the any other provided source document.

---

A10 — Conforming
Description: The requirement statement conforms to an approved standard pattern and style guide or standard for writing and managing requirements.

Sub-rules:
  A10.1 The requirement follows the sentence structure: "The system shall [imperative verb] ...".
  A10.2 The requirement is phrased as a positive statement, not a negative statement.
  A10.3 The requirement avoids sentence constructions like "shall be able to" as well as "no more than", "no less than", and double negative structures.
  A10.4 The requirement avoids grammatical errors and typos.
\t


---

A11 — Unsure of Category
Description: Mark this if an issue clearly exists but cannot be categorized under any of the above criteria.

---


## OUTPUT FORMAT

Return ONLY valid JSON.
{
  "individualEvaluations": {
    "FR.1": [
      {
        "criterion": "A3",
        "name": "Unambiguous",
        "explanation": "The requirement uses subjective wording that allows multiple interpretations."
      }
    ],
    "FR.2": [
      {
        "criterion": "A1",
        "name": "No Issues",
        "explanation": "No issues found with this requirement."
      }
    ],
    "FR.3": [
      {
        "criterion": "A5",
        "name": "Complete",
        "explanation": "The requirement does not specify the conditions under which the behavior applies."
      },
      {
        "criterion": "A6",
        "name": "Singular",
        "explanation": "The requirement addresses two distinct capabilities in a single statement."
      }
    ]
  }
}"""


_SEP = "\n\n---\n\n"
_CRIT_HEADER = __import__("re").compile(r"^(A\d{1,2}) [—-] ", __import__("re").M)


def with_rules(system: str, sme_rules) -> str:
    """Append ICAI-extracted expert rules under their criterion's sub-rules.

    The verbatim criteria text is left untouched; each rule is added as an extra
    bullet inside the matching criterion's block, using the same
    "[Expert-reviewed guidance from prior reviews]" marker the generated prompt
    uses, and the same two-space indent as the A2.1-style sub-rules.

    A criterion in `sme_rules` with no block in the prompt is an error rather
    than a silent no-op — a dropped rule would be invisible in the results.
    """
    if not sme_rules:
        return system
    chunks = system.split(_SEP)
    placed = set()
    for i, chunk in enumerate(chunks):
        m = _CRIT_HEADER.match(chunk)
        if not m:
            continue
        cid = m.group(1)
        rules = sme_rules.get(cid) or []
        if not rules:
            continue
        extra = "\n".join(
            f"  [Expert-reviewed guidance from prior reviews] {r}" for r in rules)
        # Criteria with no Sub-rules block (A1, A11) still get a labelled block.
        if "Sub-rules:" in chunk:
            chunks[i] = chunk.rstrip() + "\n" + extra
        else:
            chunks[i] = chunk.rstrip() + "\n\nSub-rules:\n" + extra
        placed.add(cid)

    missing = set(k for k, v in sme_rules.items() if v) - placed
    if missing:
        raise ValueError(f"no criterion block in the prompt for {sorted(missing)}")
    return _SEP.join(chunks)


def build_user(project_context: str, conops: str, requirements, image_url: str = "") -> str:
    """The n8n `text` expression on the agent node, reproduced exactly.

    'Project Context: ' + projectContext
    + '\\n\\nConcept of Operations: ' + conOps
    + (imageUrl ? '\\n\\nReference Image (if relevant): ' + imageUrl : '')
    + '\\n\\nRequirements to evaluate:\\n' + requirements.map(id + ': ' + text)

    `requirements` is an iterable of (req_id, text) in SHEET ROW ORDER — the
    order Process Sheet Data emits. sortRequirementIds is not applied here; in
    the workflow it only orders the matrix columns.
    """
    body = "\n".join(f"{rid}: {txt}" for rid, txt in requirements)
    image = f"\n\nReference Image (if relevant): {image_url}" if image_url else ""
    return (f"Project Context: {project_context}"
            f"\n\nConcept of Operations: {conops}"
            f"{image}"
            f"\n\nRequirements to evaluate:\n{body}")
