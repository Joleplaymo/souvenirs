"""Catalogue musical : synchronisation, règle anti-mélancolie, choix des morceaux."""
import json
import logging
import os
import time
import urllib.request
from pathlib import Path

from .. import config, db

log = logging.getLogger("souvenirs")

SAD_MOODS = ("melancolique", "triste")
SOFT_TONES = ("tendre", "nostalgique")
FINAL_MOODS = ("tendre", "calme", "melancolique")


def _track(row) -> dict | None:
    if row is None:
        return None
    t = dict(row)
    t["genres"] = [g for g in (t.get("genres") or "").split(",") if g]
    return t


def get(track_id: int) -> dict | None:
    return _track(db.one("SELECT * FROM tracks WHERE id=?", track_id))


def get_by_key(key: str) -> dict | None:
    return _track(db.one("SELECT * FROM tracks WHERE key=?", key))


def all_tracks() -> list[dict]:
    return [_track(r) for r in db.q("SELECT * FROM tracks ORDER BY id")]


def path(track: dict) -> Path | None:
    """Fichier audio du morceau, ou None s'il est absent."""
    if track.get("origin") == "upload":
        p = config.DATA_DIR / "music" / "uploads" / track["file"]
        return p if p.is_file() else None
    p = library_dir() / track["file"]
    if p.is_file():
        return p
    p = config.MUSIC_DIR / track["file"]
    return p if p.is_file() else None


def library_dir() -> Path:
    """Dossier où sont téléchargés les morceaux de la bibliothèque (volume de données)."""
    return config.DATA_DIR / "music" / "library"


def fetch_missing(dest=None, delay: float = 1.0, opener=None) -> dict:
    """Télécharge les morceaux du catalogue (entrées avec mp3_url) absents de dest.
    Écriture atomique, une pause entre deux téléchargements, un échec est journalisé et n'arrête rien."""
    dest = Path(dest) if dest else library_dir()
    opener = opener or urllib.request.urlopen
    res = {"ok": 0, "skipped": 0, "failed": 0}
    f = config.MUSIC_DIR / "catalogue.json"
    if not f.is_file():
        return res
    dest.mkdir(parents=True, exist_ok=True)
    first = True
    for e in json.loads(f.read_text(encoding="utf-8")):
        url = e.get("mp3_url")
        if not url:
            continue
        target = dest / e["file"]
        if target.is_file():
            res["skipped"] += 1
            continue
        if not first and delay:
            time.sleep(delay)
        first = False
        tmp = target.with_name(target.name + ".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "souvenirs-app"})
            with opener(req, timeout=60) as r:
                data = r.read()
            if not data:
                raise ValueError("fichier vide")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            res["ok"] += 1
        except Exception as ex:
            log.warning("téléchargement impossible : %s (%s)", url, ex)
            res["failed"] += 1
            tmp.unlink(missing_ok=True)
    log.info("bibliothèque musicale : %s", res)
    return res


def public(track: dict) -> dict:
    return {"id": track["id"], "title": track["title"], "artist": track["artist"],
            "credit": track["credit"], "url": f"/api/music/{track['id']}.mp3"}


def detail(track: dict) -> dict:
    """Vue complète pour l'écran Musiques : public() + genres, énergie, humeur, origine, licence, durée."""
    return {**public(track), "genres": track["genres"], "energy": track["energy"], "mood": track["mood"],
            "origin": track["origin"], "license": track["license"], "duration": track["duration"]}


def sync_catalogue() -> int:
    """Charge MUSIC_DIR/catalogue.json dans la table tracks (par key). Ne télécharge rien,
    ne touche pas aux morceaux importés ni aux morceaux retirés du catalogue."""
    f = config.MUSIC_DIR / "catalogue.json"
    if not f.is_file():
        log.warning("catalogue musical introuvable : %s", f)
        return 0
    entries = json.loads(f.read_text(encoding="utf-8"))
    for e in entries:
        vals = dict(title=e["title"], artist=e.get("artist", ""), license=e.get("license", ""),
                    source_url=e.get("source_url", ""), credit=e.get("credit", ""),
                    genres=",".join(e.get("genres", [])), energy=e["energy"], mood=e["mood"],
                    bpm=e.get("bpm"), file=e["file"])
        row = db.one("SELECT id, origin FROM tracks WHERE key=?", e["key"])
        if row is None:
            db.insert("tracks", key=e["key"], origin="library", created_at=db.now(), **vals)
        elif row["origin"] == "library":
            db.update("tracks", "id", row["id"], **vals)
    for t in db.q("SELECT id, file FROM tracks WHERE origin='library' AND duration IS NULL"):
        p = path(dict(t))
        if p is None:
            continue
        try:
            from . import media

            d = media.probe(p)["duration"]
            if d:
                db.update("tracks", "id", t["id"], duration=d)
        except Exception:
            log.warning("durée illisible pour %s", p, exc_info=True)
    return len(entries)


def allowed(track: dict, tones: list[str], final: bool, ending: str) -> bool:
    """Règle anti-mélancolie : pas de morceau triste sauf ton tendre/nostalgique,
    ou séquence finale d'une fin touchante."""
    if track["mood"] not in SAD_MOODS:
        return True
    if any(t in SOFT_TONES for t in tones):
        return True
    return bool(final and ending == "touchante")


def candidates(tones: list[str], settings: dict, final: bool = False, exclude=()) -> list[dict]:
    target = settings.get("energy", 3)
    wanted = set(settings.get("genres") or [])
    ending = settings.get("ending")
    pool = []
    for t in all_tracks():
        if t["id"] in exclude or path(t) is None or not allowed(t, tones, final, ending):
            continue
        pool.append((abs(t["energy"] - target), -len(wanted & set(t["genres"])), t["id"], t))
    pool.sort(key=lambda x: x[:3])
    for need_genre, gap in ((True, 1), (False, 1), (False, 2)):
        got = [x[3] for x in pool if x[0] <= gap and (not need_genre or x[1] < 0)]
        if got:
            return got
    return []


def choose(tones: list[str], settings: dict, exclude=()) -> dict:
    cands = candidates(tones, settings, final=False, exclude=exclude)
    main = cands[0] if cands else None
    final = None
    if settings.get("ending") == "touchante":
        wanted = set(settings.get("genres") or [])
        best = None
        for t in all_tracks():
            if (t["id"] in exclude or (main and t["id"] == main["id"]) or path(t) is None
                    or t["mood"] not in FINAL_MOODS or t["energy"] > 2
                    or not allowed(t, tones, True, "touchante")):
                continue
            key = (-len(wanted & set(t["genres"])), t["energy"], t["id"])
            if best is None or key < best[0]:
                best = (key, t)
        final = best[1] if best else None
    return {"main": main, "final": final}
