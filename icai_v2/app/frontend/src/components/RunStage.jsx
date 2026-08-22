import { useEffect, useMemo, useRef, useState } from 'react'
import { cancelRun, estimate, readRun, startRun, errorText } from '../api'

const POLL_MS = 1200

/* Cost is shown in dollars, live, for every supported model — a call count told
   you almost nothing, because the three call types differ by ~7x in prompt size
   and the testing prompt carries every surviving principle. The three knobs that
   actually move the bill (model, corpus size, k) sit next to the number they
   move, so tuning down to a cheap exploratory run is a matter of watching it. */

function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

function CostTable({ options, selected, onSelect, models }) {
  const noteFor = (id) => models?.find((m) => m.id === id)?.note
  return (
    <table className="table cost-table">
      <thead>
        <tr>
          <th>Model</th>
          <th className="num">$ / MTok</th>
          <th className="num">Calls</th>
          <th className="num">Est. cost</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {options.map((o) => (
          <tr key={o.model} className={o.model === selected ? 'row-selected' : ''}>
            <td>
              <strong>{o.model_label}</strong>
              <span className="field-hint block">{noteFor(o.model)}</span>
            </td>
            <td className="num mono">
              {models?.find((m) => m.id === o.model)?.input_per_mtok}/
              {models?.find((m) => m.id === o.model)?.output_per_mtok}
            </td>
            <td className="num">{o.calls.toLocaleString()}</td>
            <td className="num">
              <strong>${o.usd.toFixed(2)}</strong>
              <span className="field-hint block">up to ${o.usd_high.toFixed(2)}</span>
            </td>
            <td>
              <button
                className={o.model === selected ? 'btn-primary' : 'btn-secondary'}
                onClick={() => onSelect(o.model)}
              >
                {o.model === selected ? 'Selected' : 'Use'}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function RunStage({ upload, config, onDone, onBack }) {
  const [params, setParams] = useState({
    seeds: 3,
    k_clusters: 100,
    n_constitution: 5,
    stability_min: 2,
    dry_run: true,
    tag: 'icai_v2_studio',
    model: '',
    max_cases: '',
  })
  const [quote, setQuote] = useState(null)
  const [run, setRun] = useState(null)
  const [error, setError] = useState('')
  const logRef = useRef(null)

  // Default to the cheapest supported model once config arrives.
  useEffect(() => {
    if (config?.default_model && !params.model) {
      setParams((p) => ({ ...p, model: config.default_model }))
    }
  }, [config?.default_model])

  const set = (k) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setParams((p) => ({ ...p, [k]: e.target.type === 'number' ? Number(v) : v }))
  }

  const cap = Number(params.max_cases) || null

  useEffect(() => {
    estimate(upload.upload_id, {
      seeds: params.seeds,
      k_clusters: params.k_clusters,
      ...(cap ? { max_cases: cap } : {}),
    })
      .then(setQuote)
      .catch(() => setQuote(null))
  }, [upload.upload_id, params.seeds, params.k_clusters, cap])

  const chosen = useMemo(
    () => quote?.options?.find((o) => o.model === params.model),
    [quote, params.model],
  )

  // Poll while the run is in flight. The pipeline appends one line per step, so
  // the log is the progress bar — a percentage would be a guess.
  useEffect(() => {
    if (!run || ['done', 'error', 'cancelled'].includes(run.status)) return
    const t = setTimeout(async () => {
      try {
        setRun(await readRun(run.run_id))
      } catch (err) {
        setError(errorText(err))
      }
    }, POLL_MS)
    return () => clearTimeout(t)
  }, [run])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [run?.log?.length])

  useEffect(() => {
    if (run?.status === 'done' && run.result) onDone(run)
  }, [run?.status])

  const begin = async () => {
    setError('')
    try {
      setRun(await startRun({
        upload_id: upload.upload_id,
        ...params,
        max_cases: cap,
      }))
    } catch (err) {
      setError(errorText(err))
    }
  }

  const running = run && ['queued', 'running'].includes(run.status)
  const liveBlocked = !params.dry_run && !config?.live_runs_available

  return (
    <section className="card">
      <h2>2 &middot; Configure &amp; run</h2>

      <div className="grid">
        <Field label="Seeds" hint="Independent pipeline runs; stability is measured across them">
          <input type="number" min="1" max="20" value={params.seeds}
                 onChange={set('seeds')} disabled={running} />
        </Field>
        <Field label="k clusters"
               hint={`Candidates collapse to at most k before testing. 100 is the published value; lowering it is the second-biggest cost lever${chosen ? ` (${chosen.rules_per_test_call} per test call)` : ''}`}>
          <input type="number" min="2" max="500" value={params.k_clusters}
                 onChange={set('k_clusters')} disabled={running} />
        </Field>
        <Field label="Sample size"
               hint={`Blank = all ${quote?.n_cases ?? '…'} decisions. Cost is linear in this`}>
          <input type="number" min="10" placeholder="all" value={params.max_cases}
                 onChange={set('max_cases')} disabled={running} />
        </Field>
        <Field label="Keep n" hint="Constitution size per seed (paper default 5)">
          <input type="number" min="1" max="50" value={params.n_constitution}
                 onChange={set('n_constitution')} disabled={running} />
        </Field>
        <Field label="Stability threshold"
               hint={`Keep a principle found in >= this many of ${params.seeds} seeds`}>
          <input type="number" min="1" max="20" value={params.stability_min}
                 onChange={set('stability_min')} disabled={running} />
        </Field>
        <Field label="Tag" hint="Names the rule set: rules_group_<tag>.json">
          <input type="text" value={params.tag} onChange={set('tag')} disabled={running} />
        </Field>
      </div>

      {params.stability_min > params.seeds && (
        <p className="notice notice-warn">
          The threshold is above the seed count, so nothing can reach it — the run
          will fall back to the top {params.n_constitution} by seed count and say so.
        </p>
      )}

      {quote && (
        <>
          <h3 className="section-head">Cost of a live run at these settings</h3>
          <CostTable options={quote.options} models={config?.models}
                     selected={params.model}
                     onSelect={(m) => setParams((p) => ({ ...p, model: m }))} />
          <p className="muted small">
            Prompt sizes are measured; reply lengths are inferred from their required
            shape, so treat the upper figure as the realistic ceiling. Embeddings add
            well under a cent.
          </p>
        </>
      )}

      <div className="mode">
        <label className="check">
          <input type="checkbox" checked={params.dry_run} onChange={set('dry_run')}
                 disabled={running} />
          <span>
            <strong>Dry run</strong> — no API calls, stub principles, $0. Use it to
            check the corpus and the wiring for free.
          </span>
        </label>

        {!params.dry_run && (
          <p className={`notice ${liveBlocked ? 'notice-error' : 'notice-warn'}`}>
            {liveBlocked ? (
              <>
                A live run needs both keys on the server:
                {' '}Anthropic ({config?.keys?.anthropic ? 'set' : 'missing'}) for
                generation and testing, OpenAI ({config?.keys?.openai ? 'set' : 'missing'})
                for the clustering embeddings.
              </>
            ) : (
              <>
                Live run on <strong>{chosen?.model_label ?? params.model}</strong>:
                {' '}about <strong>${chosen?.usd?.toFixed(2) ?? '…'}</strong> across{' '}
                {params.seeds} seeds over {chosen?.n_cases ?? '…'} decisions. Takes minutes.
              </>
            )}
          </p>
        )}
      </div>

      <div className="row">
        <button className="btn-secondary" onClick={onBack} disabled={running}>
          &larr; Change corpus
        </button>
        <button className="btn-primary" onClick={begin} disabled={running || liveBlocked}>
          {running ? 'Running…' : params.dry_run ? 'Run (dry)' : `Run live · $${chosen?.usd?.toFixed(2) ?? '?'}`}
        </button>
        {running && (
          <button className="btn-danger" onClick={() => cancelRun(run.run_id)}>
            Cancel
          </button>
        )}
        {run && <span className={`pill pill-${run.status}`}>{run.status}</span>}
      </div>

      {error && <p className="error">{error}</p>}
      {run?.error && <p className="error">{run.error}</p>}

      {run && (
        <pre className="log" ref={logRef}>
          {run.log.join('\n') || 'starting…'}
        </pre>
      )}
    </section>
  )
}
