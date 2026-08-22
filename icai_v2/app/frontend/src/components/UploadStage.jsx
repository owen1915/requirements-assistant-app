import { useCallback, useRef, useState } from 'react'
import { uploadFeedback, useSampleCorpus, errorText } from '../api'

/* The corpus report is shown before anything is spent, because the two numbers
   that decide whether a run is worth doing are in it: how many decisions there
   are, and how many of them are corrective. A rubber-stamp session contributes
   records but no signal, and the pipeline weights that distinction, so the
   operator should see it here rather than discover it in the results. */

function SessionTable({ report }) {
  const sessions = Object.entries(report.sessions || {})
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Session</th>
          <th className="num">Accept</th>
          <th className="num">Reject</th>
          <th className="num">Modify</th>
          <th>Engaged</th>
        </tr>
      </thead>
      <tbody>
        {sessions.map(([id, s]) => (
          <tr key={id}>
            <td className="mono">{id}</td>
            <td className="num">{s.accept}</td>
            <td className="num">{s.reject}</td>
            <td className="num">{s.modify}</td>
            <td>
              <span className={`pill ${s.engaged ? 'pill-ok' : 'pill-warn'}`}>
                {s.engaged ? 'yes' : 'rubber-stamp'}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function UploadStage({ onReady }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef(null)

  const submit = useCallback(async (files) => {
    if (!files.length) return
    setBusy(true)
    setError('')
    try {
      setResult(await uploadFeedback(files))
    } catch (err) {
      // A 422 carries per-file reasons, which are far more useful than the status.
      const data = err?.response?.data
      if (data?.files) setResult(data)
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }, [])

  const loadSample = async () => {
    setBusy(true)
    setError('')
    try {
      setResult(await useSampleCorpus())
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const rejected = (result?.files || []).filter((f) => !f.ok)

  return (
    <section className="card">
      <h2>1 &middot; Feedback corpus</h2>
      <p className="muted">
        Upload one or more reviewer feedback exports — the JSON the prototype&rsquo;s
        download step produces, one file per review session.
      </p>

      <div
        className={`dropzone${dragging ? ' dragging' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          submit([...e.dataTransfer.files])
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
        }}
      >
        <strong>Drop feedback JSON files here</strong>
        <span className="muted">or click to choose them</span>
        <input
          ref={inputRef}
          type="file"
          accept="application/json,.json"
          multiple
          hidden
          onChange={(e) => submit([...e.target.files])}
        />
      </div>

      <div className="row">
        <button className="btn-secondary" onClick={loadSample} disabled={busy}>
          Use the 5 checked-in PM sessions
        </button>
        {busy && <span className="muted">Reading&hellip;</span>}
      </div>

      {error && !rejected.length && <p className="error">{error}</p>}

      {rejected.length > 0 && (
        <div className="notice notice-error">
          <strong>{rejected.length} file(s) could not be used</strong>
          <ul>
            {rejected.map((f) => (
              <li key={f.file}>
                <span className="mono">{f.file}</span> — {f.error}
              </li>
            ))}
          </ul>
        </div>
      )}

      {result?.ok && (
        <div className="result">
          <div className="stat-row">
            <div className="stat">
              <span className="stat-value">{result.report.total_records}</span>
              <span className="stat-label">decisions</span>
            </div>
            <div className="stat">
              <span className="stat-value">{result.n_corrective}</span>
              <span className="stat-label">corrective (the signal)</span>
            </div>
            <div className="stat">
              <span className="stat-value">
                {Object.keys(result.report.sessions || {}).length}
              </span>
              <span className="stat-label">sessions</span>
            </div>
            <div className="stat">
              <span className="stat-value">{result.report.relabelled_by_text}</span>
              <span className="stat-label">relabelled by text</span>
            </div>
          </div>

          <SessionTable report={result.report} />

          <p className="muted small">
            Corrective signal by criterion:{' '}
            {Object.entries(result.report.engaged_corrective_by_criterion || {})
              .map(([c, n]) => `${c} ${n}`)
              .join(' · ') || 'none'}
          </p>

          {result.n_corrective === 0 && (
            <p className="notice notice-warn">
              No corrective decisions. Every session accepted everything the model
              proposed, so there is no disagreement for the pipeline to learn from.
            </p>
          )}

          <button className="btn-primary" onClick={() => onReady(result)}>
            Configure the run &rarr;
          </button>
        </div>
      )}
    </section>
  )
}
