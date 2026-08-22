from datetime import datetime
from typing import Dict, List, Optional
from feedback_storage import load_analysis
from reviewer_manager import get_reviewer

CONFLICT_THRESHOLD = 0.6  # Actions need >60% weighted vote for clear majority

# In-memory stores (process memory only, nothing written to disk).
_SESSION_CONFIG: Dict[str, Dict] = {}
_REVIEWER_FEEDBACK: Dict[str, Dict[str, Dict]] = {}  # session_id -> {reviewer_id: feedback}
_RESOLVED: Dict[str, Dict] = {}


def _load_session_config(session_id: str) -> Dict:
    if session_id not in _SESSION_CONFIG:
        raise FileNotFoundError(f'Session config not found for {session_id}')
    return _SESSION_CONFIG[session_id]


def save_session_config(session_id: str, config: Dict):
    _SESSION_CONFIG[session_id] = config


def create_session_config(session_id: str, reviewer_ids: List[str], strategy: str = 'weighted_vote') -> Dict:
    """Create a session config for multi-reviewer mode."""
    config = {
        'session_id': session_id,
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'expected_reviewers': reviewer_ids,
        'submitted_reviewers': [],
        'status': 'reviewing',
        'resolution_strategy': strategy
    }
    save_session_config(session_id, config)
    return config


def load_reviewer_feedback(session_id: str, reviewer_id: str) -> Dict:
    """Load a specific reviewer's feedback."""
    session = _REVIEWER_FEEDBACK.get(session_id, {})
    if reviewer_id not in session:
        raise FileNotFoundError(f'Feedback not found for reviewer {reviewer_id} in session {session_id}')
    return session[reviewer_id]


def save_reviewer_feedback(session_id: str, reviewer_id: str, feedback: Dict) -> str:
    """Save a specific reviewer's feedback."""
    reviewer = get_reviewer(reviewer_id)
    if not reviewer:
        raise ValueError(f'Reviewer {reviewer_id} not found')

    feedback['session_id'] = session_id
    feedback['reviewer_id'] = reviewer_id
    feedback['reviewer_name'] = reviewer['name']
    feedback['reviewer_role'] = reviewer['role']
    feedback['timestamp'] = datetime.utcnow().isoformat() + 'Z'

    _REVIEWER_FEEDBACK.setdefault(session_id, {})[reviewer_id] = feedback

    # Update session config
    try:
        config = _load_session_config(session_id)
        if reviewer_id not in config['submitted_reviewers']:
            config['submitted_reviewers'].append(reviewer_id)
        if set(config['submitted_reviewers']) == set(config['expected_reviewers']):
            config['status'] = 'ready_for_resolution'
        save_session_config(session_id, config)
    except FileNotFoundError:
        pass  # No session config = single-reviewer mode, that's fine

    return reviewer_id


def _collect_all_feedback(session_id: str) -> List[Dict]:
    """Load all reviewer feedback files for a session."""
    config = _load_session_config(session_id)
    all_feedback = []
    for reviewer_id in config['submitted_reviewers']:
        try:
            fb = load_reviewer_feedback(session_id, reviewer_id)
            all_feedback.append(fb)
        except FileNotFoundError:
            continue
    return all_feedback


def _resolve_violation(votes: List[Dict]) -> Dict:
    """Resolve a single violation using weighted voting.

    Each vote: {reviewer_id, action, weight, text, notes}
    """
    weighted_scores = {'accept': 0, 'reject': 0, 'modify': 0}
    total_weight = 0

    for vote in votes:
        action = vote['action']
        weight = vote['weight']
        if action in weighted_scores:
            weighted_scores[action] += weight
            total_weight += weight

    if total_weight == 0:
        return {'resolved_action': 'reject', 'confidence': 0, 'conflict': True, 'resolution_method': 'no_votes'}

    # Find winning action
    winning_action = max(weighted_scores, key=weighted_scores.get)
    winning_weight = weighted_scores[winning_action]
    confidence = winning_weight / total_weight

    # Check for unanimity
    actions_used = {v['action'] for v in votes}
    if len(actions_used) == 1:
        resolution_method = 'unanimous'
        confidence = 1.0
        conflict = False
    elif confidence > CONFLICT_THRESHOLD:
        resolution_method = 'weighted_majority'
        conflict = False
    else:
        resolution_method = 'closest_weighted'
        conflict = True

    # Determine resolved text
    winning_voters = [v for v in votes if v['action'] == winning_action]
    texts = [v['text'] for v in winning_voters]

    if len(set(texts)) == 1:
        resolved_text = texts[0]
    else:
        # Prefer text from highest-weighted voter
        winning_voters.sort(key=lambda v: v['weight'], reverse=True)
        resolved_text = winning_voters[0]['text']

    return {
        'resolved_action': winning_action,
        'resolved_text': resolved_text,
        'resolution_method': resolution_method,
        'confidence': round(confidence, 3),
        'conflict': conflict,
        'reviewer_votes': [
            {'reviewer_id': v['reviewer_id'], 'action': v['action'], 'weight': v['weight']}
            for v in votes
        ]
    }


def compute_resolution(session_id: str) -> Dict:
    """Compute consensus resolution for all violations in a session."""
    all_feedback = _collect_all_feedback(session_id)
    if not all_feedback:
        raise ValueError(f'No reviewer feedback found for session {session_id}')

    # Build a map: violation_id -> list of votes
    # Use the first reviewer's structure as the template
    template = all_feedback[0]

    resolved = {
        'session_id': session_id,
        'resolved_at': datetime.utcnow().isoformat() + 'Z',
        'resolved_by': 'system_weighted_vote',
        'reviewer_count': len(all_feedback),
        'requirement_feedback': []
    }

    for req_idx, req_fb in enumerate(template['requirement_feedback']):
        req_id = req_fb['req_id']
        original_text = req_fb['original_text']

        resolved_req = {
            'req_id': req_id,
            'original_text': original_text,
            'violation_feedback': [],
            'final_text': original_text,
            'overall_notes': ''
        }

        for viol_idx, viol_fb in enumerate(req_fb['violation_feedback']):
            violation_id = viol_fb['violation_id']
            rule_id = viol_fb['rule_id']
            ai_suggestion = viol_fb.get('ai_suggestion', '')

            # Collect votes from all reviewers for this violation
            votes = []
            for fb in all_feedback:
                reviewer_id = fb['reviewer_id']
                reviewer = get_reviewer(reviewer_id)
                weight = reviewer['weight'] if reviewer else 1

                try:
                    rv = fb['requirement_feedback'][req_idx]['violation_feedback'][viol_idx]
                    votes.append({
                        'reviewer_id': reviewer_id,
                        'action': rv.get('user_action', 'reject'),
                        'weight': weight,
                        'text': rv.get('user_text', ''),
                        'notes': rv.get('notes', '')
                    })
                except (IndexError, KeyError):
                    continue

            resolution = _resolve_violation(votes)
            resolution['violation_id'] = violation_id
            resolution['rule_id'] = rule_id
            resolution['ai_suggestion'] = ai_suggestion

            resolved_req['violation_feedback'].append(resolution)

        # Build final text by applying resolved actions
        final_text = original_text
        analysis = load_analysis(session_id)
        for req_analysis in analysis.get('requirements', []):
            if req_analysis.get('req_id') == req_id:
                for viol_analysis in req_analysis.get('violations', []):
                    vid = viol_analysis['violation_id']
                    for rv in resolved_req['violation_feedback']:
                        if rv['violation_id'] == vid and rv['resolved_action'] != 'reject':
                            affected = viol_analysis.get('affected_text', '')
                            replacement = rv['resolved_text']
                            if affected and affected in final_text:
                                final_text = final_text.replace(affected, replacement, 1)
                break

        resolved_req['final_text'] = final_text
        resolved['requirement_feedback'].append(resolved_req)

    # Calculate summary statistics
    total_violations = 0
    conflicts = 0
    actions = {'accept': 0, 'reject': 0, 'modify': 0}
    for req in resolved['requirement_feedback']:
        for viol in req['violation_feedback']:
            total_violations += 1
            if viol['conflict']:
                conflicts += 1
            action = viol['resolved_action']
            if action in actions:
                actions[action] += 1

    resolved['summary_statistics'] = {
        'total_violations': total_violations,
        'conflicts': conflicts,
        'conflict_rate': round(conflicts / total_violations, 3) if total_violations > 0 else 0,
        'actions': actions
    }

    # Store resolved feedback in memory
    _RESOLVED[session_id] = resolved

    # Update session config
    try:
        config = _load_session_config(session_id)
        config['status'] = 'resolved'
        save_session_config(session_id, config)
    except FileNotFoundError:
        pass

    return resolved


def apply_override(session_id: str, violation_id: str, action: str, text: str, reviewer_id: str) -> Dict:
    """Lead reviewer manually overrides a conflict resolution."""
    if session_id not in _RESOLVED:
        raise FileNotFoundError(f'No resolved feedback found for session {session_id}')

    resolved = _RESOLVED[session_id]

    for req in resolved['requirement_feedback']:
        for viol in req['violation_feedback']:
            if viol['violation_id'] == violation_id:
                viol['resolved_action'] = action
                viol['resolved_text'] = text
                viol['resolution_method'] = 'lead_override'
                viol['overridden_by'] = reviewer_id
                viol['confidence'] = 1.0
                viol['conflict'] = False
                break

    resolved['resolved_at'] = datetime.utcnow().isoformat() + 'Z'
    _RESOLVED[session_id] = resolved

    return resolved


def get_consensus_summary(session_id: str) -> Dict:
    """Get a summary of consensus state — who agreed, who didn't, what's conflicted."""
    all_feedback = _collect_all_feedback(session_id)
    config = _load_session_config(session_id)

    summary = {
        'session_id': session_id,
        'status': config['status'],
        'expected_reviewers': config['expected_reviewers'],
        'submitted_reviewers': config['submitted_reviewers'],
        'pending_reviewers': [r for r in config['expected_reviewers'] if r not in config['submitted_reviewers']],
        'violations': []
    }

    if not all_feedback:
        return summary

    template = all_feedback[0]
    for req_idx, req_fb in enumerate(template['requirement_feedback']):
        for viol_idx, viol_fb in enumerate(req_fb['violation_feedback']):
            violation_summary = {
                'violation_id': viol_fb['violation_id'],
                'rule_id': viol_fb['rule_id'],
                'req_id': req_fb['req_id'],
                'ai_suggestion': viol_fb.get('ai_suggestion', ''),
                'votes': []
            }

            for fb in all_feedback:
                reviewer_id = fb['reviewer_id']
                reviewer = get_reviewer(reviewer_id)
                try:
                    rv = fb['requirement_feedback'][req_idx]['violation_feedback'][viol_idx]
                    violation_summary['votes'].append({
                        'reviewer_id': reviewer_id,
                        'reviewer_name': fb.get('reviewer_name', ''),
                        'reviewer_role': fb.get('reviewer_role', ''),
                        'action': rv.get('user_action', ''),
                        'text': rv.get('user_text', ''),
                        'notes': rv.get('notes', ''),
                        'weight': reviewer['weight'] if reviewer else 1
                    })
                except (IndexError, KeyError):
                    continue

            # Determine agreement status
            actions_used = {v['action'] for v in violation_summary['votes'] if v['action']}
            if len(actions_used) == 1:
                violation_summary['agreement'] = 'unanimous'
            elif len(actions_used) > 1:
                # Check weighted majority
                weighted = {}
                total_w = 0
                for v in violation_summary['votes']:
                    a = v['action']
                    if a:
                        weighted[a] = weighted.get(a, 0) + v['weight']
                        total_w += v['weight']
                if total_w > 0:
                    max_w = max(weighted.values())
                    if max_w / total_w > CONFLICT_THRESHOLD:
                        violation_summary['agreement'] = 'majority'
                    else:
                        violation_summary['agreement'] = 'conflict'
                else:
                    violation_summary['agreement'] = 'pending'
            else:
                violation_summary['agreement'] = 'pending'

            summary['violations'].append(violation_summary)

    return summary
