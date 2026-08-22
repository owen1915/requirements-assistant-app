import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'

export default function ConsensusPage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const [consensus, setConsensus] = useState(null)
  const [resolved, setResolved] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [loading, setLoading] = useState(true)
  const [resolving, setResolving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    loadData()
  }, [sessionId])

  async function loadData() {
    setLoading(true)
    try {
      const [consensusRes, analysisRes] = await Promise.all([
        axios.get(`/api/consensus/${sessionId}`),
        axios.get(`/api/analysis/${sessionId}`)
      ])
      setConsensus(consensusRes.data)
      setAnalysis(analysisRes.data)

      // Check if already resolved
      try {
        const filepath = `/api/download/json/${sessionId}`
        // We check the session config status instead
        if (consensusRes.data.status === 'resolved') {
          // Load resolved data
        }
      } catch (err) {
        // Not resolved yet
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load consensus data')
    } finally {
      setLoading(false)
    }
  }

  async function handleResolve() {
    setResolving(true)
    setError('')
    try {
      const res = await axios.post(`/api/consensus/${sessionId}/resolve`)
      setResolved(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Resolution failed')
    } finally {
      setResolving(false)
    }
  }

  async function handleOverride(violationId, action, text) {
    // For now, find a lead reviewer from the votes
    const violation = consensus.violations.find(v => v.violation_id === violationId)
    const leadVoter = violation?.votes.find(v => v.reviewer_role === 'lead')
    if (!leadVoter) {
      setError('No lead reviewer found for override')
      return
    }

    try {
      const res = await axios.post(`/api/consensus/${sessionId}/override`, {
        violation_id: violationId,
        action: action,
        text: text,
        reviewer_id: leadVoter.reviewer_id
      })
      setResolved(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Override failed')
    }
  }

  if (loading) return <div className="loading">Loading consensus data...</div>
  if (error && !consensus) return <div className="error-page"><div className="error-msg">{error}</div></div>

  const agreementLabels = {
    unanimous: 'Unanimous',
    majority: 'Majority',
    conflict: 'Conflict',
    pending: 'Pending'
  }

  // Build a map of violations from analysis for context
  const violationMap = {}
  if (analysis) {
    for (const req of analysis.requirements || []) {
      for (const v of req.violations || []) {
        violationMap[v.violation_id] = { ...v, req_id: req.req_id, original_text: req.original_text }
      }
    }
  }

  return (
    <div className="review-page">
      <div className="review-header">
        <h2>Consensus Dashboard</h2>
        <p className="subtitle">Session: {sessionId}</p>
      </div>

      {error && <div className="error-msg">{error}</div>}

      {/* Status summary */}
      <div className="feedback-controls section-block">
        <div className="stat-row">
          <div className="stat-box">
            <span className="stat-number">{consensus?.submitted_reviewers?.length || 0}</span>
            <span className="stat-label">Submitted</span>
          </div>
          <div className="stat-box">
            <span className="stat-number">{consensus?.pending_reviewers?.length || 0}</span>
            <span className="stat-label">Pending</span>
          </div>
          <div className="stat-box accent-unanimous">
            <span className="stat-number">
              {consensus?.violations?.filter(v => v.agreement === 'unanimous').length || 0}
            </span>
            <span className="stat-label">Unanimous</span>
          </div>
          <div className="stat-box accent-majority">
            <span className="stat-number">
              {consensus?.violations?.filter(v => v.agreement === 'majority').length || 0}
            </span>
            <span className="stat-label">Majority</span>
          </div>
          <div className="stat-box accent-conflict">
            <span className="stat-number">
              {consensus?.violations?.filter(v => v.agreement === 'conflict').length || 0}
            </span>
            <span className="stat-label">Conflicts</span>
          </div>
        </div>
      </div>

      {/* Violations table */}
      {consensus?.violations?.map(violation => {
        const vInfo = violationMap[violation.violation_id] || {}
        const resolvedViol = resolved?.requirement_feedback
          ?.flatMap(r => r.violation_feedback)
          ?.find(v => v.violation_id === violation.violation_id)

        return (
          <div
            key={violation.violation_id}
            className={`requirement-card consensus-card ${violation.agreement || 'pending'}`}
          >
            {/* Header */}
            <div className="violation-header">
              <span className="rule-badge">{violation.rule_id}</span>
              <span className="rule-name">Req {violation.req_id}</span>
              <span className={`agreement-badge ${violation.agreement || 'pending'}`}>
                {agreementLabels[violation.agreement] || violation.agreement}
              </span>
            </div>

            {/* Context */}
            {vInfo.original_text && (
              <div className="req-original section-block">
                <label>Requirement</label>
                <p>{vInfo.original_text}</p>
              </div>
            )}

            {vInfo.affected_text && (
              <div className="text-comparison">
                <div className="text-box affected">
                  <label>Affected Text</label>
                  <div className="text-value">{vInfo.affected_text}</div>
                </div>
                <div className="text-box suggested">
                  <label>AI Suggestion</label>
                  <div className="text-value">{vInfo.suggested_replacement || violation.ai_suggestion}</div>
                </div>
              </div>
            )}

            {/* Votes from each reviewer */}
            <div className="vote-list">
              <span className="eyebrow">Reviewer Votes</span>
              {violation.votes.map(vote => (
                <div key={vote.reviewer_id} className="vote-row">
                  <span className={`role-badge ${vote.reviewer_role || 'junior'}`}>
                    {vote.reviewer_role}
                  </span>
                  <span className="vote-name">{vote.reviewer_name}</span>
                  <span className={`action-badge ${vote.action}`}>
                    {vote.action}
                  </span>
                  {vote.action !== 'reject' && vote.text && (
                    <span className="vote-text">"{vote.text}"</span>
                  )}
                  {vote.notes && <span className="vote-notes">{vote.notes}</span>}
                  <span className="vote-weight">wt: {vote.weight}</span>
                </div>
              ))}
            </div>

            {/* Show resolved result if available */}
            {resolvedViol && (
              <div className={`resolution-box${resolvedViol.conflict ? ' conflict' : ''}`}>
                <div className="resolution-meta">
                  Resolution: {resolvedViol.resolution_method} (confidence: {resolvedViol.confidence})
                </div>
                <div className="resolution-result">
                  <span className={`action-badge ${resolvedViol.resolved_action}`}>
                    {resolvedViol.resolved_action}
                  </span>
                  {resolvedViol.resolved_action !== 'reject' && (
                    <span className="resolution-text">"{resolvedViol.resolved_text}"</span>
                  )}
                </div>
              </div>
            )}

            {/* Override button for conflicts */}
            {violation.agreement === 'conflict' && !resolvedViol && (
              <p className="conflict-note">
                This violation needs lead reviewer attention after resolution.
              </p>
            )}
          </div>
        )
      })}

      {/* Action buttons */}
      <div className="feedback-controls">
        {!resolved ? (
          <button
            className="btn-primary"
            onClick={handleResolve}
            disabled={resolving || consensus?.pending_reviewers?.length > 0}
          >
            {resolving
              ? 'Resolving...'
              : consensus?.pending_reviewers?.length > 0
                ? `Waiting for ${consensus.pending_reviewers.length} reviewer(s)`
                : 'Resolve Consensus'
            }
          </button>
        ) : (
          <div>
            <div className="progress-msg">
              Resolution complete. {resolved.summary_statistics?.conflicts || 0} conflict(s) found.
            </div>
            <button
              className="btn-primary"
              onClick={() => navigate(`/download/${sessionId}`)}
            >
              View Results &amp; Download
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
