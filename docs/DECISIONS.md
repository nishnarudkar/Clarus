# Decisions

Newest first. Each entry says what was decided, why, and where it lives in code.

---

## M2: Features and normalisers (2026-09-26)

### Features (`backend/app/features.py`, PROJECT.md §4.1)
- **Pure functions over a final Turn's `words[]`**, computed per `final_turn` and sent to the browser as `features` on each `final_turn`. When a formatted re-send arrives, features are recomputed on it, because the formatted text has the commas that filler detection needs.
- **Thresholds** are in `config.py`: pause ≥ 250 ms, long pause ≥ 1000 ms, low confidence < 0.6, repetition when Jaccard ≥ 0.6. The filler list and the self-repair marker list are in `config.py` too.
- **Undefined values are `None`, never 0.** Examples: `speaking_rate_wpm` for a zero-length turn, `mean_pause_ms` when there are no pauses, `repetition_overlap` for the first turn. The UI shows these as "—".
- **`filler_rate` = fillers / words.** Fillers are included in `word_count` and in the speaking rate.
- **Discourse fillers ("like", "you know")** count only when set off by commas: preceded by a comma (or at the start of the turn) and followed by one. That needs punctuation, so it only works on formatted turns. Known limits:
  - Unformatted turns never count them.
  - Unpunctuated filler uses ("it was like gate 15") are missed.
- **Self-repair markers** ("sorry", "i mean", "no wait", "actually", "rather", "correction") count only mid-turn, i.e. with at least one word before them. A turn-initial "Sorry, what?" is a repair request (M3), not a self-repair. Known false positives: "I'd rather", "actually" used as emphasis.
- **Repetition** compares against the previous *distinct* user turn. The formatted re-send of a turn is compared with the turn before it, not with its own unformatted version. Tokens are compared with fillers dropped and number words converted to digits, because a formatted turn writes "15" where the plain turn says "fifteen" (a test caught this).
- **`slot_span_conf` and `latency_to_respond_ms`** are implemented and unit-tested but stay `None` until M3:
  - `slot_span_conf` needs the interpreter's `evidence_words`.
  - `latency_to_respond_ms` needs the agent's speech-end time. That time is on the browser's wall clock, while word timestamps are on the AssemblyAI stream clock, so M3 must map one to the other.
- **Not yet checked on real audio:** whether the chosen streaming model transcribes disfluencies ("um", "uh") at all. If it doesn't, `filler_count` will read 0. Check on the first live run.

### Normalisers (`backend/app/normalize.py`, PROJECT.md §3.1)
- **Spoken numbers.** `numbers_to_digits` handles teens and tens ("fifteen" vs "fifty"), compounds ("twenty one"), "N hundred [and] M", and digit-by-digit runs ("one five" → 15, "four oh five" → 405).
  - "oh" counts as zero only inside a digit run.
  - "four thirty" stays two numbers ("4 30"), which the time parser then reads as 4:30.
- **person:** letters only, title-cased. A match needs difflib similarity ≥ `person_fuzzy_threshold` (0.85). That threshold keeps the confusable pairs apart: Ravi/Rabi scores 0.75 and Anna/Hannah 0.80.
- **place:** numbers become digits and leading "at/the/to/in/on/by" are dropped ("at gate one five" → "Gate 15"). Matching is case-insensitive equality.
- **day:** a weekday name or abbreviation → a lowercase name. It returns `None` if zero weekdays, or two different ones, are mentioned.
- **time:** returns `NormalizedTime(hour, minute, explicit)`.
  - `explicit` is true when am/pm, noon/midnight, a 24-hour hour (0 or 13–23) or a zero-padded `HH:MM` like "09:15" is given.
  - When nothing says am or pm, times are compared modulo 12, so "4:30" and "half past four" match a 16:30 target, as §3.1 requires. A time that is explicit and wrong ("4:30 am") does not match.
  - Card targets are written zero-padded 24-hour, so they are always explicit.
- **number:** exactly one number in the text, otherwise `None`.
- **code_word:** exact match after lowercasing and stripping everything except letters. Spelled-out letters ("B-A-T") are not handled yet; revisit in M3 if clarifications use spelling.
- **Entry points.** `slot_matches(type, heard, target)` is what the Scorer (M4) will use. `normalize_slot` gives a canonical display value. For ambiguous times it returns the hour as spoken (e.g. "04:30").

### UI
- Each final turn shows a feature row: rate (wpm), pauses (and how many are long), fillers, mean/min confidence, low-confidence share, overlap with the previous turn, and self-repair markers. Notable values get a border plus a "●" marker, so colour is never the only cue.
- Tooltip thresholds come from `/api/config`, which now also serves `pause_min_ms`, `long_pause_min_ms` and `low_conf_threshold`, so the thresholds stay defined only in `config.py`.

---

## M1 — Streaming spine (2026-09-26)

### How the AssemblyAI API was verified

The docs site (`www.assemblyai.com/docs`) was **blocked by the build environment's
network policy**, so I couldn't read it directly. Instead the wire protocol was
checked against AssemblyAI's **official SDK source**, which implements the same
protocol:

- Python SDK `assemblyai` **1.6.1** (PyPI): `assemblyai/streaming/v3/{models,_base,async_client}.py`
- JS SDK `assemblyai` **4.41.5** (npm): `src/types/streaming/index.ts`, `src/services/streaming/service.ts`, `README.md`

**TODO for a human with docs access:** skim the Universal-Streaming docs page and confirm the
items marked *(unverified)* below before the demo.

### Differences from PROJECT.md §2.1

| Topic | PROJECT.md expected | Actual (per SDKs) | What we do |
|---|---|---|---|
| URL | `wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&encoding=pcm_s16le&format_turns=true` | Same | Same, plus `speech_model` |
| Auth | `Authorization: <API_KEY>` header | Same. SDKs also send `AssemblyAI-Version: 2025-05-12` | We send both (`assemblyai_stream.build_headers`) |
| Model selection | "newest model, confirm the param name" | Query param is **`speech_model`**. Values: `universal-streaming-english`, `universal-streaming-multilingual`, `u3-rt-pro`, `universal-3-5-pro`, `universal-3-6`, `universal-3-6-pro`, `whisper-rt` (`u3-pro` is deprecated) | Default **`universal-3-5-pro`** (the model used in the JS SDK's own streaming example), overridable with `STREAMING_SPEECH_MODEL`. *(Unverified: which model the hackathon promotes, and whether `universal-3-6-pro` would be better.)* |
| Turn tuning | `end_of_turn_confidence_threshold`, `min_end_of_turn_silence_when_confident`, `max_turn_silence` | **`min_end_of_turn_silence_when_confident` is deprecated → `min_turn_silence`**. The other two are unchanged. New: `vad_threshold` | We send `min_turn_silence`. All three are **omitted by default** so each model's own defaults apply (the defaults differ per model and couldn't be verified). Set them with the `END_OF_TURN_CONFIDENCE_THRESHOLD`, `MIN_TURN_SILENCE_MS` and `MAX_TURN_SILENCE_MS` env vars |
| Server messages | `Begin`, `Turn`, `Termination` | Same, plus `turn_order` on Turn, and more message types: `SpeechStarted`, `Error` (`error_code`, `error`), `Warning`, `Heartbeat`, `Silence`, `LLMGatewayResponse`, `SpeakerRevision` | We parse Begin, Turn, Termination and Error. Other types are accepted and ignored (`models.AaiOther`). Unknown fields are ignored |
| Turn fields | `transcript, end_of_turn, turn_is_formatted, end_of_turn_confidence, words[text,start,end,confidence,word_is_final]` | Same, plus optional `language_code`, `language_confidence`, `speaker_label` | As expected |
| Shutdown | "terminate message" | Client sends `{"type":"Terminate"}`. The server flushes any final Turn, then sends `Termination` | `AssemblyAIStreamClient.terminate()` waits up to `upstream_terminate_timeout_s` for it |
| Audio frame size | 50–100 ms | Server rejects frames **< 50 ms or > 1000 ms** (error 3007) | The browser sends **100 ms** frames (3200 bytes) |
| Other client messages | — | `ForceEndpoint`, `KeepAlive`, `UpdateConfiguration` exist | Not used yet. `ForceEndpoint` may be useful in M3 |
| Temporary tokens | "for browser-direct streaming" | `GET https://streaming.assemblyai.com/v3/token?expires_in_seconds=N` | Not needed, because audio is relayed through the backend and the key never reaches the browser |
| Fatal close codes | — | e.g. 4001 Not Authorized, 4002 Insufficient Funds, 4003 paid-only, 4102 too many streams, and HTTP 401/403 at handshake | Reported to the UI as non-recoverable, with no retry loop |
| Formatted turns | — | With `format_turns=true`, a turn's end arrives **twice**: first unformatted, then with `turn_is_formatted=true`, both with the same `turn_order` *(unverified for U3 models: they may send only one)* | Both are forwarded as `final_turn`, and the UI upserts by `(stream_id, turn_order)`. **M3 must pick one trigger point.** Plan: act on the formatted turn, with a short timeout fallback to the unformatted one |

### Other M1 decisions

- **Backend relays audio.** Browser → our WS → AssemblyAI. This keeps the API key server-side and lets us see word-level data for features (§2.1).
- **Explicit `start_stream` / `stop_stream` control messages.** These are extra to the §8 protocol. The upstream session opens only when the user starts listening (AssemblyAI bills by session time), and the browser starts sending audio only after `Begin` (`state: listening`), so no audio is lost while connecting. M3's `start_episode` will call the same path.
- **Server events carry `stream_id`** (the AssemblyAI session id), because `turn_order` restarts at 0 after an upstream reconnect.
- **Word confidence bands are computed on the backend** (`band` on each word) from `config.conf_band_high` and `config.conf_band_low` (0.85 / 0.6, §6). The UI legend reads the same values from `/api/config`, so the thresholds live only in `config.py`.
- **Reconnects happen at both hops.**
  - Backend → AssemblyAI: after an unexpected drop, up to `upstream_max_reconnect_attempts` retries with doubling backoff. The attempt counter resets on each `Begin`. Fatal auth or billing errors are not retried.
  - Browser → backend: up to 6 retries with doubling backoff. After reconnecting, the browser re-sends `start_stream` if it was listening.
  - Audio captured while a hop is down is dropped, not queued, because a burst of queued audio could trip AssemblyAI's "audio sent too fast" error (4029).
- **Audio capture.** An AudioWorklet runs at the AudioContext's native rate and box-filter decimates to 16 kHz PCM16. We don't force `AudioContext({sampleRate: 16000})` because that isn't portable across browsers. Chrome's noise suppression and AGC stay on (defaults). Revisit for the P1 noise condition: injected noise is mixed in after capture, so browser noise suppression won't remove it.
- **Colour is never the only signal:** mid-confidence words have a dotted underline, and low-confidence words have a wavy underline plus a "?" marker (CSS-generated, so it isn't copied with the text).
- **Tests stay offline.** `tests/fake_upstream.py` is an in-memory AssemblyAI stand-in. `tests/test_real_websocket.py` runs the real `websockets` client against a server on 127.0.0.1. No API key or internet is needed.
