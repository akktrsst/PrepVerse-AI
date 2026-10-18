# PrepVerse AI

Interview prep for Data Science, ML, GenAI and AI Agent roles: **Learn** (curated, AI-summarised resources), **Discuss** (voice or text AI tutor), **Notes** (highlights and AI study notes), and **Mock Interview** (get tested). Infrastructure is serverless on GCP: Vertex AI Gemini, Cloud Run, Firestore, and Firebase Auth.

## Status

| Area | State |
|---|---|
| Gemini wrapper with tier routing (`lite` / `std` / `pro`) | ✅ `backend/app/llm.py` |
| Mock Interview engine (Planner → Interviewer → Evaluator → Coach) | ✅ `backend/app/interview/` |
| Interview REST API, Firebase auth, daily usage limits | ✅ `backend/app/routers/interview.py` |
| Seed question bank (DS, GenAI/LLMs, AI Agents) | ✅ 18 reviewed questions in `backend/seed/questions/` |
| Learn Hub: daily ingestion of YouTube, arXiv, blogs (RSS), GitHub, Hacker News → summaries, ranking, embeddings | ✅ `backend/ingest/`, `backend/app/routers/learn.py` |
| Discuss: grounded tutor chat (SSE streaming, citations, personas) + browser voice mode | ✅ `backend/app/discuss/`, `web/discuss/` |
| Notes: highlights, AI session notes, Markdown export | ✅ `backend/app/routers/notes.py`, `web/notes/` |
| Firebase Google sign-in UI | ✅ `web/assets/auth.js` (needs Firebase web config) |
| Deploy: Cloud Run API + ingest job + Firebase Hosting | ✅ `infra/deploy.sh`, `firebase.json` |
| Web UI: Home, Mock Interview, Dashboard, Pricing (USD) | ✅ `backend/web/` (served by FastAPI at `/`) |
| Payments (plan limits are display-only), X/Twitter source, Gemini Live voice | ⏳ next |

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # set GCP_PROJECT; AUTH_DISABLED=true for local dev

pytest                        # runs offline with a fake LLM, no GCP needed

gcloud auth application-default login
python -m scripts.smoke_llm   # one real call per model tier + an embedding
python -m ingest.run --topic rag --dry-run   # preview Learn Hub results for one topic
python -m ingest.run                         # fill the Learn Hub (≈20 min, ≈$1–2 first run)
uvicorn app.main:app --reload # UI: http://localhost:8000  ·  API docs: /api/docs
```

Use `STORE_BACKEND=file` locally so the ingest job and the API server share data (`backend/.data/store.json`).

## Learn Hub, Discuss and Notes

- **Ingestion** (`backend/ingest/`): each topic in `seed/topics.json` is fetched from YouTube, arXiv, GitHub and Hacker News. Blog feeds in `seed/feeds.json` are fetched once and matched to topics by keyword. Then:
  1. New items are deduped against the store.
  2. Flash-Lite summarises and rates them in batches of 10. A blog or HN thread needs relevance ≥ 4; other types need ≥ 3.
  3. Items are ranked, and the top 3 videos per topic get a deeper Flash summary with chapters. Timestamps past the video's end are dropped.
  4. Items are embedded at 768 dimensions and saved per topic.

  Only summaries and links are stored; videos play through the official YouTube player. Production runs it daily as a Cloud Run Job.
- **Discuss** (`POST /api/discuss/sessions/{id}/messages`, SSE):
  - Each message retrieves the pinned resource plus the top 5 by vector search, and streams a Flash answer that cites them as `[n]`.
  - Older history is folded into a rolling Flash-Lite summary.
  - Voice mode uses the browser's speech recognition and speech synthesis, which are free. It speaks sentence by sentence while the answer streams, and supports barge-in and hands-free mode.
- **Notes**: select text in any summary or AI answer to save a coloured highlight. "End & make notes" turns a discussion into takeaways, definitions and review questions. `GET /api/notes/export.md` exports everything as Markdown.

## Mock interview API

| Method | Path | What it does | LLM calls charged |
|---|---|---|---|
| POST | `/api/interview/start` | Body: `{role, level, company_type, modules, num_questions, resume?, job_description?}`. Plans the interview and returns question 1. | 1 |
| POST | `/api/interview/{id}/answer` | Body: `{answer}`. Returns a follow-up (max 2 per question) or the next question. | 1 |
| POST | `/api/interview/{id}/finish` | Evaluates all answered questions in parallel and returns the report. You can call it early. | answered + 1 |
| GET | `/api/interview/{id}` | Current turn, plus the report once the interview is completed. | 0 |

Key points and evaluations stay on the server until the report is generated, so the client never sees the grading guide mid-interview.

### Cost shape per interview (6 questions)

- **Plan:** 1 Flash call. It's a Pro call only when a resume or JD is attached.
- **Follow-up decisions:** 1 Flash call per answer, with thinking off.
- **Evaluation:** 1 Pro call per answered question, run at `finish`, never on every turn.
- **Coach report:** 1 Flash call. The overall score and weak topics are computed in code, so the Watch recommender can depend on them.

## Layout

```
backend/
  app/
    llm.py            Gemini wrapper (Vertex AI billing, tiers, structured output, usage logs)
    config.py         env settings
    store.py          MemoryStore (dev/tests) | FirestoreStore (prod)
    deps.py           Firebase auth, per-user daily LLM limit
    prompts/          versioned prompt files ($placeholders)
    interview/        planner, interviewer, evaluator, coach, engine, rubrics, seed
    routers/          HTTP endpoints
    learn/ discuss/ notes/   Learn Hub, tutor chat and notebook
  ingest/             daily resource ingestion (sources/, pipeline, ranking)
  seed/               questions/ (interview bank), topics.json, feeds.json
  scripts/smoke_llm.py
  tests/
infra/deploy.sh       enable APIs, service account, Cloud Run deploy
```

## Notes

- Embeddings are requested at 768 dimensions. Firestore vector search caps embeddings at 2048 dimensions, and `gemini-embedding-001` defaults to 3072.
- Resume, JD, and answer text is wrapped in `<untrusted_*>` tags, and the system prompts tell the model to treat it as data only.
- Confirm the model IDs in Vertex AI → Model Garden for your project before the first real run.

## Deploy (Firebase Hosting + Cloud Run)

Everything runs in one GCP project, the one with billing and Vertex AI:

- **Firebase Hosting** serves the pages from `backend/web/` on `https://<project>.web.app`, with a global CDN and HTTPS.
- **Cloud Run** runs the FastAPI backend. Hosting forwards every `/api/**` request to it (`firebase.json`), so the browser only ever talks to one domain.

One-time setup:

1. **Add Firebase to the project.** In the Firebase console, click *Add project* and pick the existing GCP project `project-07b0787a-…`.
2. **Enable sign-in.** Turn on Google sign-in under *Authentication*. Then add a **Web app** under *Project settings* and note its `apiKey` and `appId`.
3. **Install the Firebase CLI:** `npm i -g firebase-tools`, then `firebase login`. Cloud Shell has it preinstalled.
4. **Deploy:**
   `PROJECT=project-07b0787a-9825-4af5-af6 FIREBASE_WEB_API_KEY=… FIREBASE_APP_ID=… YOUTUBE_API_KEY=… GITHUB_TOKEN=… ./infra/deploy.sh`

Limits to know:

- **60-second timeout:** requests that go through Hosting are cut off after 60 s. Discuss replies (about 3–10 s) and interview reports (about 15–40 s) fit within that.
- **Streaming may be buffered:** if Discuss answers arrive all at once instead of word by word, Hosting is buffering the stream. The fix is to call Cloud Run directly for that one endpoint.
- **Local sign-in:** to use Google sign-in locally, set `FIREBASE_PROJECT_ID` and the `FIREBASE_WEB_*` values in `backend/.env` to the new Web app's config.
