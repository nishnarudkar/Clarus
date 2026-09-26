import type { StreamState } from '../types'
import type { SocketStatus } from '../ws'

const LABELS: Record<StreamState, string> = {
  idle: 'Ready',
  connecting: 'Connecting…',
  listening: 'Listening',
  reconnecting: 'Reconnecting…',
  stopping: 'Stopping…',
  stopped: 'Stopped',
}

export function StatusPill({ socket, stream }: { socket: SocketStatus; stream: StreamState }) {
  let label = LABELS[stream]
  let tone = stream === 'listening' ? 'live' : stream === 'reconnecting' || stream === 'connecting' ? 'busy' : 'idle'
  if (socket !== 'open') {
    label = socket === 'closed' ? 'Disconnected' : 'Connecting to server…'
    tone = socket === 'closed' ? 'bad' : 'busy'
  }
  return (
    <span className={`pill pill-${tone}`} role="status">
      <span className="dot" aria-hidden="true" />
      {label}
    </span>
  )
}
