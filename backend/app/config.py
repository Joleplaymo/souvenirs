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
    "weekend": "Week-end copains",
    "course": "Course, trail",
    "anniversaire": "Anniversaire",
    "mariage": "Mariage",
    "vacances": "Vacances famille",
    "roadtrip": "Road-trip",
    "rando": "Rando, montagne",
    "soiree": "Soirée",
    "evg": "EVG, EVJF",
    "autre": "Autre",
}
TONES = {
    "drole": "Drôle",
    "festif": "Festif",
    "epique": "Épique",
    "tendre": "Tendre",
    "chill": "Chill",
    "nostalgique": "Nostalgique",
    "motivant": "Motivant",
    "decale": "Décalé",
    "cinema": "Cinéma",
    "documentaire": "Documentaire",
}
ENDINGS = {
    "festive": "Festive",
    "betisier": "Bêtisier",
    "touchante": "Touchante",
    "epique": "Épique",
}
GENRES = {
    "pop": "Pop",
    "electro": "Électro",
    "rock": "Rock",
    "indie": "Indie",
    "hiphop": "Hip-hop",
    "funk": "Funk, disco",
    "tropical": "Tropical",
    "folk": "Folk",
    "lofi": "Lo-fi",
    "annees80": "Années 80",
    "chanson": "Chanson FR",
    "jazz": "Jazz",
    "piano": "Piano",
    "orchestral": "Orchestral",
}
RHYTHMS = {
    "pose": "Posé",
    "dynamique": "Dynamique",
    "nerveux": "Clip nerveux",
}
EFFECTS = {
    "slowmo": "Ralentis",
    "speedup": "Accélérés",
    "freeze": "Arrêts sur image",
    "humor": "Effets humoristiques",
}
TITLE_STYLES = {
    "carnet": "Carnet manuscrit",
    "sobre": "Sobre",
    "pop": "Pop coloré",
    "aucun": "Aucun",
}
FRAMINGS = {
    "16:9": "Horizontal 16:9",
    "9:16": "Vertical 9:16",
    "1:1": "Carré 1:1",
}
EVOLUTIONS = {
    "constante": "Constante",
    "montee": "Montée progressive",
    "calme_explosion": "Calme puis explosion",
    "festif_emotion": "Festif puis émotion",
}
MOOD_LABELS = {
    "joyeux": "Joyeux",
    "festif": "Festif",
    "epique": "Épique",
    "tendre": "Tendre",
    "calme": "Calme",
    "melancolique": "Mélancolique",
    "triste": "Triste",
}
MOODS = tuple(MOOD_LABELS)
DURATIONS = (30, 60, 120, 180, 300)


def _td(tones, genres, energy, evolution, ending, rhythm, humor_fx=True):
    return {
        "tones": tones, "genres": genres, "energy": energy,
        "evolution": evolution, "ending": ending, "rhythm": rhythm,
        "humor_fx": humor_fx,
    }


TYPE_DEFAULTS = {
    "weekend": _td(["drole", "festif"], ["pop", "electro", "funk"], 4, "montee", "festive", "dynamique"),
    "course": _td(["epique", "motivant"], ["rock", "electro", "orchestral"], 5, "calme_explosion", "epique", "nerveux"),
    "anniversaire": _td(["festif", "tendre"], ["pop", "funk", "chanson"], 4, "festif_emotion", "touchante", "dynamique"),
    "mariage": _td(["tendre", "cinema"], ["piano", "folk", "orchestral"], 3, "montee", "touchante", "pose", False),
    "vacances": _td(["chill", "tendre"], ["folk", "pop", "tropical"], 3, "constante", "touchante", "pose"),
    "roadtrip": _td(["chill", "decale"], ["indie", "rock", "annees80"], 4, "constante", "festive", "dynamique"),
    "rando": _td(["epique", "chill"], ["folk", "orchestral", "indie"], 3, "montee", "epique", "pose"),
    "soiree": _td(["festif", "drole"], ["electro", "hiphop", "funk"], 5, "constante", "betisier", "nerveux"),
    "evg": _td(["drole", "decale"], ["pop", "annees80", "funk"], 5, "montee", "betisier", "nerveux"),
    "autre": _td(["drole", "chill"], ["pop", "indie"], 3, "montee", "festive", "dynamique"),
}
LEGACY_TONES = {
    "detendu": ["chill", "drole"],
    "sportif": ["motivant", "documentaire"],
    "humour": ["drole"],
    "emotion": ["tendre", "nostalgique"],
}
LEGACY_TYPES = {"voyage": "roadtrip", "fete": "anniversaire"}
KINDS = ("dictee", "conversation", "video", "photo", "note")


def event_dir(event_id: int) -> Path:
    return DATA_DIR / "events" / str(event_id)
