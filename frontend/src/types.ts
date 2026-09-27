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

// PROJECT.md §4.1; null = not defined for this turn.
export interface TurnFeatures {
  word_count: number
  duration_s: number
  speaking_rate_wpm: number | null
  pause_count: number
  long_pause_count: number
  mean_pause_ms: number | null
  max_pause_ms: number | null
  filler_count: number
  filler_rate: number
  mean_asr_conf: number | null
  min_asr_conf: number | null
  low_conf_frac: number | null
  slot_span_conf: number | null
  self_repair_markers: string[]
  repetition_overlap: number | null
  is_repetition: boolean
  latency_to_respond_ms: number | null
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
  features: TurnFeatures
}

export interface ErrorEvent {
  type: 'error'
  ts: number
  message: string
  code: number | null
  recoverable: boolean
}

export type ServerEvent = StateEvent | PartialTranscriptEvent | FinalTurnEvent | ErrorEvent
