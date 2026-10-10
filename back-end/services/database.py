"""
Database Module - SQLite schema initialization and query helpers

This module manages all database operations for the application:
- User management (registration, authentication, admin status)
- Login session tracking (token revocation, session status)
- Chat session storage (conversation metadata)
- Chat message persistence (conversation history)
- Personalities management (custom system prompts for the LLM)

Database Structure:
- users: User accounts with hashed passwords and admin flags
- login_sessions: Active/revoked JWT tokens for auth security
- chat_sessions: Chat conversation containers (one per user session)
- chat_messages: Individual messages within conversations (user + assistant)
- personalities: Custom system prompts created by admins

Rules :
-Min 0 personalities → fallback to generic system prompt
- Max 5 personalities in database
- One personality per chat session

All tables use CASCADE DELETE for referential integrity.
Foreign keys enforce user ownership of sessions and messages.

⚠️ NOTE: Using SQLite with check_same_thread=False is suitable for development only.
For production, migrate to PostgreSQL to handle concurrent requests safely.
"""

import sqlite3
import os
import json

os.makedirs("data", exist_ok=True)
conn = sqlite3.connect("data/users.db", check_same_thread=False)
# SQLite connection with check_same_thread=False to allow multi-threaded access.
# ⚠️ Not thread-safe for production. Use connection pooling (e.g., ThreadPoolExecutor) or migrate to PostgreSQL.


def init_db():
    """
    Initialize database schema on application startup.
    Creates all tables if they don't exist.
    Performs migrations for existing databases (e.g., adding is_admin column).
    """
    cursor = conn.cursor()

    # ──────────────────────────────────────────────────────────────────────────────
    # Users Table
    # ──────────────────────────────────────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT,
        username TEXT UNIQUE,
        password TEXT,
        is_admin INTEGER DEFAULT 0
    )
    """)
    conn.commit()

    # Migration: Add is_admin column if missing (for existing databases)
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    if "is_admin" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        conn.commit()

    # ──────────────────────────────────────────────────────────────────────────────
    # Login Sessions Table - tracks active/revoked JWT tokens
    # ──────────────────────────────────────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS login_sessions (
        session_number INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
        user_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    conn.commit()

    # ──────────────────────────────────────────────────────────────────────────────
    # Chat Sessions Table - represents a conversation container
    # One personality per session. NULL = generic fallback.
    # ──────────────────────────────────────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        personality_id INTEGER NULL,
        title TEXT DEFAULT 'New chat',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        deleted_at TIMESTAMP NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    conn.commit()

    # Migration: add personality_id if missing on existing DB
    cursor.execute("PRAGMA table_info(chat_sessions)")
    columns = [column[1] for column in cursor.fetchall()]
    if "personality_id" not in columns:
        cursor.execute(
            "ALTER TABLE chat_sessions ADD COLUMN personality_id INTEGER NULL"
        )
        conn.commit()

    if "deleted_at" not in columns:
        cursor.execute("ALTER TABLE chat_sessions ADD COLUMN deleted_at TIMESTAMP NULL")
        conn.commit()

    # Migration: Set all NULL personality_id values to STANDARD_PERSONALITY_ID (0)
    cursor.execute(
        "UPDATE chat_sessions SET personality_id = 0 WHERE personality_id IS NULL"
    )
    conn.commit()

    # ──────────────────────────────────────────────────────────────────────────────
    # Chat Messages Table - individual messages within a session
    # ──────────────────────────────────────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content TEXT NOT NULL,
        sources_json TEXT DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
    )
    """)
    conn.commit()

    cursor.execute("PRAGMA table_info(chat_messages)")
    columns = [column[1] for column in cursor.fetchall()]
    if "sources_json" not in columns:
        cursor.execute(
            "ALTER TABLE chat_messages ADD COLUMN sources_json TEXT DEFAULT '[]'"
        )
        conn.commit()

    cursor.close()


init_db()


# ──────────────────────────────────────────────────────────────────────────────
# USER QUERY CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
insert_user = (
    "INSERT INTO users (full_name, username, password, is_admin) VALUES (?, ?, ?, ?)"
)
select_user = "SELECT id, full_name, username, is_admin FROM users WHERE username=?"
select_password = "SELECT password FROM users WHERE username=?"
select_user_id = "SELECT id FROM users WHERE username=?"
get_user_by_id = "SELECT id, full_name, username, is_admin FROM users WHERE id=?"
get_all_users = "SELECT id, full_name, username, is_admin FROM users"
update_user_admin_status = "UPDATE users SET is_admin = ? WHERE id = ?"
update_username_by_id = "UPDATE users SET username = ? WHERE id = ?"
delete_user_by_id = "DELETE FROM users WHERE id = ?"

# ──────────────────────────────────────────────────────────────────────────────
# LOGIN SESSION QUERY CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
insert_session = (
    "INSERT INTO login_sessions (token, status, user_id) VALUES (?, 'active', ?)"
)
revoke_session = "UPDATE login_sessions SET status = 'revoked' WHERE token = ?"
check_session_status = "SELECT status FROM login_sessions WHERE token = ?"
get_user_sessions = "SELECT session_number, token, status, created_at FROM login_sessions WHERE user_id = ?"


# ──────────────────────────────────────────────────────────────────────────────
# CHAT SESSION HELPER FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────


def create_chat_session(
    user_id: int, title: str = "New chat", personality_id: int = 0
) -> int:
    """
    Create a new chat session for a user.

    Args:
        user_id (int): ID of the user creating the session.
        title (str): Initial session title. Defaults to "New chat".

    Returns:
        int: ID of the newly created session (lastrowid).

    Note:
        - Uses default title "New chat" until first message is sent
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO chat_sessions (user_id,personality_id, title) VALUES (?, ?, ?)",
            (user_id, personality_id, title),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()


def get_chat_sessions(user_id: int) -> list:
    """
    Retrieve all active chat sessions for a user, sorted by most recent first.

    Args:
        user_id (int): ID of the user whose sessions to retrieve.

    Returns:
        list[dict]: List of session objects with keys: id, title, created_at, updated_at.
                   Sorted by updated_at DESC (most recent conversations first).

    Use Case:
        Called to populate sidebar/conversation list in frontend.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, title, created_at, updated_at, personality_id
                        FROM chat_sessions
                        WHERE user_id = ?
                            AND deleted_at IS NULL
            ORDER BY updated_at DESC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "created_at": r[2],
                "updated_at": r[3],
                "personality_id": r[4],
            }
            for r in rows
        ]
    finally:
        cursor.close()


def delete_chat_session(session_id: int, user_id: int) -> bool:
    """
    Soft-delete a chat session so stats can keep historical usage.

    Args:
        session_id (int): ID of the session to delete.
        user_id (int): ID of the user (ownership verification).

    Returns:
        bool: True if session was deleted, False if session not found or doesn't belong to user.

    Cascade Behavior:
        - Marks session as deleted (deleted_at)
        - Messages stay available for stats aggregation

    Note:
        Verifies ownership: only deletes sessions that belong to the authenticated user.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE chat_sessions
            SET deleted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND user_id = ?
              AND deleted_at IS NULL
            """,
            (session_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        cursor.close()


def update_session_title(session_id: int, title: str) -> None:
    """
    Update the title of a chat session.

    Args:
        session_id (int): ID of the session to update.
        title (str): New title for the session.

    Note:
        Called by chat.py on first message to replace "New chat".
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE chat_sessions SET title = ? WHERE id = ? AND deleted_at IS NULL",
            (title, session_id),
        )
        conn.commit()
    finally:
        cursor.close()


def get_session_title(session_id: int) -> str:
    """
    Retrieve the current title of a chat session.

    Args:
        session_id (int): ID of the session.

    Returns:
        str: Current session title, or "New chat" if session not found.

    Note:
        Used to detect first message: if title is still "New chat", generate new title.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT title FROM chat_sessions WHERE id = ? AND deleted_at IS NULL",
            (session_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else "New chat"
    finally:
        cursor.close()


def get_session_personality_id(session_id: int) -> int:
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT personality_id FROM chat_sessions WHERE id = ? AND deleted_at IS NULL",
            (session_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else 0
    finally:
        cursor.close()


# ──────────────────────────────────────────────────────────────────────────────
# CHAT MESSAGE HELPER FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────


def save_message(
    session_id: int, role: str, content: str, sources: list | None = None
) -> None:
    """
    Save a message (user or assistant) to a chat session.

    Args:
        session_id (int): ID of the session to save message to.
        role (str): Message role: "user" or "assistant".
        content (str): Message text content.

    Side Effects:
        - Inserts message into chat_messages table
        - Updates parent session's updated_at timestamp to CURRENT_TIMESTAMP

    Note:
        Timestamp update ensures sessions sort by most recent activity.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content, sources_json) VALUES (?, ?, ?, ?)",
            (session_id, role, content, json.dumps(sources or [])),
        )
        cursor.execute(
            "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (session_id,),
        )
        conn.commit()
    finally:
        cursor.close()


def get_messages(session_id: int, limit: int = 10) -> list:
    """
    Retrieve recent messages from a chat session in chronological order.

    Args:
        session_id (int): ID of the session to retrieve messages from.
        limit (int): Maximum number of recent messages to return. Defaults to 10.
                    Typical use: 50 for context window (≈25 exchanges).

    Returns:
        list[dict]: Messages sorted oldest-to-newest with keys: role, content.
                   Example: [{"role": "user", "content": "Hello"}, ...]

    Context Window:
        The limit parameter prevents exceeding LLM context limits (Ollama window).
        Typical range: 10-50 messages depending on token budget.
        Recent messages included only; older messages discarded if limit exceeded.

    Note:
        - Messages retrieved in DESC order then reversed to be chronological
        - Used by chat.py to build RAG context for LLM
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT role, content, sources_json
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = cursor.fetchall()
        # Reverse to restore chronological order (oldest first, newest last)
        messages = []
        for row in reversed(rows):
            sources = []
            if row[2]:
                try:
                    sources = json.loads(row[2])
                except json.JSONDecodeError:
                    sources = []
            messages.append({"role": row[0], "content": row[1], "sources": sources})
        return messages
    finally:
        cursor.close()


def session_belongs_to_user(session_id: int, user_id: int) -> bool:
    """
    Verify that an active chat session belongs to a specific user.

    Args:
        session_id (int): ID of the session to verify.
        user_id (int): ID of the user to check ownership against.

    Returns:
        bool: True if session exists and belongs to user, False otherwise.

    Security:
        Used by chat.py endpoints to enforce user isolation:
        - Only user can access their sessions
        - Prevents cross-user data leakage
        - All session operations require this verification

    Note:
        Critical for multi-tenant safety. Always called before allowing access.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id
            FROM chat_sessions
            WHERE id = ?
              AND user_id = ?
              AND deleted_at IS NULL
            """,
            (session_id, user_id),
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def get_user_id_by_username(username: str) -> int | None:
    cursor = conn.cursor()
    try:
        cursor.execute(select_user_id, (username,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        cursor.close()


def _session_scope_clause(session_scope: str | None) -> str:
    scope = (session_scope or "active").lower()
    if scope == "deleted":
        return "AND s.deleted_at IS NOT NULL"
    if scope == "all":
        return ""
    return "AND s.deleted_at IS NULL"


def count_user_messages_in_range(
    user_id: int, start_ts: str, end_ts: str, session_scope: str | None = None
) -> int:
    cursor = conn.cursor()
    try:
        scope_clause = _session_scope_clause(session_scope)
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM chat_messages AS m
            JOIN chat_sessions AS s ON s.id = m.session_id
            WHERE s.user_id = ?
              {scope_clause}
              AND m.role = 'user'
              AND m.created_at >= ?
              AND m.created_at < ?
            """,
            (user_id, start_ts, end_ts),
        )
        row = cursor.fetchone()
        return row[0] if row else 0
    finally:
        cursor.close()


def get_assistant_sources_in_range(
    user_id: int, start_ts: str, end_ts: str, session_scope: str | None = None
) -> list[str]:
    cursor = conn.cursor()
    try:
        scope_clause = _session_scope_clause(session_scope)
        cursor.execute(
            f"""
            SELECT m.sources_json
            FROM chat_messages AS m
            JOIN chat_sessions AS s ON s.id = m.session_id
            WHERE s.user_id = ?
              {scope_clause}
              AND m.role = 'assistant'
              AND m.created_at >= ?
              AND m.created_at < ?
            """,
            (user_id, start_ts, end_ts),
        )
        rows = cursor.fetchall()
        return [row[0] for row in rows if row and row[0]]
    finally:
        cursor.close()


def get_user_file_daily_stats(
    user_id: int,
    source_path_or_filename: str,
    start_ts: str,
    end_ts: str,
    session_scope: str | None = None,
) -> dict[str, int]:
    """
    Get daily usage count for a specific file over a date range.

    Args:
        user_id: The user ID
        source_path_or_filename: The file to match (source_path or filename)
        start_ts: Start timestamp (YYYY-MM-DD HH:MM:SS)
        end_ts: End timestamp (YYYY-MM-DD HH:MM:SS)

    Returns:
        Dictionary with date as key (YYYY-MM-DD) and usage count as value
    """
    cursor = conn.cursor()
    try:
        scope_clause = _session_scope_clause(session_scope)
        cursor.execute(
            f"""
            SELECT m.sources_json, DATE(m.created_at) as day
            FROM chat_messages AS m
            JOIN chat_sessions AS s ON s.id = m.session_id
            WHERE s.user_id = ?
              {scope_clause}
              AND m.role = 'assistant'
              AND m.created_at >= ?
              AND m.created_at < ?
            ORDER BY DATE(m.created_at)
            """,
            (user_id, start_ts, end_ts),
        )
        rows = cursor.fetchall()

        daily_stats = {}
        target = source_path_or_filename.lower()
        for sources_json, day in rows:
            if not sources_json:
                continue

            try:
                sources = json.loads(sources_json)
            except json.JSONDecodeError:
                continue

            if not isinstance(sources, list):
                continue

            for source in sources:
                if not isinstance(source, dict):
                    continue

                filename = (source.get("filename") or "").strip().lower()
                source_path = (source.get("source_path") or "").strip().lower()

                if (source_path and source_path == target) or (
                    filename and filename == target
                ):
                    daily_stats[day] = daily_stats.get(day, 0) + 1
                    break

        return daily_stats
    finally:
        cursor.close()
