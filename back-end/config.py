"""
Configuration Module - Central hub for all application settings

This module loads environment variables and initializes:
- Authentication & security (JWT signing key, password hashing, OAuth2 scheme)
- CORS middleware (cross-origin resource sharing permissions)
- Ollama LLM configuration (local language model for chat responses)
- Qdrant Vector Database configuration (document embeddings and semantic search)

All sensitive values MUST be set in .env file and never hardcoded.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
import os


load_dotenv()


# ──────────────────────────────────────────────────────────────────────────────
# AUTHENTICATION & SECURITY
# ──────────────────────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("SECRET_KEY")
# Master key for signing/verifying JWT tokens. REQUIRED in .env.
# MUST be a strong random string (minimum 32 characters).
# Used in auth.py to encode login tokens and verify admin requests in admin_endpoints.py.
# SECURITY: Never expose or commit to version control.

ADMIN_SECRET = os.getenv("ADMIN_SECRET")
# One-time gatekeeper for granting initial admin privileges during registration.
# REQUIRED in .env. Users requesting is_admin=True must provide correct ADMIN_SECRET.
# After first admin is created, subsequent admins are managed by existing admins.
# SECURITY: Change this value in production to prevent unauthorized admin creation.


if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not set. Add SECRET_KEY to .env file.")


# ──────────────────────────────────────────────────────────────────────────────
# OLLAMA CONFIGURATION (Local Language Model)
# ──────────────────────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# Base URL of Ollama server (local LLM provider).
# Default: http://localhost:11434 (standard Ollama port)
# Used by rag_service.py to generate chat responses with context.

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4")
# Name of LLM model to use for chat completions.
# Default: gemma4 (lightweight, multi-lingual model)
# Must be installed in Ollama. Change for different capabilities (e.g., "mistral", "llama2").

OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "embeddinggemma")
# Name of embedding model to use for document vectorization.
# Default: embeddinggemma (compatible with search operations)
# Used by rag_service.py to convert documents/queries to semantic vectors for Qdrant.


# ──────────────────────────────────────────────────────────────────────────────
# QDRANT CONFIGURATION (Vector Database)
# ──────────────────────────────────────────────────────────────────────────────

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
# Base URL of Qdrant vector database.
# Default: http://localhost:6333 (standard Qdrant port)
# Stores document embeddings for semantic search and RAG retrieval.

QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "documents")
# Collection for temporary, session-scoped uploads from chat.
TEMP_COLLECTION_NAME = os.getenv("TEMP_COLLECTION_NAME", "temp_documents")
# Name of Qdrant collection storing document vectors.
# Default: "documents"
# Queried by rag_service.py to retrieve contextually relevant documents for answers.


# ──────────────────────────────────────────────────────────────────────────────
# OCR CONFIGURATION (Optional)
# ──────────────────────────────────────────────────────────────────────────────

OCR_PROVIDER = os.getenv("OCR_PROVIDER", "ollama")
OCR_MODE = os.getenv("OCR_MODE", "auto")
OCR_ENABLED = os.getenv("OCR_ENABLED", "").lower() in ("1", "true", "yes")
OCR_OLLAMA_MODEL = os.getenv("OCR_OLLAMA_MODEL", "glm-ocr:bf16")

# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "2000"))
"""
Maximum number of characters accepted per TTS request.
Long LLM answers can be very large — cap to avoid huge audio files.
The frontend should trim/summarise before sending if needed.
"""

# ──────────────────────────────────────────────────────────────────────────────
# FASTAPI APPLICATION & MIDDLEWARE
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI()

# CORS (Cross-Origin Resource Sharing) Middleware
# ⚠️ WARNING: allow_origins=["*"] exposes API to ALL domains.
# For production: restrict to specific frontend domain (e.g., ["https://frontend.com"])
# Current setting suitable for development/testing only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Change to specific domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────────────
# PASSWORD HASHING & TOKEN AUTHENTICATION
# ──────────────────────────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# Password hashing context using bcrypt algorithm.
# Used by auth.py to hash user passwords before storage and verify during login.
# Bcrypt: one-way hashing with adaptive difficulty (resistant to brute force).

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
# OAuth2 Bearer token scheme for JWT authentication.
# Expects "Bearer <token>" in Authorization header on protected endpoints.
# Used by auth.py check_token() to extract token from request headers.
