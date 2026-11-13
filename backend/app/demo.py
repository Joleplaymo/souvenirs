"""Événement de démonstration « Week-end entre copains », créé au premier démarrage."""
import json
import mimetypes
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, db


def seed():
    manifest = config.DEMO_DIR / "manifest.json"
    if not config.DEMO_EVENT or not manifest.exists() or db.one("SELECT id FROM events WHERE is_demo=1"):
        return
    m = json.loads(manifest.read_text())
    tz = ZoneInfo(config.DEFAULT_TZ)
    today = datetime.now(tz).date()
    start = today - timedelta(days=(today.weekday() - 5) % 7 or 7)  # le dernier samedi passé
    end = start + timedelta(days=m["days"] - 1)
    eid = db.insert("events", slug=secrets.token_urlsafe(24), admin_token=secrets.token_urlsafe(24),
                    name=m["name"], start_date=str(start), end_date=str(end), type=m["type"], tone=m["tone"],
                    tz=config.DEFAULT_TZ, created_at=db.now(), is_demo=1)
    people = {n: db.insert("participants", event_id=eid, name=n, token=secrets.token_urlsafe(24),
                           created_at=db.now()) for n in m["participants"]}
    raw = config.event_dir(eid) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for it in m["items"]:
        h, mn = (int(x) for x in it["time"].split(":"))
        when = datetime.combine(start + timedelta(days=it["day"]), datetime.min.time(), tz).replace(hour=h, minute=mn)
        vals = dict(event_id=eid, participant_id=people[it["author"]], kind=it["kind"],
                    captured_at=when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), created_at=db.now())
        if it["kind"] == "note":
            db.insert("items", text=it["text"], **vals)
            continue
        src = config.DEMO_DIR / it["file"]
        item_id = db.insert("items", filename=it["file"], mime=mimetypes.guess_type(src.name)[0],
                            size=src.stat().st_size, status="processing", **vals)
        ext = src.suffix.lstrip(".")
        shutil.copy2(src, raw / f"{item_id}.{ext}")
        db.update("items", "id", item_id, path=f"raw/{item_id}.{ext}")
        db.enqueue(eid, "prepare", item_id=item_id)
    print(f"[démo] événement « {m['name']} » créé (visible dans « Mes événements » avec le code administrateur)",
          flush=True)
