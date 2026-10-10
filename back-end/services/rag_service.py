# ── LlamaIndex core ───────────────────────────────────────────────────────────
from llama_index.core import (
    VectorStoreIndex,
    Settings,
    Document,
    StorageContext,
    PromptTemplate,
)
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.core.llms import ChatMessage, MessageRole

# ── LlamaIndex integrations ───────────────────────────────────────────────────
from llama_index.vector_stores.qdrant import QdrantVectorStore as _QdrantVectorStoreBase
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama

# ── Qdrant ────────────────────────────────────────────────────────────────────
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    Filter,
    FieldCondition,
    MatchValue,
    FilterSelector,
)

from typing import List, Optional, Iterator
import re
import logging
import io
import hashlib
import uuid
import base64
import json
import urllib.request
import urllib.error
import os
from datetime import datetime, timezone

from config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_EMBEDDING_MODEL,
    QDRANT_URL,
    QDRANT_COLLECTION_NAME,
    TEMP_COLLECTION_NAME,
    OCR_PROVIDER,
    OCR_ENABLED,
    OCR_MODE,
    OCR_OLLAMA_MODEL,
)
from services.personalities_store import (
    STANDARD_PERSONALITY_ID,
    get_personality_by_id,
)


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


# =====================================================================
# PAYLOAD WHITELIST — seuls ces champs sont conservés dans Qdrant
# =====================================================================

_ALLOWED_PAYLOAD_KEYS = {
    "document_id",
    "source_filename",
    "source_path",
    "source_type",
    "file_hash",
    "file_size_mb",
    "unit_count",
    "unit_label",
    "used_ocr",
    "ocr_needed",
    "extraction_method",
    "page_number",
    "chunk_index",
    "chunk_total",
    "chunk_label",
    "ingested_at",
    "chunk_id",
    # Champs LlamaIndex nécessaires pour la récupération interne
    "_node_content",
    "_node_type",
    "doc_id",
    "ref_doc_id",
}

# Champs injectés par LlamaIndex qu'on veut supprimer du payload Qdrant
# ATTENTION : _node_content et _node_type sont NÉCESSAIRES pour le retrieval
# (metadata_dict_to_node les utilise pour reconstruire les nodes).
# On retire uniquement les alias redondants.
_STRIP_PAYLOAD_KEYS = {"doc_id", "ref_doc_id"}


class QdrantVectorStore(_QdrantVectorStoreBase):
    """
    Sous-classe de QdrantVectorStore qui retire les champs internes LlamaIndex
    (_node_content, _node_type, doc_id, ref_doc_id) du payload Qdrant.
    Ces champs sont injectés par node_to_metadata_dict() dans la méthode
    _build_points() et ne peuvent pas être filtrés autrement.
    """

    def _build_points(self, nodes, sparse_vector_name):  # type: ignore[override]
        points, ids = super()._build_points(nodes, sparse_vector_name)
        for point in points:
            for key in _STRIP_PAYLOAD_KEYS:
                point.payload.pop(key, None)
        return points, ids


# =====================================================================
# LLM / EMBEDDINGS
# =====================================================================

Settings.embed_model = OllamaEmbedding(
    model_name=OLLAMA_EMBEDDING_MODEL,
    base_url=OLLAMA_BASE_URL,
)

Settings.llm = Ollama(
    model=OLLAMA_MODEL,
    base_url=OLLAMA_BASE_URL,
    request_timeout=90.0,
    temperature=0,
)


# =====================================================================
# QDRANT
# =====================================================================

qdrant_client = QdrantClient(url=QDRANT_URL)
COLLECTION_NAME = QDRANT_COLLECTION_NAME
index_cache: dict[str, VectorStoreIndex] = {}


def create_semantic_splitter(buffer_size=1, breakpoint_percentile_threshold=95):
    return SemanticSplitterNodeParser(
        embed_model=Settings.embed_model,
        buffer_size=buffer_size,
        breakpoint_percentile_threshold=breakpoint_percentile_threshold,
    )


text_splitter = create_semantic_splitter()


def _collection_exists(collection_name: str) -> bool:
    collections = qdrant_client.get_collections().collections
    return any(c.name == collection_name for c in collections)


def _get_index(collection_name: str) -> Optional[VectorStoreIndex]:
    cached = index_cache.get(collection_name)
    if cached is not None:
        return cached

    if not _collection_exists(collection_name):
        return None

    vector_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=collection_name,
    )
    index = VectorStoreIndex.from_vector_store(vector_store)
    index_cache[collection_name] = index
    return index


def initialize_index():
    try:
        if not _collection_exists(COLLECTION_NAME):
            return None

        vector_store = QdrantVectorStore(
            client=qdrant_client,
            collection_name=COLLECTION_NAME,
        )
        index = VectorStoreIndex.from_vector_store(vector_store)
        index_cache[COLLECTION_NAME] = index
        return index
    except Exception as e:
        logger.error(f"Error initializing index: {e}")
        return None


index = initialize_index()


# =====================================================================
# FILE EXTRACTION
# =====================================================================

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".pptx"}
MIN_PDF_TEXT_CHARS = 50

# Retrieval tuning
RETRIEVE_TOP_K = 8
FINAL_CONTEXT_CHUNKS = 5
MAX_CHUNKS_PER_DOCUMENT = 2
MAX_EXCERPT_CHARS = 240
MAX_CONTEXT_CHARS_PER_CHUNK = 1800
MIN_RELEVANCE_SCORE = 0.39  # Seuil minimum de pertinence — chunks en dessous = ignorés


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _normalize_source_path(source_path: Optional[str]) -> Optional[str]:
    if not source_path:
        return None
    try:
        return os.path.abspath(source_path)
    except Exception:
        return source_path


def _build_document_id(
    filename: str,
    source_path: Optional[str],
    file_hash: Optional[str] = None,
) -> str:
    normalized_path = _normalize_source_path(source_path)
    if normalized_path:
        return hashlib.sha256(
            normalized_path.encode("utf-8", errors="ignore")
        ).hexdigest()
    seed = f"{filename}:{file_hash or ''}"
    return hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()


def _safe_excerpt(text: str, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def run_ocr_on_pdf(
    content: bytes,
    provider: str = "none",
    api_key: Optional[str] = None,
    api_url: Optional[str] = None,
) -> str:
    if provider == "none":
        logger.warning("OCR provider is disabled; skipping OCR.")
        return ""

    if provider == "ollama":
        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber is not installed. Run: pip install pdfplumber")
            return ""

        url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
        prompt = (
            "Extract all text from this image. "
            "Return only the extracted text, preserving line breaks."
        )

        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                page_images = []
                for page in pdf.pages:
                    image = page.to_image(resolution=200).original
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    page_images.append(
                        base64.b64encode(buffer.getvalue()).decode("ascii")
                    )
        except Exception as exc:
            logger.warning("Ollama OCR image render failed: %s", exc)
            return ""

        outputs = []
        for image_b64 in page_images:
            payload = {
                "model": OCR_OLLAMA_MODEL,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = resp.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="ignore")
                logger.warning("Ollama OCR error %s: %s", exc.code, err_body)
                return ""
            except urllib.error.URLError as exc:
                logger.warning("Ollama OCR connection error: %s", exc.reason)
                return ""

            try:
                response = json.loads(body)
            except json.JSONDecodeError:
                logger.warning("Ollama OCR returned non-JSON response.")
                return ""

            outputs.append(response.get("response", "").strip())

        return "\n\n".join([o for o in outputs if o])

    logger.warning("OCR provider '%s' is not configured.", provider)
    return ""


def extract_document_payload(filename: str, content: bytes) -> dict:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if ext in (".txt", ".md"):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        text = text.strip()
        if not text:
            raise ValueError("The text file appears to be empty.")
        return {
            "text": text,
            "doc_type": ext.lstrip("."),
            "page_count": 1,
            "unit_count": 1,
            "unit_label": "pages",
            "used_ocr": False,
            "ocr_needed": False,
            "ocr_failed": False,
            "extraction_method": "plain-text",
            "pages": [{"page_number": 1, "text": text}],
            "empty_pages": [],
        }

    if ext == ".pdf":
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError(
                "pdfplumber is not installed. Run: pip install pdfplumber"
            )

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            raw_pages = [(page.extract_text() or "").strip() for page in pdf.pages]
            page_count = len(raw_pages)

        pages = []
        empty_pages = []
        for idx, page_text in enumerate(raw_pages, start=1):
            if not page_text:
                empty_pages.append(idx)
            pages.append({"page_number": idx, "text": page_text})

        non_empty = [p["text"] for p in pages if p["text"]]
        ocr_needed = len("".join(non_empty)) < MIN_PDF_TEXT_CHARS

        return {
            "text": "\n\n".join(non_empty) if non_empty else "",
            "doc_type": "pdf",
            "page_count": page_count,
            "unit_count": page_count,
            "unit_label": "pages",
            "used_ocr": False,
            "ocr_needed": ocr_needed,
            "ocr_failed": False,
            "extraction_method": "pdfplumber",
            "pages": pages,
            "empty_pages": empty_pages,
        }

    if ext == ".docx":
        try:
            from docx import Document as DocxDocument
        except ImportError:
            raise RuntimeError(
                "python-docx is not installed. Run: pip install python-docx"
            )

        doc = DocxDocument(io.BytesIO(content))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

        if not paragraphs:
            raise ValueError("Could not extract text from DOCX file.")

        text = "\n\n".join(paragraphs)
        return {
            "text": text,
            "doc_type": "docx",
            "page_count": None,
            "unit_count": max(1, len(paragraphs)),
            "unit_label": "paragraphs",
            "used_ocr": False,
            "ocr_needed": False,
            "ocr_failed": False,
            "extraction_method": "python-docx",
            "pages": [{"page_number": 1, "text": text}],
            "empty_pages": [],
        }

    if ext == ".pptx":
        try:
            from pptx import Presentation
        except ImportError:
            raise RuntimeError(
                "python-pptx is not installed. Run: pip install python-pptx"
            )

        prs = Presentation(io.BytesIO(content))
        slides = []
        empty_pages = []

        for idx, slide in enumerate(prs.slides, start=1):
            parts = []
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text = shape.text.strip()
                    if text:
                        parts.append(text)
            slide_text = "\n".join(parts).strip()
            if not slide_text:
                empty_pages.append(idx)
            slides.append({"page_number": idx, "text": slide_text})

        non_empty = [s["text"] for s in slides if s["text"]]
        if not non_empty:
            raise ValueError("Could not extract text from PPTX file.")

        return {
            "text": "\n\n".join(non_empty),
            "doc_type": "pptx",
            "page_count": len(slides),
            "unit_count": len(slides),
            "unit_label": "slides",
            "used_ocr": False,
            "ocr_needed": False,
            "ocr_failed": False,
            "extraction_method": "python-pptx",
            "pages": slides,
            "empty_pages": empty_pages,
        }

    raise ValueError(f"Unhandled extension: {ext}")


def extract_text_with_optional_ocr(
    filename: str,
    content: bytes,
    enable_ocr: bool = False,
    ocr_provider: str = "none",
    ocr_mode: str = "auto",
    ocr_api_key: Optional[str] = None,
    ocr_api_url: Optional[str] = None,
) -> dict:
    payload = extract_document_payload(filename, content)

    if payload.get("doc_type") != "pdf":
        return payload

    if ocr_mode != "always" and not payload.get("ocr_needed"):
        return payload

    if not enable_ocr:
        payload["ocr_failed"] = True
        payload["error_message"] = "OCR required but disabled."
        return payload

    ocr_text = run_ocr_on_pdf(
        content,
        provider=ocr_provider,
        api_key=ocr_api_key,
        api_url=ocr_api_url,
    ).strip()

    if not ocr_text:
        payload["ocr_failed"] = True
        payload["error_message"] = "OCR failed or returned no text."
        return payload

    payload["text"] = ocr_text
    payload["used_ocr"] = True
    payload["ocr_failed"] = False
    payload["extraction_method"] = f"ocr:{ocr_provider}"
    payload["pages"] = [{"page_number": 1, "text": ocr_text}]
    payload["empty_pages"] = []
    return payload


# =====================================================================
# INGESTION
# =====================================================================


def _create_documents_from_payload(payload: dict) -> list[Document]:
    documents: list[Document] = []

    text = (payload.get("text") or "").strip()
    if not text and not payload.get("pages"):
        return documents

    metadata = {
        "document_id": payload.get("document_id"),
        "source_filename": payload.get("filename"),
        "source_path": payload.get("source_path"),
        "source_type": payload.get("file_type"),
        "file_hash": payload.get("file_hash"),
        "file_size_mb": payload.get("file_size_mb"),
        "unit_count": payload.get("unit_count"),
        "unit_label": payload.get("unit_label"),
        "used_ocr": payload.get("used_ocr"),
        "ocr_needed": payload.get("ocr_needed"),
        "extraction_method": payload.get("extraction_method"),
    }

    pages = payload.get("pages") or []
    if pages:
        for page in pages:
            page_text = (page.get("text") or "").strip()
            if not page_text:
                continue
            page_metadata = {**metadata, "page_number": page.get("page_number")}
            documents.append(Document(text=page_text, metadata=page_metadata))
    else:
        documents.append(Document(text=text, metadata=metadata))

    return documents


def _ensure_named_collection(collection_name: str) -> None:
    if _collection_exists(collection_name):
        return

    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
    )


def _ensure_collection() -> None:
    _ensure_named_collection(COLLECTION_NAME)


def _session_collection_name(session_id: int) -> str:
    return f"{TEMP_COLLECTION_NAME}_session_{session_id}"


def _delete_existing_document_chunks(collection_name: str, document_id: str) -> None:
    if not document_id or not _collection_exists(collection_name):
        return

    try:
        qdrant_client.delete(
            collection_name=collection_name,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id),
                        )
                    ]
                )
            ),
        )
    except Exception as e:
        logger.warning(
            "Failed to delete previous chunks for document_id=%s: %s", document_id, e
        )


def ingest_file_payload(payload: dict, collection_name: str = COLLECTION_NAME) -> dict:
    global index
    try:
        documents = _create_documents_from_payload(payload)
        if not documents:
            return {"status": "error", "message": "No valid document content."}

        _ensure_named_collection(collection_name)

        document_id = payload.get("document_id")
        if document_id:
            _delete_existing_document_chunks(collection_name, document_id)

        vector_store = QdrantVectorStore(
            client=qdrant_client,
            collection_name=collection_name,
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        collection_index = _get_index(collection_name)
        if collection_index is None:
            collection_index = VectorStoreIndex.from_vector_store(
                vector_store,
                storage_context=storage_context,
            )
            index_cache[collection_name] = collection_index
            if collection_name == COLLECTION_NAME:
                index = collection_index

        nodes = text_splitter.get_nodes_from_documents(documents)
        total_chunks = len(nodes)
        if total_chunks == 0:
            return {"status": "error", "message": "No chunks created from document."}

        ingested_at = _now_iso()
        file_hash = payload.get("file_hash") or ""

        for idx, node in enumerate(nodes, start=1):
            node.metadata = node.metadata or {}
            node.metadata.update(
                {
                    "document_id": document_id,
                    "chunk_index": idx,
                    "chunk_total": total_chunks,
                    "chunk_label": f"chunk {idx}/{total_chunks}",
                    "ingested_at": ingested_at,
                }
            )

            chunk_seed = f"{document_id}:{file_hash}:{idx}:{node.get_content()}"
            chunk_id = _hash_text(chunk_seed)
            node.metadata["chunk_id"] = chunk_id
            node.id_ = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))

        collection_index.insert_nodes(nodes)

        index_cache.pop(collection_name, None)
        if collection_name == COLLECTION_NAME:
            index = None

        return {
            "status": "success",
            "documents_added": len(documents),
            "chunks_created": total_chunks,
            "total_chunks": total_chunks,
        }
    except Exception as e:
        logger.error(f"Error ingesting payload: {e}")
        return {"status": "error", "message": str(e)}


def ingest_documents(items: List[dict], collection_name: str = COLLECTION_NAME) -> dict:
    total_documents = 0
    total_chunks = 0

    for payload in items:
        result = ingest_file_payload(payload, collection_name=collection_name)
        if result.get("status") != "success":
            return result
        total_documents += result.get("documents_added", 0)
        total_chunks += result.get("chunks_created", 0)

    return {
        "status": "success",
        "documents_added": total_documents,
        "chunks_created": total_chunks,
        "total_chunks": total_chunks,
        "message": f"Successfully split {total_documents} document(s) into {total_chunks} optimized chunks",
    }


def ingest_uploaded_file(
    filename: str,
    content: bytes,
    source_path: Optional[str] = None,
    enable_ocr: Optional[bool] = None,
    ocr_provider: Optional[str] = None,
    ocr_mode: str = "auto",
    ocr_api_key: Optional[str] = None,
    ocr_api_url: Optional[str] = None,
    collection_name: str = COLLECTION_NAME,
) -> dict:
    if enable_ocr is None:
        enable_ocr = OCR_ENABLED
    if ocr_provider is None:
        ocr_provider = OCR_PROVIDER
    if ocr_mode == "auto":
        ocr_mode = OCR_MODE

    extraction = extract_text_with_optional_ocr(
        filename,
        content,
        enable_ocr=enable_ocr,
        ocr_provider=ocr_provider,
        ocr_mode=ocr_mode,
        ocr_api_key=ocr_api_key,
        ocr_api_url=ocr_api_url,
    )
    if extraction.get("ocr_failed"):
        return {"status": "error", "message": extraction.get("error_message")}

    file_hash = _hash_bytes(content)
    file_size_mb = round(len(content) / (1024 * 1024), 2)
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    document_id = _build_document_id(filename, source_path, file_hash)

    payload = {
        **extraction,
        "document_id": document_id,
        "filename": filename,
        "source_path": _normalize_source_path(source_path),
        "source_ext": ext,
        "file_hash": file_hash,
        "file_size_mb": file_size_mb,
        "file_type": extraction.get("doc_type"),
    }

    result = ingest_file_payload(payload, collection_name=collection_name)
    if result.get("status") != "success":
        return result

    return {
        **result,
        "document_id": document_id,
        "file_hash": file_hash,
        "file_size_mb": file_size_mb,
        "doc_type": extraction.get("doc_type"),
        "page_count": extraction.get("page_count"),
        "used_ocr": extraction.get("used_ocr"),
        "extraction_method": extraction.get("extraction_method"),
        "empty_pages": extraction.get("empty_pages"),
        "characters_extracted": len(extraction.get("text", "")),
    }


def add_documents(items: List[dict]) -> dict:
    return ingest_documents(items)


def ingest_chat_upload(
    session_id: int,
    filename: str,
    content: bytes,
    source_path: Optional[str] = None,
) -> dict:
    collection_name = _session_collection_name(session_id)
    return ingest_uploaded_file(
        filename=filename,
        content=content,
        source_path=source_path,
        collection_name=collection_name,
    )


def reset_session_collection(session_id: int) -> dict:
    collection_name = _session_collection_name(session_id)
    try:
        if not _collection_exists(collection_name):
            return {"status": "success", "message": "Session collection missing"}
        qdrant_client.delete_collection(collection_name)
        index_cache.pop(collection_name, None)
        return {"status": "success", "message": "Session collection deleted"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def query_rag(question: str, similarity_top_k: int = 5) -> str:
    global index
    try:
        if index is None:
            index = initialize_index()

        if index is None:
            return "No documents in the knowledge base. Please upload documents first."

        query_engine = index.as_query_engine(similarity_top_k=similarity_top_k)
        response = query_engine.query(question)
        return str(response)
    except Exception as e:
        logger.error(f"Query error: {e}")
        return f"Error: {str(e)}"


def get_collection_info() -> dict:
    try:
        collections = qdrant_client.get_collections().collections
        collection_exists = any(c.name == COLLECTION_NAME for c in collections)

        if not collection_exists:
            return {
                "status": "success",
                "collection_name": COLLECTION_NAME,
                "points_count": 0,
                "message": "Collection does not exist yet",
            }

        info = qdrant_client.get_collection(COLLECTION_NAME)
        return {
            "status": "success",
            "collection_name": COLLECTION_NAME,
            "points_count": info.points_count,
            "vectors_in_collection": info.points_count,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


CACHE_STATS_PATH = os.path.join("data", "processed-files-cache.json")


def _load_processed_cache() -> dict:
    if not os.path.exists(CACHE_STATS_PATH):
        return {}
    try:
        with open(CACHE_STATS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_processed_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_STATS_PATH), exist_ok=True)
    with open(CACHE_STATS_PATH, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2, sort_keys=True)


def record_processed_file_stats(
    *,
    filename: str,
    file_type: str | None,
    document_id: str | None,
    chunks_created: int,
    source_path: str | None = None,
    file_size_bytes: int | None = None,
) -> None:
    cache = _load_processed_cache()
    cache_key = source_path or filename
    cache[cache_key] = {
        "status": "success",
        "filename": filename,
        "file_type": file_type,
        "document_id": document_id,
        "chunks_count": chunks_created,
        "size_bytes": file_size_bytes,
        "last_processed_at": _now_iso(),
    }
    _save_processed_cache(cache)


def _get_ingestion_stats_from_collection() -> dict:
    if not _collection_exists(COLLECTION_NAME):
        return {}

    counts = {
        "pdf": 0,
        "txt": 0,
        "csv": 0,
        "excel": 0,
        "docx": 0,
        "pptx": 0,
        "other": 0,
    }
    seen_documents: set[str] = set()
    offset = None

    while True:
        points, offset = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        if not points:
            break

        for point in points:
            payload = point.payload or {}
            document_id = (
                payload.get("document_id")
                or payload.get("source_path")
                or payload.get("source_filename")
                or str(point.id)
            )
            if document_id in seen_documents:
                continue
            seen_documents.add(document_id)

            source_type = str(
                payload.get("source_type")
                or payload.get("doc_type")
                or payload.get("file_type")
                or "other"
            ).lower()

            if source_type == "pdf":
                counts["pdf"] += 1
            elif source_type in ("txt", "md", "markdown", "text"):
                counts["txt"] += 1
            elif source_type == "csv":
                counts["csv"] += 1
            elif source_type in ("xls", "xlsx", "excel"):
                counts["excel"] += 1
            elif source_type == "docx":
                counts["docx"] += 1
            elif source_type == "pptx":
                counts["pptx"] += 1
            else:
                counts["other"] += 1

        if offset is None:
            break

    total_files = sum(counts.values())
    return {
        "status": "success",
        "total_files": total_files,
        "pdf_count": counts["pdf"],
        "txt_count": counts["txt"],
        "csv_count": counts["csv"],
        "excel_count": counts["excel"],
        "docx_count": counts["docx"],
        "pptx_count": counts["pptx"],
        "other_count": counts["other"],
    }


def get_ingestion_stats() -> dict:
    cache = _load_processed_cache()
    if cache:
        counts = {
            "pdf": 0,
            "txt": 0,
            "csv": 0,
            "excel": 0,
            "docx": 0,
            "pptx": 0,
            "other": 0,
        }

        # The cache stores one record per processed file, which is the right
        # level for the stats page. Qdrant stores chunks, so counting it directly
        # would inflate the totals.
        seen_filenames: set = set()

        for path, meta in cache.items():
            if isinstance(path, str) and (path.startswith("_") or path == "summary"):
                continue
            if isinstance(meta, dict):
                status = meta.get("status")
                if status not in (None, "success"):
                    continue
                filename = meta.get("filename")
            else:
                filename = None

            source = filename or os.path.basename(path) or ""

            if source and source in seen_filenames:
                continue
            if source:
                seen_filenames.add(source)

            ext = os.path.splitext(source)[1].lower()
            if not ext:
                counts["other"] += 1
                continue

            if ext == ".pdf":
                counts["pdf"] += 1
            elif ext in (".txt", ".md"):
                counts["txt"] += 1
            elif ext == ".csv":
                counts["csv"] += 1
            elif ext in (".xls", ".xlsx"):
                counts["excel"] += 1
            elif ext == ".docx":
                counts["docx"] += 1
            elif ext == ".pptx":
                counts["pptx"] += 1
            else:
                counts["other"] += 1

        total_files = sum(counts.values())

        return {
            "status": "success",
            "total_files": total_files,
            "pdf_count": counts["pdf"],
            "txt_count": counts["txt"],
            "csv_count": counts["csv"],
            "excel_count": counts["excel"],
            "docx_count": counts["docx"],
            "pptx_count": counts["pptx"],
            "other_count": counts["other"],
        }

    collection_stats = _get_ingestion_stats_from_collection()
    if collection_stats:
        return collection_stats

    counts = {
        "pdf": 0,
        "txt": 0,
        "csv": 0,
        "excel": 0,
        "docx": 0,
        "pptx": 0,
        "other": 0,
    }

    # Dédupliquer par filename : un même fichier peut avoir été ingéré depuis
    # plusieurs chemins différents (ex: deux machines).
    # On ne compte chaque nom de fichier qu'une seule fois.
    seen_filenames: set = set()

    for path, meta in cache.items():
        if isinstance(path, str) and (path.startswith("_") or path == "summary"):
            continue
        if isinstance(meta, dict):
            status = meta.get("status")
            if status not in (None, "success"):
                continue
            filename = meta.get("filename")
        else:
            filename = None

        source = filename or os.path.basename(path) or ""

        # Skip si ce nom de fichier a déjà été compté
        if source and source in seen_filenames:
            continue
        if source:
            seen_filenames.add(source)

        ext = os.path.splitext(source)[1].lower()
        if not ext:
            counts["other"] += 1
            continue

        if ext == ".pdf":
            counts["pdf"] += 1
        elif ext in (".txt", ".md"):
            counts["txt"] += 1
        elif ext == ".csv":
            counts["csv"] += 1
        elif ext in (".xls", ".xlsx"):
            counts["excel"] += 1
        elif ext == ".docx":
            counts["docx"] += 1
        elif ext == ".pptx":
            counts["pptx"] += 1
        else:
            counts["other"] += 1

    total_files = sum(counts.values())

    return {
        "status": "success",
        "total_files": total_files,
        "pdf_count": counts["pdf"],
        "txt_count": counts["txt"],
        "csv_count": counts["csv"],
        "excel_count": counts["excel"],
        "docx_count": counts["docx"],
        "pptx_count": counts["pptx"],
        "other_count": counts["other"],
    }


def reset_collection() -> dict:
    global index
    try:
        qdrant_client.delete_collection(COLLECTION_NAME)
        index_cache.pop(COLLECTION_NAME, None)
        index = None
        return {"status": "success", "message": "Collection deleted successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# =====================================================================
# PROMPTS
# =====================================================================

CONDENSE_PROMPT = PromptTemplate(
    "Étant donné l'historique de conversation ci-dessous et une question de suivi, "
    "reformulez la question de suivi en une question autonome qui capture tout le contexte nécessaire. "
    "Répondez uniquement avec la question reformulée, sans explication.\n\n"
    "Historique de conversation :\n"
    "{chat_history}\n\n"
    "Question de suivi : {question}\n"
    "Question autonome :"
)

RAG_ROUTER_PROMPT = PromptTemplate(
    "Tu es un routeur. Decide si la question doit utiliser la base documentaire (RAG) ou non. "
    "Utilise RAG si l'utilisateur demande des infos qui devraient venir des documents. "
    "N'utilise PAS RAG pour salutations, bavardage, remerciements, ou questions sur la conversation "
    "(preferences mentionnees, 'tu te souviens...'). "
    "Si incertain, choisis RAG. "
    "Reponds avec un seul token: RAG ou NO_RAG.\n\n"
    "Historique recent:\n"
    "{chat_history}\n\n"
    "Question: {question}\n"
    "Decision:"
)


def _resolve_system_prompt(personality_id: int | None) -> str:
    standard = get_personality_by_id(STANDARD_PERSONALITY_ID)
    if standard is None:
        raise RuntimeError("Standard personality not found in personalities.json.")

    standard_prompt = (standard.get("system_prompt") or "").strip()
    if not standard_prompt:
        raise RuntimeError(
            "Standard personality must define a non-empty system_prompt."
        )

    if personality_id is None or personality_id == STANDARD_PERSONALITY_ID:
        return standard_prompt

    personality = get_personality_by_id(personality_id)
    if personality is None:
        return standard_prompt

    personality_prompt = (personality.get("system_prompt") or "").strip()
    if not personality_prompt:
        return standard_prompt

    personality_name = (personality.get("name") or "Custom").strip()
    return (
        f"{standard_prompt}\n\n"
        "Regles de base obligatoires: conserve toutes les instructions Standard ci-dessus.\n"
        f"Ajouts de la personnalite choisie ({personality_name}) :\n"
        f"{personality_prompt}"
    )


def _to_chat_messages(history: list) -> List[ChatMessage]:
    role_map = {
        "user": MessageRole.USER,
        "assistant": MessageRole.ASSISTANT,
    }
    return [
        ChatMessage(
            role=role_map.get(msg.get("role", "user"), MessageRole.USER),
            content=msg["content"],
        )
        for msg in history
    ]


def _history_to_text(history: list) -> str:
    lines = []
    for msg in history[-10:]:
        role = "Utilisateur" if msg.get("role") == "user" else "Assistant"
        content = (msg.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _should_use_rag(question: str, history: list) -> bool:
    history_text = _history_to_text(history) or "(aucun)"
    prompt = RAG_ROUTER_PROMPT.format(
        chat_history=history_text,
        question=question.strip(),
    )

    try:
        response = Settings.llm.chat(
            [ChatMessage(role=MessageRole.USER, content=prompt)]
        )
        decision = str(response.message.content).strip().upper()
        decision = re.sub(r"[^A-Z_]", "", decision)

        if "NO_RAG" in decision:
            return False
        if "RAG" in decision:
            return True
    except Exception as e:
        logger.warning("RAG routing failed, fallback to RAG: %s", e)

    return True


def _condense_question(question: str, history: list) -> str:
    if not history:
        return question.strip()

    chat_history_text = _history_to_text(history)
    prompt = CONDENSE_PROMPT.format(
        chat_history=chat_history_text,
        question=question.strip(),
    )

    try:
        response = Settings.llm.chat(
            [ChatMessage(role=MessageRole.USER, content=prompt)]
        )
        condensed = str(response.message.content).strip()
        return condensed or question.strip()
    except Exception as e:
        logger.warning("Condense failed, fallback to original question: %s", e)
        return question.strip()


def _retrieve_nodes(
    question: str,
    similarity_top_k: int,
    collection_name: str,
) -> list:
    index_for_collection = _get_index(collection_name)
    if index_for_collection is None:
        return []
    retriever = index_for_collection.as_retriever(similarity_top_k=similarity_top_k)
    return retriever.retrieve(question)


def _merge_and_rank_results(question: str, session_id: int | None = None) -> list:
    retrieved = []

    if _collection_exists(COLLECTION_NAME):
        retrieved.extend(_retrieve_nodes(question, RETRIEVE_TOP_K, COLLECTION_NAME))

    if session_id is not None:
        session_collection = _session_collection_name(session_id)
        if _collection_exists(session_collection):
            retrieved.extend(
                _retrieve_nodes(question, RETRIEVE_TOP_K, session_collection)
            )

    unique = {}
    for item in retrieved:
        node = item.node
        metadata = node.metadata or {}
        key = (
            metadata.get("chunk_id")
            or node.node_id
            or metadata.get("document_id")
            or metadata.get("source_path")
            or metadata.get("source_filename")
            or str(uuid.uuid4())
        )

        existing = unique.get(key)
        current_score = item.score if item.score is not None else 0
        existing_score = (
            existing.score if existing is not None and existing.score is not None else 0
        )

        if existing is None or current_score > existing_score:
            unique[key] = item

    ranked = list(unique.values())
    ranked.sort(key=lambda x: x.score if x.score is not None else 0, reverse=True)
    return ranked


def _select_final_chunks(retrieved_nodes: list) -> list:
    selected = []
    per_document_counts: dict[str, int] = {}

    for item in retrieved_nodes:
        # Filter out chunks below relevance threshold
        item_score = item.score if item.score is not None else 0
        if item_score < MIN_RELEVANCE_SCORE:
            continue

        metadata = item.node.metadata or {}
        document_key = (
            metadata.get("document_id")
            or metadata.get("source_path")
            or metadata.get("source_filename")
            or "unknown-document"
        )

        current_count = per_document_counts.get(document_key, 0)
        if current_count >= MAX_CHUNKS_PER_DOCUMENT:
            continue

        selected.append(item)
        per_document_counts[document_key] = current_count + 1

        if len(selected) >= FINAL_CONTEXT_CHUNKS:
            break

    return selected


def _format_context_from_nodes(retrieved_nodes: list) -> str:
    blocks = []

    for idx, item in enumerate(retrieved_nodes, start=1):
        node = item.node
        metadata = node.metadata or {}
        text = node.get_content().strip()
        if len(text) > MAX_CONTEXT_CHARS_PER_CHUNK:
            text = text[: MAX_CONTEXT_CHARS_PER_CHUNK - 1].rstrip() + "…"

        filename = metadata.get("source_filename") or "Document"
        file_type = (metadata.get("source_type") or "unknown").upper()
        page_number = metadata.get("page_number")
        chunk_label = metadata.get("chunk_label")
        score = item.score if item.score is not None else 0

        location_parts = []
        if page_number is not None:
            location_parts.append(f"page {page_number}")
        if chunk_label:
            location_parts.append(chunk_label)

        location_str = (
            " • ".join(location_parts) if location_parts else "unknown location"
        )

        blocks.append(
            f"[Source {idx}] {filename} ({file_type}) | {location_str} | score={score:.4f}\n{text}"
        )

    return "\n\n".join(blocks)


def _build_sources(retrieved_nodes: list) -> list[dict]:
    sources = []

    for item in retrieved_nodes:
        node = item.node
        metadata = node.metadata or {}
        text = node.get_content().strip()

        sources.append(
            {
                "filename": metadata.get("source_filename") or "Document",
                "file_type": metadata.get("source_type")
                or metadata.get("doc_type")
                or "unknown",
                "file_size_mb": metadata.get("file_size_mb"),
                "page_count": metadata.get("page_count"),
                "page_number": metadata.get("page_number"),
                "chunk_index": metadata.get("chunk_index"),
                "chunk_total": metadata.get("chunk_total"),
                "chunk_label": metadata.get("chunk_label"),
                "score": item.score,
                "excerpt": _safe_excerpt(text),
                "document_id": metadata.get("document_id"),
                "source_path": metadata.get("source_path"),
            }
        )

    return sources


def _build_answer_messages(
    system_prompt_text: str,
    question: str,
    standalone_question: str,
    history: list,
    context_str: str,
) -> list[ChatMessage]:
    history_text = _history_to_text(history)

    # Le system prompt de la personnalité est la seule source d'instructions comportementales.
    system_content = system_prompt_text

    user_content = (
        "Historique récent de conversation :\n"
        f"{history_text or '(aucun)'}\n\n"
        "Question de l'utilisateur :\n"
        f"{question.strip()}\n\n"
        "Contexte documentaire disponible (utilise-le uniquement s'il est pertinent) :\n"
        "---------------------\n"
        f"{context_str}\n"
        "---------------------\n\n"
        "Réponds maintenant à l'utilisateur."
    )

    return [
        ChatMessage(role=MessageRole.SYSTEM, content=system_content),
        ChatMessage(role=MessageRole.USER, content=user_content),
    ]


def _build_plain_messages(
    system_prompt_text: str,
    history: list,
    question: str,
) -> list[ChatMessage]:
    return [
        ChatMessage(role=MessageRole.SYSTEM, content=system_prompt_text),
        *(_to_chat_messages(history)),
        ChatMessage(role=MessageRole.USER, content=question.strip()),
    ]


def generate_session_title(question: str, answer: str) -> str:
    try:
        prompt_msg = ChatMessage(
            role=MessageRole.USER,
            content=(
                "Génère un titre très court (3 à 6 mots maximum) qui résume "
                "l'idée générale de cet échange. Le titre doit être nominal "
                "(pas de verbe conjugué), dans la même langue que la question. "
                "Retourne UNIQUEMENT le titre, sans guillemets, sans ponctuation finale.\n\n"
                f"Question : {question}\n"
                f"Réponse : {answer[:300]}"
            ),
        )
        response = Settings.llm.chat([prompt_msg])
        title = str(response.message.content).strip().strip('"').strip("'")
        words = title.split()
        if len(words) > 8:
            title = " ".join(words[:6]) + "…"
        return title if title else " ".join(question.split()[:6])
    except Exception as e:
        logger.error(f"Title generation error: {e}")
        words = question.split()
        return " ".join(words[:6]) + ("…" if len(words) > 6 else "")


def generate_chat_response(
    question: str,
    history: list,
    personality_id: int | None = None,
    similarity_top_k: int = 5,
    session_id: int | None = None,
) -> dict:
    global index

    system_prompt_text = _resolve_system_prompt(personality_id)

    try:
        question_clean = question.strip()

        if not _should_use_rag(question_clean, history):
            messages = _build_plain_messages(
                system_prompt_text=system_prompt_text,
                history=history,
                question=question_clean,
            )
            response = Settings.llm.chat(messages)
            return {
                "answer": str(response.message.content).strip(),
                "sources": [],
            }

        standalone_question = _condense_question(question_clean, history)

        # Refresh global index lazily if needed
        if _collection_exists(COLLECTION_NAME) and index is None:
            index = initialize_index()

        retrieved = _merge_and_rank_results(
            question=standalone_question,
            session_id=session_id,
        )

        final_nodes = _select_final_chunks(retrieved)

        if final_nodes:
            context_str = _format_context_from_nodes(final_nodes)
            messages = _build_answer_messages(
                system_prompt_text=system_prompt_text,
                question=question_clean,
                standalone_question=standalone_question,
                history=history,
                context_str=context_str,
            )
            response = Settings.llm.chat(messages)
            answer = str(response.message.content).strip()
            sources = _build_sources(final_nodes)
            return {"answer": answer, "sources": sources}

        # No KB result → plain LLM fallback
        fallback_messages = [
            ChatMessage(
                role=MessageRole.SYSTEM,
                content=(
                    f"{system_prompt_text}\n\n"
                    "Aucune information pertinente n'a été retrouvée dans la base documentaire. "
                    "Réponds prudemment à partir de tes connaissances générales, "
                    "et indique que l'utilisateur peut charger plus de documents pour une réponse mieux fondée."
                ),
            ),
            *(_to_chat_messages(history)),
            ChatMessage(role=MessageRole.USER, content=question_clean),
        ]
        llm_response = Settings.llm.chat(fallback_messages)
        return {
            "answer": str(llm_response.message.content).strip(),
            "sources": [],
        }

    except Exception as e:
        logger.error(f"Chat generation error: {e}")
        return {"answer": f"Error generating response: {str(e)}", "sources": []}


def _stream_llm_response(messages: list[ChatMessage]) -> Iterator[str]:
    """
    Yield LLM output token by token.
    Ollama/LlamaIndex renvoie les chunks en mode CUMULATIF via chunk.message.content.
    On calcule le delta manuellement. Fallback sur chat() classique si besoin.
    """
    try:
        stream = Settings.llm.stream_chat(messages)
        last_content = ""
        emitted_any = False

        for chunk in stream:
            current_content = ""

            if hasattr(chunk, "delta") and chunk.delta:
                current_content = last_content + str(chunk.delta)
            elif hasattr(chunk, "message") and getattr(chunk.message, "content", None):
                current_content = str(chunk.message.content)
            elif isinstance(chunk, str) and chunk:
                current_content = last_content + chunk
            else:
                continue

            if current_content.startswith(last_content):
                delta = current_content[len(last_content) :]
            else:
                delta = current_content
                last_content = ""

            if delta:
                emitted_any = True
                last_content = current_content
                yield delta

        if not emitted_any:
            raise ValueError("Stream produced no tokens")

    except Exception as e:
        logger.warning("LLM streaming failed (%s), fallback to non-stream mode.", e)
        try:
            response = Settings.llm.chat(messages)
            text = str(response.message.content).strip()
            if text:
                yield text
        except Exception as fallback_error:
            logger.error("Streaming fallback chat also failed: %s", fallback_error)
            yield ""


def generate_chat_response_stream(
    question: str,
    history: list,
    personality_id: int | None = None,
    similarity_top_k: int = 5,
    session_id: int | None = None,
) -> dict:
    global index

    system_prompt_text = _resolve_system_prompt(personality_id)

    try:
        question_clean = question.strip()

        if not _should_use_rag(question_clean, history):
            messages = _build_plain_messages(
                system_prompt_text=system_prompt_text,
                history=history,
                question=question_clean,
            )
            return {
                "stream": _stream_llm_response(messages),
                "sources": [],
            }

        standalone_question = _condense_question(question_clean, history)

        if _collection_exists(COLLECTION_NAME) and index is None:
            index = initialize_index()

        retrieved = _merge_and_rank_results(
            question=standalone_question,
            session_id=session_id,
        )
        final_nodes = _select_final_chunks(retrieved)

        if final_nodes:
            context_str = _format_context_from_nodes(final_nodes)
            messages = _build_answer_messages(
                system_prompt_text=system_prompt_text,
                question=question_clean,
                standalone_question=standalone_question,
                history=history,
                context_str=context_str,
            )
            return {
                "stream": _stream_llm_response(messages),
                "sources": _build_sources(final_nodes),
            }

        fallback_messages = [
            ChatMessage(
                role=MessageRole.SYSTEM,
                content=(
                    f"{system_prompt_text}\n\n"
                    "Aucune information pertinente n'a été retrouvée dans la base documentaire. "
                    "Réponds prudemment à partir de tes connaissances générales, "
                    "et indique que l'utilisateur peut charger plus de documents pour une réponse mieux fondée."
                ),
            ),
            *(_to_chat_messages(history)),
            ChatMessage(role=MessageRole.USER, content=question_clean),
        ]

        return {
            "stream": _stream_llm_response(fallback_messages),
            "sources": [],
        }

    except Exception as e:
        logger.error("Chat streaming generation error: %s", e)
        error_message = f"Error generating response: {str(e)}"

        def _error_stream() -> Iterator[str]:
            yield error_message

        return {"stream": _error_stream(), "sources": []}
