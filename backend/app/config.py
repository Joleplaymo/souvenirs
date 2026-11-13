"""Configuration lue depuis les variables d'environnement."""
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
ADMIN_CODE = os.environ.get("ADMIN_CODE", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "fr")
RAW_RETENTION_DAYS = int(os.environ.get("RAW_RETENTION_DAYS", "90"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "2048"))
DEMO_EVENT = os.environ.get("DEMO_EVENT", "true").lower() in ("1", "true", "yes", "oui")
DEMO_DIR = Path(os.environ.get("DEMO_DIR", "/app/demo"))
MUSIC_DIR = Path(os.environ.get("MUSIC_DIR", "/app/music"))
STATIC_DIR = Path(os.environ.get("STATIC_DIR", "/app/static"))
DEFAULT_TZ = os.environ.get("TZ", "Europe/Paris")

EVENT_TYPES = {
    "weekend": "Week-end entre copains",
    "course": "Course à pied",
    "voyage": "Voyage",
    "fete": "Fête ou anniversaire",
    "autre": "Autre",
}
TONES = {
    "detendu": "Souvenir détendu",
    "sportif": "Bilan sportif",
    "humour": "Humoristique",
    "emotion": "Émouvant et nostalgique",
}
KINDS = ("dictee", "conversation", "video", "photo", "note")


def event_dir(event_id: int) -> Path:
    return DATA_DIR / "events" / str(event_id)
