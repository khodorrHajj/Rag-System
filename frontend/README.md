# Frontend

React + TypeScript + Vite frontend for authentication, document management, and grounded chat.

## Pages

| Route        | Page         | Description                                   |
| ------------ | ------------ | --------------------------------------------- |
| `/login`     | Login        | Supabase email authentication                 |
| `/signup`    | Sign Up      | Account creation with email verification      |
| `/verify`    | Verify Email | Email confirmation handler                    |
| `/documents` | Documents    | Upload, track, and delete documents           |
| `/chat`      | Chat         | Chat sessions with grounded answers           |
| `/developer` | Developer    | Monitoring dashboard, evaluations, audit logs |

## Key Features

- **Supabase Auth** — sign up, sign in, sign out, email verification flow, protected routes
- **Document management** — upload with status tracking, document list with indexed state
- **Chat interface** — session management, grounded answers with backend-controlled citations, feedback actions (positive/negative) under each answer
- **WebSocket real-time** — live answer streaming and chat events
- **Developer tools** — toggleable debug panel per answer showing retrieval diagnostics (original question, retrieval query, threshold, latency, exact chunks with scores); dedicated developer dashboard with system metrics, retrieval logs, audit events, feedback, and evaluation results
- **Safe rendering** — no `dangerouslySetInnerHTML`; model output rendered as plain text

## Frontend Flow

1. User authenticates with Supabase
2. Frontend stores access token
3. Backend requests include `Authorization: Bearer <token>`
4. Documents and chats load from backend APIs
5. Chat answers render with backend-provided citations
6. Developer accounts see additional debug panels and dashboard access

## Run

The frontend runs inside Docker Compose as one of five services:

```bash
docker compose up --build
```

### Standalone (outside Docker)

```bash
npm install
npm run dev
```
