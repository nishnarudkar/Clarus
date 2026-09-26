import { Fragment, useEffect, useRef, useState } from 'react'
import type { ConfBand, FinalTurnEvent, PartialTranscriptEvent, Word } from '../types'

// Colour is never the only signal: each band also has its own underline and marker.
const BAND_LABEL: Record<ConfBand, string> = {
  high: 'high confidence',
  mid: 'medium confidence',
  low: 'low confidence',
}

function WordSpan({ word, partial }: { word: Word; partial?: boolean }) {
  const cls = partial ? 'w w-partial' : `w w-${word.band}`
  const label = `${word.text}, ${BAND_LABEL[word.band]} ${word.confidence.toFixed(2)}`
  return (
    <span className={cls} title={label} aria-label={label}>
      {word.text}
    </span>
  )
}

export function ConfidenceLegend() {
  // Band thresholds live in backend config.py; the backend also assigns each word's band.
  const [bands, setBands] = useState<{ conf_band_high: number; conf_band_low: number } | null>(null)
  useEffect(() => {
    fetch('/api/config')
      .then((r) => (r.ok ? r.json() : null))
      .then(setBands)
      .catch(() => setBands(null))
  }, [])
  const hi = bands ? bands.conf_band_high.toFixed(2) : '…'
  const lo = bands ? bands.conf_band_low.toFixed(2) : '…'
  return (
    <p className="legend" aria-label="Word confidence legend">
      <span className="w w-high">high ≥ {hi}</span>
      <span className="w w-mid">
        medium {lo}–{hi}
      </span>
      <span className="w w-low">
        low &lt; {lo}
      </span>
      <span className="w w-partial">in progress</span>
    </p>
  )
}

export function Transcript({ turns, partial }: { turns: FinalTurnEvent[]; partial: PartialTranscriptEvent | null }) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => endRef.current?.scrollIntoView({ block: 'nearest' }), [turns, partial])

  return (
    <div className="transcript">
      {turns.length === 0 && !partial && <p className="muted">Your finished turns will appear here.</p>}
      <ol className="turns" aria-live="polite">
        {turns.map((t) => (
          <li key={`${t.stream_id}:${t.turn_order}`} className="turn">
            <div className="turn-words">
              {t.words.map((w, i) => (
                <Fragment key={i}>
                  <WordSpan word={w} />{' '}
                </Fragment>
              ))}
            </div>
            <div className="turn-meta">
              turn {t.turn_order + 1} · {t.words.length} words · end-of-turn conf {t.end_of_turn_confidence.toFixed(2)}
              {t.formatted ? ' · formatted' : ''}
            </div>
          </li>
        ))}
      </ol>
      {partial && partial.words.length > 0 && (
        <div className="turn turn-partial" aria-hidden="true">
          <div className="turn-words">
            {partial.words.map((w, i) => (
              <Fragment key={i}>
                <WordSpan word={w} partial />{' '}
              </Fragment>
            ))}
          </div>
        </div>
      )}
      <div ref={endRef} />
    </div>
  )
}
