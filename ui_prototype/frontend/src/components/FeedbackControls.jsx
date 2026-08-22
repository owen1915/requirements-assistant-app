export default function FeedbackControls({
  totalViolations,
  reviewedCount,
  onSubmit,
  submitting,
}) {
  const allReviewed = reviewedCount === totalViolations
  const pct = totalViolations > 0 ? Math.round((reviewedCount / totalViolations) * 100) : 100

  return (
    <div className="feedback-controls">
      <div className="progress-bar-container">
        <div className="progress-info">
          <span>{reviewedCount} of {totalViolations} violations reviewed ({pct}%)</span>
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>

      <button
        className="btn-primary btn-submit"
        onClick={onSubmit}
        disabled={submitting || !allReviewed}
      >
        {submitting
          ? 'Submitting...'
          : allReviewed
            ? 'Submit All Feedback'
            : `Review all violations to submit (${totalViolations - reviewedCount} remaining)`}
      </button>
    </div>
  )
}
