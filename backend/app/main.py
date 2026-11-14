"""API HTTP + service de l'interface (PWA)."""
import hmac
import json
import mimetypes
import re
import secrets
import shutil
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse

from . import config, db
from .pipeline import album as album_mod
from .pipeline import generate, media

app = FastAPI(title="Souvenirs", docs_url=None, redoc_url=None, openapi_url=None)
db.init()

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


def event_public(ev, is_admin=False):
    n = db.one("SELECT COUNT(*) c FROM items WHERE event_id=?", ev["id"])["c"]
    today = datetime.now(ZoneInfo(ev["tz"])).date()
    start, end = date.fromisoformat(ev["start_date"]), date.fromisoformat(ev["end_date"])
    purge_on = None
    if ev["published_at"] and not ev["is_demo"]:
        d = datetime.strptime(ev["published_at"][:10], "%Y-%m-%d") + timedelta(days=config.RAW_RETENTION_DAYS)
        purge_on = d.strftime("%Y-%m-%d")
    return {
        "slug": ev["slug"], "name": ev["name"], "start_date": ev["start_date"], "end_date": ev["end_date"],
        "type": ev["type"], "type_label": config.EVENT_TYPES.get(ev["type"], ev["type"]),
        "tone": ev["tone"], "tone_label": config.TONES.get(ev["tone"], ev["tone"]),
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
    return {"types": config.EVENT_TYPES, "tones": config.TONES, "max_upload_mb": config.MAX_UPLOAD_MB}


@app.post("/api/events")
def create_event(body: dict = Body(...), x_admin_code: str = Header(None)):
    require_code(x_admin_code)
    name = (body.get("name") or "").strip()[:120]
    try:
        start, end = date.fromisoformat(body["start_date"]), date.fromisoformat(body["end_date"])
        ZoneInfo(body.get("tz") or config.DEFAULT_TZ)
    except Exception:
        err(400, "Dates invalides.")
    if not name or end < start:
        err(400, "Donne un nom, et une date de fin après la date de début.")
    if body.get("type") not in config.EVENT_TYPES or body.get("tone") not in config.TONES:
        err(400, "Type ou ton inconnu.")
    slug, admin = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    db.insert("events", slug=slug, admin_token=admin, name=name, start_date=str(start), end_date=str(end),
              type=body["type"], tone=body["tone"], tz=body.get("tz") or config.DEFAULT_TZ, created_at=db.now())
    return {"slug": slug, "admin_token": admin}


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
    with open(path, "r+b" if path.exists() else "wb") as f:
        f.seek(offset)
        f.truncate()
        async for chunk in request.stream():
            got += len(chunk)
            if offset + got > up["size"]:
                err(400, "Plus de données que la taille annoncée.")
            f.write(chunk)
    if db.one("SELECT id FROM uploads WHERE id=?", uid) is None:  # envoi annulé pendant l'écriture
        path.unlink(missing_ok=True)
        err(404, "Envoi annulé.")
    db.update("uploads", "id", uid, received=offset + got)
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


@app.post("/api/events/{slug}/generate")
def start_generate(slug: str, body: dict = Body(...), x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    if ev["raw_purged_at"]:
        err(409, "Les fichiers bruts ont été supprimés : la génération n'est plus possible.")
    if _active_job(ev["id"]):
        err(409, "Une génération est déjà en cours.")
    parts = [p for p in (body.get("parts") or ["text", "video", "album"]) if p in ("text", "video", "album")]
    dur = body.get("video_duration")
    dur = max(20, min(900, int(dur))) if dur else None
    if not parts:
        err(400, "Rien à générer.")
    if db.one("SELECT COUNT(*) c FROM items WHERE event_id=? AND status='processing'", ev["id"])["c"]:
        err(409, "Des fichiers sont encore en cours de préparation, réessaie dans un instant.")
    jid = db.enqueue(ev["id"], "generate", parts=parts, video_duration=dur, ai=True)
    return {"job_id": jid}


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
    return {
        "text_md": rep["text_md"], "selection": db.jl(rep["selection"], []),
        "items": [item_public(r, admin=True) for r in rows],
        "segments": segs, "video_ready": bool(rep["video_ready"]), "album_ready": bool(rep["album_ready"]),
        "album_pages": len(alb.get("pages", [])) + 2 if alb.get("pages") else 0,
        "video_duration": rep["video_duration"], "ai_mode": rep["ai_mode"], "updated_at": rep["updated_at"],
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


@app.post("/api/events/{slug}/publish")
def publish(slug: str, x_admin_token: str = Header(None)):
    ev = get_event(slug)
    require_admin(ev, x_admin_token)
    if _active_job(ev["id"]):
        err(409, "Attends la fin de la génération en cours avant de publier.")
    if not db.report(ev["id"])["text_md"].strip():
        err(400, "Le compte rendu est vide : génère-le d'abord.")
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
    return {"published": True, "text_md": rep["pub_text_md"], "photos": db.jl(rep["pub_selection"], []),
            "has_video": bool(rep["pub_has_video"]), "has_album": bool(rep["pub_has_album"]),
            "version": rep["pub_version"], "published_at": ev["published_at"]}


@app.get("/api/events/{slug}/download-all")
def download_all(slug: str, k: str = ""):
    """Archive ZIP de tous les fichiers bruts et des résultats (organisateur)."""
    ev = get_event(slug)
    require_admin(ev, k)
    from zipstream import ZIP_STORED, ZipStream

    zs = ZipStream(compress_type=ZIP_STORED)
    base = config.event_dir(ev["id"])
    rows = db.q("""SELECT i.*, p.name AS author FROM items i JOIN participants p ON p.id=i.participant_id
                   WHERE i.event_id=? ORDER BY i.captured_at""", ev["id"])
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
    if rep["text_md"]:
        zs.add(rep["text_md"].encode(), "compte-rendu.md")
    for which in ("published", "draft"):
        d = generate.out_dir(ev["id"], which)
        if (d / "video.mp4").exists() or (d / "album.pdf").exists():
            for n in ("video.mp4", "album.pdf"):
                if (d / n).exists():
                    zs.add_path(str(d / n), f"resultats/{n}")
            break
    fname = re.sub(r"[^\w\-]", "-", ev["name"]) or "souvenirs"
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
