import asyncio
import logging
import subprocess
import threading

import numpy as np

from app.config import settings

log = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()
_infer_lock = threading.Lock()  # one transcription at a time: CPU bound


def _get_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            _model = WhisperModel(
                settings.whisper_model,
                device="cpu",
                compute_type=settings.whisper_compute_type,
                download_root=settings.whisper_model_dir or None,
            )
    return _model


def load_audio(path: str) -> np.ndarray | None:
    """16 kHz mono float32 via ffmpeg (avoids PyAV version drift). None when there is no audio."""
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True,
        timeout=300,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def transcribe_sync(path: str) -> dict:
    """Word-level transcript. Returns empty words if there is no speech or no audio."""
    empty = {"language": None, "words": [], "text": ""}
    audio = load_audio(path)
    if audio is None or audio.size < 1600:
        return empty
    model = _get_model()
    with _infer_lock:
        try:
            segments, info = model.transcribe(
                audio,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                beam_size=1,
                condition_on_previous_text=False,
            )
            words = []
            for seg in segments:
                for w in seg.words or []:
                    text = w.word.strip()
                    if text:
                        words.append(
                            {"start": round(w.start, 3), "end": round(w.end, 3), "text": text, "p": round(w.probability, 3)}
                        )
        except Exception as exc:  # decode error, model error, ...
            log.warning("transcription failed for %s: %s", path, exc)
            return empty
    return {"language": info.language, "words": words, "text": " ".join(w["text"] for w in words)}


def _groq_enabled() -> bool:
    if settings.transcribe_provider == "local":
        return False
    return bool(settings.groq_api_key)


async def transcribe_groq(path: str) -> dict | None:
    """Groq Whisper API with word timestamps. None on any failure (caller falls back to local Whisper)."""
    import tempfile

    import httpx

    with tempfile.TemporaryDirectory() as tmp:
        audio = f"{tmp}/audio.mp3"
        result = await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-y", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", audio],
            capture_output=True,
            timeout=300,
        )
        if result.returncode != 0:
            return {"language": None, "words": [], "text": ""}  # no audio track
        data = {
            "model": settings.groq_whisper_model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["word", "segment"],
            "temperature": "0",
        }
        try:
            with open(audio, "rb") as fh:
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(
                        f"{settings.groq_base_url.rstrip('/')}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                        data=data,
                        files={"file": ("audio.mp3", fh, "audio/mpeg")},
                    )
        except httpx.HTTPError as exc:
            log.warning("groq transcription failed: %s", exc)
            return None
    if response.status_code >= 400:
        log.warning("groq transcription %s: %s", response.status_code, response.text[:300])
        return None
    payload = response.json()
    words = [
        {"start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3), "text": str(w["word"]).strip(), "p": 1.0}
        for w in payload.get("words") or []
        if str(w.get("word", "")).strip()
    ]
    return {"language": payload.get("language"), "words": words, "text": " ".join(w["text"] for w in words),
            "engine": "groq"}


async def transcribe(path: str) -> dict:
    if _groq_enabled():
        result = await transcribe_groq(path)
        if result is not None:
            return result
    return await asyncio.to_thread(transcribe_sync, path)


def warm_up() -> None:
    if _groq_enabled() and settings.transcribe_provider == "groq":
        return
    try:
        _get_model()
    except Exception as exc:
        log.warning("whisper model not loaded: %s", exc)
