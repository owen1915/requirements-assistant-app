"""In-memory session storage.

Nothing is persisted to disk. All analysis results, user feedback, and the
generated Word document live in process memory only for the lifetime of the
running server. On restart everything is cleared. This keeps the deployed
prototype stateless — no uploaded requirements, context, or results are stored
on the server side.
"""

from typing import Dict, Optional
from datetime import datetime

# session_id -> data (process memory only)
_ANALYSIS: Dict[str, Dict] = {}
_FEEDBACK: Dict[str, Dict] = {}
_SET_ANALYSIS: Dict[str, Dict] = {}
_DOCX: Dict[str, bytes] = {}


def save_analysis(session_id: str, analysis: Dict) -> str:
    """Store AI analysis results in memory."""
    _ANALYSIS[session_id] = analysis
    return session_id


def load_analysis(session_id: str) -> Dict:
    """Load analysis results from memory."""
    if session_id not in _ANALYSIS:
        raise FileNotFoundError(f'Analysis not found for session {session_id}')
    return _ANALYSIS[session_id]


def save_feedback(session_id: str, feedback: Dict, reviewer_id: str = None) -> str:
    """Store user feedback in memory (single/legacy reviewer mode)."""
    feedback['session_id'] = session_id
    feedback['timestamp'] = datetime.utcnow().isoformat() + 'Z'

    # Calculate statistics
    feedback['summary_statistics'] = calculate_statistics(feedback)

    _FEEDBACK[session_id] = feedback
    return session_id


def load_feedback(session_id: str) -> Dict:
    """Load feedback from memory."""
    if session_id not in _FEEDBACK:
        raise FileNotFoundError(f'Feedback not found for session {session_id}')
    return _FEEDBACK[session_id]


def save_docx(session_id: str, data: bytes) -> None:
    """Store generated Word document bytes in memory."""
    _DOCX[session_id] = data


def load_docx(session_id: str) -> Optional[bytes]:
    """Load generated Word document bytes from memory (None if not generated)."""
    return _DOCX.get(session_id)


def calculate_statistics(feedback: Dict) -> Dict:
    """Calculate acceptance rates and other statistics."""
    stats = {
        'total_requirements': len(feedback.get('requirement_feedback', [])),
        'total_violations': 0,
        # Reviewer suggestions on criteria the AI marked satisfied. Counted
        # separately so they never distort the violation acceptance rates.
        'total_suggestions': 0,
        'actions': {
            'accept': 0,
            'reject': 0,
            'modify': 0
        },
        'acceptance_rate_by_rule': {}
    }

    rule_stats = {}

    for req_feedback in feedback.get('requirement_feedback', []):
        stats['total_suggestions'] += len(req_feedback.get('suggestion_feedback', []))

        for viol_feedback in req_feedback.get('violation_feedback', []):
            stats['total_violations'] += 1

            action = viol_feedback.get('user_action', 'accept')
            if action in stats['actions']:
                stats['actions'][action] += 1

            rule_id = viol_feedback.get('rule_id', 'unknown')
            if rule_id not in rule_stats:
                rule_stats[rule_id] = {'accept': 0, 'reject': 0, 'modify': 0, 'total': 0}

            if action in rule_stats[rule_id]:
                rule_stats[rule_id][action] += 1
            rule_stats[rule_id]['total'] += 1

    for rule_id, counts in rule_stats.items():
        total = counts['total']
        stats['acceptance_rate_by_rule'][rule_id] = {
            'accept': counts['accept'],
            'reject': counts['reject'],
            'modify': counts['modify'],
            'rate': (counts['accept'] + counts['modify']) / total if total > 0 else 0
        }

    return stats


def save_set_analysis(session_id: str, set_analysis: Dict) -> str:
    """Store set-level analysis results in memory."""
    _SET_ANALYSIS[session_id] = set_analysis
    return session_id


def load_set_analysis(session_id: str) -> Optional[Dict]:
    """Load set-level analysis results from memory (None if not present)."""
    return _SET_ANALYSIS.get(session_id)
