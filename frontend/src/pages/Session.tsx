import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { MicCapture } from '../audio/mic'
import { StatusPill } from '../components/StatusPill'
import { ConfidenceLegend, Transcript } from '../components/Transcript'
import type { ErrorEvent, FinalTurnEvent, PartialTranscriptEvent, ServerEvent, StreamState } from '../types'
import { SessionSocket, type SocketStatus } from '../ws'

export default function Session() {
  const location = useLocation()
  const consent = (location.state as { consent?: boolean } | null)?.consent
  if (!consent) return <Navigate to="/" replace />
  return <LiveSession />
}

function sameTurn(a: { stream_id: string; turn_order: number }, b: { stream_id: string; turn_order: number }) {
  return a.stream_id === b.stream_id && a.turn_order === b.turn_order
}

function LiveSession() {
  const [socketStatus, setSocketStatus] = useState<SocketStatus>('connecting')
  const [stream, setStream] = useState<StreamState>('idle')
  const [turns, setTurns] = useState<FinalTurnEvent[]>([])
  const [partial, setPartial] = useState<PartialTranscriptEvent | null>(null)
  const [errors, setErrors] = useState<ErrorEvent[]>([])
  const [micOn, setMicOn] = useState(false)

  const socketRef = useRef<SessionSocket | null>(null)
  const micRef = useRef<MicCapture | null>(null)
  const streamRef = useRef<StreamState>('idle')

  const handleEvent = useCallback((e: ServerEvent) => {
    switch (e.type) {
      case 'state':
        streamRef.current = e.state
        setStream(e.state)
        if (e.state === 'listening') setErrors((prev) => prev.filter((x) => !x.recoverable))
        if (e.state === 'stopped' && micRef.current) {
          // Stream ended (user stop, or the backend gave up, e.g. bad API key): release the mic.
          micRef.current.stop()
          micRef.current = null
          setMicOn(false)
        }
        break
      case 'partial_transcript':
        setPartial(e)
        break
      case 'final_turn':
        // The formatted version of a turn replaces the unformatted one.
        setTurns((prev) => {
          const i = prev.findIndex((t) => sameTurn(t, e))
          return i === -1 ? [...prev, e] : prev.map((t, j) => (j === i ? e : t))
        })
        setPartial((p) => (p && sameTurn(p, e) ? null : p))
        break
      case 'error':
        setErrors((prev) => [...prev.slice(-3), e])
        break
    }
  }, [])

  useEffect(() => {
    const socket = new SessionSocket(crypto.randomUUID(), handleEvent, setSocketStatus)
    socket.connect()
    socketRef.current = socket
    return () => {
      micRef.current?.stop()
      micRef.current = null
      socket.close()
    }
  }, [handleEvent])

  const stopMic = () => {
    micRef.current?.stop()
    micRef.current = null
    setMicOn(false)
  }

  const start = async () => {
    const socket = socketRef.current
    if (!socket) return
    setErrors([])
    socket.startStream()
    const mic = new MicCapture()
    try {
      // Frames are only forwarded once AssemblyAI has opened the stream.
      await mic.start((pcm) => {
        if (streamRef.current === 'listening') socket.sendAudio(pcm)
      })
      micRef.current = mic
      setMicOn(true)
    } catch (err) {
      mic.stop()
      socket.stopStream()
      handleEvent({
        type: 'error',
        ts: Date.now(),
        message: `Microphone unavailable: ${err instanceof Error ? err.message : String(err)}`,
        code: null,
        recoverable: false,
      })
    }
  }

  const stop = () => {
    stopMic()
    streamRef.current = 'stopping'
    setStream('stopping')
    socketRef.current?.stopStream()
  }

  // Only start from a settled state, so a late 'stopped' can't kill a fresh mic.
  const canStart = socketStatus === 'open' && !micOn && (stream === 'idle' || stream === 'stopped')
  return (
    <main className="page session">
      <header className="session-header">
        <Link to="/" className="brand">
          Clarus
        </Link>
        <StatusPill socket={socketStatus} stream={stream} />
      </header>

      {errors.length > 0 && (
        <div className="errors" role="alert">
          {errors.map((e) => (
            <p key={e.ts + e.message} className={e.recoverable ? 'warn' : 'bad'}>
              {e.recoverable ? '⚠ ' : '✖ '}
              {e.message}
              {e.code != null ? ` (code ${e.code})` : ''}
            </p>
          ))}
        </div>
      )}

      <section className="controls">
        {!micOn ? (
          <button type="button" className="primary" onClick={start} disabled={!canStart}>
            🎙 Start listening
          </button>
        ) : (
          <button type="button" onClick={stop}>
            ■ Stop
          </button>
        )}
        <span className="muted">
          {micOn && stream !== 'listening' ? 'Waiting for the transcription stream…' : ''}
          {micOn && stream === 'listening' ? 'Speak now. Pause to end a turn.' : ''}
        </span>
      </section>

      <section className="card">
        <h2>Live transcript</h2>
        <ConfidenceLegend />
        <Transcript turns={turns} partial={partial} />
      </section>
    </main>
  )
}
