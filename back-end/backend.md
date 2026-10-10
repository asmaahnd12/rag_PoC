# Backend Architecture & Implementation Guide

Detailed documentation for the PFE RAG 2026 backend system.

## 📐 Project Structure

```
back-end/
├── core_endpoints/          # FastAPI routers & business logic
│   ├── __init__.py         # Package initialization
│   ├── auth.py             # User registration, login, logout, token validation
│   ├── chat.py             # Multi-turn chat with RAG context
│   ├── admin.py            # User management (admin only)
│   └── rag.py              # Document ingestion & semantic search
├── services/               # Utility modules
│   ├── __init__.py
│   ├── database.py         # SQLite schema & query helpers
│   └── rag_service.py      # Qdrant + Ollama integration
├── config.py               # Environment variables & secrets
├── models.py               # Pydantic request/response schemas
├── main.py                 # FastAPI app entry point
├── pyproject.toml          # Project metadata & dependencies
└── .env                    # Secrets (git-ignored)
```

## 🗄️ Database Schema

### Tables

**users**

- `id` (INTEGER PRIMARY KEY)
- `full_name` (TEXT)
- `username` (TEXT UNIQUE)
- `password_hash` (TEXT) — Bcrypt hashed
- `is_admin` (BOOLEAN) — Role flag
- `created_at` (TIMESTAMP)

**login_sessions**

- `id` (INTEGER PRIMARY KEY)
- `token` (TEXT UNIQUE) — JWT token string
- `user_id` (INTEGER FK users)
- `status` (TEXT) — "active" or "revoked"
- `created_at` (TIMESTAMP)

**chat_sessions**

- `id` (INTEGER PRIMARY KEY)
- `user_id` (INTEGER FK users)
- `title` (auto-generated on first message)
- `created_at` (TIMESTAMP)

**chat_messages**

- `id` (INTEGER PRIMARY KEY)
- `session_id` (INTEGER FK chat_sessions)
- `user_message` (TEXT)
- `assistant_response` (TEXT)
- `created_at` (TIMESTAMP)

**Relationships:**

- Cascade delete: users → login_sessions, chat_sessions → chat_messages
- Session ownership enforced: user can only access own sessions

## 🔐 Authentication Flow

### Registration

```
1. POST /admin/register {full_name, username, is_admin?, admin_secret?}
2. If is_admin=true: validate admin_secret
3. Generate random 12-char password (mixed case, digits, symbols)
4. Hash password with bcrypt (cost=12)
5. Insert user record
6. Return plaintext password (shown once to user)
```

### Login

```
1. POST /auth/login {username, password}
2. Hash input password with bcrypt
3. Verify against stored hash
4. Generate JWT token with claims:
   - sub: username
   - user_id: database ID
   - role: "admin" or "user"
   - jti: unique token identifier (UUID v4)
   - exp: 24 hours from now
5. Insert token record in login_sessions (status=active)
6. Return {access_token, role}
```

### Token Verification (Dependency)

```
1. Extract "Bearer TOKEN" from Authorization header
2. Decode JWT (validates signature + expiration)
3. Query login_sessions for token status
4. If not found or status != "active": reject (401)
5. Return user data {username, user_id, role, token}
```

### Logout

```
1. POST /auth/logout {token}
2. Update login_sessions WHERE token=? SET status='revoked'
3. Future requests with this token rejected (revoked check)
```

**Security:** Two-level verification prevents token replay after logout.

## 💬 Chat System

### Session Lifecycle

```
1. User sends first message → ChatRequest {user_id, message}
2. If no active session: create new chat_session (title=NULL)
3. Load last 50 messages from chat_session (context window)
4. Call RAG pipeline: embed query + search Qdrant + call Ollama
5. Save both user_message & assistant_response to chat_messages
6. If title still NULL: generate UUID v4 title (update session)
7. Return ChatResponse {session_id, answer, title}
```

### Context Window

- Default: 50 previous messages loaded per query
- Oldest messages first (chronological order)
- Prevents token overflow in LLM context

### Title Generation

- Set on first message in session (not on registration)

## 🤖 RAG Pipeline

### Document Ingestion

```
1. User uploads file (PDF, DOCX, PPTX, TXT) — max 20 MB
2. Validate file type by extension
3. Extract text using extract_text_from_file()
4. Split text into chunks (~300 tokens each)
5. Embed each chunk via Ollama embeddings model
6. Store vectors + metadata in Qdrant collection
7. Return summary: {filename, chunks_created, total_chunks}
```

### Admin Operations

- `POST /rag/upload` — Upload file from disk

**Supported Formats:**

- PDF: PyPDF2 text extraction
- DOCX: python-docx
- PPTX: python-pptx
- TXT: plain text

## 📊 Admin Panel Features

**User Management** (`/admin/users` endpoints)

- List all users with registration timestamps
- Toggle admin status (admin-only operation)
- Delete users (cascades: removes sessions → messages)

## 🚨 Error Handling

### Authentication Errors

| Status | Error                 | Cause                                   |
| ------ | --------------------- | --------------------------------------- |
| 401    | Invalid credentials   | Wrong username/password at login        |
| 401    | Token expired         | JWT exp claim in past                   |
| 401    | Invalid token         | Malformed JWT or signature mismatch     |
| 401    | Token revoked         | Session marked revoked in DB (logout)   |
| 403    | Admin access required | Non-admin user accessing admin endpoint |
| 403    | Invalid admin secret  | Wrong secret during admin registration  |

### RAG Errors

| Status | Error                    | Cause                  |
| ------ | ------------------------ | ---------------------- |
| 400    | No documents provided    | Empty ingest request   |
| 400    | Unsupported file type    | Not PDF/DOCX/PPTX/TXT  |
| 413    | File too large           | > 20 MB upload         |
| 422    | Text extraction failed   | Corrupted file         |
| 500    | Qdrant connection failed | Vector DB unreachable  |
| 500    | Ollama inference failed  | LLM server unreachable |
