# CLAUDE.md — Clarus

Clarus is a real-time voice agent (AssemblyAI Voice Agent Hackathon) that measures whether a
spoken message was *understood*, not just transcribed. Deadline: Wed 30 Sep 2026, 8:30 PM IST.

## Source of truth
- `Project.md` (the build spec, called PROJECT.md inside it) is the source of truth. Read the
  relevant section before each task: §3 episode flow, §4 signals/metrics, §5 data model,
  §8 layout + WS protocol, §9 milestones, §11 rules.
- If the spec is silent, do the simplest thing that works and record it in `docs/DECISIONS.md`.
- Respect priorities: no P1 work while any P0 item is broken. Feature freeze Tue 29 Sep 23:59 IST.

## Stack
- Backend: Python 3.11+, FastAPI, `websockets`, `httpx`, pydantic v2, SQLite.
- AssemblyAI Universal-Streaming (STT) + AssemblyAI LLM Gateway (interpretation, JSON output).
  Verify endpoints/params against current AssemblyAI docs; note differences in DECISIONS.md.
- Frontend: React + Vite + TypeScript, Recharts, AudioWorklet (16 kHz PCM16), `speechSynthesis` TTS.
- Tests: pytest. Deploy: single service (FastAPI serves built frontend) on Render/Railway/Fly.

## Layout (repo root)
- `backend/app/` — `main.py`, `config.py`, `ws_session.py`, `assemblyai_stream.py`,
  `llm_gateway.py`, `features.py`, `interpreter.py`, `breakdown.py`, `dialogue.py`,
  `scoring.py`, `normalize.py`, `storage.py`, `models.py`, `api.py`, `tasks/cards.json`
- `backend/tests/` — unit + offline replay tests
- `frontend/src/` — `audio/`, `ws.ts`, `tts.ts`, `pages/`, `components/`
- `eval/` — `analyze.py`, `fixtures/*.json`, `results/`
- `docs/` — `DECISIONS.md`, `ARCHITECTURE.md`, `RESEARCH_NOTES.md`, `DEMO_SCRIPT.md`
- `data/` — SQLite DB, gitignored

## Run
```bash
cp .env.example .env                                  # add ASSEMBLYAI_API_KEY
python3 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev             # http://localhost:5173 (proxies /ws, /api)
cd backend && ../.venv/bin/pytest                     # offline; no network / keys needed
cd frontend && npx tsc -b && npx oxlint && npm run build
```
AssemblyAI API details and deviations from Project.md: `docs/DECISIONS.md`.

## Rules
- Decisions live in code, not the LLM: clarify or not, which slot, readback, scoring.
  The LLM only interprets and phrases. The Interpreter never sees the target card.
- Every threshold and weight lives in `backend/app/config.py` with a comment. No magic numbers.
- Tests must pass offline: mock AssemblyAI and the LLM Gateway; no network, no API keys.
- Never commit `.env` or any key. The browser never receives the raw API key.
- No fabricated metrics or fake data presented as real. Report real pilot numbers only, with n;
  label any seeded demo data "sample". Never claim clinical validity.
- Fail visibly: on STT/LLM errors show an error state; never invent an interpretation.
- Pydantic for every message crossing a boundary. Keep it small (no auth, no microservices).

## After each milestone (M1–M6, see Project.md §9)
1. Run `pytest` (and frontend checks if present); everything green.
2. Update `docs/DECISIONS.md` with what changed or was decided.
3. Commit with a clear message.
