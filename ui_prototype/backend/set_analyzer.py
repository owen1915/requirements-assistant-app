import re
from difflib import SequenceMatcher
from collections import Counter, defaultdict

# Set quality characteristic definitions (INCOSE Guide V4, Section 3)
SET_CHARACTERISTICS = [
    {"id": "C10", "label": "Complete (Set)"},
    {"id": "C11", "label": "Consistent"},
    {"id": "C12", "label": "Feasible (Set)"},
    {"id": "C13", "label": "Comprehensible"},
    {"id": "C14", "label": "Able to be Validated"},
    {"id": "C15", "label": "Correct (Set)"},
]

# Patterns for extracting numeric constraints
_NUMERIC_PATTERN = re.compile(
    r'(\d+(?:\.\d+)?)\s*'
    r'(seconds?|ms|milliseconds?|minutes?|hours?|'
    r'kg|kilograms?|lbs?|pounds?|'
    r'meters?|m|km|miles?|feet|ft|'
    r'percent|%|Hz|kHz|MHz|GHz|'
    r'bits?|bytes?|KB|MB|GB|TB)',
    re.IGNORECASE,
)

# Patterns for vague/unverifiable language
_VAGUE_TERMS = re.compile(
    r'\b(appropriately|timely|adequate|sufficient|reasonable|'
    r'as needed|user-friendly|easy|flexible|robust|reliable|'
    r'efficient|performant|scalable|fast|slow|good|bad|'
    r'minimize|maximize|optimal|significant|normal)\b',
    re.IGNORECASE,
)

# Acronym pattern: 2+ uppercase letters, possibly with digits
_ACRONYM_PATTERN = re.compile(r'\b([A-Z][A-Z0-9]{1,})\b')

# Capitalized multi-word term (e.g., "Flight Control System")
_MULTIWORD_TERM = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')


class SetAnalyzer:
    def __init__(self, ontology_service):
        self._svc = ontology_service

    def extract_glossary(self, requirements):
        term_reqs = defaultdict(set)

        for req in requirements:
            rid = req["id"]
            text = req["text"]

            # Capitalized multi-word terms (strip leading "The")
            for match in _MULTIWORD_TERM.finditer(text):
                term = match.group(1)
                if term.startswith("The "):
                    term = term[4:]
                if len(term.split()) >= 2:
                    term_reqs[term].add(rid)

            # Acronyms (exclude common words like "The", "A")
            for match in _ACRONYM_PATTERN.finditer(text):
                acronym = match.group(1)
                if len(acronym) >= 2:
                    term_reqs[acronym].add(rid)

            # Terms after "the" -- short noun phrases, stopping before "shall"
            for match in re.finditer(r'\bthe\s+((?:[a-z]+\s+){1,3}[a-z]+)\b', text, re.IGNORECASE):
                candidate = match.group(1).strip()
                # Remove "shall" and anything after it
                candidate = re.split(r'\bshall\b', candidate, flags=re.IGNORECASE)[0].strip()
                words = candidate.split()
                if 2 <= len(words) <= 4 and len(candidate) <= 40:
                    term_reqs[candidate.lower()].add(rid)

        glossary = []
        for term, rids in term_reqs.items():
            glossary.append({
                "term": term,
                "frequency": len(rids),
                "requirement_ids": sorted(rids),
            })

        glossary.sort(key=lambda g: g["frequency"], reverse=True)
        return glossary

    def check_terminology_consistency(self, requirements, glossary):
        issues = []
        terms = [g["term"] for g in glossary]

        # Group terms that might refer to the same concept
        # Compare lowercase/normalized forms
        normalized = defaultdict(list)
        for term in terms:
            key = re.sub(r'\s+', ' ', term.lower().strip())
            # Also strip trailing 's' for basic plural handling
            key_singular = key.rstrip('s') if key.endswith('s') and not key.endswith('ss') else key
            normalized[key_singular].append(term)

        # Find groups with multiple surface forms
        for key, variants in normalized.items():
            if len(variants) > 1:
                affected = set()
                for g in glossary:
                    if g["term"] in variants:
                        affected.update(g["requirement_ids"])
                issues.append({
                    "issue_type": "inconsistent_naming",
                    "terms": variants,
                    "affected_requirements": sorted(affected),
                    "suggestion": f"Use a single term consistently. Variants found: {', '.join(variants)}",
                })

        # Detect acronym vs. full-name pairs (e.g., "FCS" and "Flight Control System")
        acronyms = [t for t in terms if t.isupper() and len(t) >= 2]
        full_names = [t for t in terms if not t.isupper() and ' ' in t]

        for acr in acronyms:
            for full in full_names:
                # Check if acronym matches initials of full name
                initials = ''.join(w[0].upper() for w in full.split() if w[0].isupper() or w[0].islower())
                if not initials:
                    initials = ''.join(w[0].upper() for w in full.split())
                if acr == initials:
                    acr_reqs = set()
                    full_reqs = set()
                    for g in glossary:
                        if g["term"] == acr:
                            acr_reqs.update(g["requirement_ids"])
                        elif g["term"] == full:
                            full_reqs.update(g["requirement_ids"])
                    issues.append({
                        "issue_type": "acronym_without_definition",
                        "terms": [acr, full],
                        "affected_requirements": sorted(acr_reqs | full_reqs),
                        "suggestion": f"Define '{acr}' as '{full}' in a glossary. Use one form consistently or define the abbreviation on first use.",
                    })

        # Detect case inconsistencies for the same base term
        case_groups = defaultdict(list)
        for term in terms:
            if not term.isupper():
                case_groups[term.lower()].append(term)

        for key, variants in case_groups.items():
            unique = list(set(variants))
            if len(unique) > 1:
                affected = set()
                for g in glossary:
                    if g["term"] in unique:
                        affected.update(g["requirement_ids"])
                issues.append({
                    "issue_type": "inconsistent_capitalization",
                    "terms": unique,
                    "affected_requirements": sorted(affected),
                    "suggestion": f"Standardize capitalization: {', '.join(unique)}",
                })

        return issues

    def detect_conflicts(self, requirements):
        conflicts = []

        # Build acronym-to-fullname map from requirement texts
        acronym_map = {}
        all_acronyms = set()
        all_fullnames = []
        for req in requirements:
            for m in _ACRONYM_PATTERN.finditer(req["text"]):
                all_acronyms.add(m.group(1))
            for m in _MULTIWORD_TERM.finditer(req["text"]):
                all_fullnames.append(m.group(1))
        for acr in all_acronyms:
            for full in all_fullnames:
                initials = ''.join(w[0].upper() for w in full.split())
                if acr == initials:
                    acronym_map[acr.lower()] = full.lower()

        # Extract subject and numeric constraints per requirement
        parsed = []
        for req in requirements:
            text = req["text"]
            # Extract subject: text before "shall"
            shall_match = re.search(r'^(.*?)\bshall\b', text, re.IGNORECASE)
            subject = shall_match.group(1).strip().lower() if shall_match else ""
            # Remove leading "the"
            subject = re.sub(r'^the\s+', '', subject)
            # Expand known acronyms in subject for comparison
            normalized_subject = subject
            for acr, full in acronym_map.items():
                normalized_subject = re.sub(r'\b' + re.escape(acr) + r'\b', full, normalized_subject)

            numerics = []
            for m in _NUMERIC_PATTERN.finditer(text):
                numerics.append({"value": float(m.group(1)), "unit": m.group(2).lower()})

            parsed.append({
                "id": req["id"],
                "text": text,
                "subject": subject,
                "normalized_subject": normalized_subject,
                "numerics": numerics,
            })

        # Check for contradictory numeric constraints on same subject
        for i in range(len(parsed)):
            for j in range(i + 1, len(parsed)):
                a, b = parsed[i], parsed[j]

                # Subject similarity check using normalized subjects
                if a["normalized_subject"] and b["normalized_subject"]:
                    subj_ratio = SequenceMatcher(
                        None, a["normalized_subject"], b["normalized_subject"],
                    ).ratio()
                    if subj_ratio > 0.6 and a["numerics"] and b["numerics"]:
                        # Compare numeric constraints with same units
                        for na in a["numerics"]:
                            for nb in b["numerics"]:
                                if na["unit"] == nb["unit"] and na["value"] != nb["value"]:
                                    conflicts.append({
                                        "conflict_type": "contradictory_constraint",
                                        "req_a_id": a["id"],
                                        "req_b_id": b["id"],
                                        "description": (
                                            f"Same subject '{a['subject']}' has conflicting values: "
                                            f"{na['value']} {na['unit']} vs {nb['value']} {nb['unit']}"
                                        ),
                                        "severity": "high",
                                    })

                # Near-duplicate detection
                ratio = SequenceMatcher(None, a["text"], b["text"]).ratio()
                if ratio > 0.7:
                    conflicts.append({
                        "conflict_type": "near_duplicate",
                        "req_a_id": a["id"],
                        "req_b_id": b["id"],
                        "description": f"Requirements are {ratio:.0%} similar and may be duplicates.",
                        "severity": "medium",
                    })

        return conflicts

    def assess_set_characteristics(self, requirements, glossary, conflicts, terminology_issues):
        total = len(requirements)
        if total == 0:
            return [
                {"characteristic_id": c["id"], "label": c["label"],
                 "score": 0.0, "assessment": "No requirements to assess.", "issues": []}
                for c in SET_CHARACTERISTICS
            ]

        results = []

        # C10 Complete: glossary terms with only 1 requirement = potential gap
        single_mention = [g for g in glossary if g["frequency"] == 1]
        total_terms = len(glossary) if glossary else 1
        c10_score = max(0.0, 1.0 - (len(single_mention) / total_terms))
        c10_issues = [
            f"Term '{g['term']}' appears in only 1 requirement ({g['requirement_ids'][0]})"
            for g in single_mention[:10]  # cap at 10 for readability
        ]
        results.append({
            "characteristic_id": "C10",
            "label": "Complete (Set)",
            "score": round(c10_score, 3),
            "assessment": f"{len(single_mention)}/{total_terms} terms appear in only one requirement.",
            "issues": c10_issues,
        })

        # C11 Consistent: conflicts + terminology inconsistencies
        conflict_count = len(conflicts)
        term_issue_count = len(terminology_issues)
        c11_score = max(0.0, 1.0 - min(1.0, conflict_count * 0.2 + term_issue_count * 0.1))
        c11_issues = (
            [f"Conflict: {c['description']}" for c in conflicts]
            + [f"Terminology: {t['suggestion']}" for t in terminology_issues]
        )
        results.append({
            "characteristic_id": "C11",
            "label": "Consistent",
            "score": round(c11_score, 3),
            "assessment": f"{conflict_count} conflicts and {term_issue_count} terminology issues found.",
            "issues": c11_issues,
        })

        # C12 Feasible: contradictory constraints making set infeasible
        contradictory = [c for c in conflicts if c["conflict_type"] == "contradictory_constraint"]
        c12_score = max(0.0, 1.0 - min(1.0, len(contradictory) * 0.3))
        c12_issues = [
            f"Contradictory: {c['description']}" for c in contradictory
        ]
        results.append({
            "characteristic_id": "C12",
            "label": "Feasible (Set)",
            "score": round(c12_score, 3),
            "assessment": f"{len(contradictory)} contradictory constraints detected.",
            "issues": c12_issues,
        })

        # C13 Comprehensible: formatting consistency, avg length, outliers
        lengths = [len(r["text"]) for r in requirements]
        avg_len = sum(lengths) / total
        variance = sum((l - avg_len) ** 2 for l in lengths) / total
        std_dev = variance ** 0.5
        cv = std_dev / avg_len if avg_len > 0 else 0  # coefficient of variation
        c13_score = max(0.0, 1.0 - min(1.0, cv))
        c13_issues = []
        for r in requirements:
            rlen = len(r["text"])
            if rlen > avg_len + 2 * std_dev:
                c13_issues.append(f"{r['id']} is unusually long ({rlen} chars, avg {avg_len:.0f})")
            elif rlen < avg_len - 2 * std_dev and rlen < 30:
                c13_issues.append(f"{r['id']} is unusually short ({rlen} chars, avg {avg_len:.0f})")
        # Check formatting: do all start with "The" and contain "shall"?
        nonstandard = [
            r["id"] for r in requirements
            if not re.match(r'^The\b', r["text"]) or 'shall' not in r["text"].lower()
        ]
        if nonstandard:
            c13_issues.append(
                f"Non-standard format (missing 'The...shall' pattern): {', '.join(nonstandard[:5])}"
            )
        results.append({
            "characteristic_id": "C13",
            "label": "Comprehensible",
            "score": round(c13_score, 3),
            "assessment": f"Avg length {avg_len:.0f} chars, CV={cv:.2f}. {len(nonstandard)} non-standard format.",
            "issues": c13_issues,
        })

        # C14 Validatable: count requirements lacking quantifiable criteria
        unverifiable = []
        for r in requirements:
            has_numeric = bool(_NUMERIC_PATTERN.search(r["text"]))
            has_vague = bool(_VAGUE_TERMS.search(r["text"]))
            if not has_numeric and has_vague:
                unverifiable.append(r["id"])
        c14_score = max(0.0, 1.0 - (len(unverifiable) / total))
        c14_issues = [
            f"{rid} lacks quantifiable criteria and uses vague language"
            for rid in unverifiable
        ]
        results.append({
            "characteristic_id": "C14",
            "label": "Able to be Validated",
            "score": round(c14_score, 3),
            "assessment": f"{len(unverifiable)}/{total} requirements lack verifiable criteria.",
            "issues": c14_issues,
        })

        # C15 Correct: requires external needs document
        results.append({
            "characteristic_id": "C15",
            "label": "Correct (Set)",
            "score": None,
            "assessment": "Cannot assess without external needs/stakeholder document for comparison.",
            "issues": ["Correctness assessment requires traceability to source needs document."],
        })

        return results

    def generate_set_report(self, requirements, individual_analysis=None):
        glossary = self.extract_glossary(requirements)
        terminology_issues = self.check_terminology_consistency(requirements, glossary)
        conflicts = self.detect_conflicts(requirements)
        characteristics = self.assess_set_characteristics(
            requirements, glossary, conflicts, terminology_issues,
        )

        report = {
            "glossary": glossary,
            "terminology_issues": terminology_issues,
            "conflicts": conflicts,
            "set_characteristics": characteristics,
            "summary": {
                "total_requirements": len(requirements),
                "glossary_terms": len(glossary),
                "terminology_issues": len(terminology_issues),
                "conflicts": len(conflicts),
                "characteristics_assessed": len([c for c in characteristics if c["score"] is not None]),
            },
        }

        if individual_analysis:
            report["individual_analysis"] = individual_analysis

        return report
