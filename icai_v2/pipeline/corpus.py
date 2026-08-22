"""Shared corpus layer for rule extraction (Methods A and B).

Offline — not imported by the live app. Loads exported SME feedback JSON files,
cleans them, and emits a single canonical list of "disagreement records" that
both extraction methods consume. Doing the cleaning in exactly one place is the
whole point: neither method should re-derive it, so they always agree on what
the data says.

Three data-quality fixes are applied here, once:

  1. EFFECTIVE ACTION is re-derived from the text, not trusted from the stored
     `user_action`. Several records labelled 'modify' actually have
     user_text == ai_suggestion (an accept), and some rejects are mislabelled.
     We decide accept/reject/modify by comparing the text itself.

  2. USER_TEXT is the reviewer's decision — never `final_text`. The
     requirement-level `final_text` is produced by a known splice bug that can
     duplicate or drop clauses; the per-violation `user_text` is clean.

  3. Each session is tagged with an ENGAGEMENT flag. Sessions that accepted
     almost everything (rubber-stamps) carry no corrective signal and can drown
     the real rules, so they are flagged here and can be excluded downstream.
     We tag rather than delete — the caller decides.

Run it directly to see the corpus report and write the canonical records:

    python -m icai_v2.pipeline.corpus
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

from shared.paths import FEEDBACK_DIR as DATA_DIR
from shared.paths import output_dir, RULE_SETS_DIR

OUTPUT_DIR = output_dir("icai_v2")

# A session needs at least this many corrective (reject/modify) records, after
# relabelling, to count as "engaged". Rubber-stamp sessions fall below it.
MIN_CORRECTIVE_FOR_ENGAGED = 2

CORRECTIVE_ACTIONS = ("reject", "modify")


@dataclass
class CanonicalRecord:
    """One SME decision on one flagged criterion, cleaned and normalised."""

    record_id: str          # e.g. "aee204f7:req4:A9" — stable evidence id
    session_id: str
    req_id: str
    criterion_id: str       # A2, A4, A9, ...
    criterion_name: str     # Necessary, Correct, ...
    requirement_text: str   # the original requirement (the "prompt")
    ai_suggestion: str      # what the model proposed (rejected pole for reject)
    user_text: str          # what the SME kept/wrote (preferred pole)
    stated_action: str      # the label as exported (may be unreliable)
    effective_action: str   # re-derived from the text: accept | reject | modify
    notes: str              # reviewer rationale (often empty)
    session_engaged: bool   # False for rubber-stamp sessions


# --------------------------------------------------------------------------- #
# Text handling
# --------------------------------------------------------------------------- #

_QUOTE_MAP = {"“": '"', "”": '"', "‘": "'", "’": "'"}


def _norm(text: str) -> str:
    """Normalise for comparison only: unify quotes, collapse whitespace, lower.

    Used to decide whether two strings are 'the same' despite curly-vs-straight
    quotes or spacing differences. Never used for stored/displayed text.
    """
    text = text or ""
    for curly, straight in _QUOTE_MAP.items():
        text = text.replace(curly, straight)
    return " ".join(text.split()).strip().lower()


def effective_action(ai_suggestion: str, user_text: str, requirement_text: str) -> str:
    """Re-derive the reviewer's real decision from the text.

    - accept: the SME kept the AI's exact suggestion.
    - reject: the SME kept wording already present in the original requirement
              (i.e. declined the change).
    - modify: the SME wrote something that is neither the AI's text nor a
              verbatim slice of the original — genuine reviewer authorship.

    The reject test assumes a declined suggestion leaves behind original
    wording, which holds throughout the pilot corpus. A paraphrased reject would
    fall through to 'modify'; that is the safe direction to be wrong in.
    """
    ai, user, req = _norm(ai_suggestion), _norm(user_text), _norm(requirement_text)
    if not user:
        return "reject"          # nothing kept / defaulted — treat conservatively
    if user == ai:
        return "accept"
    if user in req:
        return "reject"
    return "modify"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def _load_session_records(path: Path) -> List[CanonicalRecord]:
    """Read one feedback file into CanonicalRecords (engagement filled later)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    session_id = data.get("session_id", path.stem.replace("feedback_", ""))

    records: List[CanonicalRecord] = []
    for req in data.get("requirement_feedback", []):
        req_id = str(req.get("req_id", "?"))
        requirement_text = req.get("original_text", "")

        for viol in req.get("violation_feedback", []):
            ai_suggestion = viol.get("ai_suggestion", "")
            user_text = viol.get("user_text", "")
            rule_id = viol.get("rule_id", "unknown")

            records.append(
                CanonicalRecord(
                    record_id=f"{session_id}:req{req_id}:{rule_id}",
                    session_id=session_id,
                    req_id=req_id,
                    criterion_id=rule_id,
                    criterion_name=viol.get("criterion_name", ""),
                    requirement_text=requirement_text,
                    ai_suggestion=ai_suggestion,
                    user_text=user_text,
                    stated_action=viol.get("user_action", ""),
                    effective_action=effective_action(
                        ai_suggestion, user_text, requirement_text
                    ),
                    notes=(viol.get("notes") or "").strip(),
                    session_engaged=False,  # set in _apply_engagement
                )
            )
    return records


def _apply_engagement(records: List[CanonicalRecord]) -> None:
    """Tag each record with whether its session is engaged (mutates in place)."""
    per_session: Dict[str, int] = {}
    for r in records:
        if r.effective_action in CORRECTIVE_ACTIONS:
            per_session[r.session_id] = per_session.get(r.session_id, 0) + 1

    for r in records:
        corrective = per_session.get(r.session_id, 0)
        r.session_engaged = corrective >= MIN_CORRECTIVE_FOR_ENGAGED


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def build_corpus(data_dir: Path = DATA_DIR) -> Tuple[List[CanonicalRecord], Dict]:
    """Load every feedback file in `data_dir`, clean it, and return
    (all_records, report). Both extraction methods start from this.
    """
    files = sorted(data_dir.glob("feedback_*.json"))
    if not files:
        raise FileNotFoundError(f"No feedback_*.json files in {data_dir}")

    all_records: List[CanonicalRecord] = []
    for path in files:
        all_records.extend(_load_session_records(path))

    _apply_engagement(all_records)
    report = _build_report(all_records, files)
    return all_records, report


def disagreements(records: List[CanonicalRecord], engaged_only: bool = True
                  ) -> List[CanonicalRecord]:
    """The records the methods actually consume: reject/modify decisions.

    By default restricted to engaged sessions, since rubber-stamp sessions carry
    no corrective signal. Pass engaged_only=False to include everything.
    """
    return [
        r for r in records
        if r.effective_action in CORRECTIVE_ACTIONS
        and (r.session_engaged or not engaged_only)
    ]


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def _build_report(records: List[CanonicalRecord], files: List[Path]) -> Dict:
    sessions: Dict[str, Dict] = {}
    relabelled = 0
    for r in records:
        s = sessions.setdefault(
            r.session_id,
            {"accept": 0, "reject": 0, "modify": 0, "engaged": r.session_engaged},
        )
        s[r.effective_action] += 1
        if r.stated_action != r.effective_action:
            relabelled += 1

    corrective = disagreements(records, engaged_only=False)
    corrective_engaged = disagreements(records, engaged_only=True)

    by_criterion: Dict[str, int] = {}
    for r in corrective_engaged:
        by_criterion[r.criterion_id] = by_criterion.get(r.criterion_id, 0) + 1

    return {
        "files": [f.name for f in files],
        "total_records": len(records),
        "relabelled_by_text": relabelled,
        "corrective_records_total": len(corrective),
        "corrective_records_engaged_only": len(corrective_engaged),
        "sessions": sessions,
        "engaged_corrective_by_criterion": dict(
            sorted(by_criterion.items(), key=lambda kv: -kv[1])
        ),
    }


def _print_report(report: Dict) -> None:
    print("=" * 70)
    print("RULE-EXTRACTION CORPUS REPORT")
    print("=" * 70)
    print(f"Files loaded: {', '.join(report['files'])}")
    print(f"Total violation records: {report['total_records']}")
    print(f"Records relabelled by text (stated != effective): "
          f"{report['relabelled_by_text']}")
    print()
    print(f"{'Session':<12}{'accept':>8}{'reject':>8}{'modify':>8}{'engaged':>10}")
    print("-" * 46)
    for sid, s in report["sessions"].items():
        print(f"{sid:<12}{s['accept']:>8}{s['reject']:>8}{s['modify']:>8}"
              f"{('yes' if s['engaged'] else 'NO'):>10}")
    print("-" * 46)
    print()
    print(f"Corrective records (all sessions):     "
          f"{report['corrective_records_total']}")
    print(f"Corrective records (engaged only):     "
          f"{report['corrective_records_engaged_only']}"
          "   <- what the methods run on")
    print()
    print("Engaged corrective signal by criterion:")
    for cid, n in report["engaged_corrective_by_criterion"].items():
        print(f"    {cid:<5} {n}")
    print("=" * 70)


def main() -> None:
    records, report = build_corpus()
    _print_report(report)

    OUTPUT_DIR.mkdir(exist_ok=True)
    corr = disagreements(records, engaged_only=True)

    (OUTPUT_DIR / "canonical_records.json").write_text(
        json.dumps([asdict(r) for r in corr], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "corpus_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(corr)} disagreement records -> "
          f"outputs/canonical_records.json")
    print("Wrote corpus_report.json")


if __name__ == "__main__":
    main()
