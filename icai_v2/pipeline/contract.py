"""The common rule schema both extraction methods emit.

Keeping a single shape means Method A (ICAI) and Method B (directed coding) are
directly comparable and can be merged — a rule that both methods produce for the
same criterion is your most trustworthy rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List


@dataclass
class ExtractedRule:
    criterion: str                       # "A9"
    criterion_name: str                  # "Correct"
    rule_text: str                       # the articulated, testable rule
    method: str                          # "directed_coding" | "icai"
    evidence: List[str] = field(default_factory=list)   # canonical record_ids
    support_count: int = 0
    direction: str = ""                  # suppress|tighten|remediate (Method B)
    sub_rule_id: str = ""                # "A9.3" — the codebook anchor (Method B)
    extra: Dict = field(default_factory=dict)   # method-specific (scores, etc.)


def save_rules(rules: List[ExtractedRule], path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps([asdict(r) for r in rules], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_rules(path: Path) -> List[ExtractedRule]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [ExtractedRule(**r) for r in raw]
