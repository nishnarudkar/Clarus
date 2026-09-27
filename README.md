# Clarus

**A real-time voice agent framework that evaluates spoken message comprehension beyond standard transcription.**

Built on **AssemblyAI** Universal-Streaming and LLM Gateway for the AssemblyAI Voice Agent Hackathon (lablab.ai, September 2026).

**Live Demo:** `<DEMO_URL>` | **Video:** `<VIDEO_URL>` | **Slides:** `<SLIDES_URL>`

---

## Overview & Problem Statement

Speech-to-text systems evaluate *what was spoken*, but do not verify *whether the listener understood the intended message*.

* A transcript can be 100% accurate verbatim while the semantic meaning is misunderstood (e.g., "fifteen" transcribed correctly, but mapped to the wrong destination code).
* A transcript can contain low-confidence acoustic segments while the overall core message is successfully conveyed following a brief clarification.

Critical domains including healthcare, emergency dispatch, contact centres, and language instruction require verification of successful communication rather than simple transcription accuracy. Clarus provides a framework to quantify and bridge this gap.

## How Clarus Works

During a session, a speaker reads and relays a designated message card by voice:

> *"Meet Priya at Gate 15 on Thursday at 4:30. Code word: BAT."*

Serving as the intelligent listener, Clarus performs real-time processing:

1. **Transcription:** Transcribes incoming audio via AssemblyAI streaming STT, maintaining word-level timestamps and confidence metrics.
2. **Interpretation:** Maps the spoken message into structured semantic slots (person, location, day, time, code word).
3. **Breakdown Detection:** Identifies communication breakdowns categorized by type (acoustic, confusable-word, incomplete, and semantic).
4. **Targeted Repair:** Initiates single-point clarification requests when needed ("Was that fifteen — one-five — or fifty?").
5. **Readback Verification:** Synthesizes its final structured understanding for speaker confirmation.
6. **Logging & Scoring:** Records all breakdown and repair events to generate an episode performance evaluation.

Because Clarus operates with hidden target card ground truth, it evaluates metrics inaccessible to standard voice agents:

* **Repaired Breakdowns:** Communication failures that were successfully resolved.
* **Unrepaired Breakdowns:** Communication failures that remained uncorrected.
* **False Alarms:** Unnecessary clarification requests when the message was already correctly understood.
* **Undetected Failures:** Incorrect interpretations that occurred without detection.

## Key Insights & Metrics

The analytics dashboard correlates **ASR confidence against semantic understanding** across episodes, highlighting:

* **Heard but Misunderstood:** High transcript confidence with incorrect semantic interpretation.
* **Misheard but Communicated:** Low-confidence acoustic input where the core message was successfully repaired and delivered.

Clarus formalizes the distinction between verbatim transcription quality and communication success.

## Breakdown & Repair Taxonomy

| Breakdown Type | Detection Signal |
|---|---|
| **Acoustic** | Low ASR confidence on key information-bearing words |
| **Confusable** | Matching known confusable word families (e.g., 15/50, Tuesday/Thursday, MRT rhyme sets like bat/pat/cat) |
| **Incomplete** | Omission of required target message slots |
| **Semantic** | High-confidence transcription yielding incorrect slot values (detected via speaker correction) |
| **User Repair Request** | Explicit speaker indication that the agent's understanding is incorrect |

Repairs are categorized by origin — speaker self-repair, system-initiated clarification, or speaker correction — adhering to established conversation analysis standards. Confusable code words are derived from **Modified Rhyme Test (MRT)** protocols to link controlled intelligibility testing with conversational interaction.

## Metrics & Scoring

* **Per Turn:** Speaking rate, pause duration, long pauses, filler word frequency, mean/min ASR confidence, low-confidence token ratio, repetition, and self-repair markers.
* **Per Episode:** Completion success rate, slot accuracy, turn counts, repair turn ratio, latency to completion, and the **Communication Effectiveness Index (CEI)**:

```
CEI = 100 × (0.60 · slot accuracy + 0.25 · efficiency + 0.15 · (1 − unrepaired rate))
```

> **Note:** CEI is an experimental metric with fixed initial weighting, displayed alongside its constituent components.

* **Per Session:** Aggregate success rate, breakdown frequency by type, repair efficiency, and detector precision/recall relative to ground truth.

## System Architecture

```
Browser Mic (16 kHz PCM) ──WS──► FastAPI ──WS──► AssemblyAI Universal-Streaming
                                   │  (turns, word timings, confidences)
                                   ├── Feature Extractor
                                   ├── Interpreter ──► AssemblyAI LLM Gateway (JSON)
                                   ├── Breakdown Detector (Rule Engine)
                                   ├── Dialogue Manager (Clarify / Read Back / Confirm)
                                   ├── Scorer (vs Hidden Target Card)
                                   └── SQLite + JSONL/CSV Export
Browser UI: Real-time confidence-coded transcript, timeline event log, reports & Web Speech API TTS
```

**Architectural Rationale:** Clarus utilizes streaming STT rather than an end-to-end voice agent API to access granular word-level timestamps and confidence scores. This data powers pause detection, rate calculation, and acoustic uncertainty scoring, while ensuring repair logic is driven by explicit, deterministic rules rather than opaque model behavior.

## Results (Pilot Study)

> **Note:** To be populated from `eval/results/summary.md` following pilot execution.

| Metric | Value |
|---|---|
| Speakers / Episodes | `<n speakers> / <n episodes>` |
| Episode Success Rate | `<…>` |
| Mean CEI | `<…>` |
| Breakdown Counts (by type) | `<…>` |
| Repair Success Rate | `<…>` |
| Detector Precision / Recall | `<…> / <…>` |
| False Alarms / Undetected | `<…> / <…>` |
| "Heard but Misunderstood" Count | `<…>` |

## Quick Start

**Prerequisites:** Python 3.11+, Node 20+, AssemblyAI API Key, Google Chrome.

```bash
git clone <REPO_URL> && cd Clarus
cp .env.example .env            # Configure ASSEMBLYAI_API_KEY

# Backend Setup (Terminal 1)
python3 -m venv .venv && source .venv/bin/activate
pip install -e "backend[dev]"
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend Setup (Terminal 2)
cd frontend
npm install
npm run dev                     # Open http://localhost:5173 in Chrome
```

*Single-port deployment:* Run `cd frontend && npm run build`, then access `http://localhost:8000` (FastAPI serves the static frontend).

**Execution of Offline Test Suite:**
```bash
cd backend && pytest
```

**Evaluation & Analytics:**
```bash
python eval/analyze.py          # Generates eval/results/summary.md
```

**Containerized Deployment:**
```bash
docker build -t Clarus . && docker run -p 8000:8000 --env-file .env Clarus
```

## User Workflow

1. Launch application, accept consent terms, and select **Message Relay** mode.
2. Review the displayed card and articulate the message naturally.
3. Respond to any agent clarification queries and verify or correct the read-back output.
4. Complete multiple cards to generate performance reports detailing breakdowns, repairs, and CEI scores.
5. (Optional) Toggle the **Noise Condition** simulation to test live acoustic breakdown detection, or explore **Free Conversation** mode.

## Applications & Use Cases

* **Contact Centre Quality Assurance:** Identify calls where customer intent was misunderstood beyond transcription quality.
* **Healthcare & Pharmacy:** Verify patient comprehension of dosage, frequency, and administration instructions.
* **Speech Therapy & Language Learning:** Quantify repair frequency and breakdown patterns across speakers.
* **Accessibility Assessment:** Measure speech communication success across diverse acoustic and speech characteristics.
* **Voice Agent Evaluation:** Benchmark false positive clarifications and silent failures in conversational AI.

## Data Governance & Privacy

Audio streams are processed transiently and are **not stored** by default. Transcripts and session metrics are stored locally in SQLite. User consent is gathered prior to session initialization. External data transmission is strictly limited to required AssemblyAI API endpoints.

## Limitations & Scope

* Communication evaluation is benchmarked on **structured relay tasks**; free conversation mode lacks ground truth target cards.
* ASR variances due to accent or ambient noise do not inherently constitute communication failures; Clarus distinguishes between transcription noise and semantic intent delivery.
* Scoring weights and threshold parameters are heuristically set and require empirical validation.
* Clarus is designed as an evaluation prototype and **is not a clinical diagnostic tool**.

## Project Background

Clarus builds upon research in speech intelligibility testing using the **Modified Rhyme Test (MRT)**. The project extends these principles to investigate whether message delivery and comprehension can be quantified deterministically during natural spoken interaction.

## Core Technologies

AssemblyAI Universal-Streaming · AssemblyAI LLM Gateway · FastAPI · React · TypeScript · Vite · Web Audio API · Web Speech API · SQLite

## License

MIT License — see [LICENSE](LICENSE) for details.

