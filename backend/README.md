# Backend

FastAPI backend for authentication, document processing, retrieval, and grounded chat.

## Request Flow

1. JWT verification via Supabase JWKS (server-side cached)
2. Rate limit check (Redis-backed, per-IP and per-user)
3. Request validation
4. Service logic execution
5. Database persistence
6. Safe response returned

## Retrieval Pipeline

1. Embed the query using Sentence Transformers (`all-MiniLM-L6-v2`)
2. Vector search on `document_chunks` (cosine similarity, pgvector)
3. Keyword search on indexed documents
4. Merge and rerank results
5. Apply score threshold
6. Return final chunks with citation metadata

## Chat Pipeline

1. Create or load a chat session
2. Store the user message
3. Run retrieval on selected documents or all indexed documents
4. Build a grounded prompt from retrieved chunks only
5. Extract subqueries, build evidence guide, prioritize chunks
6. Call OpenRouter (primary model with fallback on rate-limit)
7. Self-correction loop: faithfulness check + re-generation if needed
8. Backend-controlled citations applied to each claim segment
9. Store assistant message, citations, and audit log
10. Return answer with sources and optional debug info

## Key Services

| Service                    | Role                                                                                    |
| -------------------------- | --------------------------------------------------------------------------------------- |
| `chat_service.py`          | Chat orchestration: session management, retrieval, LLM call, correction, citation       |
| `retrieval_service.py`     | Hybrid vector + keyword search, reranking, thresholding                                 |
| `llm_service.py`           | OpenRouter API calls, rate-limit handling, model fallback                               |
| `prompt_builder.py`        | Subquery extraction, evidence guide, chunk prioritization, grounded prompt construction |
| `embedding_service.py`     | Sentence Transformers model management, batched embedding                               |
| `reranking_service.py`     | Score merging and candidate reranking                                                   |
| `indexing_service.py`      | Document parsing, chunking, embedding, and storage orchestration                        |
| `evaluation_service.py`    | Automated RAG evaluation pipelines                                                      |
| `observability_service.py` | Developer dashboard metrics and monitoring                                              |
| `feedback_service.py`      | User feedback on assistant answers                                                      |

## Run

The backend runs inside Docker Compose as one of five services:

```bash
docker compose up --build
```

### Standalone (outside Docker)

```bash
pip install -e .
python -m app.scripts.apply_migrations
uvicorn app.main:app --reload
```

### Indexing Worker (standalone)

```bash
python -m app.workers.index_worker
```
