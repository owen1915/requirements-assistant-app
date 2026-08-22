import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import axios from 'axios'

export default function SessionSetupPage() {
  const { sessionId } = useParams()
  const [reviewers, setReviewers] = useState([])
  const [selectedReviewers, setSelectedReviewers] = useState([])
  const [newName, setNewName] = useState('')
  const [newRole, setNewRole] = useState('senior')
  const [sessionConfig, setSessionConfig] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    loadReviewers()
    loadSessionConfig()
  }, [sessionId])

  async function loadReviewers() {
    try {
      const res = await axios.get('/api/reviewers')
      setReviewers(res.data.reviewers || [])
    } catch (err) {
      console.error('Failed to load reviewers', err)
    }
  }

  async function loadSessionConfig() {
    try {
      const res = await axios.get(`/api/sessions/${sessionId}/config`)
      setSessionConfig(res.data)
    } catch (err) {
      // No config yet = not set up
    }
  }

  async function handleAddReviewer() {
    if (!newName.trim()) return
    setError('')
    try {
      const res = await axios.post('/api/reviewers', { name: newName.trim(), role: newRole })
      setReviewers(prev => [...prev, res.data])
      setNewName('')
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to add reviewer')
    }
  }

  function toggleReviewer(reviewerId) {
    setSelectedReviewers(prev =>
      prev.includes(reviewerId)
        ? prev.filter(id => id !== reviewerId)
        : [...prev, reviewerId]
    )
  }

  async function handleInvite() {
    if (selectedReviewers.length < 2) {
      setError('Select at least 2 reviewers')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await axios.post(`/api/sessions/${sessionId}/invite`, {
        reviewer_ids: selectedReviewers
      })
      setSessionConfig(res.data.config)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to invite reviewers')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="upload-page">
      <div className="upload-card wide">
        <h2>Multi-Reviewer Setup</h2>
        <p className="subtitle">Session: {sessionId}</p>

        {error && <div className="error-msg">{error}</div>}

        {/* If session is already configured, show review links */}
        {sessionConfig && sessionConfig.status !== undefined ? (
          <div>
            <div className="progress-msg">
              Session is in <strong>{sessionConfig.status}</strong> mode
              with {sessionConfig.expected_reviewers.length} reviewers assigned.
            </div>

            <h3 className="section-heading">Review Links</h3>
            <p className="hint">Share these links with each reviewer:</p>

            {sessionConfig.expected_reviewers.map(rid => {
              const reviewer = reviewers.find(r => r.reviewer_id === rid)
              const submitted = (sessionConfig.submitted_reviewers || []).includes(rid)
              return (
                <div key={rid} className={`list-row${submitted ? ' complete' : ''}`}>
                  <span className={`role-badge ${reviewer?.role || 'junior'}`}>
                    {reviewer?.role || 'reviewer'}
                  </span>
                  <span className="list-row-name">{reviewer?.name || rid}</span>
                  {submitted ? (
                    <span className="list-row-status">Submitted</span>
                  ) : (
                    <Link className="list-row-link" to={`/review/${sessionId}?reviewer=${rid}`}>
                      /review/{sessionId}?reviewer={rid}
                    </Link>
                  )}
                </div>
              )
            })}

            {sessionConfig.status === 'ready_for_resolution' && (
              <div className="section-block">
                <Link to={`/consensus/${sessionId}`}>
                  <button className="btn-primary">View Consensus Dashboard</button>
                </Link>
              </div>
            )}

            {sessionConfig.status === 'reviewing' && (
              <p className="hint">
                Waiting for {sessionConfig.expected_reviewers.length - (sessionConfig.submitted_reviewers || []).length} reviewer(s) to submit.
              </p>
            )}
          </div>
        ) : (
          <>
            {/* Add new reviewer */}
            <div className="section-block">
              <h3 className="section-heading">Add Reviewer</h3>
              <div className="field-row">
                <input
                  type="text"
                  className="text-input"
                  placeholder="Name"
                  aria-label="Reviewer name"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAddReviewer()}
                />
                <select
                  className="select-input"
                  aria-label="Reviewer role"
                  value={newRole}
                  onChange={e => setNewRole(e.target.value)}
                >
                  <option value="lead">Lead (weight 3)</option>
                  <option value="senior">Senior (weight 2)</option>
                  <option value="junior">Junior (weight 1)</option>
                </select>
                <button className="btn-secondary btn-inline" onClick={handleAddReviewer}>
                  Add
                </button>
              </div>
            </div>

            {/* Select reviewers */}
            <div className="section-block">
              <h3 className="section-heading">
                Select Reviewers ({selectedReviewers.length} selected)
              </h3>
              {reviewers.length === 0 ? (
                <p className="hint">No reviewers registered yet. Add some above.</p>
              ) : (
                reviewers.map(r => {
                  const isSelected = selectedReviewers.includes(r.reviewer_id)
                  return (
                    <label
                      key={r.reviewer_id}
                      className={`list-row selectable${isSelected ? ' selected' : ''}`}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleReviewer(r.reviewer_id)}
                      />
                      <span className={`role-badge ${r.role}`}>{r.role}</span>
                      <span className="list-row-name">{r.name}</span>
                      <span className="list-row-meta">weight {r.weight}</span>
                    </label>
                  )
                })
              )}
            </div>

            <button
              className="btn-primary"
              onClick={handleInvite}
              disabled={loading || selectedReviewers.length < 2}
            >
              {loading ? 'Setting up...' : `Invite ${selectedReviewers.length} Reviewers`}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
