# RAG Document Assistant

A secure, full-stack Retrieval-Augmented Generation application for private document chat. Users upload PDF files; the backend indexes them asynchronously; and chat answers are grounded exclusively in the retrieved content, with backend-controlled citations.

---

**Five Docker services:** Postgres + pgvector, Redis, backend API, indexing worker, frontend (nginx).

---

## Features

### Document Pipeline

| Step       | Detail                                                                |
| ---------- | --------------------------------------------------------------------- |
| Upload     | Private storage, backend-generated paths, extension & size validation |
| Parsing    | PDF (pdfplumber)                                                      |
| Chunking   | Structure-aware recursive splitting with semantic grouping            |
| Embeddings | Sentence Transformers `all-MiniLM-L6-v2` (384-dim), batched           |
| Storage    | PostgreSQL + pgvector with tenant-scoped rows                         |
| Queue      | Redis-backed, separate worker process, failure handling               |

### Retrieval System

- **Hybrid search** — vector similarity (cosine) + keyword (PostgreSQL with weighted fields), configurable weight ratio
- **Reranking** — scores merged and reranked before thresholding
- **Score threshold** — configurable minimum score; low-confidence retrievals trigger re-retrieval or soft-confidence fallback
- **Section detection** — automatically resolves section/chapter references in questions
- **Multi-part question handling** — subquery derivation, per-part evidence guide, and targeted chunk prioritization

### Chat Pipeline

1. User message stored, session created or loaded
2. Retrieval runs against indexed documents (tenant-scoped)
3. Grounded prompt built from retrieved chunks only
4. LLM call via OpenRouter with primary + fallback model chain
5. **Self-correction loop** — faithfulness check validates every number, date, and region against cited sources; unsupported claims trigger re-generation or segment removal
6. Backend-controlled citations applied to each claim
7. Answer, sources, and optional debug metadata returned

### Citation System

- Citations are derived from retrieved chunk metadata, not from model output
- Backend splits the answer into claim segments, matches each to supporting sources
- Faithfulness verification: every numeric value must appear in the cited source text
- Self-correction: the LLM is called again to fix unsupported claims before fallback

### Developer Mode

A dedicated developer dashboard for monitoring RAG quality in production:

- **Retrieval diagnostics** — per-query logs with original question, rewritten query, chunk count, score threshold, latency
- **Audit trail** — chat lifecycle events, indexing operations, model fallbacks, retrieval failures
- **Human feedback** — positive/negative ratings on assistant answers with comments
- **Automated evaluation suite** — run predefined test cases against the full RAG pipeline (retrieval + generation); tracks pass/fail rates over time
- **System metrics** — indexed documents, chunk count, low-confidence retrievals, failed indexing jobs, feedback split, average retrieval latency
- **Debug snapshots** — per-answer debug panel showing original question, retrieval query, threshold, latency, and the exact chunks used (with scores)

### Security

- **JWT verification** — Supabase JWKS with server-side caching
- **Tenant isolation** — every retrieval query is scoped by authenticated `user_id`; RLS-ready schema
- **Prompt injection** — document chunks are explicitly treated as untrusted data; the model is instructed not to follow instructions in uploaded files
- **XSS prevention** — no `dangerouslySetInnerHTML`; model output rendered as plain text
- **Rate limiting** — Redis-backed, per-IP and per-user for chat, retrieval, upload, and indexing
- **Private storage** — files stored with backend-generated paths, no public bucket assumption
- **Audit logging** — all sensitive operations logged with sanitized metadata
- **CORS & headers** — strict CORS, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `Cache-Control`

---

## Stack

| Layer      | Technology                                                        |
| ---------- | ----------------------------------------------------------------- |
| Frontend   | React 19, TypeScript, Vite, React Router                          |
| Backend    | Python 3.12, FastAPI, psycopg, httpx                              |
| Database   | PostgreSQL 16 + pgvector                                          |
| Auth       | Supabase Auth (JWT + JWKS)                                        |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`)                        |
| LLM        | OpenRouter (primary + fallback models, auto-switch on rate-limit) |
| Queue      | Redis 7 (AOF persistence)                                         |
| Infra      | Docker Compose, nginx, health checks                              |

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Supabase project (free tier)
- OpenRouter API key

### Environment

Copy and fill the template:

```bash
cp .env.compose.example .env.compose
```

### Run

```bash
docker compose up --build
```

Services:

| Service     | Address                 |
| ----------- | ----------------------- |
| Frontend    | `http://127.0.0.1:4173` |
| Backend API | `http://127.0.0.1:8000` |
| Postgres    | `127.0.0.1:5432`        |
| Redis       | `127.0.0.1:6379`        |

---

## Screenshots

| Area          | Screenshots                                                                 |
| ------------- | --------------------------------------------------------------------------- |
| **Auth**      | Login, Sign Up, Email Verification                                          |
| **Chat**      | New session, grounded answers with citations, feedback actions              |
| **Documents** | Document list with status, indexed documents                                |
| **Developer** | Dashboard with metrics, retrieval logs, audit events, feedback, evaluations |

> Screenshots are located in the `screenshots/` directory.

---

## Project Structure

```
rag-document-assistant/
├── backend/
│   ├── app/
│   │   ├── api/              # Route definitions
│   │   ├── core/             # Auth, database, middleware, rate limiting
│   │   ├── schemas/          # Pydantic models
│   │   ├── services/         # Business logic (retrieval, chat, indexing, etc.)
│   │   └── workers/          # Background indexing worker
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/              # Backend client
│   │   ├── components/       # Reusable UI components
│   │   ├── hooks/            # React hooks
│   │   ├── pages/            # Route pages
│   │   └── types/            # TypeScript types
│   └── package.json
├── database/
│   └── migrations/           # Sequential SQL migrations
├── screenshots/              # App screenshots
├── docker-compose.yml
├── SECURITY.md
└── README.md
```

---

## Development

The entire stack runs via Docker Compose (see Quick Start). For individual service development:

### Backend (standalone)

```bash
cd backend
pip install -e .
python -m app.scripts.apply_migrations
uvicorn app.main:app --reload
```

### Indexing Worker (standalone)

```bash
cd backend
python -m app.workers.index_worker
```

### Frontend (standalone)

```bash
cd frontend
npm install
npm run dev
```
