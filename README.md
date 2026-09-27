# Clarus

**A real-time voice agent framework that measures whether a spoken message was *understood*, not just transcribed.**

Built on **AssemblyAI** Universal-Streaming and LLM Gateway for the AssemblyAI Voice Agent Hackathon (lablab.ai, September 2026).

**Live Demo:** `<DEMO_URL>` | **Video Presentation:** `<VIDEO_URL>` | **Slide Deck:** `<SLIDES_URL>`

---

## Executive Summary

Speech-to-text (STT) systems measure **Word Error Rate (WER)**—they answer *what was spoken*. However, they fail to answer the critical operational question: *did the listener understand the intended message?*

- A transcript can be 100% accurate verbatim while the downstream meaning is misunderstood (e.g., "fifteen" transcribed correctly, but registered as the wrong flight gate).
- A transcript can contain low-confidence acoustic segments while the core message is successfully delivered and confirmed following a brief clarification.

**Clarus** bridges this gap by introducing a real-time conversational agent designed around a **referential message relay task**. By maintaining hidden target card ground truth, Clarus evaluates communication success deterministically, quantifies breakdown and repair dynamics, and tracks performance metrics that traditional voice agents cannot surface.

---

## The Core Problem: Transcription vs. Comprehension

Traditional voice metrics rely heavily on ASR confidence scores and verbatim transcription accuracy. In safety-critical and high-accuracy domains—such as telehealth, pharmacy instructions, emergency dispatch, contact center compliance, and language learning—verbatim accuracy does not guarantee successful communication.

Clarus formalizes the distinction between two failure modes:

1. **Heard but Misunderstood:** High transcript confidence with incorrect semantic interpretation.
2. **Misheard but Communicated:** Low-confidence acoustic input where the core message was successfully repaired and delivered.

```
                   High Semantic Understanding
                               │
   Misheard but Communicated   │   Successful Communication
   (Low ASR Conf, High Slot)   │   (High ASR Conf, High Slot)
 ───────────────▲──────────────┼───────────────▲───────────────
 low ASR conf   │              │               │   high ASR conf
 ───────────────▼──────────────┼───────────────▼───────────────
   Unrepaired Acoustic Failure │   Heard but Misunderstood
   (Low ASR Conf, Low Slot)    │   (High ASR Conf, Low Slot)
                               │
                   Low Semantic Understanding
```

---

## Key Differentiators & Technical Innovations

1. **Structured Breakdown & Repair Taxonomy:** Grounded in Conversation Analysis (CA) frameworks, categorizing self-initiated repairs versus system-initiated clarifications.
2. **Acoustic vs. Communication Disambiguation:** Disentangles acoustic signal quality (word-level confidence, speaking rate, pause ratios) from semantic task completion.
3. **Objective Ground-Truth Evaluation:** Uses referential task cards so the agent can self-evaluate its breakdown detector using precision, recall, false alarms, and undetected failures.
4. **Modified Rhyme Test (MRT) Integration:** Incorporates phonetically balanced confusable rhyme sets (e.g., *bat/pat/cat/mat/sat/that*) into message cards to connect speech intelligibility research with natural dialogue.
5. **Deterministic Dialogue Control:** Decouples interpretation from control flow—the LLM extracts structured intent, while code-level state machines decide when and how to clarify.

---

## System Architecture

Clarus separates high-throughput audio streaming from structured semantic processing and rule-based dialogue management.

```
                               ┌────────────────────────────────────────────────────────┐
                               │                    FastAPI Backend                     │
                               │                                                        │
┌────────────────────────┐     │  ┌───────────────────────┐   WS   ┌─────────────────┐  │
│  Browser Client        │  WS │  │ AssemblyAIStreamClient│───────►│ AssemblyAI      │  │
│                        │◄────┼─►│                       │◄───────│ Streaming STT   │  │
│ - Mic (16 kHz PCM16)   │     │  └───────────┬───────────┘        └─────────────────┘  │
│ - AudioWorklet         │     │              │ Turn & Word Confidences                 │
│ - Live Transcript UI   │     │              ▼                                         │
│ - SpeechSynthesis TTS  │     │  ┌───────────────────────┐        ┌─────────────────┐  │
└────────────────────────┘     │  │ FeatureExtractor      │        │ AssemblyAI      │  │
                               │  └───────────┬───────────┘        │ LLM Gateway     │  │
                               │              │ Turn Features      │ (JSON Mode)     │  │
                               │              ▼                    └────────▲────────┘  │
                               │  ┌───────────────────────┐                 │           │
                               │  │ Interpreter           │─────────────────┘           │
                               │  └───────────┬───────────┘ Structured Slots            │
                               │              │                                         │
                               │              ▼                                         │
                               │  ┌───────────────────────┐                             │
                               │  │ BreakdownDetector     │ (Deterministic Rules)       │
                               │  └───────────┬───────────┘                             │
                               │              │ Active Breakdowns                       │
                               │              ▼                                         │
                               │  ┌───────────────────────┐        ┌─────────────────┐  │
                               │  │ DialogueManager       │───────►│ Scorer & SQLite │  │
                               │  │ (State Machine)       │        │ Storage         │  │
                               │  └───────────────────────┘        └─────────────────┘  │
                               └────────────────────────────────────────────────────────┘
```

### Why Real-Time Streaming STT over All-in-One Voice Agent APIs?
Clarus requires fine-grained word-level timestamps and confidence metrics to compute speaking rates, pause durations, and acoustic uncertainty. Furthermore, clarification decisions must follow transparent, reproducible logic rather than non-deterministic model behavior. Clarus uses **AssemblyAI Universal-Streaming** for raw speech processing and **AssemblyAI LLM Gateway** for structured JSON extraction.

---

## Episode Flow & State Machine

Every referential relay session operates as an episode governed by a deterministic state machine inside the `DialogueManager`:

```
┌──────────────┐     ┌───────────┐     ┌──────────────┐
│ PRESENT_CARD │────►│ LISTENING │────►│ INTERPRETING │
└──────────────┘     └───────────┘     └──────┬───────┘
                           ▲                  │
                           │     Breakdown    ├──────────────────────┐ No Breakdown
                           └──────────────────┤                      │
                             (Clarification)  ▼                      ▼
                                      ┌──────────────┐        ┌──────────────┐
                                      │  CLARIFYING  │        │   READBACK   │
                                      └──────────────┘        └──────┬───────┘
                                                                     │ User Confirmation
                                                                     ▼
                                                              ┌──────────────┐
                                                              │    SCORED    │
                                                              └──────────────┘
```

1. **PRESENT_CARD:** The user is presented with a target message card containing specific semantic slots.
2. **LISTENING:** Audio frames are captured via `AudioWorklet` (16 kHz PCM16 mono) and streamed to AssemblyAI.
3. **INTERPRETING:** Incoming word timings and confidences are processed by `FeatureExtractor` and structured by `Interpreter`.
4. **CLARIFYING:** If a breakdown is detected (e.g., confusable slot value), the agent asks a single targeted question ("Did you say Gate 15 or Gate 50?").
5. **READBACK:** Once all slots are populated without active breakdowns, the agent reads back its complete understanding for confirmation.
6. **SCORED:** Upon user confirmation, `Scorer` compares the final confirmed interpretation against the hidden target card to evaluate precision, recall, and efficiency.

---

## Breakdown & Repair Taxonomy

Clarus implements a formal taxonomy of communication breakdowns and repair types:

### Breakdown Types

| Type | Trigger Condition / Rule | Description & Example |
|---|---|---|
| **Acoustic** | `slot_span_conf < 0.6` OR evidence word confidence `< 0.5` | Low ASR confidence on key information-bearing tokens (e.g., *"Meet [Priya](conf:0.42) at Gate 15"*). |
| **Confusable** | Matching confusable word family AND slot confidence `< 0.8` | Acoustic or phonetically ambiguous pairs (e.g., 15 vs 50, Tuesday vs Thursday, MRT rhyme set *bat/pat/cat*). |
| **Incomplete** | Required slot `value == null` after turn completion | Omission of required target slots (e.g., user forgot to mention the code word). |
| **Semantic** | High ASR confidence (`≥ 0.8`), followed by subsequent correction | Words heard with high confidence, but meaning was wrong (detected retrospectively via user rejection). |
| **User Repair Request** | `user_act == repair_request` | The speaker explicitly indicates they did not understand the agent ("Sorry, what was that?"). |

### Repair Categories
* **Self-Initiated Self-Repair:** Speaker corrects themselves mid-turn ("Meet at Gate 50—sorry, I mean Gate 15").
* **Other-Initiated by System:** Agent detects ambiguity and prompts for targeted clarification.
* **Other-Initiated by User:** Speaker rejects or corrects the agent's readback summary.

---

## Information Hiding Principle

To preserve measurement integrity and ensure scientific validity:
- **The Interpreter never receives target card values.** It processes only the spoken transcript, acoustic confidence scores, and dialogue history.
- Target values are accessed exclusively by the **Scorer** *after* the episode reaches a terminal state.

---

## Metrics & Evaluation Framework

Clarus logs turn-level features, episode-level performance, and session-level aggregate statistics.

### 1. Per-Turn Acoustic & Prosodic Features
* `speaking_rate_wpm`: Words spoken per minute.
* `pause_count` & `long_pause_count`: Pauses `≥ 250 ms` and `≥ 1000 ms`.
* `mean_asr_conf` & `min_asr_conf`: Word-level ASR confidence statistics.
* `low_conf_frac`: Proportion of turn words with confidence `< 0.6`.
* `slot_span_conf`: Mean confidence of tokens mapped directly to semantic slots.
* `repetition_overlap`: Token Jaccard index relative to preceding turns.

### 2. Communication Effectiveness Index (CEI)
Episode performance is summarized by the experimental **CEI** formula:

$$\text{CEI} = 100 \times \left(0.60 \cdot S + 0.25 \cdot E + 0.15 \cdot (1 - U)\right)$$

Where:
- $S = \text{Slot Accuracy}$ (correct slots / total target slots).
- $E = \text{Efficiency} = \min(1, \frac{2}{\text{Total Turns}})$.
- $U = \text{Unrepaired Rate}$ (unrepaired breakdowns / total flagged breakdowns).

> *Note: CEI is an experimental metric computed with fixed heuristic weights, displayed alongside raw components.*

### 3. Ground-Truth Performance Outcomes
Because ground truth is known, every breakdown event resolves to one of four objective outcomes:

* **REPAIRED:** Breakdown correctly identified and resolved; final slot value is correct.
* **UNREPAIRED:** Breakdown identified, but final slot value remains incorrect.
* **FALSE_ALARM:** System requested clarification on a slot that was already correctly understood.
* **UNDETECTED:** Slot was incorrect in the final state, but no breakdown was ever flagged by the system.

---

## Data Model & Schema

Persistence is handled via SQLite (`data/Clarus.db`). Pydantic v2 schemas mirror all database models:

```
Session (id, created_at, mode, condition, participant_label, consent_given)
  ├── Episode (id, session_id, card_id, status, slot_accuracy, efficiency, cei, metrics_json)
  │     ├── Turn (id, episode_id, idx, speaker, text, words_json, features_json, interpretation_json)
  │     ├── Event (id, episode_id, turn_id, type, slot, repair_initiation, details_json, outcome)
  │     └── Annotation (id, episode_id, annotator, understood_bool, breakdown_types_json, notes)
```

### Event Export Format (JSONL)
```json
{
  "episode_id": "ep_8f9a2b",
  "slot": "place",
  "original_utterance": "meet her at gate fifteen",
  "ai_interpretation": "Gate 50",
  "breakdown_type": "CONFUSABLE",
  "clarification_requested": "Was that Gate 15 (one-five) or Gate 50 (five-zero)?",
  "speaker_correction": "Gate 15, one-five",
  "final_interpretation": "Gate 15",
  "target": "Gate 15",
  "outcome": "REPAIRED",
  "speech_measures": {
    "slot_span_conf": 0.41,
    "speaking_rate_wpm": 168.5,
    "pause_count": 1
  }
}
```

---

## Getting Started

### Prerequisites
- **Python:** 3.11 or higher
- **Node.js:** 20.0 or higher
- **API Key:** AssemblyAI API Key ([Get a key](https://www.assemblyai.com/))
- **Browser:** Google Chrome (recommended for Web Audio & Web Speech API support)

### Installation & Environment Setup

1. **Clone Repository & Environment Configuration:**
   ```bash
   git clone https://github.com/nishnarudkar/Clarus.git
   cd Clarus
   cp .env.example .env
   ```
   Edit `.env` and add your AssemblyAI API key:
   ```env
   ASSEMBLYAI_API_KEY=your_assemblyai_api_key_here
   ```

2. **Backend Setup:**
   ```bash
   python3 -m venv .venv
   # Windows: .venv\Scripts\activate | Unix: source .venv/bin/activate
   pip install -e "backend[dev]"
   cd backend
   uvicorn app.main:app --reload --port 8000
   ```

3. **Frontend Setup:**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   Navigate to `http://localhost:5173` in Google Chrome.

---

## Verification & Testing Suite

Clarus includes a complete offline test suite that mocks AssemblyAI stream responses and LLM Gateway calls, requiring no external network access or API keys.

### Running Backend Unit & Replay Tests
```bash
cd backend
pytest
```
*Executes feature extraction tests, slot normalizer tests, rule engine checks, and synthetic turn sequence replays.*

### Running Frontend Type-Check & Build Verification
```bash
cd frontend
npm run build
```

### Running Evaluation Analytics Harness
```bash
python eval/analyze.py
```
*Parses stored database sessions and exports an analytical evaluation summary to `eval/results/summary.md`.*

---

## Single-Port & Docker Deployment

### Single-Port FastAPI Deployment
FastAPI can serve the static frontend bundle directly on a single port:
```bash
cd frontend && npm run build
cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Access the application at `http://localhost:8000`.

### Docker Deployment
```bash
docker build -t clarus .
docker run -p 8000:8000 --env-file .env clarus
```

---

## Applications & Use Cases

- **Contact Center Quality Assurance:** Identify calls where customer intent was misunderstood despite clear audio, moving beyond simple call duration metrics.
- **Healthcare & Telehealth:** Verify that critical patient instructions (dosage, schedule, medication name) are accurately comprehended.
- **Speech Therapy & Language Learning:** Measure repair frequencies and categorize specific phonological breakdown types over time.
- **Accessibility & Assistive Speech AI:** Benchmark conversational success for speakers with atypical speech patterns or strong accents.
- **Voice Agent Evaluation:** Quantify false clarification rates and silent interpretation failures in conversational systems.

---

## Data Privacy & Governance

- **Audio Non-Retention:** Audio streams are processed transiently in memory and are **not stored** on disk by default.
- **Local Storage:** Transcripts, extracted features, and structured event metrics are persisted locally in SQLite.
- **Consent Control:** A user consent modal is required prior to session initiation.
- **Data Transmission:** External communication is restricted to authorized AssemblyAI STT and LLM Gateway endpoints.
- **Medical Disclaimer:** Clarus is an evaluation research prototype and **is not a clinical diagnostic instrument**.

---

## Future Roadmap

- **Two-Human Mode:** Deploy Clarus as a passive listener evaluating communication breakdowns between two human speakers.
- **Hosted TTS Integration:** Support server-side neural TTS engines with barge-in interruption handling.
- **Multilingual & Code-Switching:** Expand task cards to support Hindi-English and regional code-switched dialogues.
- **MRT Intelligibility Module:** Correlate per-speaker Modified Rhyme Test intelligibility baselines with real-time conversational CEI.

---

## Core Technologies

[AssemblyAI Universal-Streaming](https://www.assemblyai.com/) · [AssemblyAI LLM Gateway](https://www.assemblyai.com/) · FastAPI · Python 3.11 · React 18 · TypeScript · Vite · Web Audio API · Web Speech API · SQLite · Pytest

---

## License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details.
