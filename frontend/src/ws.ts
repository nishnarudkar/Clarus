import type { ServerEvent } from './types'

export type SocketStatus = 'connecting' | 'open' | 'reconnecting' | 'closed'

// Browser ↔ backend reconnect policy.
const MAX_RECONNECT_ATTEMPTS = 6
const BASE_BACKOFF_MS = 500
// Drop audio rather than queue it if the socket is backed up (≈ 2 s of PCM16 @ 16 kHz).
const MAX_BUFFERED_BYTES = 64_000

/** `/ws/session/{id}` client: JSON events in, PCM16 frames + control out, auto-reconnect. */
export class SessionSocket {
  private ws: WebSocket | null = null
  private attempts = 0
  private wantStream = false
  private closedByUser = false
  private readonly sessionId: string
  private readonly onEvent: (e: ServerEvent) => void
  private readonly onStatus: (s: SocketStatus) => void

  constructor(sessionId: string, onEvent: (e: ServerEvent) => void, onStatus: (s: SocketStatus) => void) {
    this.sessionId = sessionId
    this.onEvent = onEvent
    this.onStatus = onStatus
  }

  connect(): void {
    this.closedByUser = false
    this.open()
  }

  private open(): void {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/session/${this.sessionId}`)
    ws.binaryType = 'arraybuffer'
    this.ws = ws
    this.onStatus(this.attempts === 0 ? 'connecting' : 'reconnecting')

    ws.onopen = () => {
      this.attempts = 0
      this.onStatus('open')
      // After a reconnect, resume streaming where the user left off.
      if (this.wantStream) this.sendControl({ type: 'start_stream' })
    }
    ws.onmessage = (msg) => {
      if (typeof msg.data !== 'string') return
      try {
        this.onEvent(JSON.parse(msg.data) as ServerEvent)
      } catch {
        console.warn('Unparseable server message', msg.data)
      }
    }
    ws.onclose = () => {
      if (this.ws !== ws) return
      this.ws = null
      if (this.closedByUser) {
        this.onStatus('closed')
        return
      }
      if (this.attempts >= MAX_RECONNECT_ATTEMPTS) {
        this.onStatus('closed')
        this.onEvent({
          type: 'error',
          ts: Date.now(),
          message: 'Lost connection to the Clarus server.',
          code: null,
          recoverable: false,
        })
        return
      }
      const delay = BASE_BACKOFF_MS * 2 ** this.attempts++
      this.onStatus('reconnecting')
      setTimeout(() => !this.closedByUser && this.open(), delay)
    }
  }

  startStream(): void {
    this.wantStream = true
    this.sendControl({ type: 'start_stream' })
  }

  stopStream(): void {
    this.wantStream = false
    this.sendControl({ type: 'stop_stream' })
  }

  sendAudio(pcm16: ArrayBuffer): void {
    const ws = this.ws
    if (ws && ws.readyState === WebSocket.OPEN && ws.bufferedAmount < MAX_BUFFERED_BYTES) ws.send(pcm16)
  }

  close(): void {
    this.closedByUser = true
    this.wantStream = false
    this.sendControl({ type: 'end_session' })
    this.ws?.close()
  }

  private sendControl(msg: { type: string }): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg))
  }
}
