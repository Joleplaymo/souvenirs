"""Transcription Whisper (faster-whisper, CPU)."""
from .. import config

_model = None


def _load():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            config.WHISPER_MODEL, device="cpu", compute_type="int8",
            download_root=str(config.DATA_DIR / "models"),
        )
    return _model


def transcribe(path, on_progress=None, duration=None) -> list[dict]:
    """Retourne des segments [{s, e, t}] (secondes, texte)."""
    segments, info = _load().transcribe(
        str(path), language=config.WHISPER_LANGUAGE or None, vad_filter=True, beam_size=5,
        condition_on_previous_text=False,
    )
    total = duration or getattr(info, "duration", 0) or 0
    out = []
    for s in segments:
        text = s.text.strip()
        if text:
            out.append({"s": round(s.start, 2), "e": round(s.end, 2), "t": text})
        if on_progress and total:
            on_progress(min(1.0, s.end / total))
    return out
