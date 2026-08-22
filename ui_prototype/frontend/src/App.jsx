import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import UploadPage from './pages/UploadPage'
import ReviewPage from './pages/ReviewPage'
import DownloadPage from './pages/DownloadPage'
import SessionSetupPage from './pages/SessionSetupPage'
import ConsensusPage from './pages/ConsensusPage'
import AccessGate from './components/AccessGate'

function Header() {
  const location = useLocation()
  const path = location.pathname

  const steps = [
    { label: 'Upload', match: '/' },
    { label: 'Setup', match: '/setup' },
    { label: 'Review', match: '/review' },
    { label: 'Consensus', match: '/consensus' },
    { label: 'Download', match: '/download' },
  ]

  const isActive = (step) =>
    path.startsWith(step.match) && (step.match !== '/' || path === '/')

  // Steps before the current one are complete — shown with a check rather
  // than just dimmed, so progress through the flow is legible at a glance.
  const activeIndex = steps.findIndex(isActive)

  return (
    <header className="app-header">
      <h1>INCOSE Requirements Analyzer</h1>
      <nav className="step-nav" aria-label="Progress">
        {steps.map((step, i) => {
          const active = isActive(step)
          const done = activeIndex > -1 && i < activeIndex
          return (
            <span
              key={step.match}
              className={`step${active ? ' active' : ''}${done ? ' done' : ''}`}
              aria-current={active ? 'step' : undefined}
            >
              <span className="step-marker" aria-hidden="true">
                {done ? '✓' : i + 1}
              </span>
              <span className="step-label">{step.label}</span>
            </span>
          )
        })}
      </nav>
    </header>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AccessGate>
        <Header />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<UploadPage />} />
            <Route path="/setup/:sessionId" element={<SessionSetupPage />} />
            <Route path="/review/:sessionId" element={<ReviewPage />} />
            <Route path="/consensus/:sessionId" element={<ConsensusPage />} />
            <Route path="/download/:sessionId" element={<DownloadPage />} />
          </Routes>
        </main>
      </AccessGate>
    </BrowserRouter>
  )
}
