import io
import wave

import numpy as np
import whisper

import logging
import os
import re

from pathlib import Path
from config import MAX_CHARS


_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = whisper.load_model("tiny")
    return _whisper_model


def process_wav_bytes(audio_bytes: bytes) -> str:
    """
    Decode a PCM WAV file from bytes and return transcribed text using Whisper.
    The frontend should send 16kHz mono audio.
    """
    with io.BytesIO(audio_bytes) as buffer:
        with wave.open(buffer, "rb") as wav_file:
            n_channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())

    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    if n_channels > 1:
        audio = audio.reshape((-1, n_channels)).mean(axis=1)

    model = get_whisper_model()
    result = model.transcribe(audio, fp16=False)
    text = result.get("text", "").strip()

    if sample_rate != 16000:
        # The frontend should resample to 16kHz, but do not fail if it does not.
        pass

    return text


"""
TTS Service - Text-to-Speech using Piper (local/offline)

Setup:
    pip install piper-tts

Download a French model:
    python -m piper --download-dir ./piper-models --download fr_FR-siwis-medium
    (or fr_FR-upmc-medium for slightly faster inference)

Then set in .env:
    PIPER_MODEL_PATH=./piper-models/fr_FR-siwis-medium.onnx

Piper generates a raw PCM WAV file in memory — no disk I/O needed.
"""


logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# PIPER MODEL — loaded once at first call (lazy singleton)
# ──────────────────────────────────────────────────────────────────────────────

_piper_voice = None


def _get_piper_voice():
    """
    Lazy-load the Piper voice model.
    Raises RuntimeError if the model file is not found.
    """
    global _piper_voice

    if _piper_voice is not None:
        return _piper_voice

    try:
        from piper.voice import PiperVoice
    except ImportError as exc:
        raise RuntimeError(
            "piper-tts is not installed. Run: pip install piper-tts"
        ) from exc

    model_path = os.getenv("PIPER_MODEL_PATH", "./piper-models/fr_FR-siwis-medium.onnx")

    if not Path(model_path).exists():
        raise RuntimeError(
            f"Piper model not found at '{model_path}'.\n"
            "Download it with:\n"
            "  python -m piper --download-dir ./piper-models --download fr_FR-siwis-medium\n"
            "Then set PIPER_MODEL_PATH in your .env file."
        )

    logger.info(f"Loading Piper TTS model from: {model_path}")
    _piper_voice = PiperVoice.load(model_path)
    logger.info("Piper TTS model loaded.")
    return _piper_voice


def synthesize(text: str) -> bytes:
    """
    Convert *text* to a WAV audio file and return it as raw bytes.

    Args:
        text: Plain text to synthesize (markdown stripped by caller).

    Returns:
        WAV audio as bytes (16-bit PCM, 22 050 Hz mono by default for siwis).

    Raises:
        ValueError: If text is empty or exceeds MAX_CHARS.
        RuntimeError: If Piper model cannot be loaded.
    """
    text = text.strip()

    if not text:
        raise ValueError("TTS input text is empty.")

    if len(text) > MAX_CHARS:
        raise ValueError(
            f"Text too long for TTS ({len(text)} chars > {MAX_CHARS} limit). "
            "Trim the text before calling synthesize()."
        )

    voice = _get_piper_voice()

    chunks = list(voice.synthesize(text))
    if not chunks:
        raise RuntimeError("Piper returned no audio chunks.")

    first = chunks[0]
    pcm_bytes = b"".join(chunk.audio_int16_bytes for chunk in chunks)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(first.sample_channels)
        wav_file.setsampwidth(first.sample_width)
        wav_file.setframerate(first.sample_rate)
        wav_file.writeframes(pcm_bytes)

    return buffer.getvalue()


def strip_markdown(text: str) -> str:
    """
    Very lightweight markdown stripper so Piper doesn't read
    asterisks, backticks, headers, etc. aloud.
    """

    # Remove code blocks first
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]*`", "", text)

    # Headers → plain text (remove #)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Bold / italic
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)

    # Links → label only
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Bullet points & ordered lists
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)

    # Horizontal rules
    text = re.sub(r"^[-_*]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Extra blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
