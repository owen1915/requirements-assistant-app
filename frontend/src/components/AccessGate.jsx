import { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import {
  getAccessCode, setAccessCode, clearAccessCode, onAccessRejected,
} from '../accessCode'

/**
 * Blocks the app behind the shared access code when the server requires one.
 *
 * Analysis runs on the operator's API keys, so this keeps a public URL from
 * spending them. When the server has no ACCESS_CODE configured the gate is
 * transparent and children render immediately.
 */
export default function AccessGate({ children }) {
  const [status, setStatus] = useState('checking') // checking | locked | open
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const verify = useCallback(async (candidate) => {
    const res = await axios.post('/api/access/verify', { code: candidate }, { timeout: 10000 })
    return res.data?.ok === true
  }, [])

  // Resolve whether a code is needed, and whether the stored one still works.
  useEffect(() => {
    let cancelled = false

    const check = async (attemptsLeft = 20) => {
      try {
        const res = await axios.get('/api/config', { timeout: 5000 })
        if (cancelled) return

        if (!res.data?.auth_required) {
          clearAccessCode()
          setStatus('open')
          return
        }

        const stored = getAccessCode()
        if (!stored) {
          setStatus('locked')
          return
        }

        try {
          if (await verify(stored)) {
            if (!cancelled) setStatus('open')
          } else if (!cancelled) {
            clearAccessCode()
            setStatus('locked')
          }
        } catch {
          // Rejected or unreachable — fall back to asking for the code.
          if (!cancelled) {
            clearAccessCode()
            setStatus('locked')
          }
        }
      } catch {
        // Backend still waking up (Render free tier cold start) — retry.
        if (cancelled || attemptsLeft <= 0) {
          if (!cancelled) setStatus('locked')
          return
        }
        setTimeout(() => check(attemptsLeft - 1), 2000)
      }
    }

    check()
    return () => { cancelled = true }
  }, [verify])

  // If the server later rejects the stored code, return to the gate.
  useEffect(() => onAccessRejected(() => {
    setStatus('locked')
    setError('Your access code is no longer valid. Please re-enter it.')
  }), [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    const candidate = code.trim()
    if (!candidate) {
      setError('Please enter the access code.')
      return
    }

    setSubmitting(true)
    setError('')
    try {
      if (await verify(candidate)) {
        setAccessCode(candidate)
        setCode('')
        setStatus('open')
      } else {
        setError('Incorrect access code.')
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not verify the code. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (status === 'open') return children

  if (status === 'checking') {
    return (
      <div className="gate-screen">
        <p className="gate-checking">Connecting…</p>
      </div>
    )
  }

  return (
    <div className="gate-screen">
      <form className="gate-card" onSubmit={handleSubmit}>
        <h2>Access Code Required</h2>
        <p className="subtitle">
          This tool is limited to invited users. Enter the access code you were given.
        </p>

        <div className="form-group">
          <label htmlFor="access-code">Access Code</label>
          <input
            id="access-code"
            type="password"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            disabled={submitting}
            autoFocus
            autoComplete="off"
          />
        </div>

        {error && <div className="error-msg">{error}</div>}

        <button type="submit" className="btn-primary" disabled={submitting || !code.trim()}>
          {submitting ? 'Checking…' : 'Continue'}
        </button>
      </form>
    </div>
  )
}
