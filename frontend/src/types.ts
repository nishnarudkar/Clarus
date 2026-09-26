// Mirrors backend/app/models.py (server → browser events).

export type ConfBand = 'high' | 'mid' | 'low'
export type StreamState = 'idle' | 'connecting' | 'listening' | 'reconnecting' | 'stopping' | 'stopped'

export interface Word {
  text: string
  start: number
  end: number
  confidence: number
  band: ConfBand
  final: boolean
}

export interface StateEvent {
  type: 'state'
  ts: number
  state: StreamState
  detail: string | null
}

export interface PartialTranscriptEvent {
  type: 'partial_transcript'
  ts: number
  stream_id: string
  turn_order: number
  text: string
  words: Word[]
}

export interface FinalTurnEvent {
  type: 'final_turn'
  ts: number
  stream_id: string
  turn_order: number
  text: string
  formatted: boolean
  end_of_turn_confidence: number
  words: Word[]
}

export interface ErrorEvent {
  type: 'error'
  ts: number
  message: string
  code: number | null
  recoverable: boolean
}

export type ServerEvent = StateEvent | PartialTranscriptEvent | FinalTurnEvent | ErrorEvent
