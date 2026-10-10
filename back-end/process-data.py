import json
import os
from datetime import datetime, timezone

import xxhash
from rich.console import Console
from rich.prompt import Prompt

from services.rag_service import (
    SUPPORTED_EXTENSIONS,
    ingest_uploaded_file,
    reset_collection,
)
from config import OCR_ENABLED, OCR_PROVIDER, OCR_MODE


CACHE_PATH = os.path.join("data", "processed-files-cache.json")
console = Console()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_processed_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {}


def save_processed_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=2, sort_keys=True)


def _build_cache_summary(root: str, files: list[str], cache: dict) -> dict:
    processed_count = 0
    for path in files:
        meta = cache.get(path)
        if isinstance(meta, dict) and meta.get("status") == "success":
            processed_count += 1

    total_present = len(files)
    return {
        "generated_at": _now_iso(),
        "root": root,
        "total_present": total_present,
        "processed": processed_count,
        "unprocessed": max(total_present - processed_count, 0),
    }


def compute_fast_hash_from_bytes(content: bytes) -> str:
    """
    Fast non-cryptographic hash for cache invalidation / file change detection.
    Much faster than SHA-256 and sufficient for local ingestion cache usage.
    """
    return xxhash.xxh3_128_hexdigest(content)


def iter_supported_files(root: str):
    for base, _, files in os.walk(root):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                yield os.path.join(base, name)


def prompt_data_folder() -> str:
    while True:
        folder = Prompt.ask("Root data folder path")
        if not os.path.isdir(folder):
            console.print("[red]Folder not found. Try again.[/red]")
            continue

        subfolders = [
            name
            for name in sorted(os.listdir(folder))
            if os.path.isdir(os.path.join(folder, name))
        ]
        if not subfolders:
            return folder

        console.print("[bold]Select a subfolder to process:[/bold]")
        for idx, name in enumerate(subfolders, start=1):
            console.print(f"{idx}) {name}")

        choice = Prompt.ask(
            "Choose", choices=[str(i) for i in range(1, len(subfolders) + 1)]
        )
        return os.path.join(folder, subfolders[int(choice) - 1])


def process_folder(root: str) -> None:
    enable_ocr = OCR_ENABLED

    cache = load_processed_cache()
    processed = 0
    skipped = 0
    failed = 0

    files = list(iter_supported_files(root))
    if not files:
        console.print("[yellow]No supported files found.[/yellow]")
        return

    for path in files:
        try:
            stat = os.stat(path)
        except OSError as exc:
            failed += 1
            console.print(f"[red]Failed to stat {path}: {exc}[/red]")
            continue

        cached = cache.get(path)

        # Fast skip path: if size and mtime_ns didn't change, do not even read the file.
        if (
            cached
            and cached.get("size_bytes") == stat.st_size
            and cached.get("mtime_ns") == stat.st_mtime_ns
        ):
            skipped += 1
            console.print(f"[cyan]Skipped:[/cyan] {path}")
            continue

        # Read file only once
        try:
            with open(path, "rb") as handle:
                content = handle.read()
        except OSError as exc:
            failed += 1
            console.print(f"[red]Failed to read {path}: {exc}[/red]")
            continue

        # Compute fast hash from already-loaded bytes
        file_hash = compute_fast_hash_from_bytes(content)

        # Secondary skip check: protects against mtime-only or metadata-only changes
        if cached and cached.get("hash") == file_hash:
            cache[path] = {
                **cached,
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "last_checked_at": _now_iso(),
            }
            skipped += 1
            console.print(f"[cyan]Skipped (same content):[/cyan] {path}")
            continue

        result = ingest_uploaded_file(
            filename=os.path.basename(path),
            content=content,
            source_path=path,
            enable_ocr=enable_ocr,
            ocr_provider=OCR_PROVIDER if enable_ocr else "none",
            ocr_mode=OCR_MODE,
        )

        if result.get("status") == "success":
            processed += 1
            cache[path] = {
                "hash": file_hash,
                "document_id": result.get("document_id"),
                "filename": os.path.basename(path),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "last_processed_at": _now_iso(),
                "chunks_count": result.get("chunks_created", 0),
                "status": "success",
            }
            console.print(f"[green]Processed:[/green] {path}")
        else:
            failed += 1
            cache.pop(path, None)
            error_message = result.get("message", "Unknown error")
            console.print(f"[red]Failed:[/red] {path} - {error_message}")

    cache["_summary"] = _build_cache_summary(root, files, cache)
    save_processed_cache(cache)
    console.print(
        f"[bold]Done[/bold] - processed: {processed}, skipped: {skipped}, failed: {failed}"
    )


def reset_pipeline() -> None:
    result = reset_collection()
    if result.get("status") == "success":
        console.print("[green]Qdrant collection deleted.[/green]")
    else:
        console.print(f"[red]Failed to reset collection: {result.get('message')}[/red]")

    if os.path.exists(CACHE_PATH):
        try:
            os.remove(CACHE_PATH)
            console.print("[green]Cache removed.[/green]")
        except OSError as exc:
            console.print(f"[red]Failed to remove cache: {exc}[/red]")


def main_menu() -> None:
    while True:
        console.print("\n[bold]RAG Data Pipeline[/bold]")
        console.print("1) Process data folder")
        console.print("2) Reset Qdrant + cache")
        console.print("3) Exit")

        choice = Prompt.ask("Choose", choices=["1", "2", "3"], default="1")

        if choice == "1":
            folder = prompt_data_folder()
            process_folder(folder)
        elif choice == "2":
            reset_pipeline()
        elif choice == "3":
            console.print("Bye.")
            return


if __name__ == "__main__":
    main_menu()
