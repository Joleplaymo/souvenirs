"""Réglages vidéo : tons, valeurs par défaut par type, validation."""
from .. import config

MAX_TONES = 2


def parse_tones(value) -> list[str]:
    """Accepte un CSV, une liste ou un ancien ton ; lève ValueError (français)."""
    if isinstance(value, str):
        items = [v.strip() for v in value.split(",")]
    else:
        items = [str(v).strip() for v in (value or [])]
    items = [v for v in items if v]
    if len(items) == 1 and items[0] in config.LEGACY_TONES:
        return list(config.LEGACY_TONES[items[0]])
    if not items:
        raise ValueError("Choisis au moins 1 ton.")
    seen: list[str] = []
    for t in items:
        if t not in config.TONES:
            raise ValueError(f"Ton inconnu : « {t} ».")
        if t not in seen:
            seen.append(t)
    if len(seen) > MAX_TONES:
        raise ValueError("Choisis 2 tons au maximum.")
    return seen


def tones_csv(tones: list[str]) -> str:
    return ",".join(tones)


def tones_label(value) -> str:
    return " + ".join(config.TONES[t] for t in parse_tones(value))


def defaults(event_type: str) -> dict:
    event_type = config.LEGACY_TYPES.get(event_type, event_type)
    if event_type not in config.TYPE_DEFAULTS:
        event_type = "autre"
    d = config.TYPE_DEFAULTS[event_type]
    return {k: list(v) if isinstance(v, list) else v for k, v in d.items()}


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize(raw: dict | None, event_type: str) -> dict:
    raw = raw or {}
    d = defaults(event_type)
    ending = raw.get("ending")
    if ending not in config.ENDINGS:
        ending = d["ending"]
    genres_in = raw.get("genres")
    genres: list[str] = []
    if isinstance(genres_in, (list, tuple)):
        for g in genres_in:
            if g in config.GENRES and g not in genres:
                genres.append(g)
    if not genres:
        genres = d["genres"]
    energy = max(1, min(5, _int(raw.get("energy"), d["energy"])))
    mix = max(0, min(100, _int(raw.get("mix"), 55)))
    duration = _int(raw.get("duration"), 120)
    if duration not in config.DURATIONS:
        duration = 120
    subtitles = raw.get("subtitles", True)
    subtitles = True if subtitles is None else bool(subtitles)
    return {"ending": ending, "genres": genres, "energy": energy,
            "mix": mix, "duration": duration, "subtitles": subtitles}
