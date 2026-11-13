"""Remise en ordre chronologique et mise en forme pour Claude."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .. import db

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
LABELS = {"dictee": "dictée vocale", "conversation": "conversation enregistrée", "video": "vidéo",
          "photo": "photo", "note": "note écrite"}


def local_dt(iso: str, tz: str) -> datetime:
    d = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return d.astimezone(ZoneInfo(tz))


def fr_day(d: datetime) -> str:
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"


def day_part(d: datetime) -> str:
    h = d.hour
    return "nuit" if h < 6 else "matin" if h < 12 else "après-midi" if h < 18 else "soir"


def fr_stamp(iso: str, tz: str) -> str:
    d = local_dt(iso, tz)
    return f"{fr_day(d)}, {d:%H:%M}"


def mmss(sec) -> str:
    sec = int(sec or 0)
    return f"{sec // 60}:{sec % 60:02d}"


def load_items(event_id: int):
    """Éléments utilisables, du plus ancien au plus récent."""
    return db.q(
        """SELECT i.*, p.name AS author FROM items i JOIN participants p ON p.id=i.participant_id
           WHERE i.event_id=? AND i.status='ready' AND i.excluded=0 ORDER BY i.captured_at, i.id""",
        event_id,
    )


def render(ev, items, with_segments=True) -> str:
    lines = []
    for it in items:
        head = f"[#{it['id']}] {fr_stamp(it['captured_at'], ev['tz'])} — {LABELS[it['kind']]} de {it['author']}"
        if it["duration"]:
            head += f" (durée {mmss(it['duration'])})"
        if it["kind"] == "photo" and it["width"] and it["height"]:
            head += " — " + ("portrait" if it["height"] > it["width"] else "paysage")
        lines.append(head)
        vision = db.jl(it["vision"])
        if vision:
            lines.append(f"    Image : {vision.get('description', '')} (qualité {vision.get('score', '?')}/10)")
        if it["kind"] == "note" and it["text"]:
            lines.append(f"    Note : {it['text']}")
        segs = db.jl(it["transcript"], [])
        if segs:
            if with_segments:
                for s in segs:
                    lines.append(f"    [{s['s']:.1f}–{s['e']:.1f} s] {s['t']}")
            else:
                lines.append("    Transcription : " + " ".join(s["t"] for s in segs))
        elif it["kind"] in ("dictee", "conversation"):
            lines.append("    (aucune parole reconnue)")
    return "\n".join(lines)
