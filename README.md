# Clarus

**A real-time voice agent that measures whether a spoken message was *understood* — not just transcribed.**

Built on **AssemblyAI** Universal-Streaming and LLM Gateway for the AssemblyAI Voice Agent Hackathon (lablab.ai, September 2026).

🔗 **Live demo:** `<DEMO_URL>` · 🎬 **Video:** `<VIDEO_URL>` · 📊 **Slides:** `<SLIDES_URL>`

---

## The problem

Speech-to-text tells you *what was said*. It does not tell you *whether the listener got the message*.

- A transcript can look perfect while the meaning is wrong ("fifteen" heard correctly, but written down as the wrong gate).
- A transcript can be full of low-confidence words while the message still gets through after a quick clarification.

Call centres, telehealth, pharmacy instructions, dispatch and language learning all care about the second question — *did communication succeed?* — and today it is mostly judged by gut feel.

## What Clarus does

A speaker is shown a short message card and relays it by voice:

> *"Meet Priya at Gate 15 on Thursday at 4:30. Code word: BAT."*

Clarus is the listener. In real time it:

1. **Transcribes** the speech with AssemblyAI streaming STT, keeping word-level timings and confidences.
2. **Interprets** the message into structured slots (person, place, day, time, code word).
3. **Detects communication breakdowns** — acoustic, confusable-word, incomplete, and semantic.
4. **Repairs** them with one targeted clarification at a time ("Was that fifteen — one-five — or fifty?").
5. **Reads back** its final understanding and waits for a yes.
6. **Logs every breakdown and repair event** and scores the episode.

Because Clarus secretly knows the card, **every conversation has ground truth**. That lets it measure things most voice agents can't:

- ✅ breakdowns that were **repaired**
- ❌ breakdowns that stayed **unrepaired**
- ⚠️ **false alarms** (it asked when it had already understood)
- 🕳️ **undetected failures** (it was wrong and never noticed)

## The key insight it surfaces

The report page plots **ASR confidence against actual understanding** for every episode, and counts:

- **Heard but misunderstood** — high transcript confidence, wrong meaning.
- **Misheard but communicated** — low-confidence words, message still delivered after repair.

Good transcription and successful communication are related, but they are not the same thing. Clarus makes the gap measurable.

## Breakdown & repair taxonomy

| Breakdown | Signal |
|---|---|
| **Acoustic** | low word confidence on the words carrying the information |
| **Confusable** | known confusable families: 15/50, Tuesday/Thursday, rhyme sets like bat/pat/cat |
| **Incomplete** | a required piece of the message is missing |
| **Semantic** | words heard with high confidence, meaning still wrong (revealed by a correction) |
| **User repair request** | the speaker didn't understand the agent |

Repairs are tagged with who started them — speaker self-repair, system-initiated clarification, or speaker correcting the agent — following the repair categories used in conversation analysis.

The confusable code words are modelled on **Modified Rhyme Test**-style word sets, linking controlled intelligibility testing to natural conversation.

## Metrics

Per turn: speaking rate, pauses, long pauses, filler words, mean/min ASR confidence, low-confidence fraction, repetition, self-repair markers.

Per episode: success, slot accuracy, turns, repair turns, time to success, and the **Communication Effectiveness Index (CEI)**:

```
CEI = 100 × (0.60 · slot accuracy + 0.25 · efficiency + 0.15 · (1 − unrepaired rate))
```

> CEI is **experimental**. Weights were fixed before collecting data and have not been validated. It is always shown next to its components.

Per session: success rate, breakdowns by type, repair rate by type, and the breakdown detector's precision and recall against ground truth.

## Architecture

```
Browser mic (16 kHz PCM) ──WS──► FastAPI ──WS──► AssemblyAI Universal-Streaming
                                   │  (turns, word timings, confidences)
                                   ├── Feature extractor
                                   ├── Interpreter ──► AssemblyAI LLM Gateway (JSON)
                                   ├── Breakdown detector (deterministic rules)
                                   ├── Dialogue manager (clarify / read back / confirm)
                                   ├── Scorer (vs hidden target card)
                                   └── SQLite + JSONL/CSV export
Browser: live confidence-coloured transcript, event timeline, report · agent voice via Web Speech API
```

**Why Realtime STT instead of the all-in-one Voice Agent API?** Clarus needs raw word-level timestamps and confidences to measure pauses, speaking rate and acoustic uncertainty, and it needs the decision to clarify to be made by transparent code, not by the model. The LLM interprets and phrases; the rules decide.

## Results (pilot)

> ⚠️ Fill in from `eval/results/summary.md` after the pilot. Do not estimate.

| | Value |
|---|---|
| Speakers / episodes | `<n speakers> / <n episodes>` |
| Episode success rate | `<…>` |
| Mean CEI | `<…>` |
| Breakdowns flagged (by type) | `<…>` |
| Repair success rate | `<…>` |
| Detector precision / recall | `<…> / <…>` |
| False alarms / undetected | `<…> / <…>` |
| "Heard but misunderstood" episodes | `<…>` |

This is a small pilot, not a validated study.

## Quick start

**Requirements:** Python 3.11+, Node 20+, an AssemblyAI API key, Chrome.

```bash
git clone <REPO_URL> && cd Clarus
cp .env.example .env            # add ASSEMBLYAI_API_KEY

# backend (terminal 1)
python3 -m venv .venv && source .venv/bin/activate
pip install -e "backend[dev]"
cd backend && uvicorn app.main:app --reload --port 8000

# frontend (terminal 2)
cd frontend
npm install
npm run dev                     # open http://localhost:5173 in Chrome, allow microphone
```

Single-port alternative: `cd frontend && npm run build`, then open http://localhost:8000. FastAPI serves the built frontend.

Run tests (no API key or network needed):

```bash
cd backend && pytest
```

Analyse collected sessions:

```bash
python eval/analyze.py          # writes eval/results/summary.md
```

Docker (single service, frontend served by FastAPI):

```bash
docker build -t Clarus . && docker run -p 8000:8000 --env-file .env Clarus
```

## Using it

1. Open the app, tick the consent box, choose **Message Relay** mode.
2. Read the card and say it out loud in your own words.
3. Answer the agent's clarification questions; confirm or correct its read-back.
4. Do several cards, then open **Report** to see your breakdowns, repairs and CEI.
5. Optional: switch on the **noise condition** to see acoustic breakdowns appear live, or try **Free Conversation** mode.

## Where this is useful

- **Contact-centre QA:** flag calls where the customer's request was probably misunderstood, not just calls with poor audio.
- **Healthcare & pharmacy:** confirm that dosage, time and day were actually understood.
- **Speech therapy & language learning:** track how often a speaker's messages need repair, and which kinds.
- **Accessibility:** measure communication success for speakers that ASR handles poorly.
- **Voice-agent developers:** measure false alarms and silent failures, not just word error rate.

## Privacy

Audio is **not stored** by default. Transcripts and derived measurements are stored locally in SQLite. A consent checkbox appears before the first session. Nothing is shared with third parties beyond the AssemblyAI API calls needed for transcription and interpretation.

## Limitations

- Communication success is measured on a **structured relay task**, not open conversation; free-conversation mode has no ground truth.
- ASR errors from accent, noise or recording quality are not automatically communication failures — separating the two is exactly what this project explores, and the current rules are a first attempt.
- Thresholds and CEI weights are hand-set, not learned or validated.
- The pilot is small and English-only; conversational norms vary across languages and cultures.
- **Clarus is not a clinical or validated intelligibility measure.**

## Roadmap

- Human-annotated study comparing Clarus judgments with listener judgments (agreement, κ).
- Short MRT-style intelligibility module per speaker, correlated with conversational CEI.
- Hindi–English and other code-switched message cards.
- Two-human mode: detect breakdowns between two people, not just between a person and an agent.
- Barge-in and hosted TTS voice.

## Background

Clarus grew out of earlier work on the **Modified Rhyme Test**, a controlled measure of speech intelligibility. The question behind it: can the same idea — *was the message received correctly?* — be measured in natural, real-time conversation? The longer-term research proposal is in [`docs/RESEARCH_NOTES.md`](docs/RESEARCH_NOTES.md).

## Built with

AssemblyAI Universal-Streaming · AssemblyAI LLM Gateway · FastAPI · React + Vite + TypeScript · Web Audio API · Web Speech API · SQLite

## Licence

MIT — see [LICENSE](LICENSE).
