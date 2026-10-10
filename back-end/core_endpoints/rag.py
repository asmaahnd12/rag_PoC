"""
RAG API Endpoints - Document ingestion and semantic search


Provides REST endpoints for:
- Uploading files for ingestion into the RAG vector store


Key Concepts:
- RAG (Retrieval-Augmented Generation): Uses document embeddings for semantic search
  to enhance LLM responses with relevant context from uploaded documents
- Supported formats: PDF, TXT, DOCX, PPTX (structured extraction)
- File size limit: 20 MB per file
"""

from fastapi import HTTPException, UploadFile, File, Depends
from services.rag_service import (
    ingest_uploaded_file,
    SUPPORTED_EXTENSIONS,
    get_collection_info,
    get_ingestion_stats,
    record_processed_file_stats,
)
from models import FileUploadResponse
from core_endpoints.auth import check_token


# ──────────────────────────────────────────────────────────────────────────────
# AUTHENTICATION & AUTHORIZATION HELPERS
# ──────────────────────────────────────────────────────────────────────────────


def require_admin(user_data: dict = Depends(check_token)) -> dict:
    """
    FastAPI dependency: enforce admin-only access.


    Args:
        user_data (dict): Authenticated user data from check_token dependency.


    Returns:
        dict: User data if authorized, else raises HTTPException(403).


    Raises:
        HTTPException(403): If user role is not 'admin'.
    """
    if user_data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_data


# ── Endpoints ─────────────────────────────────────────────────────────────────


async def upload_file(
    file: UploadFile = File(...),
    user_data: dict = Depends(require_admin),
) -> FileUploadResponse:
    """
    Upload and ingest a file into RAG vector store (admin only).


    Args:
        file (UploadFile): File to upload (PDF, TXT, DOCX, PPTX).
        user_data (dict): Authenticated admin user data from require_admin dependency.


    Returns:
        FileUploadResponse: Ingestion summary with filename, size, text extracted, chunks created.


    Raises:
        HTTPException(403): If user is not an admin.
        HTTPException(400): If unsupported file type or empty file.
        HTTPException(413): If file exceeds 20 MB size limit.
        HTTPException(422): If text extraction fails (malformed file).
        HTTPException(500): If Qdrant ingestion fails.


    Process:
        1. Validate file type (check extension against SUPPORTED_EXTENSIONS)
        2. Read file content with size guard (max 20 MB)
        3. Extract text from file (handles PDF, DOCX, PPTX, TXT)
        4. Split text into chunks and embed via Qdrant
        5. Return ingestion statistics


    Note:
        - Supported formats: PDF, TXT, DOCX, PPTX
        - File size limit: 20 MB
        - Admin-only endpoint
    """
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

    filename = file.filename or "upload"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # Validate file type
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    # Read file with size guard
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) / 1_048_576:.1f} MB). Maximum: 20 MB.",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Extract and ingest into vector store
    result = ingest_uploaded_file(filename=filename, content=content)
    if result["status"] == "error":
        raise HTTPException(status_code=422, detail=result["message"])

    record_processed_file_stats(
        filename=filename,
        file_type=result.get("doc_type"),
        document_id=result.get("document_id"),
        chunks_created=result.get("chunks_created", 0),
        file_size_bytes=len(content),
    )

    return FileUploadResponse(
        filename=filename,
        file_size_kb=round(len(content) / 1024, 1),
        characters_extracted=result.get("characters_extracted", 0),
        file_type=result.get("doc_type"),
        page_count=result.get("page_count"),
        used_ocr=result.get("used_ocr", False),
        extraction_method=result.get("extraction_method"),
        empty_pages=result.get("empty_pages", []),
        chunks_created=result["chunks_created"],
        total_chunks=result["total_chunks"],
        message=f"✓ '{filename}' uploaded and ingested successfully.",
    )


def get_collection_stats(user_data: dict = Depends(require_admin)) -> dict:
    """
    Return document counts by file type plus collection info (admin only).
    """
    stats = get_ingestion_stats()
    collection_info = get_collection_info()
    return {
        **stats,
        "collection": collection_info,
    }
