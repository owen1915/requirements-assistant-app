import { useMemo } from 'react'
import CriterionCard from './CriterionCard'

export default function RequirementCard({ requirement, feedbackState, onFeedbackChange }) {
  const evals = requirement.criteria_evaluations || []
  const violated = evals.filter((e) => !e.satisfied)
  const satisfied = evals.filter((e) => e.satisfied)

  // Count how many violated criteria have a decision
  const decidedCount = violated.filter((e) => {
    const key = `${requirement.req_id}-${e.criterion_id}`
    return feedbackState[key]?.user_action
  }).length

  // Full preview: apply ALL accepted/modified criteria fixes to the original text
  const fullPreview = useMemo(() => {
    const original = requirement.original_text
    const replacements = []

    for (const ev of violated) {
      if (!ev.affected_text) continue
      const key = `${requirement.req_id}-${ev.criterion_id}`
      const fb = feedbackState[key]
      if (!fb?.user_action || fb.user_action === 'reject') continue

      const pos = original.indexOf(ev.affected_text)
      if (pos === -1) continue

      const replacement =
        fb.user_action === 'modify'
          ? (fb.user_text || ev.suggested_replacement || ev.affected_text)
          : (ev.suggested_replacement || ev.affected_text)

      replacements.push({ start: pos, end: pos + ev.affected_text.length, text: replacement })
    }

    if (!replacements.length) return null

    // Sort descending by start so we splice from the end
    replacements.sort((a, b) => b.start - a.start)

    // Remove overlaps (keep later-found replacement)
    const filtered = []
    let lastStart = Infinity
    for (const r of replacements) {
      if (r.end <= lastStart) { filtered.push(r); lastStart = r.start }
    }

    let result = original
    for (const { start, end, text } of filtered) {
      result = result.slice(0, start) + text + result.slice(end)
    }
    return result
  }, [requirement, feedbackState, violated])

  return (
    <div className="req-card">
      {/* Requirement header */}
      <div className="req-card-header">
        <h3>{requirement.req_id}</h3>
        <div className="req-stats">
          <span className="req-stat-violated">{violated.length} violated</span>
          <span className="req-stat-sep">·</span>
          <span className="req-stat-satisfied">{satisfied.length} satisfied</span>
          {violated.length > 0 && (
            <>
              <span className="req-stat-sep">·</span>
              <span className="req-stat-meta">{decidedCount}/{violated.length} reviewed</span>
            </>
          )}
        </div>
      </div>

      {/* Original text */}
      <div className="req-text-block original">
        <span className="eyebrow">Original</span>
        {requirement.original_text}
      </div>

      {/* Full preview (shown when at least one decision made) */}
      {fullPreview && (
        <div className="req-text-block preview">
          <span className="eyebrow">Combined preview</span>
          {fullPreview}
        </div>
      )}

      {/* Criterion cards */}
      {evals.length === 0 ? (
        <p className="req-empty">
          {requirement.error ? `Analysis error: ${requirement.error}` : 'No evaluations available.'}
        </p>
      ) : (
        <div>
          {evals.map((ev) => {
            const key = `${requirement.req_id}-${ev.criterion_id}`
            const feedback = feedbackState[key] || {
              criterion_id: ev.criterion_id,
              user_action: '',
              // Satisfied criteria start blank: the box asks the reviewer to
              // describe a change, so prefilling it with AI text would get
              // submitted back as if the reviewer had written it.
              user_text: ev.satisfied ? '' : (ev.suggested_replacement || ''),
              notes: '',
            }
            return (
              <CriterionCard
                key={ev.criterion_id}
                evaluation={ev}
                originalText={requirement.original_text}
                feedback={feedback}
                onFeedbackChange={(fb) => onFeedbackChange(key, fb)}
              />
            )
          })}
        </div>
      )}
    </div>
  )
}
