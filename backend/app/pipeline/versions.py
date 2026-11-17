"""Versions enregistrées d'un souvenir : copies complètes du brouillon (texte, choix de photos, plan de montage,
album, film et PDF rendus) pour comparer plusieurs tons et reprendre l'une d'elles à tout moment."""
import shutil

from .. import config, db
from . import generate

FILES = ("video.mp4", "album.pdf")
FIELDS = ("text_md", "selection", "montage", "album")


def vdir(event_id: int, vid: int):
    return config.event_dir(event_id) / "out" / "versions" / str(vid)


def dirty(event_id: int) -> bool:
    """Le brouillon diffère-t-il de la version dont il est issu (ou n'en a-t-il pas) ?"""
    rep = db.report(event_id)
    if not (rep["text_md"] or "").strip():
        return False  # rien à garder
    v = db.one("SELECT * FROM versions WHERE id=? AND event_id=?", rep["current_version"], event_id) if rep["current_version"] else None
    return v is None or any((rep[f] or "") != (v[f] or "") for f in FIELDS)


def snapshot(event_id: int, label: str = "", origin: str = "manual", suffix: str = "") -> int | None:
    """Enregistre le brouillon actuel comme nouvelle version et la rattache au brouillon.

    Le ton retenu est celui du contenu : celui de la version dont le brouillon est issu (les réglages ont pu
    changer depuis sans que rien n'ait été régénéré), sinon celui de l'événement."""
    rep = db.report(event_id)
    if not (rep["text_md"] or "").strip():
        return None
    ev = db.one("SELECT * FROM events WHERE id=?", event_id)
    src = db.one("SELECT tone, type FROM versions WHERE id=?", rep["current_version"]) if rep["current_version"] else None
    tone, typ = (src["tone"], src["type"]) if src and origin != "generation" else (ev["tone"], ev["type"])
    draft = generate.out_dir(event_id)
    has = {n: bool(rep["video_ready" if n == "video.mp4" else "album_ready"]) and (draft / n).exists() for n in FILES}
    vid = db.insert("versions", event_id=event_id, label=(label or config.TONES.get(tone, tone) + suffix)[:80],
                    tone=tone, type=typ, origin=origin, created_at=db.now(),
                    text_md=rep["text_md"], selection=rep["selection"], montage=rep["montage"], album=rep["album"],
                    video_duration=rep["video_duration"], ai_mode=rep["ai_mode"], video_prompt=rep["video_prompt"],
                    has_video=int(has["video.mp4"]), has_album=int(has["album.pdf"]))
    d = vdir(event_id, vid)
    d.mkdir(parents=True, exist_ok=True)
    for n in FILES:
        if has[n]:
            shutil.copy2(draft / n, d / n)  # copie (pas de lien) : le rendu suivant réécrit le brouillon
    db.update("reports", "event_id", event_id, current_version=vid)
    return vid


def restore(event_id: int, vid: int):
    """Remet une version dans le brouillon, avec son ton et son type."""
    v = db.one("SELECT * FROM versions WHERE id=? AND event_id=?", vid, event_id)
    if v is None:
        return False
    draft, d = generate.out_dir(event_id), vdir(event_id, vid)
    ready = {}
    for n in FILES:
        if (d / n).exists():
            shutil.copy2(d / n, draft / n)
            ready[n] = 1
        else:
            (draft / n).unlink(missing_ok=True)
            ready[n] = 0
    db.update("reports", "event_id", event_id, text_md=v["text_md"], selection=v["selection"], montage=v["montage"],
              album=v["album"], video_duration=v["video_duration"], ai_mode=v["ai_mode"], video_prompt=v["video_prompt"],
              video_ready=ready["video.mp4"], album_ready=ready["album.pdf"], current_version=vid, updated_at=db.now())
    db.update("events", "id", event_id, tone=v["tone"], type=v["type"])
    return True


def delete(event_id: int, vid: int):
    db.run("DELETE FROM versions WHERE id=? AND event_id=?", vid, event_id)
    shutil.rmtree(vdir(event_id, vid), ignore_errors=True)
    db.run("UPDATE reports SET current_version=NULL WHERE event_id=? AND current_version=?", event_id, vid)
    db.run("UPDATE reports SET published_from=NULL WHERE event_id=? AND published_from=?", event_id, vid)
