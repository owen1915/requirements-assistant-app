import re
from typing import List, Dict


def parse_requirements(text: str) -> List[Dict]:
    """
    Extract numbered requirements from text.

    Handles a broad range of formats, e.g.:
      1. The system shall...
      1) The system shall...
      REQ-001: The system shall...
      REQ001: The system shall...
      FR.1: The system shall...
      FR-1: The system shall...
      SYS-REQ-001: The system shall...
      [1] The system shall...
      [1.1.1] The system shall...
      (1) The system shall...
      R1: The system shall...

    Also handles ID-on-its-own-line layouts, where the ID (optionally followed
    by a parenthesised category) sits alone and the requirement text follows on
    the next line — the format SysML model extracts use:

      [1.1.1]  (Mission Computer Secure Boot)
        The mission computer shall boot securely...

    Multi-line requirements (continuation lines with no ID prefix) are joined.
    """
    requirements = []
    lines = text.split('\n')

    # A line that is nothing but a parenthesised label, e.g. "(Secure Boot)".
    # These are category annotations, not requirement text.
    category_only = re.compile(r'^\((.*)\)$')

    # Each pattern: group 1 = ID, group 2 = text
    patterns = [
        # [1], [1.1.1], [C-1.26] or [MR - 1]; separators may be padded with
        # spaces. Trailing text is optional so the ID may sit on its own line
        # with the requirement following beneath it.
        r'^\[([A-Za-z0-9]+(?:\s*[-.]\s*[A-Za-z0-9]+)*)\]\s*(.*)$',
        r'^\((\d+)\)\s+(.+)$',                          # (1) text
        r'^(\d+)\.\s+(.+)$',                            # 1. text
        r'^(\d+)\)\s+(.+)$',                            # 1) text
        r'^([A-Z]+-[A-Z]+-\d+):\s*(.+)$',              # SYS-REQ-001: text
        r'^([A-Z]+-\d+):\s*(.+)$',                     # REQ-001, FR-1: text
        r'^([A-Z]+\d+):\s*(.+)$',                      # REQ001, R1: text
        r'^([A-Z]+\.\d+):\s*(.+)$',                    # FR.1: text
        r'^([A-Z]+\.\d+\.\d+):\s*(.+)$',              # FR.1.1: text
        r'^([A-Z]+-[A-Z0-9]+(?:\.[A-Z0-9]+)*):\s*(.+)$',  # MR-C1.1, MR-C1: text
    ]

    current_req = None

    def flush(req):
        """Emit a requirement, dropping any that never picked up text."""
        if req and req['text'].strip():
            req['text'] = req['text'].strip()
            requirements.append(req)

    for line in lines:
        line = line.strip()
        if not line:
            # A blank line ends a requirement only once it actually has text.
            # When the ID sits on its own line, the blank that may follow it
            # must not discard the requirement before its text arrives.
            if current_req and current_req['text'].strip():
                flush(current_req)
                current_req = None
            continue

        matched = False
        for pattern in patterns:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                flush(current_req)
                req_id, req_text = match.groups()
                req_text = req_text.strip()

                # "[1.1] (Hardened)" — the parenthetical is a category label,
                # so keep it aside and let the following line supply the text.
                category = None
                cat_match = category_only.match(req_text)
                if cat_match:
                    category = cat_match.group(1).strip()
                    req_text = ''

                current_req = {
                    'id': req_id.strip(),
                    'text': req_text,
                }
                if category:
                    current_req['category'] = category
                matched = True
                break

        if not matched and current_req:
            # Continuation line — append to current requirement
            current_req['text'] = (current_req['text'] + ' ' + line).strip()

    flush(current_req)

    return requirements


def validate_requirements(requirements: List[Dict]) -> Dict:
    """Validate parsed requirements."""
    if not requirements:
        return {
            'valid': False,
            'error': (
                'No requirements found. Supported formats include: '
                '"1. text", "REQ-001: text", "FR.1: text", "R1: text", etc.'
            )
        }

    ids = [r['id'] for r in requirements]
    if len(ids) != len(set(ids)):
        duplicates = [id for id in ids if ids.count(id) > 1]
        return {
            'valid': False,
            'error': f'Duplicate requirement IDs found: {", ".join(set(duplicates))}'
        }

    return {
        'valid': True,
        'count': len(requirements)
    }
