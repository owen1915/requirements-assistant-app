import { useState } from 'react'
import { publishRules, rulesUrl, errorText } from '../api'

/* Two things every rule needs to be read honestly, and which a bare list hides:
   how many seeds independently found it (the Rashomon check the paper asks for),
   and the sibling phrasings its cluster absorbed. Both are shown, and the ranked
   principles that missed the cut stay visible below rather than being discarded —
   a rule that reached 2 of 5 seeds is a different claim from one that reached 0. */

function Metric({ label, value }) {
  return (
    <span className="metric">
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
    </span>
  )
}

function RuleCard({ rule, index, seeds }) {
  const [open, setOpen] = useState(false)
  const x = rule.extra || {}
  const variants = x.variants || []
  const found = x.seeds_found ?? 0
  const strong = seeds > 0 && found / seeds >= 0.6

  return (
    <article className="rule">
      <header>
        <span className="rank">{index + 1}</span>
        <span className="criterion">{rule.criterion}</span>
        <span className={`pill ${strong ? 'pill-ok' : 'pill-warn'}`}>
          {found}/{seeds} seeds
        </span>
      </header>
      <p className="rule-text">{rule.rule_text}</p>
      <div className="metrics">
        <Metric label="net" value={x.net ?? '—'} />
        <Metric label="relevance" value={x.relevance ?? '—'} />
        <Metric label="accuracy" value={x.accuracy ?? '—'} />
        <Metric label="correct" value={x.correct ?? '—'} />
        <Metric label="incorrect" value={x.incorrect ?? '—'} />
      </div>
      {variants.length > 1 && (
        <>
          <button className="linkish" onClick={() => setOpen(!open)}>
            {open ? 'Hide' : 'Show'} {variants.length} clustered phrasings
          </button>
          {open && (
            <ul className="variants">
              {variants.map((v) => <li key={v}>{v}</li>)}
            </ul>
          )}
        </>
      )}
    </article>
  )
}

export default function RulesStage({ run, onRestart }) {
  const [publishState, setPublishState] = useState(null)
  const [error, setError] = useState('')
  const result = run.result
  const seeds = run.params.seeds
  const rules = result.rules || []
  const belowCut = (result.all_ranked || []).filter(
    (p) => !rules.some((r) => r.rule_text === p.principle),
  )

  const publish = async () => {
    setError('')
    try {
      setPublishState(await publishRules(run.run_id))
    } catch (err) {
      setError(errorText(err))
    }
  }

  return (
    <section className="card">
      <h2>3 &middot; Induced constitution</h2>

      {run.params.dry_run && (
        <p className="notice notice-warn">
          Dry run — these principles are stubs, not induced from the corpus. The
          shape and the plumbing are real; the text is not.
        </p>
      )}

      {result.below_stability_threshold && (
        <p className="notice notice-warn">
          No principle reached {run.params.stability_min} of {seeds} seeds. What
          follows is the top {run.params.n_constitution} by seed count — a weaker
          claim than the stability filter is meant to make.
        </p>
      )}

      <div className="stat-row">
        <div className="stat">
          <span className="stat-value">{rules.length}</span>
          <span className="stat-label">rules kept</span>
        </div>
        <div className="stat">
          <span className="stat-value">{(result.all_ranked || []).length}</span>
          <span className="stat-label">clusters ranked</span>
        </div>
        <div className="stat">
          <span className="stat-value">
            {result.lift_mean > 0 ? '+' : ''}{result.lift_mean}
          </span>
          <span className="stat-label">mean Eq. 1 lift</span>
        </div>
      </div>

      {rules.map((r, i) => (
        <RuleCard key={`${r.criterion}-${i}`} rule={r} index={i} seeds={seeds} />
      ))}

      {belowCut.length > 0 && (
        <details className="below-cut">
          <summary>{belowCut.length} ranked principles below the cut</summary>
          <ul>
            {belowCut.map((p, i) => (
              <li key={i}>
                <span className="criterion small">{p.criterion}</span>
                <span className="pill pill-warn">{p.seeds_found}/{seeds}</span>
                {p.principle}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="row">
        <a className="btn-primary" href={rulesUrl(run.run_id)} download>
          Download rules_group_{run.params.tag}.json
        </a>
        <button className="btn-secondary" onClick={publish} disabled={run.params.dry_run}>
          Publish to rule_sets/
        </button>
        <button className="btn-secondary" onClick={onRestart}>
          Start over
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {publishState?.ok && (
        <p className="notice notice-ok">
          Written to <span className="mono">{publishState.path}</span>. The testbed
          can now inject it:{' '}
          <span className="mono">
            python -m n8n_testbed.batch_runner submit --rules {publishState.inject_config}
          </span>
        </p>
      )}

      <p className="muted small">
        This file is the shape <span className="mono">n8n_testbed.inject.load_sme_rules</span>{' '}
        reads, so it drops straight into a testbed run.
      </p>
    </section>
  )
}
