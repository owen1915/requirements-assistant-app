import { useEffect, useState } from 'react'
import UploadStage from './components/UploadStage'
import RunStage from './components/RunStage'
import RulesStage from './components/RulesStage'
import { getConfig } from './api'

const STEPS = ['Corpus', 'Run', 'Rules']

/* One linear flow rather than routes: there is no shareable resource here — an
   upload is a temp directory and a run is process memory, so a URL for either
   would be a promise the server cannot keep across a restart. */

export default function App() {
  const [stage, setStage] = useState(0)
  const [upload, setUpload] = useState(null)
  const [run, setRun] = useState(null)
  const [config, setConfig] = useState(null)

  useEffect(() => {
    getConfig().then(setConfig).catch(() => setConfig({ keys: {} }))
  }, [])

  return (
    <>
      <header className="app-header">
        <div className="header-inner">
          <h1>ICAIv2 Studio</h1>
          <nav className="step-nav" aria-label="Progress">
            {STEPS.map((label, i) => (
              <span key={label} className={`step${i === stage ? ' active' : ''}${i < stage ? ' done' : ''}`}
                    aria-current={i === stage ? 'step' : undefined}>
                <span className="step-marker" aria-hidden="true">{i < stage ? '✓' : i + 1}</span>
                <span className="step-label">{label}</span>
              </span>
            ))}
          </nav>
        </div>
      </header>

      <main className="app-main">
        {stage === 0 && (
          <UploadStage
            onReady={(u) => {
              setUpload(u)
              setStage(1)
            }}
          />
        )}

        {stage === 1 && upload && (
          <RunStage
            upload={upload}
            config={config}
            onBack={() => setStage(0)}
            onDone={(r) => {
              setRun(r)
              setStage(2)
            }}
          />
        )}

        {stage === 2 && run && (
          <RulesStage
            run={run}
            onRestart={() => {
              setRun(null)
              setUpload(null)
              setStage(0)
            }}
          />
        )}

        <footer className="app-footer">
          Induces a constitution from reviewer disagreement, following Findeis et al.
          (ICAI, ICLR 2025), with cross-seed stability selection on top. Runs the same{' '}
          <span className="mono">icai_v2.pipeline.run_pipeline</span> the CLI runs.
        </footer>
      </main>
    </>
  )
}
