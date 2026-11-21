"""API HTTP + service de l'interface (PWA)."""
import asyncio
import hmac
import json
import logging
import mimetypes
import re
import secrets
import shutil
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.requests import ClientDisconnect

from . import config, db
from .pipeline import album as album_mod
from .pipeline import generate, media, settings
from .pipeline import music as music_mod
from .pipeline import versions as versions_mod
from .pipeline import video as video_mod

log = logging.getLogger("souvenirs")
app = FastAPI(title="Souvenirs", docs_url=None, redoc_url=None, openapi_url=None)
db.init()
try:
    music_mod.sync_catalogue()
except Exception:
    log.exception("synchronisation du catalogue musical impossible")

EXT = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/wav": "wav",
       "audio/x-m4a": "m4a", "audio/aac": "aac", "video/mp4": "mp4", "video/quicktime": "mov",
       "video/webm": "webm", "image/jpeg": "jpg", "image/png": "png", "image/heic": "heic",
       "image/heif": "heif", "image/webp": "webp"}
FAMILY = {"dictee": ("audio", "video"), "conversation": ("audio", "video"), "video": ("video",), "photo": ("image",)}


@app.middleware("http")
async def headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


def err(status, msg):
    raise HTTPException(status, msg)


def eq(a: str, b: str) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


def get_event(slug: str):
    ev = db.one("SELECT * FROM events WHERE slug=?", slug)
    if ev is None:
        time.sleep(0.3)
        err(404, "Événement introuvable. Vérifie le lien reçu.")
    return ev


def require_admin(ev, token):
    if not eq(token or "", ev["admin_token"]):
        err(403, "Réservé à l'organisateur.")


def require_participant(ev, token):
    p = db.one("SELECT * FROM participants WHERE token=? AND event_id=?", token or "", ev["id"])
    if p is None:
        err(401, "Indique ton prénom pour participer.")
    return p


def require_code(code):
    if not config.ADMIN_CODE:
        err(503, "ADMIN_CODE n'est pas configuré sur le serveur.")
    if not eq(code or "", config.ADMIN_CODE):
        time.sleep(1)
        err(403, "Code administrateur incorrect.")


def _tones(value, event_type: str | None = None) -> list[str]:
    """Tons d'une valeur stockée ; jamais vide : une valeur corrompue retombe sur les tons par défaut du type."""
    try:
        return settings.parse_tones(value)
    except ValueError as e:
        fallback = settings.defaults(event_type or "autre")["tones"] or ["chill"]
        log.warning("Ton invalide en base (%r) : %s. Repli sur %s.", value, e, fallback)
        return fallback


def _tone_label(value, event_type: str | None = None) -> str:
    return " + ".join(config.TONES[t] for t in _tones(value, event_type))


def event_public(ev, is_admin=False):
    n = db.one("SELECT COUNT(*) c FROM items WHERE event_id=?", ev["id"])["c"]
    today = datetime.now(ZoneInfo(ev["tz"])).date()
    start, end = date.fromisoformat(ev["start_date"]), date.fromisoformat(ev["end_date"])
    purge_on = None
    if ev["published_at"] and not ev["is_demo"]:
        d = datetime.strptime(ev["published_at"][:10], "%Y-%m-%d") + timedelta(days=config.RAW_RETENTION_DAYS)
        purge_on = d.strftime("%Y-%m-%d")
    return {
        "slug": ev["slug"], "name": ev["name"], "tz": ev["tz"], "start_date": ev["start_date"], "end_date": ev["end_date"],
        "type": ev["type"], "type_label": config.EVENT_TYPES.get(ev["type"], ev["type"]),
        "tone": ev["tone"], "tones": _tones(ev["tone"], ev["type"]), "tone_label": _tone_label(ev["tone"], ev["type"]),
        "count": n, "day": (today - start).days + 1, "days": (end - start).days + 1,
        "phase": "avant" if today < start else "apres" if today > end else "pendant",
        "published": bool(ev["published_at"]), "is_admin": is_admin, "is_demo": bool(ev["is_demo"]),
        "raw_purge_on": purge_on, "raw_purged": bool(ev["raw_purged_at"]),
    }


def item_public(it, me_id=None, admin=False):
    d = {"id": it["id"], "kind": it["kind"], "author": it["author"], "captured_at": it["captured_at"],
         "status": it["status"], "duration": it["duration"], "mine": it["participant_id"] == me_id,
         "text": it["text"] if it["kind"] == "note" or it["status"] == "error" else None,
         "has_thumb": it["kind"] in ("photo", "video") and it["status"] == "ready",
         "portrait": bool(it["height"] and it["width"] and it["height"] > it["width"])}
    if admin:
        d["excluded"] = bool(it["excluded"])
        d["transcript"] = it["transcript_text"]
    return d


# ------------------------------------------------------------------ événements

@app.get("/api/config")
def get_config():
    return {"types": config.EVENT_TYPES, "tones": config.TONES, "endings": config.ENDINGS, "genres": config.GENRES,
            "rhythms": config.RHYTHMS, "effects": config.EFFECTS, "title_styles": config.TITLE_STYLES,
            "framings": config.FRAMINGS, "evolutions": config.EVOLUTIONS,
            "durations": config.DURATIONS, "defaults": config.TYPE_DEFAULTS, "moods": config.MOOD_LABELS,
            "max_upload_mb": config.MAX_UPLOAD_MB}


def _settings(body: dict) -> dict:
    """Valide les réglages d'un événement (création ou modification)."""
    name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()[:120]
    tz = str(body.get("tz") or config.DEFAULT_TZ)
    try:
        start, end = date.fromisoformat(body["start_date"]), date.fromisoformat(body["end_date"])
    except Exception:
        err(400, "Dates invalides.")
    try:
        ZoneInfo(tz)
    except Exception:
        err(400, "Fuseau horaire inconnu.")
    if not name or end < start:
        err(400, "Donne un nom, et une date de fin après la date de début.")
    typ = config.LEGACY_TYPES.get(body.get("type"), body.get("type"))
    if typ not in config.EVENT_TYPES:
        err(400, "Type inconnu.")
    try:
        tones = settings.parse_tones(body.get("tone"))
    except ValueError as e:
        err(400, str(e))
    return {"name": name, "start_date": str(start), "end_date": str(end), "type": typ,
            "tone": settings.tones_csv(tones), "tz": tz}


@app.post("/api/events")
def create_event(body: dict = Body(...), x_admin_code: str = Header(None)):
    require_code(x_admin_code)
    vals = _settings(body)
    slug, admin = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    db.insert("events", slug=slug, admin_token=admin, created_at=db.now(), **vals)
    return {"slug": slug, "admin_token": admin}


@app.put("/api/events/{slug}/settings")
def update_settings(slug: str, body: dict = Body(...), x_admin_token: str = Header(None)):
    """Modifie le nom, les dates, le type, le ton ou le fuseau. Pris en compte à la prochaine génération."""
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    db.update("events", "id", ev["id"], **_settings(body))
    return event_public(get_event(slug), True)


@app.get("/api/admin/events")
def list_events(x_admin_code: str = Header(None)):
    require_code(x_admin_code)
    return [{"slug": e["slug"], "admin_token": e["admin_token"], "name": e["name"], "start_date": e["start_date"],
             "end_date": e["end_date"], "published": bool(e["published_at"]), "is_demo": bool(e["is_demo"])}
            for e in db.q("SELECT * FROM events ORDER BY start_date DESC, id DESC")]


@app.get("/api/events/{slug}")
def read_event(slug: str, x_admin_token: str = Header(None), x_participant_token: str = Header(None)):
    ev = get_event(slug)
    out = event_public(ev, eq(x_admin_token or "", ev["admin_token"]))
    p = db.one("SELECT id, name FROM participants WHERE token=? AND event_id=?", x_participant_token or "", ev["id"])
    out["me"] = {"id": p["id"], "name": p["name"]} if p else None
    return out


@app.post("/api/events/{slug}/join")
def join(slug: str, body: dict = Body(...)):
    ev = get_event(slug)
    name = re.sub(r"\s+", " ", (body.get("name") or "")).strip()[:40]
    if not name:
        err(400, "Indique ton prénom.")
    token = secrets.token_urlsafe(24)
    pid = db.insert("participants", event_id=ev["id"], name=name, token=token, created_at=db.now())
    return {"token": token, "id": pid, "name": name}


@app.get("/api/events/{slug}/feed")
def feed(slug: str, limit: int = 60, before: int = 0, x_participant_token: str = Header(None),
         x_admin_token: str = Header(None)):
    ev = get_event(slug)
    admin = eq(x_admin_token or "", ev["admin_token"])
    p = db.one("SELECT id FROM participants WHERE token=? AND event_id=?", x_participant_token or "", ev["id"])
    rows = db.q(
        """SELECT i.*, p.name AS author FROM items i JOIN participants p ON p.id=i.participant_id
           WHERE i.event_id=? AND (?=0 OR i.id<?) ORDER BY i.id DESC LIMIT ?""",
        ev["id"], before, before, min(limit, 200))
    return {"items": [item_public(r, p["id"] if p else None, admin) for r in rows],
            "event": event_public(ev, admin)}


# ------------------------------------------------------------------ contributions

def _captured(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        d = d.astimezone(timezone.utc)
        if d > datetime.now(timezone.utc) + timedelta(minutes=10):
            raise ValueError
        return d.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return db.now()


@app.post("/api/events/{slug}/notes")
def add_note(slug: str, body: dict = Body(...), x_participant_token: str = Header(None)):
    ev = get_event(slug)
    p = require_participant(ev, x_participant_token)
    text = (body.get("text") or "").strip()[:5000]
    if not text:
        err(400, "La note est vide.")
    cid = body.get("client_id")
    if cid and db.one("SELECT id FROM items WHERE client_id=?", cid):
        return {"ok": True}
    db.insert("items", event_id=ev["id"], participant_id=p["id"], kind="note", text=text,
              captured_at=_captured(body.get("captured_at")), created_at=db.now(), client_id=cid)
    return {"ok": True}


@app.post("/api/events/{slug}/uploads")
def start_upload(slug: str, body: dict = Body(...), x_participant_token: str = Header(None)):
    ev = get_event(slug)
    p = require_participant(ev, x_participant_token)
    kind, mime = body.get("kind"), (body.get("mime") or "").split(";")[0].strip().lower()
    size, cid = int(body.get("size") or 0), str(body.get("client_id") or "")
    if kind not in FAMILY or mime.split("/")[0] not in FAMILY[kind]:
        err(400, "Type de fichier non accepté.")
    if size <= 0 or size > config.MAX_UPLOAD_MB * 1024 * 1024:
        err(413, f"Fichier trop volumineux (maximum {config.MAX_UPLOAD_MB} Mo).")
    if not cid:
        err(400, "client_id manquant.")
    if db.one("SELECT id FROM items WHERE client_id=?", cid):
        return {"done": True}
    up = db.one("SELECT * FROM uploads WHERE client_id=? AND event_id=?", cid, ev["id"])
    if up:
        return {"id": up["id"], "received": up["received"]}
    uid = secrets.token_urlsafe(18)
    db.insert("uploads", id=uid, event_id=ev["id"], participant_id=p["id"], kind=kind,
              filename=(body.get("filename") or "")[:200], mime=mime, size=size,
              captured_at=_captured(body.get("captured_at")),
              source="import" if body.get("source") == "import" else "capture", client_id=cid, created_at=db.now())
    return {"id": uid, "received": 0}


def _upload(uid, token):
    up = db.one("SELECT u.*, p.token FROM uploads u JOIN participants p ON p.id=u.participant_id WHERE u.id=?", uid)
    if up is None or not eq(token or "", up["token"]):
        err(404, "Envoi introuvable.")
    return up


@app.put("/api/uploads/{uid}")
async def upload_chunk(uid: str, request: Request, offset: int = Query(...), x_participant_token: str = Header(None)):
    up = _upload(uid, x_participant_token)
    if offset != up["received"]:
        return JSONResponse({"received": up["received"]}, status_code=409)
    d = config.event_dir(up["event_id"]) / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    path = d / uid
    got = 0
    cut = False
    with open(path, "r+b" if path.exists() else "wb") as f:
        f.seek(offset)
        f.truncate()
        try:
            async for chunk in request.stream():
                if offset + got + len(chunk) > up["size"]:
                    err(400, "Plus de données que la taille annoncée.")
                f.write(chunk)
                got += len(chunk)
        except ClientDisconnect:
            # réseau coupé ou envoi interrompu par le téléphone : on garde ce qui est arrivé,
            # la reprise repartira exactement d'ici
            cut = True
    if db.one("SELECT id FROM uploads WHERE id=?", uid) is None:  # envoi annulé pendant l'écriture
        path.unlink(missing_ok=True)
        if cut:
            return Response(status_code=499)
        err(404, "Envoi annulé.")
    # n'avance que si personne d'autre n'a écrit entre-temps (deux requêtes sur le même envoi)
    moved = db.run("UPDATE uploads SET received=? WHERE id=? AND received=?", offset + got, uid, offset).rowcount
    if cut:
        return Response(status_code=499)
    if not moved:
        return JSONResponse({"received": db.one("SELECT received FROM uploads WHERE id=?", uid)["received"]}, status_code=409)
    return {"received": offset + got}


@app.post("/api/uploads/{uid}/complete")
def complete_upload(uid: str, x_participant_token: str = Header(None)):
    up = _upload(uid, x_participant_token)
    if up["received"] != up["size"]:
        return JSONResponse({"received": up["received"]}, status_code=409)
    ext = EXT.get(up["mime"]) or (up["filename"].rsplit(".", 1)[-1].lower() if "." in (up["filename"] or "") else "bin")
    ext = re.sub(r"[^a-z0-9]", "", ext)[:5] or "bin"
    item_id = db.insert("items", event_id=up["event_id"], participant_id=up["participant_id"], kind=up["kind"],
                        filename=up["filename"], mime=up["mime"], size=up["size"], captured_at=up["captured_at"],
                        created_at=db.now(), source=up["source"], status="processing", client_id=up["client_id"])
    raw = config.event_dir(up["event_id"]) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    shutil.move(config.event_dir(up["event_id"]) / "uploads" / uid, raw / f"{item_id}.{ext}")
    db.update("items", "id", item_id, path=f"raw/{item_id}.{ext}")
    db.run("DELETE FROM uploads WHERE id=?", uid)
    db.enqueue(up["event_id"], "prepare", item_id=item_id)
    return {"done": True, "item_id": item_id}


def _remove_from_draft(event_id: int, item_id: int) -> set:
    """Retire un élément de la sélection, de l'album et du montage. Retourne les parties à refaire."""
    rep = db.report(event_id)
    stale = set()
    sel = db.jl(rep["selection"], [])
    alb = db.jl(rep["album"])
    if alb and item_id in album_mod.photo_ids(alb):
        alb = album_mod.remove_photo(alb, item_id)
        db.update("reports", "event_id", event_id, album=json.dumps(alb, ensure_ascii=False))
        stale.add("album")
    if item_id in sel:
        db.update("reports", "event_id", event_id, selection=json.dumps([i for i in sel if i != item_id]))
    segs = db.jl(rep["montage"], [])
    if any(s["item_id"] == item_id for s in segs):
        db.update("reports", "event_id", event_id,
                  montage=json.dumps([s for s in segs if s["item_id"] != item_id], ensure_ascii=False))
        stale.add("video")
    return stale


def _rerender(event_id: int, parts: set):
    if parts:
        db.enqueue(event_id, "generate", parts=sorted(parts), ai=False)


def _delete_item(ev, it):
    item_id = it["id"]
    stale = _remove_from_draft(ev["id"], item_id)
    base = config.event_dir(ev["id"])
    if it["path"]:
        (base / it["path"]).unlink(missing_ok=True)
    for f in (base / "derived").glob(f"{item_id}_*.jpg"):
        f.unlink(missing_ok=True)
    db.run("DELETE FROM items WHERE id=?", item_id)
    _rerender(ev["id"], stale)


@app.delete("/api/events/{slug}/items/{item_id}")
def delete_item(slug: str, item_id: int, x_participant_token: str = Header(None), x_admin_token: str = Header(None)):
    ev = get_event(slug)
    it = db.one("SELECT * FROM items WHERE id=? AND event_id=?", item_id, ev["id"])
    if it is None:
        return {"ok": True}
    if not eq(x_admin_token or "", ev["admin_token"]):
        p = require_participant(ev, x_participant_token)
        if p["id"] != it["participant_id"]:
            err(403, "Tu ne peux supprimer que tes propres souvenirs.")
    _delete_item(ev, it)
    return {"ok": True}


@app.delete("/api/events/{slug}/uploads/{client_id}")
def cancel_upload(slug: str, client_id: str, x_participant_token: str = Header(None)):
    """Annule un envoi en attente depuis le téléphone : efface l'envoi partiel, ou le souvenir s'il a eu le
    temps d'arriver entre-temps."""
    ev = get_event(slug)
    p = require_participant(ev, x_participant_token)
    up = db.one("SELECT id FROM uploads WHERE client_id=? AND event_id=? AND participant_id=?",
                client_id, ev["id"], p["id"])
    if up:
        db.run("DELETE FROM uploads WHERE id=?", up["id"])
        (config.event_dir(ev["id"]) / "uploads" / up["id"]).unlink(missing_ok=True)
    it = db.one("SELECT * FROM items WHERE client_id=? AND event_id=? AND participant_id=?",
                client_id, ev["id"], p["id"])
    if it:
        _delete_item(ev, it)
    return {"ok": True}


@app.get("/api/events/{slug}/media/{item_id}/{variant}")
def get_media(slug: str, item_id: int, variant: str):
    ev = get_event(slug)
    it = db.one("SELECT * FROM items WHERE id=? AND event_id=?", item_id, ev["id"])
    if it is None:
        err(404, "Introuvable.")
    if variant in ("thumb", "display"):
        path = media.derived(ev["id"], item_id, "t" if variant == "thumb" else "d")
        mime = "image/jpeg"
    elif variant == "raw":
        path, mime = media.raw_path(it), it["mime"] or "application/octet-stream"
    else:
        err(404, "Introuvable.")
    if path is None or not path.exists():
        err(404, "Fichier indisponible (les fichiers bruts sont supprimés 3 mois après la publication).")
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})


# ------------------------------------------------------------------ organisateur

def _job_public(j):
    if j is None:
        return None
    return {"id": j["id"], "status": j["status"], "step": j["step"], "progress": j["progress"],
            "message": j["message"], "params": db.jl(j["params"], {})}


def _active_job(event_id):
    return db.one("SELECT * FROM jobs WHERE event_id=? AND kind='generate' AND status IN ('queued','running') "
                  "ORDER BY id DESC LIMIT 1", event_id)


GEN_PARTS = ("text", "video", "album", "music")


@app.post("/api/events/{slug}/generate")
def start_generate(slug: str, body: dict = Body(...), x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    parts = body.get("parts") or ["text", "video", "album"]
    if not isinstance(parts, list):
        err(400, "Parties à générer invalides.")
    for p in parts:
        if p not in GEN_PARTS:
            err(400, f"Partie à générer inconnue : « {p} ».")
    parts = [p for p in GEN_PARTS if p in parts]
    vs = None
    if body.get("video_settings") is not None:
        if not isinstance(body["video_settings"], dict):
            err(400, "Réglages vidéo invalides.")
        vs = settings.normalize(body["video_settings"], ev["type"])
        dur = vs["duration"]
    else:  # ancien corps : durée seule
        try:
            dur = max(20, min(900, int(body["video_duration"]))) if body.get("video_duration") else None
        except (TypeError, ValueError):
            err(400, "Durée du film invalide.")
    picked = None
    if body.get("music") is not None:
        m = body["music"]
        if not isinstance(m, dict) or any(m.get(k) is not None and (type(m.get(k)) is not int)
                                          for k in ("main_id", "final_id")):
            err(400, "Choix de musique invalide.")
        picked = {"main_id": m.get("main_id"), "final_id": m.get("final_id")}
    if ev["raw_purged_at"] and parts != ["music"]:  # changer la musique n'a besoin que du film déjà monté
        err(409, "Les fichiers bruts ont été supprimés : la génération n'est plus possible.")
    if _active_job(ev["id"]):
        err(409, "Une génération est déjà en cours.")
    if not parts:
        err(400, "Rien à générer.")
    if parts == ["music"]:
        problem = generate.remix_problem(ev["id"], db.report(ev["id"]))
        if problem:
            err(409, problem)
    if db.one("SELECT COUNT(*) c FROM items WHERE event_id=? AND status='processing'", ev["id"])["c"]:
        err(409, "Des fichiers sont encore en cours de préparation, réessaie dans un instant.")
    db.report(ev["id"])
    if vs is not None:  # réglages gardés pour les générations suivantes et la relecture
        db.update("reports", "event_id", ev["id"], video_settings=json.dumps(vs, ensure_ascii=False),
                  video_duration=vs["duration"])
    if picked is not None:
        generate.store_music(ev["id"], picked["main_id"], picked["final_id"])
    extra = {"video_prompt": str(body["video_prompt"] or "")[:4000]} if "video_prompt" in body else {}
    jid = db.enqueue(ev["id"], "generate", parts=parts, video_duration=dur, ai=True, **extra)
    return {"job_id": jid}


# ------------------------------------------------------------------ préréglages
# Communs à tous les événements (un seul organisateur par installation). Liste triée par nom.

def _preset_public(r):
    d = db.jl(r["data"], {})
    return {"id": r["id"], "name": r["name"], "tones": d.get("tones", []),
            "video_settings": d.get("video_settings", {}), "created_at": r["created_at"]}


@app.get("/api/events/{slug}/presets")
def list_presets(slug: str, x_admin_token: str = Header(None)):
    require_admin(get_event(slug), x_admin_token)
    return [_preset_public(r) for r in db.q("SELECT * FROM presets ORDER BY name COLLATE NOCASE, id")]


@app.post("/api/events/{slug}/presets")
def save_preset(slug: str, body: dict = Body(...), x_admin_token: str = Header(None)):
    """Enregistre les tons et réglages vidéo sous un nom ; un nom déjà pris est remplacé."""
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    name = body.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not 1 <= len(name) <= 60:
        err(400, "Donne un nom de 1 à 60 caractères au préréglage.")
    t = body.get("tones")
    if not isinstance(t, (list, str)) or (isinstance(t, list) and any(not isinstance(x, str) for x in t)):
        err(400, "Tons invalides.")
    try:
        tones = settings.parse_tones(t)
    except ValueError as e:
        err(400, str(e))
    raw = body.get("video_settings")
    if raw is not None and not isinstance(raw, dict):
        err(400, "Réglages vidéo invalides.")
    data = json.dumps({"tones": tones, "video_settings": settings.normalize(raw, ev["type"])}, ensure_ascii=False)
    db.run("INSERT INTO presets (name, data, created_at) VALUES (?,?,?) "
           "ON CONFLICT(name) DO UPDATE SET data=excluded.data, created_at=excluded.created_at",
           name, data, db.now())
    return _preset_public(db.one("SELECT * FROM presets WHERE name=?", name))


@app.delete("/api/events/{slug}/presets/{preset_id}")
def delete_preset(slug: str, preset_id: int, x_admin_token: str = Header(None)):
    require_admin(get_event(slug), x_admin_token)
    db.run("DELETE FROM presets WHERE id=?", preset_id)
    return {"ok": True}


NO_MUSIC_MSG = "Aucune musique ne correspond à ces réglages : le film sera sans musique."


@app.post("/api/events/{slug}/music/pick")
def pick_music(slug: str, body: dict = Body(default={}), x_admin_token: str = Header(None)):
    """Pré-écoute : propose le morceau (et celui de la fin) pour ces réglages, sans rien enregistrer."""
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    if body.get("tones") is None:
        tones = _tones(ev["tone"], ev["type"])
    else:
        if not isinstance(body["tones"], (list, str)) or (
                isinstance(body["tones"], list) and any(not isinstance(t, str) for t in body["tones"])):
            err(400, "Tons invalides.")
        try:
            tones = settings.parse_tones(body["tones"])
        except ValueError as e:
            err(400, str(e))
    raw = body.get("video_settings")
    if raw is not None and not isinstance(raw, dict):
        err(400, "Réglages vidéo invalides.")
    vs = settings.normalize(raw, ev["type"])
    exclude = body.get("exclude") or []
    if not isinstance(exclude, list) or any(type(i) is not int for i in exclude):
        err(400, "Liste de morceaux à exclure invalide.")
    if _active_job(ev["id"]):
        err(409, "Une génération est déjà en cours.")
    got = music_mod.choose(tones, vs, exclude=exclude)
    main, final = got["main"], got["final"]
    # Sans effet de bord : rien n'est enregistré ici. Les écrans envoient les morceaux entendus avec /generate,
    # qui les mémorise dans reports.music (sinon les rendus suivants changeraient de musique à l'insu de l'organisateur).
    return {"main": music_mod.public(main) if main else None, "final": music_mod.public(final) if final else None,
            "message": "" if main else NO_MUSIC_MSG}


@app.get("/api/events/{slug}/job")
def job_status(slug: str, x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    j = db.one("SELECT * FROM jobs WHERE event_id=? AND kind='generate' ORDER BY id DESC LIMIT 1", ev["id"])
    return {"job": _job_public(j)}


@app.get("/api/events/{slug}/draft")
def get_draft(slug: str, x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    rep = db.report(ev["id"])
    rows = db.q("""SELECT i.*, p.name AS author FROM items i JOIN participants p ON p.id=i.participant_id
                   WHERE i.event_id=? ORDER BY i.captured_at, i.id""", ev["id"])
    items = {r["id"]: r for r in rows}
    segs = []
    for n, s in enumerate(db.jl(rep["montage"], [])):
        it = items.get(s["item_id"])
        segs.append({"index": n, "type": s["type"], "text": s.get("text", ""), "duration": s["duration"],
                     "item_id": s["item_id"], "author": it["author"] if it else None})
    alb = db.jl(rep["album"]) or {}
    active = _active_job(ev["id"])
    last = db.one("SELECT * FROM jobs WHERE event_id=? AND kind='generate' ORDER BY id DESC LIMIT 1", ev["id"])
    picked = generate.stored_tracks(rep)
    return {
        "video_settings": generate.video_settings(ev, rep),
        "music": {k: music_mod.public(t) if t else None for k, t in picked.items()},
        "text_md": rep["text_md"], "selection": db.jl(rep["selection"], []),
        "items": [item_public(r, admin=True) for r in rows],
        "segments": segs, "video_ready": bool(rep["video_ready"]), "album_ready": bool(rep["album_ready"]),
        "can_remix": generate.remix_problem(ev["id"], rep) is None,
        "album_pages": len(alb.get("pages", [])) + 2 if alb.get("pages") else 0,
        "video_duration": rep["video_duration"], "video_prompt": rep["video_prompt"] or "",
        "ai_mode": rep["ai_mode"], "updated_at": rep["updated_at"],
        "busy": bool(active), "job": _job_public(last),
        "published": bool(ev["published_at"]), "pub_version": rep["pub_version"],
        "dirty": bool(ev["published_at"]) and rep["text_md"] != rep["pub_text_md"],
    }


@app.put("/api/events/{slug}/draft")
def save_draft(slug: str, body: dict = Body(...), x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    db.report(ev["id"])
    db.update("reports", "event_id", ev["id"], text_md=str(body.get("text_md") or "")[:200000], updated_at=db.now())
    return {"ok": True}


@app.post("/api/events/{slug}/draft/selection")
def set_selection(slug: str, body: dict = Body(...), x_admin_token: str = Header(None)):
    """Ajoute ou retire une photo de la galerie et de l'album (et du montage si on la retire)."""
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    if _active_job(ev["id"]):
        err(409, "Attends la fin de la génération en cours.")
    it = db.one("SELECT i.*, p.name AS author FROM items i JOIN participants p ON p.id=i.participant_id "
                "WHERE i.id=? AND i.event_id=? AND i.kind='photo'", int(body.get("item_id") or 0), ev["id"])
    if it is None:
        err(404, "Photo introuvable.")
    rep = db.report(ev["id"])
    if body.get("selected"):
        sel = db.jl(rep["selection"], [])
        alb = db.jl(rep["album"]) or {"title": ev["name"], "subtitle": "", "cover_photo": 0, "pages": []}
        alb = album_mod.add_photo(alb, it["id"])
        if it["id"] not in sel:
            sel.append(it["id"])
        db.update("reports", "event_id", ev["id"], album=json.dumps(alb, ensure_ascii=False),
                  selection=json.dumps(sel))
        if it["excluded"]:
            db.update("items", "id", it["id"], excluded=0)
        _rerender(ev["id"], {"album"})
    else:
        _rerender(ev["id"], _remove_from_draft(ev["id"], it["id"]))
    return {"ok": True}


@app.post("/api/events/{slug}/draft/segments/{index}/remove")
def remove_segment(slug: str, index: int, x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    if _active_job(ev["id"]):
        err(409, "Attends la fin de la génération en cours.")
    rep = db.report(ev["id"])
    segs = db.jl(rep["montage"], [])
    if not 0 <= index < len(segs):
        err(404, "Extrait introuvable.")
    segs.pop(index)
    db.update("reports", "event_id", ev["id"], montage=json.dumps(segs, ensure_ascii=False))
    _rerender(ev["id"], {"video"})
    return {"ok": True}


@app.post("/api/events/{slug}/items/{item_id}/exclude")
def exclude_item(slug: str, item_id: int, body: dict = Body(...), x_admin_token: str = Header(None)):
    """Écarte (ou réintègre) un passage : il ne sera plus utilisé par les prochaines générations."""
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    it = db.one("SELECT id FROM items WHERE id=? AND event_id=?", item_id, ev["id"])
    if it is None:
        err(404, "Introuvable.")
    excluded = 1 if body.get("excluded") else 0
    db.update("items", "id", item_id, excluded=excluded)
    if excluded and not _active_job(ev["id"]):
        _rerender(ev["id"], _remove_from_draft(ev["id"], item_id))
    return {"ok": True}


@app.post("/api/events/{slug}/items/{item_id}/time")
def set_item_time(slug: str, item_id: int, body: dict = Body(...), x_admin_token: str = Header(None)):
    """Corrige la date et l'heure d'un souvenir, saisies à l'heure locale de l'événement (AAAA-MM-JJTHH:MM)."""
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    it = db.one("SELECT id FROM items WHERE id=? AND event_id=?", item_id, ev["id"])
    if it is None:
        err(404, "Introuvable.")
    try:
        local = datetime.strptime(str(body.get("local") or "")[:16], "%Y-%m-%dT%H:%M")
        when = local.replace(tzinfo=ZoneInfo(ev["tz"])).astimezone(timezone.utc)
    except ValueError:
        err(400, "Date ou heure invalide.")
    if when.year < 1990 or when > datetime.now(timezone.utc) + timedelta(minutes=10):
        err(400, "Cette date est dans le futur ou trop ancienne.")
    captured = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    db.update("items", "id", item_id, captured_at=captured)
    return {"ok": True, "captured_at": captured}


def _version_public(v, rep):
    return {"id": v["id"], "label": v["label"], "tone": v["tone"], "tone_label": _tone_label(v["tone"]),
            "type_label": config.EVENT_TYPES.get(v["type"], v["type"]), "origin": v["origin"],
            "created_at": v["created_at"], "has_video": bool(v["has_video"]), "has_album": bool(v["has_album"]),
            "current": v["id"] == rep["current_version"], "published": v["id"] == rep["published_from"],
            "shared": bool(v["shared"])}


@app.get("/api/events/{slug}/versions")
def list_versions(slug: str, x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    rep = db.report(ev["id"])
    rows = db.q("SELECT id, label, tone, type, origin, created_at, has_video, has_album, shared FROM versions "
                "WHERE event_id=? ORDER BY id DESC", ev["id"])
    return {"versions": [_version_public(v, rep) for v in rows], "dirty": versions_mod.dirty(ev["id"]),
            "has_draft": bool((rep["text_md"] or "").strip())}


def _music_credits(folder) -> list[str]:
    """Lignes de crédit musique d'un film rendu (video_base.json à côté du film), [] si inconnues."""
    meta = video_mod.read_meta(folder / video_mod.BASE) or {}
    credits = meta.get("credits")
    return [c for c in credits if isinstance(c, str) and c.strip()] if isinstance(credits, list) else []


def _version(ev, vid):
    v = db.one("SELECT * FROM versions WHERE id=? AND event_id=?", vid, ev["id"])
    if v is None:
        err(404, "Version introuvable.")
    return v


@app.get("/api/events/{slug}/versions/{vid}")
def read_version(slug: str, vid: int, x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    v = _version(ev, vid)
    return {**_version_public(v, db.report(ev["id"])), "text_md": v["text_md"], "video_prompt": v["video_prompt"] or "",
            "music_credits": _music_credits(versions_mod.vdir(ev["id"], vid)) if v["has_video"] else []}


@app.get("/api/events/{slug}/versions/{vid}/{name}")
def version_file(slug: str, vid: int, name: str, k: str = ""):
    ev = get_event(slug)
    require_admin(ev, k)
    v = _version(ev, vid)
    if name not in versions_mod.FILES or not (versions_mod.vdir(ev["id"], vid) / name).exists():
        err(404, "Introuvable.")
    slug_name = re.sub(r"[^A-Za-z0-9\-]", "-", unicodedata.normalize("NFKD", f"{ev['name']}-{v['label']}")
                       .encode("ascii", "ignore").decode())
    slug_name = re.sub(r"-{2,}", "-", slug_name).strip("-") or "souvenir"
    kind = "film" if name.endswith("mp4") else "album"
    return FileResponse(versions_mod.vdir(ev["id"], vid) / name,
                        media_type="video/mp4" if name.endswith("mp4") else "application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{slug_name}-{kind}.{name.rsplit(".", 1)[1]}"',
                                 "Cache-Control": "private, no-cache"})


@app.post("/api/events/{slug}/versions")
def save_version(slug: str, body: dict = Body(default={}), x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    if _active_job(ev["id"]):
        err(409, "Attends la fin de la génération en cours.")
    vid = versions_mod.snapshot(ev["id"], str(body.get("label") or "").strip())
    if vid is None:
        err(400, "Le brouillon est vide : génère d'abord le compte rendu.")
    return {"ok": True, "id": vid}


@app.put("/api/events/{slug}/versions/{vid}")
def rename_version(slug: str, vid: int, body: dict = Body(...), x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    _version(ev, vid)
    label = re.sub(r"\s+", " ", str(body.get("label") or "")).strip()[:80]
    if not label:
        err(400, "Donne un nom à la version.")
    db.update("versions", "id", vid, label=label)
    return {"ok": True}


@app.post("/api/events/{slug}/versions/{vid}/share")
def share_version(slug: str, vid: int, body: dict = Body(...), x_admin_token: str = Header(None)):
    """Propose (ou retire) une version au groupe, en plus de la version publiée."""
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    _version(ev, vid)
    db.update("versions", "id", vid, shared=1 if body.get("shared") else 0)
    return {"ok": True}


@app.post("/api/events/{slug}/versions/{vid}/restore")
def restore_version(slug: str, vid: int, x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    if _active_job(ev["id"]):
        err(409, "Attends la fin de la génération en cours.")
    _version(ev, vid)
    versions_mod.restore(ev["id"], vid)
    return {"ok": True}


@app.delete("/api/events/{slug}/versions/{vid}")
def delete_version(slug: str, vid: int, x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    _version(ev, vid)
    versions_mod.delete(ev["id"], vid)
    return {"ok": True}


@app.post("/api/events/{slug}/publish")
def publish(slug: str, x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    if _active_job(ev["id"]):
        err(409, "Attends la fin de la génération en cours avant de publier.")
    if not db.report(ev["id"])["text_md"].strip():
        err(400, "Le compte rendu est vide : génère-le d'abord.")
    if versions_mod.dirty(ev["id"]):  # ce qui est publié est toujours une version enregistrée
        versions_mod.snapshot(ev["id"], origin="publish", suffix=" · publiée")
    generate.publish(ev["id"])
    return {"ok": True}


def _out_file(ev, which, name):
    if name not in ("video.mp4", "album.pdf"):
        err(404, "Introuvable.")
    path = generate.out_dir(ev["id"], which) / name
    if not path.exists():
        err(404, "Pas encore disponible.")
    slug_name = re.sub(r"[^\w\- ]", "", ev["name"]).strip().replace(" ", "-") or "souvenir"
    label = f"{slug_name}-{'film' if name.endswith('mp4') else 'album'}.{name.rsplit('.', 1)[1]}"
    return FileResponse(path, media_type="video/mp4" if name.endswith("mp4") else "application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{label}"',
                                 "Cache-Control": "private, no-cache"})


@app.get("/api/events/{slug}/out/draft/{name}")
def out_draft(slug: str, name: str, k: str = ""):
    ev = get_event(slug)
    require_admin(ev, k)
    return _out_file(ev, "draft", name)


@app.get("/api/events/{slug}/out/published/{name}")
def out_published(slug: str, name: str):
    ev = get_event(slug)
    if not ev["published_at"]:
        err(404, "Pas encore publié.")
    return _out_file(ev, "published", name)


@app.get("/api/events/{slug}/published/photos/{name}")
def published_photo(slug: str, name: str):
    ev = get_event(slug)
    if not re.fullmatch(r"\d+(_t)?\.jpg", name):
        err(404, "Introuvable.")
    path = generate.out_dir(ev["id"], "published") / "photos" / name
    if not path.exists():
        err(404, "Introuvable.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/events/{slug}/published")
def published(slug: str):
    ev = get_event(slug)
    if not ev["published_at"]:
        return {"published": False}
    rep = db.report(ev["id"])
    main_v = db.one("SELECT label, tone FROM versions WHERE id=?", rep["published_from"]) if rep["published_from"] else None
    options = [{"id": 0, "label": main_v["label"] if main_v else "Version principale",
                "tone_label": _tone_label(main_v["tone"] if main_v else ev["tone"]), "main": True}]
    for v in db.q("SELECT id, label, tone FROM versions WHERE event_id=? AND shared=1 AND id IS NOT ? ORDER BY id",
                  ev["id"], rep["published_from"]):
        options.append({"id": v["id"], "label": v["label"], "tone_label": _tone_label(v["tone"]), "main": False})
    credits = []
    if rep["pub_has_video"]:  # copie de video_base.json faite à la publication, sinon celle de la version publiée
        pub = generate.out_dir(ev["id"], "published")
        credits = _music_credits(pub) if (pub / video_mod.META).is_file() else (
            _music_credits(versions_mod.vdir(ev["id"], rep["published_from"])) if rep["published_from"] else [])
    return {"published": True, "text_md": rep["pub_text_md"], "photos": db.jl(rep["pub_selection"], []),
            "has_video": bool(rep["pub_has_video"]), "has_album": bool(rep["pub_has_album"]),
            "version": rep["pub_version"], "published_at": ev["published_at"], "versions": options,
            "music_credits": credits}


def _shared_version(slug, vid):
    ev = get_event(slug)
    if not ev["published_at"]:
        err(404, "Pas encore publié.")
    v = db.one("SELECT * FROM versions WHERE id=? AND event_id=? AND shared=1", vid, ev["id"])
    if v is None:
        err(404, "Cette version n'est pas proposée au groupe.")
    return ev, v


@app.get("/api/events/{slug}/published/versions/{vid}")
def published_version(slug: str, vid: int):
    """Une autre version proposée au groupe : son texte, ses photos (encore présentes) et ses fichiers."""
    ev, v = _shared_version(slug, vid)
    ids = [i for i in db.jl(v["selection"], []) if isinstance(i, int)]
    ok = {r["id"] for r in db.q(f"SELECT id FROM items WHERE event_id=? AND kind='photo' AND status='ready' AND excluded=0 "
                                f"AND id IN ({','.join('?' * len(ids)) or 'NULL'})", ev["id"], *ids)} if ids else set()
    d = versions_mod.vdir(ev["id"], vid)
    return {"id": v["id"], "label": v["label"], "tone_label": _tone_label(v["tone"]),
            "text_md": v["text_md"], "photos": [i for i in ids if i in ok and media.derived(ev["id"], i, "d").exists()],
            "has_video": (d / "video.mp4").exists(), "has_album": (d / "album.pdf").exists(),
            "music_credits": _music_credits(d) if (d / "video.mp4").exists() else []}


@app.get("/api/events/{slug}/published/versions/{vid}/{name}")
def published_version_file(slug: str, vid: int, name: str):
    ev, v = _shared_version(slug, vid)
    path = versions_mod.vdir(ev["id"], vid) / name
    if name not in versions_mod.FILES or not path.exists():
        err(404, "Introuvable.")
    plain = unicodedata.normalize("NFKD", f"{ev['name']}-{v['label']}").encode("ascii", "ignore").decode()
    base = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9\-]", "-", plain)).strip("-") or "souvenir"
    kind = "film" if name.endswith("mp4") else "album"
    return FileResponse(path, media_type="video/mp4" if name.endswith("mp4") else "application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{base}-{kind}.{name.rsplit(".", 1)[1]}"',
                                 "Cache-Control": "private, no-cache"})


@app.get("/api/events/{slug}/download-all")
def download_all(slug: str, k: str = ""):
    """Archive ZIP de tous les fichiers bruts et des résultats (organisateur)."""
    ev = get_event(slug)
    require_admin(ev, k)
    return _zip(ev, guest=False)


@app.get("/api/events/{slug}/download-souvenir")
def download_souvenir(slug: str):
    """Archive ZIP pour les invités, depuis la page Souvenir : les fichiers sources (sans les passages écartés
    par l'organisateur) et la version publiée du récit, du film et de l'album, jamais le brouillon."""
    ev = get_event(slug)
    if not ev["published_at"]:
        err(404, "Le souvenir n'est pas encore publié.")
    if ev["raw_purged_at"]:
        err(410, "Les fichiers sources ont été supprimés du serveur.")
    return _zip(ev, guest=True)


def _zip(ev, guest: bool):
    from zipstream import ZIP_STORED, ZipStream

    zs = ZipStream(compress_type=ZIP_STORED)
    base = config.event_dir(ev["id"])
    rows = db.q(f"""SELECT i.*, p.name AS author FROM items i JOIN participants p ON p.id=i.participant_id
                    WHERE i.event_id=? {"AND i.excluded=0" if guest else ""} ORDER BY i.captured_at""", ev["id"])
    notes = []
    for it in rows:
        stamp = it["captured_at"][:19].replace(":", "-")
        who = re.sub(r"[^\w\-]", "_", it["author"])
        if it["kind"] == "note":
            notes.append(f"[{it['captured_at']}] {it['author']} : {it['text']}")
        elif it["path"] and (base / it["path"]).exists():
            ext = it["path"].rsplit(".", 1)[-1]
            zs.add_path(str(base / it["path"]), f"bruts/{stamp}_{who}_{it['kind']}_{it['id']}.{ext}")
        if it["transcript_text"]:
            notes.append(f"[{it['captured_at']}] {it['author']} ({it['kind']}, transcription) : {it['transcript_text']}")
    if notes:
        zs.add("\n\n".join(notes).encode(), "notes-et-transcriptions.txt")
    rep = db.report(ev["id"])
    text = rep["pub_text_md"] if guest else rep["text_md"]
    if text:
        zs.add(text.encode(), "compte-rendu.md")
    for which in ("published",) if guest else ("published", "draft"):
        d = generate.out_dir(ev["id"], which)
        if (d / "video.mp4").exists() or (d / "album.pdf").exists():
            for n in ("video.mp4", "album.pdf"):
                if (d / n).exists():
                    zs.add_path(str(d / n), f"resultats/{n}")
            break
    # nom de fichier sans accents : les navigateurs ne décodent pas tous un nom UTF-8 dans l'en-tête
    plain = unicodedata.normalize("NFKD", ev["name"]).encode("ascii", "ignore").decode()
    fname = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9\-]", "-", plain)).strip("-") or "souvenirs"
    return StreamingResponse(iter(zs), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{fname}.zip"'})


# ------------------------------------------------------------------ interface

@app.get("/robots.txt")
def robots():
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


@app.get("/api/healthz")
def healthz():
    db.one("SELECT 1")
    return {"ok": True}


@app.get("/e/{slug}/manifest.webmanifest")
def manifest(slug: str):
    ev = get_event(slug)
    return JSONResponse({
        "name": ev["name"], "short_name": ev["name"][:12], "start_url": f"/e/{slug}", "scope": "/",
        "display": "standalone", "background_color": "#fbf5e9", "theme_color": "#c8662b", "lang": "fr",
        "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}],
    }, media_type="application/manifest+json")


# ------------------------------------------------------------------ musiques

MAX_MUSIC_MB = 30


@app.get("/api/music")
def list_music(x_admin_code: str = Header(None)):
    require_code(x_admin_code)
    return [music_mod.detail(t) for t in music_mod.all_tracks()]


@app.get("/api/music/{track_id}.mp3")
def music_file(track_id: int):
    t = music_mod.get(track_id)
    p = music_mod.path(t) if t else None
    if p is None:
        err(404, "Morceau introuvable.")
    return FileResponse(p, media_type="audio/mpeg")


@app.post("/api/music", status_code=201)
async def add_music(request: Request, title: str = "", artist: str = "", genres: str = "", energy: str = "",
                    mood: str = "", license: str = "", x_admin_code: str = Header(None)):
    """Le fichier MP3 est le corps brut de la requête ; les informations passent dans l'URL."""
    await asyncio.to_thread(require_code, x_admin_code)  # pause anti-essais hors de la boucle d'événements
    title, artist, license = title.strip()[:200], artist.strip()[:200], license.strip()[:300]
    gl = [g.strip() for g in genres.split(",") if g.strip()]
    if not title:
        err(400, "Indique le titre du morceau.")
    if not license:
        err(400, "Indique la licence du morceau : tu dois avoir le droit de l'utiliser dans une vidéo partagée.")
    if not gl or any(g not in config.GENRES for g in gl):
        err(400, "Choisis au moins un genre dans la liste.")
    if not energy.isdecimal() or not 1 <= int(energy) <= 5:
        err(400, "L'énergie doit être un nombre de 1 à 5.")
    if mood not in config.MOODS:
        err(400, "Choisis une humeur dans la liste.")
    limit = MAX_MUSIC_MB * 1024 * 1024
    too_big = f"Fichier trop volumineux (maximum {MAX_MUSIC_MB} Mo)."
    declared = request.headers.get("content-length") or "0"
    if declared.isdecimal() and int(declared) > limit:
        err(413, too_big)
    d = config.DATA_DIR / "music" / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".tmp-{secrets.token_hex(8)}"
    try:
        got = 0
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.stream():
                    got += len(chunk)
                    if got > limit:
                        err(413, too_big)
                    f.write(chunk)
        except ClientDisconnect:
            err(400, "Envoi interrompu, réessaie.")
        if got == 0:
            err(400, "Aucun fichier reçu.")
        try:
            info = await asyncio.to_thread(media.probe, tmp)
        except Exception:
            info = {}
        if not info.get("has_audio"):
            err(400, "Ce fichier n'est pas un MP3 lisible.")
        credit = f"Musique : « {title} »" + (f" — {artist}" if artist else "")
        tid = db.insert("tracks", key=f"upload-{secrets.token_hex(8)}", title=title, artist=artist, license=license,
                        source_url="", credit=credit, genres=",".join(gl), energy=int(energy), mood=mood,
                        duration=info.get("duration"), file="", origin="upload", created_at=db.now())
        try:
            tmp.replace(d / f"{tid}.mp3")
            db.update("tracks", "id", tid, file=f"{tid}.mp3")
        except Exception:
            db.run("DELETE FROM tracks WHERE id=?", tid)
            raise
    finally:
        tmp.unlink(missing_ok=True)
    return music_mod.detail(music_mod.get(tid))


@app.delete("/api/music/{track_id}")
def delete_music(track_id: int, x_admin_code: str = Header(None)):
    require_code(x_admin_code)
    t = music_mod.get(track_id)
    if t is None:
        err(404, "Morceau introuvable.")
    if t["origin"] != "upload":
        err(403, "Les morceaux de la bibliothèque ne peuvent pas être supprimés.")
    p = music_mod.path(t)
    db.run("DELETE FROM tracks WHERE id=?", track_id)
    if p:
        p.unlink(missing_ok=True)
    return {"ok": True}


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"):
        err(404, "Introuvable.")
    root = config.STATIC_DIR
    f = (root / path).resolve()
    if path and f.is_file() and root.resolve() in f.parents:
        cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        return FileResponse(f, media_type=mimetypes.guess_type(f.name)[0], headers={"Cache-Control": cache})
    index = root / "index.html"
    if not index.exists():
        return PlainTextResponse("Interface non construite.", status_code=503)
    html = index.read_text()
    m = re.match(r"e/([\w\-]+)", path)
    href = f"/e/{m.group(1)}/manifest.webmanifest" if m else "/manifest.webmanifest"
    html = html.replace('href="/manifest.webmanifest"', f'href="{href}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
