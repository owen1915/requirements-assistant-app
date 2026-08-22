import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

import chromadb

BASE_DIR = Path(__file__).parent
KNOWLEDGE_DIR = BASE_DIR / 'knowledge_base'
KNOWLEDGE_DIR.mkdir(exist_ok=True)

CHROMA_DIR = KNOWLEDGE_DIR / 'chroma_db'
CALIBRATION_PATH = KNOWLEDGE_DIR / 'rule_calibration.json'

COLLECTION_NAME = 'incose_feedback_knowledge'


class KnowledgeStore:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={'description': 'INCOSE requirement feedback knowledge base'}
        )

    def ingest_feedback(self, session_id: str, feedback: Dict, analysis: Dict, context: str = ''):
        """Extract knowledge units from feedback and store in ChromaDB.

        Works with both single-reviewer feedback and resolved multi-reviewer feedback.
        For resolved feedback, violation entries have 'resolved_action' and 'confidence'.
        For single-reviewer feedback, entries have 'user_action' (confidence defaults to 1.0).
        """
        requirements_analysis = {r['req_id']: r for r in analysis.get('requirements', [])}

        ids = []
        documents = []
        metadatas = []

        for req_fb in feedback.get('requirement_feedback', []):
            req_id = req_fb['req_id']
            requirement_text = req_fb.get('original_text', '')
            req_analysis = requirements_analysis.get(req_id, {})
            violations_analysis = {v['violation_id']: v for v in req_analysis.get('violations', [])}

            for viol_fb in req_fb.get('violation_feedback', []):
                violation_id = viol_fb['violation_id']
                rule_id = viol_fb.get('rule_id', 'unknown')
                viol_analysis = violations_analysis.get(violation_id, {})

                # Support both single-reviewer and resolved multi-reviewer schemas
                human_decision = viol_fb.get('resolved_action', viol_fb.get('user_action', 'reject'))
                human_text = viol_fb.get('resolved_text', viol_fb.get('user_text', ''))
                confidence = viol_fb.get('confidence', 1.0)
                resolution_method = viol_fb.get('resolution_method', 'single_reviewer')
                notes = viol_fb.get('notes', '')

                ku_id = f'ku_{session_id}_{violation_id}'

                # The document text is what gets embedded for similarity search
                context_snippet = context[:200] if context else ''
                rule_name = viol_analysis.get('rule_name', rule_id)
                doc_text = f'Requirement: {requirement_text} | Rule: {rule_id} {rule_name} | Context: {context_snippet}'

                metadata = {
                    'session_id': session_id,
                    'req_id': req_id,
                    'violation_id': violation_id,
                    'requirement_text': requirement_text,
                    'domain_context': context_snippet,
                    'rule_id': rule_id,
                    'rule_name': rule_name,
                    'violation_explanation': viol_analysis.get('explanation', ''),
                    'affected_text': viol_analysis.get('affected_text', ''),
                    'ai_suggestion': viol_fb.get('ai_suggestion', viol_analysis.get('suggested_replacement', '')),
                    'human_decision': human_decision,
                    'human_text': human_text,
                    'human_notes': notes,
                    'confidence': confidence,
                    'resolution_method': resolution_method,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                }

                ids.append(ku_id)
                documents.append(doc_text)
                metadatas.append(metadata)

        if ids:
            self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

        # Update rule calibration
        self.update_rule_calibration(feedback)

        return len(ids)

    def retrieve_similar(self, requirement_text: str, context: str = '', rule_id: Optional[str] = None, top_k: int = 5) -> List[Dict]:
        """Query ChromaDB for similar past requirements and their feedback."""
        if self.collection.count() == 0:
            return []

        context_snippet = context[:200] if context else ''
        query_text = f'Requirement: {requirement_text} | Context: {context_snippet}'
        if rule_id:
            query_text += f' | Rule: {rule_id}'

        where_filter = {'rule_id': rule_id} if rule_id else None

        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=min(top_k, self.collection.count()),
                where=where_filter if rule_id else None,
                include=['metadatas', 'distances']
            )
        except Exception:
            # Fall back without filter if it fails (e.g., no matching rule_id)
            results = self.collection.query(
                query_texts=[query_text],
                n_results=min(top_k, self.collection.count()),
                include=['metadatas', 'distances']
            )

        if not results or not results['metadatas'] or not results['metadatas'][0]:
            return []

        knowledge_units = []
        for metadata, distance in zip(results['metadatas'][0], results['distances'][0]):
            ku = dict(metadata)
            ku['similarity_score'] = round(1 - distance, 3) if distance < 1 else 0
            knowledge_units.append(ku)

        # Sort by confidence * similarity for relevance ranking
        knowledge_units.sort(
            key=lambda ku: ku.get('confidence', 1.0) * ku.get('similarity_score', 0),
            reverse=True
        )

        return knowledge_units

    def get_rule_calibration(self) -> Dict:
        """Load aggregate rule acceptance stats."""
        if CALIBRATION_PATH.exists():
            with open(CALIBRATION_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def update_rule_calibration(self, feedback: Dict):
        """Update aggregate rule calibration stats after new feedback."""
        calibration = self.get_rule_calibration()

        for req_fb in feedback.get('requirement_feedback', []):
            for viol_fb in req_fb.get('violation_feedback', []):
                rule_id = viol_fb.get('rule_id', 'unknown')
                action = viol_fb.get('resolved_action', viol_fb.get('user_action', 'reject'))
                notes = viol_fb.get('notes', viol_fb.get('human_notes', ''))

                if rule_id not in calibration:
                    calibration[rule_id] = {
                        'total_violations': 0,
                        'accept': 0,
                        'reject': 0,
                        'modify': 0,
                        'acceptance_rate': 0.0,
                        'common_reject_reasons': [],
                        'last_updated': ''
                    }

                cal = calibration[rule_id]
                cal['total_violations'] += 1
                if action in ('accept', 'reject', 'modify'):
                    cal[action] += 1

                total = cal['total_violations']
                cal['acceptance_rate'] = round((cal['accept'] + cal['modify']) / total, 3) if total > 0 else 0
                cal['last_updated'] = datetime.utcnow().isoformat() + 'Z'

                # Track reject reasons (keep last 10 unique)
                if action == 'reject' and notes and notes.strip():
                    reasons = cal['common_reject_reasons']
                    if notes.strip() not in reasons:
                        reasons.append(notes.strip())
                    cal['common_reject_reasons'] = reasons[-10:]

        with open(CALIBRATION_PATH, 'w', encoding='utf-8') as f:
            json.dump(calibration, f, indent=2, ensure_ascii=False)

    def get_knowledge_stats(self) -> Dict:
        """Return knowledge base statistics."""
        total = self.collection.count()
        calibration = self.get_rule_calibration()

        return {
            'total_knowledge_units': total,
            'rules_tracked': len(calibration),
            'rule_calibration': calibration
        }

    def reset(self):
        """Clear the knowledge base entirely."""
        self.client.delete_collection(COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={'description': 'INCOSE requirement feedback knowledge base'}
        )
        if CALIBRATION_PATH.exists():
            CALIBRATION_PATH.unlink()


def format_rag_context(knowledge_units: List[Dict], calibration: Dict) -> str:
    """Format retrieved knowledge units + calibration into a prompt section."""
    if not knowledge_units and not calibration:
        return ''

    sections = []

    if knowledge_units:
        sections.append('**Historical Feedback Context (learn from past reviews):**\n')
        sections.append('Similar requirements that were previously reviewed:\n')

        for i, ku in enumerate(knowledge_units[:5], 1):
            decision_label = ku.get('human_decision', 'unknown').upper()
            confidence = ku.get('confidence', 1.0)
            conf_label = 'unanimous' if confidence >= 1.0 else f'{confidence:.0%} agreement'

            entry = f'{i}. Requirement: "{ku.get("requirement_text", "")}"\n'
            entry += f'   - Rule {ku.get("rule_id", "")} flagged "{ku.get("affected_text", "")}"\n'
            entry += f'   - AI suggested: "{ku.get("ai_suggestion", "")}"\n'
            entry += f'   - Reviewer decision: {decision_label}'

            if ku.get('human_notes'):
                entry += f' \u2014 "{ku["human_notes"]}"'
            entry += f'\n   - Confidence: {conf_label}\n'

            sections.append(entry)

    if calibration:
        sections.append('\n**Rule Calibration (adjust your sensitivity):**\n')

        for rule_id, cal in sorted(calibration.items()):
            rate = cal.get('acceptance_rate', 0)
            total = cal.get('total_violations', 0)
            if total < 3:
                continue  # Not enough data to calibrate

            if rate >= 0.8:
                guidance = 'high value, flag when clearly applicable'
            elif rate >= 0.5:
                guidance = 'moderate value, flag when clearly applicable'
            else:
                guidance = 'low acceptance, be conservative \u2014 only flag when unambiguously violated'

            sections.append(f'- {rule_id}: {rate:.0%} acceptance rate ({total} reviews) \u2014 {guidance}\n')

            # Include top reject reasons if available
            reasons = cal.get('common_reject_reasons', [])
            if reasons and rate < 0.5:
                sections.append(f'  Common reject reasons: {"; ".join(reasons[:3])}\n')

    if sections:
        sections.append('\n**Instructions:**\n')
        sections.append('- Use this historical context to calibrate your analysis\n')
        sections.append('- If similar requirements had suggestions rejected, avoid making the same suggestion\n')
        sections.append('- Respect the acceptance rates \u2014 low-acceptance rules need more conservative flagging\n')
        sections.append('- Focus on rules with demonstrated value; apply low-acceptance rules only when the violation is unambiguous\n')

    return ''.join(sections)
