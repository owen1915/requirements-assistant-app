import uuid
from typing import Dict, List, Optional

# In-memory reviewer registry (process memory only, nothing written to disk).
_REVIEWERS: List[Dict] = []

ROLE_WEIGHTS = {
    'lead': 3,
    'senior': 2,
    'junior': 1
}


def register_reviewer(name: str, role: str) -> Dict:
    """Register a new reviewer with a role (lead, senior, junior)."""
    if role not in ROLE_WEIGHTS:
        raise ValueError(f"Invalid role '{role}'. Must be one of: {list(ROLE_WEIGHTS.keys())}")

    reviewer = {
        'reviewer_id': 'r' + str(uuid.uuid4())[:7],
        'name': name,
        'role': role,
        'weight': ROLE_WEIGHTS[role]
    }

    _REVIEWERS.append(reviewer)
    return reviewer


def get_reviewer(reviewer_id: str) -> Optional[Dict]:
    """Get a reviewer by ID."""
    for reviewer in _REVIEWERS:
        if reviewer['reviewer_id'] == reviewer_id:
            return reviewer
    return None


def list_reviewers() -> List[Dict]:
    """List all registered reviewers."""
    return list(_REVIEWERS)


def delete_reviewer(reviewer_id: str) -> bool:
    """Remove a reviewer from the registry."""
    original_count = len(_REVIEWERS)
    _REVIEWERS[:] = [r for r in _REVIEWERS if r['reviewer_id'] != reviewer_id]
    return len(_REVIEWERS) < original_count
