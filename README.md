# PFE RAG 2026 - Retrieval-Augmented Generation System

A full-stack RAG (Retrieval-Augmented Generation) application with user authentication, document ingestion, semantic search, and real-time chat powered by local LLMs.

## 🏗️ Architecture Overview

```
PFE-RAG-2026/
├── back-end/              # FastAPI backend
│   ├── core_endpoints/    # Business logic (auth, chat, RAG, admin)
│   ├── services/          # Database & RAG utilities
│   ├── config.py          # Configuration (secrets, models, keys)
│   ├── models.py          # Pydantic schemas (requests/responses)
│   ├── main.py            # FastAPI app setup
│   └── pyproject.toml     # Python dependencies
└── front-end/             # HTML/CSS/JS UI for chat & admin
```

## 🔑 Core Features

| Component          | Purpose                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------------ |
| **Authentication** | JWT tokens, role-based access (admin/user), session tracking, token revocation                   |
| **Chat System**    | Multi-turn conversations with UUID session titles, message persistence, 50-msg context window    |
| **RAG Endpoints**  | Document ingestion (PDF, DOCX, PPTX, TXT), semantic search via Qdrant, LLM generation via Ollama |
| **Admin Panel**    | User management, document collection stats, vector store reset                                   |
| **Database**       | SQLite with users, login_sessions, chat_sessions, chat_messages tables                           |

## 🚀 Quick Start

### Prerequisites

- Python 3.13
- [Poetry](https://python-poetry.org/docs/#installation) for dependency management
- [Ollama](https://ollama.com) running locally (embeddings & LLM inference)
- [Qdrant](https://qdrant.tech) running locally (vector database)

### Backend Setup

#### macOS / Linux

```bash
cd back-end

# Install dependencies
poetry install

# Activate the virtual environment
eval $(poetry env activate)

# Create .env from template and fill in your secrets
cp .env.example .env

# Start the server
poetry run python main.py
```

#### Windows

```powershell
cd back-end

# Install dependencies
poetry install

# Activate the virtual environment
Invoke-Expression (poetry env activate)

# Create .env from template and fill in your secrets
copy .env.example .env

# Start the server
poetry run python main.py
```

### Installing Poetry

#### macOS / Linux

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

#### Windows (PowerShell)

```powershell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -
```

After installing, verify with:

```bash
poetry --version
```

### Environment Variables

Copy `.env.example` to `.env` and fill in the required values:

```env
SECRET_KEY=your_secret_key_here
ADMIN_SECRET=your_admin_secret_here
```

## 📖 Detailed Documentation

### Backend

See [backend.md](back-end/backend.md) for:

- Detailed endpoint documentation
- Database schema & relationships
- Configuration reference
- Token lifecycle & revocation flow
- RAG pipeline workflow

### Frontend

See [frontend.md](front-end/frontend.md) for:

- UI components & page structure
- API integration details
- Development setup
- Configuration & security notes

## 🛠️ Tech Stack

**Backend:** FastAPI, JWT (python-jose), Bcrypt, SQLite

**RAG:** LlamaIndex

**Vector DB:** Qdrant

**LLM:** Ollama (local)

**Frontend:** Vanilla HTML, CSS, JavaScript
