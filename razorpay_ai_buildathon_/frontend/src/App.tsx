import './App.css'

function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>LedgerLens</h1>
        <p className="app-subtitle">AI Finance Controller</p>
        <span className="phase-badge">Phase 1 — Foundation</span>
      </header>
      <main className="app-main">
        <p className="app-description">
          Evidence-first reconciliation for Razorpay AI Buildathon Track 04.
        </p>
        <div className="status-card">
          <span className="status-indicator" />
          <span>Backend skeleton ready</span>
        </div>
      </main>
    </div>
  )
}

export default App
