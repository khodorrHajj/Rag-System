# Database

PostgreSQL with pgvector for document storage, chunk embeddings, chat persistence, and observability.

## Role

The database is the central persistence layer for the entire RAG pipeline. Every stage — document upload, text extraction, chunking, embedding, retrieval, chat, feedback, and system monitoring — writes to or reads from PostgreSQL.

## Schema Design

- **Tenant-scoped** — every content table includes a `user_id` column; all queries are scoped by authenticated user
- **Row-Level Security (RLS)** — enforced at the database level on all user-owned tables (profiles, documents, chat sessions, feedback)
- **Migration-based** — all schema changes are sequential SQL files in `migrations/`, applied in order

## Key Tables

| Table                  | Purpose                                                                                             |
| ---------------------- | --------------------------------------------------------------------------------------------------- |
| `profiles`             | User profiles synced from Supabase Auth on first login                                              |
| `documents`            | Uploaded file metadata, processing status, tenant ownership                                         |
| `document_chunks`      | Text chunks with `vector(384)` embeddings, source document reference, chunk index, and page numbers |
| `chat_sessions`        | Per-user chat sessions with title and creation timestamp                                            |
| `chat_messages`        | Individual messages (user + assistant) within sessions, with role and content                       |
| `message_citations`    | Backend-controlled citations linking assistant answer segments to source chunks                     |
| `retrieval_logs`       | Per-query observability: original question, rewritten query, chunk count, score threshold, latency  |
| `feedback`             | User-provided positive/negative ratings on assistant answers, with optional comments                |
| `audit_logs`           | Immutable log of sensitive operations (document upload, delete, model fallback, retrieval failures) |
| `document_permissions` | Document-level access control foundation                                                            |
| `evaluation_runs`      | Automated evaluation suite execution records                                                        |
| `evaluation_results`   | Per-question pass/fail results for eval runs                                                        |

## Vector Search

- Embeddings use `vector(384)` — output dimension of `all-MiniLM-L6-v2`
- Indexed with IVFFlat for approximate nearest neighbor search
- Hybrid search combines cosine similarity on embeddings with PostgreSQL keyword matching on chunk text and document titles

## Migrations

```bash
python -m app.scripts.apply_migrations
```

Migrations cover: extensions and helpers, table creation, indexes, RLS policies, status tracking fields, embedding dimension adjustments, keyword search indexes, retrieval logging, profile identity fields, feedback constraints, evaluation tables, and citation source numbers.

## Storage Flow

```
Upload → documents table
  → Worker parses → document_chunks (with embeddings)
    → Chat queries → retrieval_logs
      → Answer → chat_messages + message_citations
        → User rates → feedback
```

## Run

The database runs as a Docker service with pgvector pre-installed:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: rag_document_assistant
    volumes:
      - postgres_data:/var/lib/postgresql/data
```
