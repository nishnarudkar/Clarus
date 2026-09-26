import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

export default function Landing() {
  const [consent, setConsent] = useState(false)
  const navigate = useNavigate()

  return (
    <main className="page landing">
      <h1>Clarus</h1>
      <p className="lede">
        Speech recognition tells you what was said. Clarus measures whether it was <em>understood</em>.
      </p>

      <section className="card">
        <label className="consent">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            I agree that my speech is streamed to AssemblyAI for transcription. Audio is not stored; transcripts
            and derived measurements stay on this server.
          </span>
        </label>
        <button
          type="button"
          className="primary"
          disabled={!consent}
          onClick={() => navigate('/session', { state: { consent: true } })}
        >
          Start a session
        </button>
      </section>
    </main>
  )
}
