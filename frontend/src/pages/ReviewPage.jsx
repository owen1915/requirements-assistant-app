import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import axios from 'axios'
import RequirementCard from '../components/RequirementCard'
import FeedbackControls from '../components/FeedbackControls'

export default function ReviewPage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const reviewerId = searchParams.get('reviewer')

  const [analysis, setAnalysis] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [reviewerInfo, setReviewerInfo] = useState(null)

  // feedbackState: { [reqId-criterionId]: { criterion_id, user_action, user_text, notes } }
  const [feedbackState, setFeedbackState] = useState({})

  useEffect(() => {
    const fetchAnalysis = async () => {
      try {
        const res = await axios.get(`/api/analysis/${sessionId}`)
        setAnalysis(res.data)

        // Initialise feedback state for all violated criteria
        const initial = {}
        for (const req of res.data.requirements || []) {
          for (const ev of req.criteria_evaluations || []) {
            if (!ev.satisfied) {
              const key = `${req.req_id}-${ev.criterion_id}`
              initial[key] = {
                criterion_id: ev.criterion_id,
                user_action: '',
                user_text: ev.suggested_replacement || '',
                notes: '',
              }
            }
          }
        }
        setFeedbackState(initial)

        if (reviewerId) {
          try {
            const reviewersRes = await axios.get('/api/reviewers')
            const me = (reviewersRes.data.reviewers || []).find(r => r.reviewer_id === reviewerId)
            setReviewerInfo(me || { reviewer_id: reviewerId, name: 'Unknown', role: 'junior' })
          } catch {
            console.error('Could not load reviewer info')
          }
        }
      } catch (err) {
        setError(err.response?.data?.detail || 'Failed to load analysis')
      } finally {
        setLoading(false)
      }
    }
    fetchAnalysis()
  }, [sessionId, reviewerId])

  const handleFeedbackChange = useCallback((key, fb) => {
    setFeedbackState((prev) => ({ ...prev, [key]: fb }))
  }, [])

  // Count totals
  const { totalViolated, reviewedCount } = (() => {
    let tot = 0, rev = 0
    for (const req of analysis?.requirements || []) {
      for (const ev of req.criteria_evaluations || []) {
        if (!ev.satisfied) {
          tot++
          const key = `${req.req_id}-${ev.criterion_id}`
          if (feedbackState[key]?.user_action) rev++
        }
      }
    }
    return { totalViolated: tot, reviewedCount: rev }
  })()

  // Build final text for a requirement by applying all accepted/modified criteria fixes
  const buildFinalText = (req) => {
    const evals = req.criteria_evaluations || []
    const violated = evals.filter((e) => !e.satisfied && e.affected_text)
    if (!violated.length) return req.original_text

    const original = req.original_text
    const replacements = []

    for (const ev of violated) {
      const key = `${req.req_id}-${ev.criterion_id}`
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

    if (!replacements.length) return original

    replacements.sort((a, b) => b.start - a.start)
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
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    setError('')

    try {
      const requirement_feedback = (analysis?.requirements || []).map((req) => {
        const evals = req.criteria_evaluations || []

        // Map criteria feedback into violation_feedback-compatible format for downstream
        const violation_feedback = evals
          .filter((ev) => !ev.satisfied)
          .map((ev) => {
            const key = `${req.req_id}-${ev.criterion_id}`
            const fb = feedbackState[key] || {}
            return {
              violation_id: key,
              rule_id: ev.criterion_id,
              criterion_name: ev.criterion_name,
              user_action: fb.user_action || 'accept',
              ai_suggestion: ev.suggested_replacement || '',
              user_text: fb.user_text || ev.suggested_replacement || '',
              notes: fb.notes || '',
            }
          })

        // Suggestions the reviewer volunteered on criteria the AI marked
        // satisfied ("Suggest a change anyway"). Kept in their own array rather
        // than folded into violation_feedback: that array is index-aligned
        // across reviewers by the consensus engine, and it feeds the violation
        // counts in summary_statistics. These are also free-text suggestions
        // against a criterion with no affected_text, so they are deliberately
        // not applied to final_text.
        const suggestion_feedback = evals
          .filter((ev) => ev.satisfied)
          .map((ev) => ({ ev, fb: feedbackState[`${req.req_id}-${ev.criterion_id}`] }))
          .filter(({ fb }) => (fb?.user_text || '').trim() || (fb?.notes || '').trim())
          .map(({ ev, fb }) => ({
            suggestion_id: `${req.req_id}-${ev.criterion_id}`,
            rule_id: ev.criterion_id,
            criterion_name: ev.criterion_name,
            user_action: 'suggest',
            user_text: (fb.user_text || '').trim(),
            notes: (fb.notes || '').trim(),
          }))

        return {
          req_id: req.req_id,
          original_text: req.original_text,
          violation_feedback,
          suggestion_feedback,
          final_text: buildFinalText(req),
          overall_notes: '',
        }
      })

      // Session state lives in the server's memory, so a restart between
      // loading this page and submitting would otherwise throw the review
      // away. Send the analysis we already hold so the server can restore it.
      const payload = { requirement_feedback, analysis }

      if (reviewerId) {
        await axios.post(`/api/feedback/${sessionId}/${reviewerId}`, payload)
        setSubmitted(true)
        setSubmitting(false)
      } else {
        await axios.post(`/api/feedback/${sessionId}`, payload)
        navigate(`/download/${sessionId}`)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to submit feedback')
      setSubmitting(false)
    }
  }

  if (loading) return <div className="loading">Loading analysis results...</div>
  if (error && !analysis) return <div className="error-page"><p className="error-msg">{error}</p></div>

  if (submitted && reviewerId) {
    return (
      <div className="upload-page">
        <div className="upload-card centered">
          <h2>Feedback Submitted</h2>
          <p className="subtitle">
            Thank you{reviewerInfo ? `, ${reviewerInfo.name}` : ''}! Your review has been recorded.
          </p>
          <div className="progress-msg">
            Waiting for other reviewers to complete their reviews.
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="review-page">
      <div className="review-header">
        <h2>Review Requirements</h2>
        <p className="subtitle">
          Session: {sessionId} &nbsp;|&nbsp;
          {analysis.requirements.length} requirements &nbsp;|&nbsp;
          {totalViolated} criteria violated
          {reviewerInfo && (
            <span> &nbsp;|&nbsp; Reviewing as: <strong>{reviewerInfo.name}</strong> ({reviewerInfo.role})</span>
          )}
        </p>
      </div>

      {error && <div className="error-msg">{error}</div>}

      <FeedbackControls
        totalViolations={totalViolated}
        reviewedCount={reviewedCount}
        onSubmit={handleSubmit}
        submitting={submitting}
      />

      <div className="requirements-list">
        {(analysis.requirements || []).map((req) => (
          <RequirementCard
            key={req.req_id}
            requirement={req}
            feedbackState={feedbackState}
            onFeedbackChange={handleFeedbackChange}
          />
        ))}
      </div>

      <FeedbackControls
        totalViolations={totalViolated}
        reviewedCount={reviewedCount}
        onSubmit={handleSubmit}
        submitting={submitting}
      />
    </div>
  )
}
