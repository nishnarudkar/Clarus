# PROJECT.md — Clarus Build Specification

> **Audience:** AI coding agents (and humans) building Clarus.
> **Read this whole file before writing code.** It defines the scope, the architecture, the data model, the build order, and the acceptance criteria. When this file and your own judgment disagree, follow this file. When this file is silent, choose the simplest thing that works and write it down in `docs/DECISIONS.md`.

---

## 0. Hard constraints (read first)

| Constraint | Value |
|---|---|
| Event | AssemblyAI Voice Agent Hackathon (lablab.ai), online |
| **Submission deadline** | **Wed 30 Sep 2026, 8:30 PM IST** — target submitting by **6:00 PM IST** |
| Build window left | ~4 days (starting Sun 27 Sep 2026) |
| Required stack | Must be built on **AssemblyAI** |
| Licence | **MIT** (submissions must be original and MIT-compliant) |
| Required deliverables | Public GitHub repo, live demo URL, video presentation, slide deck, cover image, short + long description |
| Judging criteria | Application of Technology · Presentation · Business Value · Originality |

**Scope rule:** A small system that works end-to-end on stage beats a large system that half-works. Everything in this file is tagged **P0** (must ship), **P1** (ship if P0 is done and stable), or **P2** (only after P1, otherwise mention as future work). Do not start a P1 item while any P0 item is broken.

**Feature freeze:** Tue 29 Sep, 11:59 PM IST. After that: bug fixes, deployment, recording, docs only.

---

## 1. What Clarus is (one paragraph)

Clarus is a real-time voice agent that **measures whether a spoken message was actually understood**, not just transcribed. A speaker is shown a short message card (e.g. *"Meet Priya at Gate 15 on Thursday at 4:30; code word: BAT"*) and relays it by voice. Clarus acts as the listener: it transcribes with AssemblyAI streaming STT, interprets the message, detects **communication breakdowns** (acoustic, confusable-word, semantic, incomplete), runs **clarification and repair**, reads back its final understanding, and logs every breakdown/repair event. Because the system secretly knows the card, every episode has **objective ground truth** for whether communication succeeded. That lets Clarus show, with numbers, that **a good transcript is not the same as successful communication**.

### Why this is different from other entries
Several hackathon entries repair mishearings (Tally, Patchline, Say Less) or check understanding in one domain. Clarus's angle is **measurement**:
1. A **structured taxonomy of breakdown and repair events** grounded in conversation-analysis repair types (self-repair vs other-initiated repair).
2. **Separating acoustic failure from communication failure** — using word-level ASR confidence vs. task-level success.
3. A **built-in ground-truth task** (referential message relay), so the system can score its own breakdown detector (precision/recall, false alarms, undetected failures).
4. A bridge from controlled intelligibility testing (**Modified Rhyme Test**-style confusable pairs embedded in the cards) to natural conversation.
5. An **evaluation harness** (export + human annotation + agreement stats) — the seed of a research study.

Keep this framing in the UI, README, and video. Never claim clinical validity.

---

## 2. Architecture

### 2.1 Decision: Realtime STT path, not the all-in-one Voice Agent API

Clarus needs **word-level timestamps and confidences** to compute pauses, speaking rate, and acoustic-uncertainty signals, and it needs **deterministic control** over when to clarify. So we use:

- **AssemblyAI Universal-Streaming (Realtime STT over WebSocket)** — transcription, turn detection, word timings/confidences.
- **AssemblyAI LLM Gateway** — interpretation (structured JSON output). Keeping the LLM on AssemblyAI strengthens "Application of Technology".
- **Browser `speechSynthesis` (Web Speech API)** — agent voice output. Zero cost, zero latency to set up. (P2: swap for a hosted TTS.)

Record this in `docs/DECISIONS.md` and explain it in the README.

> ⚠️ **Verify API details against current docs before coding** — endpoints, parameter names, model names and message shapes can change. Docs: https://www.assemblyai.com/docs (Realtime/Streaming STT, LLM Gateway, temporary tokens). The values below are the expected shapes; if the docs differ, the docs win — note the difference in `docs/DECISIONS.md`.
>
> - Streaming WS (expected): `wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&encoding=pcm_s16le&format_turns=true` with `Authorization: <API_KEY>` header (server side) or a temporary token (browser side).
> - Server messages (expected): `Begin`, `Turn` (fields incl. `transcript`, `end_of_turn`, `turn_is_formatted`, `end_of_turn_confidence`, `words[]` with `text,start,end,confidence,word_is_final`), `Termination`.
> - Turn-detection tuning params (expected): `end_of_turn_confidence_threshold`, `min_end_of_turn_silence_when_confident`, `max_turn_silence`.
> - Use the newest streaming model the hackathon promotes (Universal-3 Pro / latest) if selectable; confirm the parameter name in docs.
> - LLM Gateway (expected): OpenAI-compatible chat completions endpoint, authenticated with the same AssemblyAI key.

### 2.2 Data flow

```
Browser (mic, 16 kHz PCM16 mono)
   │  WebSocket /ws/session/{id}   (binary audio frames ↑, JSON events ↓)
   ▼
FastAPI backend
   ├── AssemblyAIStreamClient  ── WS ──► AssemblyAI Universal-Streaming
   │        ▲ Turn events (words, timings, confidences)
   ├── FeatureExtractor        (per-turn acoustic/prosodic/lexical features)
   ├── Interpreter             ── HTTPS ─► AssemblyAI LLM Gateway (JSON output)
   ├── BreakdownDetector       (deterministic rules over features + interpretation)
   ├── DialogueManager         (state machine; decides clarify / read back / finish)
   ├── Scorer                  (episode vs. hidden target card → ground truth)
   └── Storage                 (SQLite + JSONL export)
   │
   ▼  JSON events: transcript partials, turn features, events, agent utterances, scores
Browser UI: live transcript (confidence-coloured), event timeline, metrics, report
Agent speech: browser speechSynthesis
```

### 2.3 Half-duplex audio (important)
To avoid the agent's own TTS being transcribed: **while the agent is speaking, the frontend stops sending mic frames** (or sends silence). Resume on `speechSynthesis` `onend`. Show a clear "Agent speaking / Your turn" indicator. Barge-in is P2.

### 2.4 Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, `websockets`, `httpx`, `pydantic` v2, SQLite (stdlib `sqlite3` or SQLModel) |
| Frontend | React + Vite + TypeScript, plain CSS or Tailwind; Recharts for charts |
| Audio capture | `AudioWorklet` → downsample to 16 kHz mono PCM16 → ~50–100 ms frames |
| TTS | `window.speechSynthesis` |
| Tests | `pytest` (backend), minimal Vitest optional |
| Deploy | **Render / Railway / Fly.io** (must support WebSockets). Backend serves the built frontend as static files → one service, one URL. Not Vercel (WebSocket limits). |

---

## 3. The core task: Message Relay episodes (P0)

### 3.1 Task cards
File: `backend/app/tasks/cards.json`. Each card has **slots** with target values. Ship **≥ 20 cards** across 3 difficulty levels.

```json
{
  "id": "card_007",
  "difficulty": "hard",
  "display_text": "Meet Priya at Gate 15 on Thursday at 4:30. Code word: BAT.",
  "slots": {
    "person": "Priya",
    "place": "Gate 15",
    "day": "Thursday",
    "time": "16:30",
    "code_word": "bat"
  },
  "confusable_slots": {
    "place": ["Gate 50"],
    "day": ["Tuesday"],
    "code_word": ["pat", "cat", "mat", "that", "sat"]
  }
}
```

Design rules for cards:
- **Easy:** 3 slots, no confusables. **Medium:** 4 slots, one confusable. **Hard:** 5 slots, 2+ confusables.
- Confusable types to include: teen/ty numbers (15/50, 13/30, 14/40), Tuesday/Thursday, similar names (Ravi/Rabi, Anna/Hannah), and a **code word from an MRT-style rhyme set** (6 words differing in one consonant, e.g. bat/pat/cat/mat/sat/that; sit/fit/hit/bit/kit/wit). Write your **own** rhyme sets; do not copy published test lists.
- Slot types and normalisers: `person` (case-insensitive, fuzzy match ≥ 0.85), `place` (normalise digits), `day` (weekday enum), `time` (normalise to HH:MM, accept "4:30", "half past four", "four thirty pm"), `number`, `code_word` (exact after lowercasing).

### 3.2 Information hiding (critical for validity)
- The **Interpreter never sees the target card.** It only sees transcripts and conversation history.
- The target is used **only** by the Scorer after the episode ends.
- Add a test that asserts the interpreter prompt contains no target slot values.

### 3.3 Episode flow (DialogueManager state machine)

```
PRESENT_CARD → LISTENING → INTERPRETING ─┬─► CLARIFYING → LISTENING → INTERPRETING …
                                         └─► READBACK → LISTENING (confirm?) ─┬─► yes → SCORED
                                                                               └─► no / correction → INTERPRETING
Limits: max 3 clarification rounds, max 2 readback rejections → end as ABANDONED.
```

1. **PRESENT_CARD:** UI shows the card. Speaker clicks "I'm ready" then the card may stay visible (default) or hide (P1 "memory mode" toggle).
2. **LISTENING:** stream audio; wait for `end_of_turn`.
3. **INTERPRETING:** run features + interpreter + breakdown detector.
4. **CLARIFYING:** agent asks **one targeted question about one slot** (e.g. "Was that Gate fifteen — one-five — or fifty?"). The *code* picks which slot; the LLM may phrase it.
5. **READBACK:** when all slots are filled and no active breakdown, agent reads back the full interpretation ("So: meet Priya at Gate 15 on Thursday at 4:30, code word bat. Is that right?").
6. **Confirm:** user yes → episode ends; user no/correction → back to INTERPRETING with the correction.
7. **SCORED:** Scorer compares the **final confirmed interpretation** with the hidden target and emits the episode report.

Latency target: agent starts speaking **≤ 1.5 s** after end of turn (p50).

### 3.4 Free Conversation mode (P1)
Same pipeline, no card, no ground truth. The agent is a general listener that summarises what it understood after each user turn and asks for confirmation when breakdown signals fire. Shows the detector works outside the task. Metrics shown, but no success scoring.

---

## 4. Signals, events and metrics

### 4.1 Per-turn features (`FeatureExtractor`, P0) — pure functions, unit-tested

Computed from the final `Turn` message's `words[]` (ms timestamps):

| Feature | Definition |
|---|---|
| `word_count` | number of words |
| `duration_s` | last word end − first word start |
| `speaking_rate_wpm` | word_count / duration_min |
| `pause_count` | inter-word gaps ≥ 250 ms |
| `long_pause_count` | gaps ≥ 1000 ms |
| `mean_pause_ms`, `max_pause_ms` | over gaps ≥ 250 ms |
| `filler_count`, `filler_rate` | tokens in {um, uh, er, ah, hmm, like*, you know*} (*only as standalone discourse markers — keep a simple list, document limits) |
| `mean_asr_conf`, `min_asr_conf` | over words |
| `low_conf_frac` | fraction of words with confidence < 0.6 |
| `slot_span_conf` | mean confidence of words the interpreter maps to slot values (from interpreter's `evidence_words`) |
| `self_repair_markers` | mid-turn markers: "sorry", "I mean", "no wait", "actually", "rather", "correction" |
| `repetition_overlap` | token Jaccard with the previous user turn (≥ 0.6 ⇒ repetition) |
| `latency_to_respond_ms` | agent speech end → first user word start |

### 4.2 Interpreter (P0)
Call the LLM Gateway with **structured JSON output** (use JSON schema / JSON mode if supported, otherwise strict instructions + pydantic validation + one retry). Low temperature.

Input: conversation history (user transcripts + agent utterances), latest user transcript **with per-word confidences inline** (e.g. `gate(0.92) fifteen(0.41)`), the slot schema (names and types only, never values).

Output schema:
```json
{
  "user_act": "new_info | correction | confirmation_yes | confirmation_no | repetition | repair_request | self_repair | off_task",
  "slots": {
    "person":    {"value": "Priya",  "confidence": 0.9, "evidence_words": ["priya"]},
    "place":     {"value": "Gate 15","confidence": 0.5, "evidence_words": ["gate","fifteen"],
                  "alternatives": ["Gate 50"]},
    "day":       {"value": null, "confidence": 0.0, "evidence_words": []}
  },
  "notes": "short free text, optional"
}
```

The interpreter **does not decide** whether to clarify. It reports; the BreakdownDetector decides.

### 4.3 BreakdownDetector (P0) — deterministic rules, unit-tested

A breakdown is raised per slot or per turn. Types:

| Type | Rule (initial thresholds; keep in `config.py`) |
|---|---|
| `ACOUSTIC` | `slot_span_conf < 0.6` OR any evidence word < 0.5 |
| `CONFUSABLE` | slot has `alternatives` non-empty OR value belongs to a known confusable family (teen/ty, weekday pair, rhyme set) AND slot confidence < 0.8 |
| `INCOMPLETE` | required slot `value == null` after user's turn |
| `SEMANTIC` | high ASR confidence (`slot_span_conf ≥ 0.8`) BUT user later issues `correction` / `confirmation_no` for that slot — i.e. the words were heard, the meaning was wrong. Detected retrospectively. |
| `USER_REPAIR_REQUEST` | `user_act == repair_request` ("sorry, what?") — the user did not understand the agent |

Repair initiation types (conversation-analysis vocabulary):
- `SELF_INITIATED_SELF_REPAIR` — speaker corrects themselves mid-turn.
- `OTHER_INITIATED_BY_SYSTEM` — agent clarification question.
- `OTHER_INITIATED_BY_USER` — user rejects/corrects the agent's readback.

Priority when several slots have breakdowns: CONFUSABLE > ACOUSTIC > INCOMPLETE; clarify one slot per turn.

### 4.4 Event log (P0)
Every breakdown and repair is an `Event` (see §5). Each event is **resolved** at episode end with one outcome:

| Outcome | Meaning |
|---|---|
| `REPAIRED` | breakdown flagged, slot correct at the end |
| `UNREPAIRED` | breakdown flagged, slot still wrong at the end |
| `FALSE_ALARM` | clarification asked, but pre-clarification value was already correct |
| `UNDETECTED` | *(from ground truth)* slot wrong at the end with no breakdown ever flagged on it |

`FALSE_ALARM` and `UNDETECTED` are only computable because of ground truth — this is a key selling point; show them prominently.

### 4.5 Episode metrics (Scorer, P0)

| Metric | Definition |
|---|---|
| `success` | all slots correct in final confirmed interpretation (bool) |
| `slot_accuracy` S | correct slots / total slots |
| `turns_total`, `repair_turns` | user turns; user turns spent on repair |
| `time_to_success_s` | card shown → confirmation |
| `efficiency` E | min(1, 2 / turns_total) (ideal: describe + confirm) |
| `unrepaired_rate` U | UNREPAIRED / flagged breakdowns (0 if none) |
| `asr_mean_conf` | mean word confidence over the episode |
| **`CEI`** (Communication Effectiveness Index, *experimental*) | `100 × (0.60·S + 0.25·E + 0.15·(1 − U))` |

Rules: always show CEI **with its components**; label it "experimental, weights fixed a priori, not validated". Weights live in config.

### 4.6 Session / aggregate metrics (P0 on report page)
- Success rate, mean slot accuracy, mean CEI.
- Breakdown counts by type; repair success rate by type.
- Detector quality vs ground truth: **precision** (flagged slots that were actually at risk ⇒ define "at risk" as pre-clarification value wrong), **recall** (wrong-at-some-point slots that were flagged), false-alarm count, undetected count.
- **"Transcript ≠ understanding" panel:** scatter of `asr_mean_conf` (x) vs `slot_accuracy` before repair (y) per episode, plus two callout counts:
  - *Heard but misunderstood:* episodes with mean conf ≥ 0.85 but ≥1 slot wrong before repair.
  - *Misheard but communicated:* episodes with low-confidence words but success after repair.

---

## 5. Data model

SQLite at `data/Clarus.db` (gitignored). Pydantic models mirror tables.

```
Session(id, created_at, mode['relay'|'free'], condition['clean'|'noise'], participant_label, consent_given)
Episode(id, session_id, card_id, started_at, ended_at, status['success'|'failed'|'abandoned'],
        final_interpretation_json, slot_accuracy, efficiency, cei, metrics_json)
Turn(id, episode_id, idx, speaker['user'|'agent'], text, start_ms, end_ms,
     words_json, features_json, interpretation_json)
Event(id, episode_id, turn_id, type, slot, repair_initiation, details_json, outcome)
Annotation(id, episode_id, annotator, understood[bool], breakdown_types_json, notes, created_at)
```

Structured event record (also the export format, one per event — matches the research proposal):
```json
{
  "episode_id": "...",
  "slot": "place",
  "original_utterance": "meet her at gate fifteen",
  "ai_interpretation": "Gate 50",
  "breakdown_type": "CONFUSABLE",
  "clarification_requested": "Was that fifteen, one-five, or fifty, five-zero?",
  "speaker_correction": "one five, fifteen",
  "final_interpretation": "Gate 15",
  "target": "Gate 15",
  "outcome": "REPAIRED",
  "speech_measures": {"slot_span_conf": 0.41, "speaking_rate_wpm": 172, "pause_count": 1}
}
```

**Privacy:** audio is **not stored** by default. Transcripts/features are stored locally. Show a consent checkbox before the first session. P1: optional "save audio for research" toggle, off by default.

---

## 6. Frontend (P0 unless tagged)

Routes:
1. **`/` Landing** — one-line pitch, "Start a session", consent checkbox, mode select, condition select (clean / noise — P1).
2. **`/session`** — the live screen:
   - Card panel (target message).
   - Status pill: *Listening · Thinking · Agent speaking · Your turn*.
   - **Live transcript** with words coloured by ASR confidence (green ≥ 0.85, amber 0.6–0.85, red < 0.6); partials in grey.
   - Agent's current interpretation as a slot table, each slot with confidence bar and breakdown badge.
   - **Event timeline** (chips: `CONFUSABLE · place · REPAIRED`).
   - Per-turn features mini-panel (wpm, pauses, fillers, mean conf).
   - "Next card" / "End session".
3. **`/report/:sessionId`** — episode table, aggregate metrics (§4.6), breakdown-by-type bar chart, "transcript ≠ understanding" scatter, detector precision/recall, export buttons (JSONL events, CSV episodes).
4. **`/annotate/:sessionId`** (P1) — for each episode: show transcript and final interpretation (not the target first), annotator marks *understood yes/no* and breakdown types; then reveal target.
5. **Noise condition** (P1) — Web Audio: mix a looped noise buffer (generate pink/babble-like noise procedurally, no copyrighted audio) into the mic signal at a chosen SNR (e.g. 10 dB) **before** it is sent to STT. Label clearly in UI and logs. This makes acoustic vs. semantic breakdowns visible live on stage.

Design: clean, research-instrument look; dark and light mode; readable at 1080p for the video. Keep one accent colour.

---

## 7. Evaluation harness (P0 minimum, P1 full)

- **P0:** `eval/analyze.py` reads the DB/exports and prints a markdown summary: success rate, CEI stats, breakdowns by type, repair rates, detector precision/recall, false alarms, undetected, and the two "transcript ≠ understanding" counts. Output written to `eval/results/summary.md`.
- **P1:** Human agreement: Cohen's κ between annotator `understood` labels and system `success`; between two annotators if available. Precision/recall of detector vs human-labelled breakdowns.
- **P0 unit tests:** feature extraction on fixed word arrays; slot normalisers (times, numbers, weekdays); breakdown rules; scorer outcomes (REPAIRED/UNREPAIRED/FALSE_ALARM/UNDETECTED); information-hiding test.
- **P0 offline replay:** `eval/fixtures/*.json` — scripted synthetic `Turn` sequences (no audio) that exercise each breakdown type end-to-end through DialogueManager with a **mocked interpreter**. Runs in CI without API keys.
- **Pilot (Tue 29 Sep):** builder + 2–4 volunteers, each ~8 cards (mix of clean and noise if P1 is done). Put the real numbers in the README. **Never fabricate or round up results.** If sample is small, say so (e.g. "n = 32 episodes, 4 speakers, pilot only").

---

## 8. Repository layout

```
Clarus/
├── PROJECT.md                 # this file
├── README.md
├── LICENSE                    # MIT
├── .env.example
├── Dockerfile                 # builds frontend, serves via FastAPI
├── render.yaml                # or fly.toml / railway.json
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py            # FastAPI app, static files, routes
│   │   ├── config.py          # thresholds, weights, model names (env-overridable)
│   │   ├── ws_session.py      # browser WS endpoint, orchestrates a session
│   │   ├── assemblyai_stream.py
│   │   ├── llm_gateway.py
│   │   ├── features.py
│   │   ├── interpreter.py
│   │   ├── breakdown.py
│   │   ├── dialogue.py        # state machine
│   │   ├── scoring.py
│   │   ├── normalize.py       # slot normalisers
│   │   ├── storage.py
│   │   ├── models.py          # pydantic
│   │   ├── api.py             # REST: sessions, reports, exports, annotations
│   │   └── tasks/cards.json
│   └── tests/
├── frontend/
│   ├── package.json
│   └── src/
│       ├── audio/worklet.ts   # capture + downsample + PCM16
│       ├── audio/noise.ts     # P1 noise mixer
│       ├── ws.ts
│       ├── tts.ts
│       ├── pages/{Landing,Session,Report,Annotate}.tsx
│       └── components/…
├── eval/
│   ├── analyze.py
│   ├── fixtures/
│   └── results/
├── docs/
│   ├── DECISIONS.md
│   ├── ARCHITECTURE.md        # diagram + event taxonomy
│   ├── RESEARCH_NOTES.md      # link to research proposal, limitations
│   └── DEMO_SCRIPT.md
└── data/                      # gitignored
```

### Environment variables (`.env.example`)
```
ASSEMBLYAI_API_KEY=
LLM_GATEWAY_MODEL=            # pick a fast model available on the gateway; confirm name in docs
STREAMING_SAMPLE_RATE=16000
DATABASE_PATH=data/Clarus.db
SAVE_AUDIO=false
```
Never commit keys. The browser must **never** receive the raw API key (audio is relayed through the backend; if you switch to browser-direct streaming, use short-lived temporary tokens only).

### Browser WS protocol (`/ws/session/{id}`)
Client → server: binary PCM16 frames; JSON control `{"type":"start_episode","card_id":…}`, `{"type":"agent_speech_done"}`, `{"type":"end_session"}`.
Server → client (JSON, all with `ts`):
`partial_transcript` · `final_turn` (text, words, features) · `interpretation` · `event` · `agent_say` (text; client speaks it and mutes mic) · `state` · `episode_scored` · `error`.

---

## 9. Build order and acceptance criteria

Work in this order. Each milestone ends with a commit and a short note in `docs/DECISIONS.md` if anything changed.

### M1 — Streaming spine (Sun 27 Sep) · P0
- Mic → AudioWorklet → backend WS → AssemblyAI streaming → partial + final turns back to UI.
- ✅ Speaking into the browser shows live partials and finalised turns with per-word confidence colours; end-of-turn detected; reconnect on WS drop; clean shutdown sends terminate message.

### M2 — Features + normalisers + tests (Sun 27 Sep) · P0
- `features.py`, `normalize.py`, unit tests green.
- ✅ Each final turn in the UI shows wpm, pauses, fillers, mean/min confidence.

### M3 — Interpreter + BreakdownDetector + DialogueManager (Mon 28 Sep) · P0
- LLM Gateway call with validated JSON; rules; state machine; agent speaks via TTS with half-duplex muting.
- ✅ Full episode works by voice: card → describe → at least one clarification on a confusable → readback → confirm. Offline fixtures cover every breakdown type and pass without API keys.

### M4 — Scoring, storage, report (Mon night–Tue 29 Sep) · P0
- Scorer with all four outcomes, CEI, SQLite, `/report`, exports, `eval/analyze.py`.
- ✅ After 5 episodes the report shows aggregates, detector precision/recall, the "transcript ≠ understanding" panel, and exports download.

### M5 — Polish + P1 (Tue 29 Sep) 
- Noise condition, free-conversation mode, annotation page — in that order, only if M1–M4 are solid.
- Run the pilot; write results into README.
- ✅ Feature freeze 11:59 PM IST.

### M6 — Ship (Wed 30 Sep, done by 6:00 PM IST) · P0
- Deploy (single service, HTTPS, WSS). Smoke test on a second device/network.
- Record video (≤ 3–4 min, see `docs/DEMO_SCRIPT.md`), slides (≤ 10), cover image, descriptions.
- ✅ Public repo with MIT licence, README, working demo URL, all lablab.ai fields submitted.

---

## 10. Demo script outline (`docs/DEMO_SCRIPT.md`)

1. **Hook (15 s):** "Speech recognition tells you what was said. It doesn't tell you whether it was understood."
2. **Clean run (45 s):** easy card, smooth success, show green transcript and CEI.
3. **Confusable run (45 s):** "Gate fifteen" heard as "fifty" → CONFUSABLE flagged → targeted clarification → REPAIRED.
4. **Noise run (30 s, P1):** noise on → red words → ACOUSTIC breakdowns → repair.
5. **The key insight (30 s):** report page — "heard but misunderstood" cases, detector precision/recall, false alarms and undetected failures, possible only because of ground truth.
6. **Business value (20 s):** call-centre QA, telehealth & pharmacy instructions, speech-therapy practice, language learning, accessibility.
7. **Research roadmap (15 s):** human-annotated study, MRT comparison, multilingual/code-switching.

---

## 11. Quality bar and rules for agents

- **Deterministic core:** decisions (clarify, which slot, when to read back, scoring) live in code, not in the LLM. The LLM interprets and phrases.
- **No hidden magic numbers:** every threshold/weight in `config.py` with a comment.
- **Fail visibly:** if STT or LLM fails, show an error state in the UI and log it; never silently invent an interpretation.
- **Honesty:** no fabricated metrics, no fake demo data presented as real. Seeded demo sessions (if any) must be labelled "sample" in the UI.
- **Types and validation:** pydantic for every message crossing a boundary.
- **Tests must pass without network/API keys** (mock AssemblyAI and the LLM).
- **Keep it small:** no auth system, no user accounts, no microservices, no vector DB, no Docker Compose zoo.
- **Accessibility:** keyboard-operable controls, colour is never the only signal (add icons/labels to confidence colours).
- **Copyright:** no copyrighted audio, word lists, logos or images. Use generated noise and your own rhyme sets.

---

## 12. P2 / future work (do not build unless everything else is done — list in README)

- Barge-in (user interrupts agent).
- Hosted TTS voice.
- Mini MRT-style intelligibility module (speaker says 10 rhyme-set words; score recognition) and correlation with CEI per speaker.
- Multilingual / code-switched (Hindi–English) cards.
- Two-human mode (Clarus listens to two people and logs breakdowns between them).
- Formal study: IRB/ethics approval, larger participant pool, pre-registered analysis.

---

## 13. Definition of done

- [ ] Live URL works on Chrome desktop over HTTPS with mic permission.
- [ ] A full relay episode with at least one repair can be completed by a first-time user without help.
- [ ] Report page shows real pilot data, detector precision/recall, and the transcript-vs-understanding panel.
- [ ] `pytest` green offline; `eval/analyze.py` produces `summary.md`.
- [ ] README complete with real results and limitations; MIT LICENSE present.
- [ ] Video, slides, cover image, descriptions submitted on lablab.ai before **30 Sep 2026, 8:30 PM IST**.
