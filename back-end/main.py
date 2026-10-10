from config import app
from core_endpoints.auth import register, login, logout
from core_endpoints.chat import (
    chat,
    chat_stream,
    new_chat_session,
    list_chat_sessions,
    get_session_messages,
    remove_chat_session,
    upload_chat_file,
    speech_to_text_endpoint,
)
from core_endpoints.admin import (
    get_user,
    list_all_users,
    update_user_admin,
    update_username,
    delete_user,
    get_weekly_user_stats,
    get_user_file_daily_trend,
)
from core_endpoints.rag import (
    upload_file,
    get_collection_stats,
)
from core_endpoints.personalities import (
    list_available_personalities,
    add_personality,
    edit_personality,
    remove_personality,
)
from core_endpoints.chat import text_to_speech_endpoint
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import os


# ──────────────────────────────────────────────────────────────────────────────
# STATIC FILES & FRONTEND SERVING
# ──────────────────────────────────────────────────────────────────────────────

# Mount front-end static files
frontend_path = os.path.join(os.path.dirname(__file__), "..", "front-end")
app.mount("/static", StaticFiles(directory=frontend_path), name="static")


# Serve login page as default (root route)
@app.get("/")
async def serve_login():
    login_path = os.path.join(frontend_path, "login", "login.html")
    return FileResponse(login_path)


# Serve chat page
@app.get("/chat")
async def serve_chat():
    chat_path = os.path.join(frontend_path, "chat", "chat.html")
    return FileResponse(chat_path)


# Serve admin page
@app.get("/admin")
async def serve_admin():
    admin_path = os.path.join(frontend_path, "admin", "admin.html")
    return FileResponse(admin_path)


# Serve stats page
@app.get("/stats")
async def serve_stats():
    stats_path = os.path.join(frontend_path, "stats", "stats.html")
    return FileResponse(stats_path)


# ──────────────────────────────────────────────────────────────────────────────
# API ROUTES
# ──────────────────────────────────────────────────────────────────────────────

# Auth routes
app.post("/admin/register")(register)
app.post("/login")(login)
app.post("/logout")(logout)

# Chat routes
app.post("/chat")(chat)
app.post("/chat/stream")(chat_stream)
app.post("/chat/new")(new_chat_session)
app.get("/chat/sessions")(list_chat_sessions)
app.get("/chat/sessions/{session_id}/messages")(get_session_messages)
app.delete("/chat/sessions/{session_id}")(remove_chat_session)
app.post("/chat/sessions/{session_id}/upload")(upload_chat_file)
app.post("/chat/speech-to-text")(speech_to_text_endpoint)   
app.post("/chat/tts")(text_to_speech_endpoint)

# Admin routes
app.get("/user")(get_user)
app.get("/admin/users")(list_all_users)
app.post("/admin/update-user-admin")(update_user_admin)
app.post("/admin/update-username")(update_username)
app.post("/admin/delete-user")(delete_user)
app.get("/admin/user-weekly-stats")(get_weekly_user_stats)
app.get("/admin/user-file-daily-trend")(get_user_file_daily_trend)

# RAG routes
app.post("/upload")(upload_file)
app.get("/admin/collection-info")(get_collection_stats)

# Personalities routes
# Read for all authenticated users
app.get("/personalities")(list_available_personalities)

# Admin-only management
app.post("/admin/personalities")(add_personality)
app.put("/admin/personalities/{id}")(edit_personality)
app.delete("/admin/personalities/{id}")(remove_personality)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
