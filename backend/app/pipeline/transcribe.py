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
EMPTY = {"language": None, "words": [], "segments": [], "text": ""}


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


def _segment(seg_start, seg_end, text, avg_logprob, compression_ratio, no_speech_prob, first, last) -> dict:
    """Whisper segment with the quality signals used to spot unclear or hallucinated audio."""
    return {
        "start": round(float(seg_start), 3),
        "end": round(float(seg_end), 3),
        "text": str(text).strip(),
        "avg_logprob": round(float(avg_logprob), 3),
        "compression_ratio": round(float(compression_ratio), 3),
        "no_speech_prob": round(float(no_speech_prob), 3),
        "first_word": first,
        "last_word": last,
    }


def transcribe_sync(path: str, task: str = "transcribe", prompt: str | None = None) -> dict:
    """Word-level transcript (task="translate" gives English words). Empty result if there is no speech/audio."""
    audio = load_audio(path)
    if audio is None or audio.size < 1600:
        return dict(EMPTY)
    model = _get_model()
    with _infer_lock:
        try:
            segments, info = model.transcribe(
                audio,
                task=task,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                beam_size=1,
                condition_on_previous_text=False,
                initial_prompt=prompt or None,  # names/terms from the user's note improve spelling
            )
            words, segs = [], []
            for seg in segments:
                first = len(words)
                for w in seg.words or []:
                    text = w.word.strip()
                    if text:
                        words.append({"start": round(float(w.start), 3), "end": round(float(w.end), 3), "text": text,
                                      "p": round(float(w.probability), 3)})
                if len(words) > first:
                    segs.append(_segment(seg.start, seg.end, seg.text, seg.avg_logprob, seg.compression_ratio,
                                         seg.no_speech_prob, first, len(words) - 1))
        except Exception as exc:  # decode error, model error, ...
            log.warning("transcription (%s) failed for %s: %s", task, path, exc)
            return dict(EMPTY)
    return {"language": info.language, "words": words, "segments": segs, "text": " ".join(w["text"] for w in words)}


def _groq_enabled() -> bool:
    if settings.transcribe_provider == "local":
        return False
    return bool(settings.groq_api_key)


_LANG_CODES = {"english": "en", "urdu": "ur", "hindi": "hi", "punjabi": "pa", "arabic": "ar", "persian": "fa",
               "pashto": "ps", "sindhi": "sd", "bengali": "bn", "turkish": "tr", "spanish": "es", "french": "fr",
               "german": "de", "portuguese": "pt", "italian": "it", "russian": "ru", "chinese": "zh",
               "japanese": "ja", "korean": "ko", "indonesian": "id", "malay": "ms"}


def _lang_code(name: str | None) -> str | None:
    """Groq reports language names ("English"); local Whisper and the rest of the pipeline use ISO codes ("en")."""
    if not name:
        return None
    return _LANG_CODES.get(name.strip().lower(), name.strip().lower())


def _words_from_segments(payload: dict) -> tuple[list[dict], list[dict]]:
    """Groq verbose_json -> our words + segments. Without word timestamps, spread words across each segment."""
    raw_words = [w for w in payload.get("words") or [] if str(w.get("word", "")).strip()]
    words: list[dict] = []
    segs: list[dict] = []
    for s in payload.get("segments") or []:
        first = len(words)
        start, end = float(s["start"]), float(s["end"])
        inside = [w for w in raw_words if start - 0.05 <= float(w["start"]) < end]
        if inside:
            for w in inside:
                words.append({"start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3),
                              "text": str(w["word"]).strip(), "p": 1.0})
        else:
            tokens = str(s.get("text", "")).split()
            step = (end - start) / max(len(tokens), 1)
            for k, token in enumerate(tokens):
                words.append({"start": round(start + k * step, 3), "end": round(start + (k + 1) * step, 3),
                              "text": token, "p": 1.0})
        if len(words) > first:
            segs.append(_segment(start, end, s.get("text", ""), s.get("avg_logprob", 0), s.get("compression_ratio", 1),
                                 s.get("no_speech_prob", 0), first, len(words) - 1))
    return words, segs


async def _groq_audio(path: str, endpoint: str, model: str, prompt: str | None = None) -> dict | None:
    """Groq Whisper (transcriptions or translations). None on any failure so callers fall back to local Whisper."""
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
            return dict(EMPTY)  # no audio track
        data = {"model": model, "response_format": "verbose_json", "temperature": "0"}
        if endpoint == "transcriptions":  # translations reject timestamp_granularities (segments only)
            data["timestamp_granularities[]"] = ["word", "segment"]
        if prompt:
            data["prompt"] = prompt[:600]
        try:
            with open(audio, "rb") as fh:
                async with httpx.AsyncClient(timeout=180) as client:
                    response = await client.post(
                        f"{settings.groq_base_url.rstrip('/')}/audio/{endpoint}",
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                        data=data,
                        files={"file": ("audio.mp3", fh, "audio/mpeg")},
                    )
        except httpx.HTTPError as exc:
            log.warning("groq %s failed: %s", endpoint, exc)
            return None
    if response.status_code >= 400:
        log.warning("groq %s %s: %s", endpoint, response.status_code, response.text[:300])
        return None
    payload = response.json()
    words, segs = _words_from_segments(payload)
    return {"language": _lang_code(payload.get("language")), "words": words, "segments": segs,
            "text": " ".join(w["text"] for w in words), "engine": "groq"}


async def transcribe(path: str, prompt: str | None = None) -> dict:
    if _groq_enabled():
        result = await _groq_audio(path, "transcriptions", settings.groq_whisper_model, prompt)
        if result is not None:
            return result
    return await asyncio.to_thread(transcribe_sync, path, "transcribe", prompt)


async def translate(path: str, prompt: str | None = None) -> dict:
    """English words with source-timeline timestamps, for captions on non-English speech."""
    if _groq_enabled():
        result = await _groq_audio(path, "translations", settings.groq_translate_model, prompt)
        if result is not None and result["words"]:
            return result
    return await asyncio.to_thread(transcribe_sync, path, "translate", prompt)


def warm_up() -> None:
    if _groq_enabled() and settings.transcribe_provider == "groq":
        return
    try:
        _get_model()
    except Exception as exc:
        log.warning("whisper model not loaded: %s", exc)
