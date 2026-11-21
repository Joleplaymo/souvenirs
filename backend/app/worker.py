"""Processus de fond : préparation des médias, génération, purge des fichiers bruts."""
import logging
import shutil
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from . import config, db
from .pipeline import generate, media, music

log = logging.getLogger("souvenirs")
LIGHT = ("prepare",)


def claim(light: bool):
    c = db.conn()
    marks = ",".join("?" * len(LIGHT))
    cond = f"kind IN ({marks})" if light else f"kind NOT IN ({marks})"
    c.execute("BEGIN IMMEDIATE")
    try:
        job = c.execute(f"SELECT * FROM jobs WHERE status='queued' AND {cond} ORDER BY id LIMIT 1", LIGHT).fetchone()
        if job:
            c.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?", (db.now(), job["id"]))
        c.execute("COMMIT")
        return job
    except Exception:
        c.execute("ROLLBACK")
        raise


def loop(light: bool):
    while True:
        try:
            job = claim(light)
        except Exception:
            traceback.print_exc()
            job = None
        if job is None:
            time.sleep(1 if light else 2)
            continue
        try:
            if job["kind"] == "prepare":
                media.prepare(db.jl(job["params"], {}).get("item_id"))
            elif job["kind"] == "generate":
                generate.generate(job)
            db.update("jobs", "id", job["id"], status="done", finished_at=db.now(), progress=1)
        except Exception as e:
            traceback.print_exc()
            db.update("jobs", "id", job["id"], status="error", finished_at=db.now(), message=str(e)[:500])


def purge():
    """Supprime les fichiers bruts des événements publiés depuis plus de RAW_RETENTION_DAYS jours."""
    limit = (datetime.now(timezone.utc) - timedelta(days=config.RAW_RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for ev in db.q("SELECT id, name FROM events WHERE published_at IS NOT NULL AND published_at < ? "
                   "AND raw_purged_at IS NULL AND is_demo=0", limit):
        shutil.rmtree(config.event_dir(ev["id"]) / "raw", ignore_errors=True)
        shutil.rmtree(config.event_dir(ev["id"]) / "uploads", ignore_errors=True)
        db.update("events", "id", ev["id"], raw_purged_at=db.now())
        print(f"[purge] fichiers bruts supprimés pour « {ev['name']} »", flush=True)
    # envois abandonnés depuis plus de 7 jours
    old = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for up in db.q("SELECT id, event_id FROM uploads WHERE created_at < ?", old):
        (config.event_dir(up["event_id"]) / "uploads" / up["id"]).unlink(missing_ok=True)
        db.run("DELETE FROM uploads WHERE id=?", up["id"])


def _fetch_library():
    """Télécharge la bibliothèque en arrière-plan, puis resynchronise (durées). Ne bloque rien."""
    try:
        music.fetch_missing()
        music.sync_catalogue()
    except Exception:
        log.exception("téléchargement de la bibliothèque musicale impossible")


def main():
    db.init()
    try:
        music.sync_catalogue()
    except Exception:
        log.exception("synchronisation du catalogue musical impossible")
    threading.Thread(target=_fetch_library, daemon=True).start()
    # reprise après redémarrage : les tâches interrompues repartent (les transcriptions déjà faites sont gardées)
    db.run("UPDATE jobs SET status='queued' WHERE status='running'")
    from . import demo

    demo.seed()
    threading.Thread(target=loop, args=(True,), daemon=True).start()
    threading.Thread(target=loop, args=(False,), daemon=True).start()
    print("[worker] prêt", flush=True)
    while True:
        try:
            purge()
        except Exception:
            traceback.print_exc()
        time.sleep(3600)


if __name__ == "__main__":
    main()
