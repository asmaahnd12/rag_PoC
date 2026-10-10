"""
Chat Endpoints - for managing multi-turn conversations with RAG-powered responses

KEY CONCEPTS:
- Each user has multiple independent chat sessions
- Each session stores conversation history (user + assistant messages)
- RAG (Retrieval-Augmented Generation) provides context-aware responses from documents
- Session title auto-generated on first message using LLM (Ollama)
- Token validation via check_token ensures only authenticated users can access their sessions
- session_belongs_to_user() enforces ownership: users can only access/modify their own sessions

Functions:
- chat(): Main conversation endpoint. Creates/reuses session, generates RAG response, saves history, generates title for first message.
- new_chat_session(): Create new empty session for "New Chat" button.
- list_chat_sessions(): Retrieve all sessions for logged-in user (sidebar display).
- get_session_messages(): Load all messages from a specific session (reload conversation).
- remove_chat_session(): Soft-delete a session (hidden from UI, kept for stats).
"""

from fastapi import Depends, HTTPException, UploadFile, File, Response
from fastapi.responses import StreamingResponse
import json
from models import ChatRequest, ChatResponse, ChatSessionInfo, MessageInfo, TTSRequest
from core_endpoints.auth import check_token
from services.rag_service import (
    generate_chat_response,
    generate_chat_response_stream,
    generate_session_title,
    ingest_chat_upload,
    reset_session_collection,
    SUPPORTED_EXTENSIONS,
)
from services.database import (
    create_chat_session,
    get_chat_sessions,
    delete_chat_session,
    save_message,
    get_messages,
    update_session_title,
    get_session_title,
    session_belongs_to_user,
    get_session_personality_id,
)
from services.personalities_store import get_personality_by_id, STANDARD_PERSONALITY_ID
from services.speech_service import (
    process_wav_bytes,
    synthesize,
    strip_markdown,
    MAX_CHARS,
)


def chat(payload: ChatRequest, user_data: dict = Depends(check_token)) -> ChatResponse:
    """
    Main chat endpoint - process user message and generate RAG-powered response.

    Args:
        payload (ChatRequest): Contains message text and optional session_id to continue existing conversation.
        user_data (dict): Authenticated user info from check_token dependency (contains user_id).

    Returns:
        ChatResponse: Contains answer text, session_id, and auto-generated title (only on first message).

    Raises:
        HTTPException(400): If message is empty or whitespace-only.
        HTTPException(404): If provided session_id does not belong to authenticated user.
        HTTPException(500): If system error occurs during processing.

    Process:
        1. Create new session if no session_id provided, else verify ownership
        2. Load up to 50 recent messages from database (full conversation context)
        3. Generate response using RAG service (Ollama LLM with document retrieval)
        4. Save both user message and assistant response to database
        5. If first message in session (title still "New chat"), generate and save new title
        6. Return response with session_id and auto-generated title (if applicable)

    Note:
        - Title generation happens once per session (on first message)
        - Full message history loaded for context (improves response quality)
        - All messages persisted to enable conversation reload
    """
    try:
        user_id = user_data["user_id"]
        user_message = payload.message.strip()

        if not user_message:
            raise HTTPException(status_code=400, detail="Message cannot be empty")

        # Get or create session
        session_id = payload.session_id

        # New session: optional personality_id may be provided
        # Existing session: personality is fixed and comes from DB
        if session_id is None:
            if payload.personality_id is not None:
                personality = get_personality_by_id(payload.personality_id)
                if personality is None:
                    raise HTTPException(
                        status_code=404, detail="Selected personality not found"
                    )
                personality_id = payload.personality_id
            else:
                personality_id = STANDARD_PERSONALITY_ID  # generic fallback

            session_id = create_chat_session(
                user_id=user_id,
                personality_id=personality_id,
            )
        else:
            if not session_belongs_to_user(session_id, user_id):
                raise HTTPException(status_code=404, detail="Session not found")

            # Prevent personality change inside an existing session
            if payload.personality_id is not None:
                stored_personality_id = get_session_personality_id(session_id)
                if payload.personality_id != stored_personality_id:
                    raise HTTPException(
                        status_code=400,
                        detail="Personality cannot be changed inside an existing session.",
                    )

        # Load real conversation history from database (max 50 messages = 25 exchanges)
        history = get_messages(session_id, limit=50)
        personality_id = get_session_personality_id(session_id)

        # Generate response with full context via RAG + Ollama
        result = generate_chat_response(
            question=user_message,
            history=history,
            session_id=session_id,
            personality_id=personality_id,
        )
        answer = result.get("answer", "")
        sources = result.get("sources", [])

        # Persist both user message and assistant response to database
        save_message(session_id, "user", user_message)
        save_message(session_id, "assistant", answer, sources=sources)

        # Generate title automatically on first message of session
        # Check current title in DB - if still "New chat", this is first exchange
        # (regardless of whether session_id was provided or newly created)
        generated_title = None
        current_title = get_session_title(session_id)
        if current_title == "New chat":
            generated_title = generate_session_title(user_message, answer)
            update_session_title(session_id, generated_title)

        return ChatResponse(
            answer=answer,
            session_id=session_id,
            title=generated_title,
            sources=sources,
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Chat system error: {str(e)}")


def chat_stream(payload: ChatRequest, user_data: dict = Depends(check_token)):
    """Streaming variant of chat endpoint using SSE token events."""
    try:
        user_id = user_data["user_id"]
        user_message = payload.message.strip()

        if not user_message:
            raise HTTPException(status_code=400, detail="Message cannot be empty")

        session_id = payload.session_id

        if session_id is None:
            if payload.personality_id is not None:
                personality = get_personality_by_id(payload.personality_id)
                if personality is None:
                    raise HTTPException(
                        status_code=404, detail="Selected personality not found"
                    )
                personality_id = payload.personality_id
            else:
                personality_id = STANDARD_PERSONALITY_ID

            session_id = create_chat_session(
                user_id=user_id,
                personality_id=personality_id,
            )
        else:
            if not session_belongs_to_user(session_id, user_id):
                raise HTTPException(status_code=404, detail="Session not found")

            if payload.personality_id is not None:
                stored_personality_id = get_session_personality_id(session_id)
                if payload.personality_id != stored_personality_id:
                    raise HTTPException(
                        status_code=400,
                        detail="Personality cannot be changed inside an existing session.",
                    )

        history = get_messages(session_id, limit=50)
        personality_id = get_session_personality_id(session_id)

        stream_result = generate_chat_response_stream(
            question=user_message,
            history=history,
            session_id=session_id,
            personality_id=personality_id,
        )
        token_stream = stream_result.get("stream")
        sources = stream_result.get("sources", [])

        def event_generator():
            answer_chunks: list[str] = []

            try:
                for chunk in token_stream:
                    if not chunk:
                        continue
                    answer_chunks.append(chunk)
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk}, ensure_ascii=False)}\n\n"

                full_answer = "".join(answer_chunks).strip()

                save_message(session_id, "user", user_message)
                save_message(session_id, "assistant", full_answer, sources=sources)

                generated_title = None
                current_title = get_session_title(session_id)
                if current_title == "New chat":
                    generated_title = generate_session_title(user_message, full_answer)
                    update_session_title(session_id, generated_title)

                done_payload = {
                    "type": "done",
                    "session_id": session_id,
                    "title": generated_title,
                    "sources": sources,
                    # "answer" intentionnellement absent :
                    # le frontend reconstruit la réponse depuis les events "token"
                    # l'inclure ici causerait un double affichage
                }
                yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

            except Exception as stream_error:
                error_payload = {
                    "type": "error",
                    "message": f"Streaming error: {str(stream_error)}",
                }
                yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in chat stream endpoint: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Chat streaming system error: {str(e)}"
        )


def new_chat_session(
    personality_id: int | None = None,
    user_data: dict = Depends(check_token),
) -> ChatSessionInfo:
    """
    Create new empty chat session.

    Args:
        user_data (dict): Authenticated user info from check_token dependency (contains user_id).

    Returns:
        ChatSessionInfo: New session object with default title "New chat", timestamps, and session_id.

    Raises:
        HTTPException(500): If session creation fails unexpectedly.

    Use Case:
        Called by "New Chat" button from frontend to start fresh conversation.
        Returns initialized session ready for first message.
    """
    user_id = user_data["user_id"]

    if personality_id is None:
        personality_to_use = STANDARD_PERSONALITY_ID
    else:
        personality = get_personality_by_id(personality_id)
        if personality is None:
            raise HTTPException(
                status_code=404, detail="Selected personality not found"
            )
        personality_to_use = personality_id

    session_id = create_chat_session(user_id, personality_id=personality_to_use)
    sessions = get_chat_sessions(user_id)
    session = next((s for s in sessions if s["id"] == session_id), None)
    if not session:
        raise HTTPException(status_code=500, detail="Failed to create session")
    return ChatSessionInfo(**session)


def list_chat_sessions(user_data: dict = Depends(check_token)) -> list[ChatSessionInfo]:
    """
    Retrieve all chat sessions for logged-in user.
    """
    user_id = user_data["user_id"]
    sessions = get_chat_sessions(user_id)
    return [ChatSessionInfo(**s) for s in sessions]


def get_session_messages(
    session_id: int,
    user_data: dict = Depends(check_token),
) -> list[MessageInfo]:
    """
    Load all messages from a specific chat session.
    """
    user_id = user_data["user_id"]

    if not session_belongs_to_user(session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")

    messages = get_messages(session_id, limit=200)
    return [MessageInfo(**m) for m in messages]


def remove_chat_session(
    session_id: int,
    user_data: dict = Depends(check_token),
) -> dict:
    """
    Soft-delete a chat session (kept for stats, hidden from UI).
    """
    user_id = user_data["user_id"]

    if not session_belongs_to_user(session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")

    success = delete_chat_session(session_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    reset_session_collection(session_id)

    return {"status": "success", "message": "Chat session deleted"}


async def upload_chat_file(
    session_id: int,
    file: UploadFile = File(...),
    user_data: dict = Depends(check_token),
) -> dict:
    user_id = user_data["user_id"]
    if not session_belongs_to_user(session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")

    MAX_FILE_SIZE = 20 * 1024 * 1024
    filename = file.filename or "upload"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) / 1_048_576:.1f} MB). Maximum: 20 MB.",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    result = ingest_chat_upload(session_id, filename, content)
    if result.get("status") != "success":
        raise HTTPException(status_code=422, detail=result.get("message"))

    return {
        "status": "success",
        "filename": filename,
        "chunks_created": result.get("chunks_created", 0),
        "message": f"✓ '{filename}' uploaded for this session.",
    }


async def speech_to_text_endpoint(
    file: UploadFile = File(...),
    user_data: dict = Depends(check_token),
) -> dict:
    """
    Process uploaded standard WAV file (16kHz PCM), convert it to text via Whisper,
    and return the text.
    """

    filename = (file.filename or "").lower()
    if not filename.endswith(".wav"):
        raise HTTPException(status_code=400, detail="Only .wav files are supported")

    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded audio is empty")

        text = process_wav_bytes(content)
        return {"text": text}
    except HTTPException:
        raise
    except Exception as e:
        print(f"STT Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def text_to_speech_endpoint(
    body: TTSRequest,
    token_data: dict = Depends(check_token),
):
    """
    POST /chat/tts
    Body : { "text": "..." }
    Returns : audio/wav binary

    Le frontend envoie le texte brut (markdown déjà strippé côté JS
    ou laissé au service qui le strip lui-même).
    """

    text = strip_markdown(body.text)

    if not text:
        raise HTTPException(status_code=400, detail="Text is empty after stripping.")

    # Tronquer silencieusement si trop long (évite une 400 agressive)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    try:
        wav_bytes = synthesize(text)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TTS error: {exc}")

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            # Force le navigateur à streamer l'audio plutôt que de le télécharger
            "Content-Disposition": 'inline; filename="tts.wav"',
            "Cache-Control": "no-store",
        },
    )
