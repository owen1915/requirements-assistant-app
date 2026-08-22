"""Load the Project Specification as the analysis INPUT.

The prior runs fed bare requirement sentences with a thin context file, which
made the evaluator over-flag necessity/correctness (nothing to trace against).
The Project Specification workbook instead carries, per system:

  * Project Context  — what the system is for
  * ConOps           — its operational modes
  * FR/PR/ER/RR      — the requirements in canonical form, IDs aligned to the GT

We use the context + ConOps as the evaluator's context, and the FR/PR/ER/RR rows
as the requirement text. Ground truth (scoring) still comes from datasets.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import openpyxl

from shared.paths import SPEC_DIR

SPEC_PATH = SPEC_DIR / "Project Specifications.xlsx"

# dataset name -> sheet in the spec workbook
SHEET_OF = {
    "PM": "GPS System Requirements",
    "Bookshelf": "Bookshelf Requirements",
}

_REQ_ID_RE = re.compile(r"^(FR|PR|ER|RR)\.(\d+)$", re.IGNORECASE)

# Common mojibake in the workbook (cp1252 artefacts) -> proper characters.
_FIX = {
    "�±2.5": "±2.5", "�": "",  # stray replacement chars
    "â€™": "'", "â€œ": '"', "â€\x9d": '"', "â€“": "-",
}


def _clean(text: str) -> str:
    text = text or ""
    text = (text.replace("±", "±").replace("°", "°").replace("²", "²"))
    for bad, good in _FIX.items():
        text = text.replace(bad, good)
    return " ".join(text.split()).strip()


@dataclass
class SpecInput:
    dataset: str
    context: str                       # Project Context + ConOps, for the evaluator
    requirements: Dict[str, str]       # req_id -> canonical requirement text
    # The n8n workflow labels Project Context and ConOps separately in the user
    # message and appends the Image row's URL when one is present, so they are
    # kept apart here rather than pre-joined. `requirements` preserves sheet row
    # order, which is the order n8n's Process Sheet Data node emits.
    project_context: str = ""
    conops: str = ""
    image_url: str = ""


def load_spec(dataset: str) -> SpecInput:
    wb = openpyxl.load_workbook(SPEC_PATH, data_only=True)
    ws = wb[SHEET_OF[dataset]]

    context_parts = []
    project_context = conops = image_url = ""
    requirements: Dict[str, str] = {}
    for row in ws.iter_rows(values_only=True):
        if not row or row[0] is None:
            continue
        section = str(row[0]).strip()
        content = _clean(str(row[1])) if len(row) > 1 and row[1] else ""
        if not content:
            continue
        m = _REQ_ID_RE.match(section)
        low = section.lower()
        if m:
            req_id = f"{m.group(1).upper()}.{int(m.group(2))}"
            requirements[req_id] = content
        elif "project context" in low:
            project_context = content
            context_parts.append(f"{section}: {content}")
        elif "conops" in low:
            conops = content
            context_parts.append(f"{section}: {content}")
        elif "image" in low:
            image_url = content

    context = "\n\n".join(context_parts)
    return SpecInput(dataset=dataset, context=context, requirements=requirements,
                     project_context=project_context, conops=conops,
                     image_url=image_url)


def _main() -> None:
    for name in SHEET_OF:
        spec = load_spec(name)
        print(f"\n=== {name}: {len(spec.requirements)} requirements ===")
        print(f"context ({len(spec.context)} chars): {spec.context[:160]}...")
        for rid, txt in list(spec.requirements.items())[:4]:
            print(f"  {rid}: {txt[:80]}")


if __name__ == "__main__":
    _main()
