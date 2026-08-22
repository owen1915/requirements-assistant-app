import { useState, useMemo } from 'react'

export default function CriterionCard({ evaluation, originalText, feedback, onFeedbackChange }) {
  const [showSatisfiedEdit, setShowSatisfiedEdit] = useState(false)
  const [showNotes, setShowNotes] = useState(false)

  const { criterion_id, criterion_name, satisfied, explanation, affected_text, suggested_replacement } = evaluation

  const handleActionChange = (action) => {
    const next = { ...feedback, user_action: action }
    if (action === 'accept') next.user_text = suggested_replacement || affected_text || ''
    if (action === 'reject') next.user_text = affected_text || ''
    if (action === 'modify') next.user_text = next.user_text || suggested_replacement || affected_text || ''
    onFeedbackChange(next)
  }

  // Live preview for accept (suggested), modify (user text), reject (original unchanged)
  const preview = useMemo(() => {
    if (!feedback.user_action || !originalText) return null
    if (feedback.user_action === 'reject') {
      return originalText // no change
    }
    if (!affected_text) return null
    const pos = originalText.indexOf(affected_text)
    if (pos === -1) return originalText
    const replacement =
      feedback.user_action === 'accept'
        ? (suggested_replacement || affected_text)
        : (feedback.user_text || affected_text)
    return (
      originalText.slice(0, pos) +
      '⟪' + replacement + '⟫' +
      originalText.slice(pos + affected_text.length)
    )
  }, [originalText, affected_text, suggested_replacement, feedback])

  return (
    <div className={`criterion-card ${satisfied ? 'satisfied' : 'violated'}`}>
      {/* Header */}
      <div className="criterion-header">
        <span className="criterion-badge">{criterion_id}</span>
        <span className="criterion-name">{criterion_name}</span>
        <span className="criterion-status">
          {satisfied ? '✓ Satisfied' : '✗ Violated'}
        </span>
      </div>

      {/* Explanation */}
      <p className="criterion-explanation">{explanation}</p>

      {/* VIOLATED: current + recommendations boxes */}
      {!satisfied && (
        <div className="text-compare">
          {/* CURRENT box */}
          {affected_text && (
            <div className="compare-box current">
              <span className="eyebrow">Current</span>
              <span className="compare-box-content">{affected_text}</span>
            </div>
          )}

          {/* SUGGESTED box — AI-rewritten replacement for the affected substring */}
          {suggested_replacement && (
            <div className="compare-box suggested">
              <span className="eyebrow">Suggested</span>
              <span className="compare-box-content">{suggested_replacement}</span>
            </div>
          )}
        </div>
      )}

      {/* VIOLATED: action buttons */}
      {!satisfied && (
        <div className="criterion-actions">
          {['accept', 'reject', 'modify'].map((action) => {
            const isSelected = feedback.user_action === action
            return (
              <button
                key={action}
                type="button"
                onClick={() => handleActionChange(action)}
                aria-pressed={isSelected}
                className={`action-btn ${action}${isSelected ? ' selected' : ''}`}
              >
                {action.charAt(0).toUpperCase() + action.slice(1)}
              </button>
            )
          })}
        </div>
      )}

      {/* Modify text input */}
      {!satisfied && feedback.user_action === 'modify' && (
        <div className="criterion-field">
          <label htmlFor={`replacement-${criterion_id}`}>Your replacement text:</label>
          <input
            id={`replacement-${criterion_id}`}
            type="text"
            className="text-input"
            value={feedback.user_text || ''}
            onChange={(e) => onFeedbackChange({ ...feedback, user_text: e.target.value, user_action: 'modify' })}
            placeholder={affected_text || 'Enter your replacement...'}
          />
        </div>
      )}

      {/* Live preview — only for Modify */}
      {preview && (
        <div className="edit-preview">
          <span className="eyebrow">Preview</span>
          <p>{preview}</p>
        </div>
      )}

      {/* Notes (violated only) */}
      {!satisfied && (
        <div>
          <button
            type="button"
            className="disclosure-btn"
            aria-expanded={showNotes}
            onClick={() => setShowNotes(!showNotes)}
          >
            {showNotes ? 'Hide notes' : 'Add notes'}
          </button>
          {showNotes && (
            <input
              type="text"
              className="text-input disclosure-field"
              value={feedback.notes || ''}
              onChange={(e) => onFeedbackChange({ ...feedback, notes: e.target.value })}
              placeholder="Optional notes..."
              aria-label="Notes"
            />
          )}
        </div>
      )}

      {/* SATISFIED: optional suggest change toggle */}
      {satisfied && (
        <div>
          <button
            type="button"
            className="disclosure-btn"
            aria-expanded={showSatisfiedEdit}
            onClick={() => setShowSatisfiedEdit(!showSatisfiedEdit)}
          >
            {showSatisfiedEdit ? 'Cancel' : 'Suggest a change anyway'}
          </button>
          {showSatisfiedEdit && (
            <input
              type="text"
              className="text-input disclosure-field"
              value={feedback.user_text || ''}
              onChange={(e) => onFeedbackChange({
                ...feedback,
                criterion_id,
                user_text: e.target.value,
                // 'suggest', not 'modify': this criterion was not flagged, so
                // it is not an accept/reject/modify decision on a violation.
                user_action: 'suggest',
              })}
              placeholder="Describe your suggested modification..."
              aria-label="Suggested modification"
            />
          )}
        </div>
      )}
    </div>
  )
}
