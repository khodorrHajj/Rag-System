# Security

This project is built as a secure-by-default RAG application. Its main risk areas are authentication, tenant isolation, untrusted document content, prompt injection, object storage access, and accidental secret exposure across frontend, backend, logs, and Docker assets.

## Threat Model

Primary threats considered in this repository:

- forged or replayed bearer tokens
- cross-tenant document access or retrieval leakage
- unsafe rendering of model output or document-derived text
- prompt injection embedded inside uploaded files
- object-storage path tampering
- accidental exposure of API keys, service-role keys, JWT secrets, DB URLs, or Redis URLs
- noisy or missing rate limiting on upload, retrieval, and chat routes
- excessive logging of sensitive content, embeddings, or credentials

## Auth And JWT Verification

- Protected routes trust identity only after cryptographic JWT verification.
- The preferred verification path uses Supabase JWKS from:
  - `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`
  - or `SUPABASE_JWKS_URL` if explicitly overridden
- JWKS keys are cached server-side to avoid calling Supabase on every request.
- Structure-only JWT decoding is never treated as authentication.
- `user_id` is derived from verified claims only and is never trusted from request bodies.

## Tenant Isolation

- Retrieval is always scoped by the authenticated `user_id`.
- `document_ids` are revalidated server-side and cannot widen search scope.
- Chunks, messages, feedback, retrieval logs, and audit trails are stored with tenant-aware ownership fields.
- The schema is RLS-ready and migration files include RLS enablement and Supabase-style policy examples.
- Frontend filtering is never treated as the authorization boundary.

## Prompt Injection Defenses

- Retrieved document chunks are explicitly treated as untrusted data.
- Final answer generation uses retrieved chunks as factual evidence, not prior chat history.
- Conversation history may help rewrite follow-up questions for retrieval, but it is not a factual source.
- The prompt forbids obeying instructions found inside uploaded documents.
- The model is not given direct tool access, database access, storage access, or internal secret material.
- Citations are backend-controlled and derived from retrieved chunk metadata only.

## XSS And Frontend Rendering Safety

- The frontend does not use `dangerouslySetInnerHTML` in application source.
- LLM output is rendered as plain text, not raw HTML.
- File names, citation labels, chunk previews, and document metadata render as text.
- Debug mode avoids hidden prompts, secrets, DB URLs, embeddings, and full internal prompts.

## File Upload And Parsing Safety

- Supported file types are `.pdf`, `.txt`, and `.docx`.
- Legacy `.doc` is rejected because it introduces an additional legacy parsing surface.
- Uploaded files are treated as untrusted content at every stage.
- File extension, type, and size checks are enforced before storage and before parsing.
- Storage paths are backend-generated, not user-provided.
- Uploaded files are stored privately; no public bucket assumption is allowed.
- Signed URLs must be issued only after backend authorization.
- Parsers do not execute macros, scripts, or embedded code.
- Parsers do not follow document links or external references.
- Password-protected or encrypted PDFs should be rejected.

## Retrieval, Embeddings, And Derived Data

- Embeddings are treated as sensitive derived user data.
- Every `document_chunks` row includes `user_id`.
- Embeddings are not returned by normal API responses.
- The same embedding model and dimension must be used for indexing and querying.
- Database writes use parameterized SQL; no LLM-generated SQL is executed.
- Full embeddings and full private document content should not be logged.

## Rate Limiting

- Redis-backed rate limits support both IP and authenticated-user enforcement.
- Key families include:
  - `rate:ip:chat:{ip}`
  - `rate:user:chat:{user_id}`
  - `rate:ip:retrieval:{ip}`
  - `rate:user:retrieval:{user_id}`
  - `rate:ip:upload:{ip}`
  - `rate:user:upload:{user_id}`
  - `rate:user:indexing:{user_id}`
- If Redis is unavailable, protected rate-limited routes fail safely instead of silently becoming unlimited.

## CORS And Response Hardening

- CORS allows the configured frontend origin plus explicit localhost development origins.
- API responses that include private data should send `Cache-Control: no-store`.

## Error Handling And Logging

- User-facing errors are intentionally concise and safe.
- Stack traces are not exposed in production responses.
- Audit logs sanitize metadata before persistence.
- Audit logs avoid storing:
  - tokens
  - secrets
  - passwords
  - DB URLs
  - Redis URLs
  - service-role keys
  - JWTs
  - embeddings
- Raw OpenRouter or crypto verification internals are not returned to clients.

## Supply Chain And Build Hygiene

- Docker images do not bake local `.env` files or `.git` into build layers.
- Frontend images receive only public `VITE_*` values.
- Backend and worker images share code but run separate commands.
- Python and Node dependencies are locked where applicable.
