"""
Data Models - Pydantic request/response schemas for API endpoints

Organized by feature:
- Authentication: RegisterRequest, LoginRequest, LogoutRequest
- Chat: ChatRequest, ChatResponse, ChatSessionInfo, MessageInfo
- Admin: UpdateUserAdminRequest, UserInfoResponse
- RAG: FileUploadResponse

All models use Pydantic for automatic validation, serialization, and documentation.
"""

from pydantic import BaseModel, Field
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
# AUTHENTICATION MODELS
# ──────────────────────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    """User registration request (auth.py: register endpoint)"""

    full_name: str
    username: str
    is_admin: bool = False
    admin_secret: Optional[str] = None


class LoginRequest(BaseModel):
    """User login request (auth.py: login endpoint)"""

    username: str
    password: str


class LogoutRequest(BaseModel):
    """User logout request (auth.py: logout endpoint)"""

    token: str


# ──────────────────────────────────────────────────────────────────────────────
# CHAT MODELS
# ──────────────────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Chat message request (chat.py: chat endpoint)"""

    message: str
    session_id: Optional[int] = None  # None = new session created automatically
    personality_id: Optional[int] = None
    # personality_id is used only when creating a NEW session.
    # If session_id is provided, the session's stored personality is used.


class SourceCitation(BaseModel):
    """Source citation metadata for chat responses."""

    filename: str
    file_type: str
    file_size_mb: float | None = None
    page_count: int | None = None
    page_number: int | None = None
    chunk_index: int | None = None
    chunk_total: int | None = None
    chunk_label: str | None = None
    score: float | None = None
    excerpt: str | None = None
    document_id: str | None = None
    source_path: str | None = None


class ChatResponse(BaseModel):
    """Chat response with answer and session metadata (chat.py: chat endpoint)"""

    answer: str
    session_id: int  # Always returned so frontend knows which session to track
    title: str | None = None  # Session title
    sources: list[SourceCitation] = Field(default_factory=list)


class ChatSessionInfo(BaseModel):
    """Chat session metadata (chat.py: list_chat_sessions endpoint)"""

    id: int
    title: str
    created_at: str
    updated_at: str
    personality_id: int = 0  # Default to standard personality if not set


class MessageInfo(BaseModel):
    """Individual message within a session (chat.py: get_session_messages endpoint)"""

    role: str  # "user" or "assistant"
    content: str
    sources: list[SourceCitation] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# RAG MODELS
# ──────────────────────────────────────────────────────────────────────────────


class FileUploadResponse(BaseModel):
    """Response after file upload and ingestion (rag.py: upload_file)"""

    filename: str
    file_size_kb: float
    characters_extracted: int
    file_type: str | None = None
    page_count: int | None = None
    used_ocr: bool = False
    extraction_method: str | None = None
    empty_pages: list[int] | None = None
    chunks_created: int
    total_chunks: int
    message: str


# ──────────────────────────────────────────────────────────────────────────────
# ADMIN MODELS
# ──────────────────────────────────────────────────────────────────────────────


class UpdateUserAdminRequest(BaseModel):
    """Request to update user admin status (admin.py: update_user_admin endpoint)"""

    token: str
    target_username: str
    is_admin: bool


class UpdateUsernameRequest(BaseModel):
    """Request to update a user's username (admin.py: update_username endpoint)"""

    token: str
    target_username: str
    new_username: str


class DeleteUserRequest(BaseModel):
    """Request to delete a user account (admin.py: delete_user endpoint)"""

    token: str
    target_username: str


class UserInfoResponse(BaseModel):
    """User information response (admin.py: get_user, list_all_users endpoints)"""

    id: int
    full_name: str
    username: str
    is_admin: bool


# ──────────────────────────────────────────────────────────────────────────────
# PERSONALITIES MODELS
# ──────────────────────────────────────────────────────────────────────────────


class PersonalityCreateRequest(BaseModel):
    name: str
    system_prompt: str


class PersonalityUpdateRequest(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None


class PersonalityResponse(BaseModel):
    id: int
    name: str
    system_prompt: str

class TTSRequest(BaseModel):
    text: str