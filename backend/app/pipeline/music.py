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


def usable(track: dict | None) -> bool:
    """Morceau jouable : fichier présent, et pas marqué illisible (durée 0) par la synchronisation."""
    if not track or path(track) is None:
        return False
    return not (track.get("origin") == "library" and track.get("duration") is not None and track["duration"] <= 0)


def library_dir() -> Path:
    """Dossier où sont téléchargés les morceaux de la bibliothèque (volume de données)."""
    return config.DATA_DIR / "music" / "library"


MIN_MP3_BYTES = 100 * 1024  # en dessous : page d'erreur ou fichier tronqué, pas un morceau


def fetch_missing(dest=None, delay: float = 1.0, opener=None, min_size: int = MIN_MP3_BYTES) -> dict:
    """Télécharge les morceaux du catalogue (entrées avec mp3_url) absents de dest.
    Écriture atomique, une pause entre deux téléchargements, un échec est journalisé et n'arrête rien.
    Un fichier trop petit ou sans piste audio lisible (page HTML, téléchargement tronqué) est refusé."""
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
            if len(data) < min_size:
                raise ValueError(f"fichier trop petit ({len(data)} octets)")
            tmp.write_bytes(data)
            from . import media

            if not media.probe(tmp)["has_audio"]:
                raise ValueError("aucune piste audio lisible")
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
    # durée des morceaux présents ; un fichier illisible est marqué durée 0 (écarté du choix, resondé au démarrage)
    for t in db.q("SELECT id, file, origin FROM tracks WHERE origin='library' AND (duration IS NULL OR duration <= 0)"):
        p = path(dict(t))
        if p is None:
            continue
        d = None
        try:
            from . import media

            info = media.probe(p)
            d = info["duration"] if info["has_audio"] else None
        except Exception:
            log.warning("morceau illisible : %s", p, exc_info=True)
        db.update("tracks", "id", t["id"], duration=d if d else 0)
    return len(entries)


def allowed(track: dict, tones: list[str], final: bool, ending: str, evolution: str = "constante") -> bool:
    """Règle anti-mélancolie : pas de morceau triste sauf ton tendre/nostalgique,
    ou morceau de la séquence finale d'une fin touchante ou d'une évolution « festif puis émotion »."""
    if track["mood"] not in SAD_MOODS:
        return True
    if any(t in SOFT_TONES for t in tones):
        return True
    return bool(final and (ending == "touchante" or evolution == "festif_emotion"))


def candidates(tones: list[str], settings: dict, final: bool = False, exclude=(), target: int | None = None) -> list[dict]:
    """Morceaux permis les plus proches de l'énergie cible (réglages par défaut) : même genre à ±1,
    puis tout genre à ±1, puis ±2. L'humeur n'est jamais assouplie."""
    target = settings.get("energy", 3) if target is None else target
    wanted = set(settings.get("genres") or [])
    ending, evolution = settings.get("ending"), settings.get("evolution", "constante")
    pool = []
    for t in all_tracks():
        if t["id"] in exclude or not usable(t) or not allowed(t, tones, final, ending, evolution):
            continue
        pool.append((abs(t["energy"] - target), -len(wanted & set(t["genres"])), t["id"], t))
    pool.sort(key=lambda x: x[:3])
    for need_genre, gap in ((True, 1), (False, 1), (False, 2)):
        got = [x[3] for x in pool if x[0] <= gap and (not need_genre or x[1] < 0)]
        if got:
            return got
    return []


ROLES = ("intro", "main", "peak", "final")  # ordre de lecture dans le film
PICK_ORDER = ("main", "peak", "final", "intro")  # ordre de choix : le morceau principal d'abord
EVOLUTION_ROLES = {"constante": ("main",), "montee": ("intro", "main", "peak"),
                   "calme_explosion": ("intro", "peak"), "festif_emotion": ("main", "final")}


def roles_for(settings: dict) -> list[str]:
    """Rôles des morceaux selon l'évolution ; « final » s'ajoute à toute évolution quand la fin est touchante."""
    roles = list(EVOLUTION_ROLES.get(settings.get("evolution"), ("main",)))
    if settings.get("ending") == "touchante" and "final" not in roles:
        roles.append("final")
    return roles


def _calm(role, tones, settings, used) -> dict | None:
    """Morceau calme (énergie ≤ 2) : intro de « calme puis explosion », ou morceau final
    (humeur tendre, calme ou mélancolique). Genre demandé d'abord, puis le plus calme."""
    final = role == "final"
    wanted = set(settings.get("genres") or [])
    best = None
    for t in all_tracks():
        if (t["id"] in used or not usable(t) or t["energy"] > 2 or (final and t["mood"] not in FINAL_MOODS)
                or not allowed(t, tones, final, settings.get("ending"), settings.get("evolution", "constante"))):
            continue
        key = (-len(wanted & set(t["genres"])), t["energy"], t["id"])
        if best is None or key < best[0]:
            best = (key, t)
    return best[1] if best else None


def _pick_role(role, tones, settings, used) -> dict | None:
    evolution = settings.get("evolution", "constante")
    if role == "final" or (role == "intro" and evolution == "calme_explosion"):
        return _calm(role, tones, settings, used)
    energy = settings.get("energy", 3)
    if role == "peak":
        target = 5 if evolution == "calme_explosion" else energy + 1
    elif role == "intro":
        target = energy - 1
    else:
        target = energy
    got = candidates(tones, settings, final=False, exclude=used, target=max(1, min(5, target)))
    return got[0] if got else None


def plan_tracks(tones: list[str], settings: dict, exclude: dict | None = None, keep: dict | None = None) -> list[dict]:
    """Morceaux du film selon l'évolution : [{"role", "track"}] dans l'ordre de lecture.
    `exclude` : {rôle: [ids]} à ne pas proposer pour ce rôle (« Autre titre ») ;
    `keep` : {rôle: morceau} déjà choisis, gardés s'ils restent jouables et permis pour ce rôle.
    Un rôle sans candidat est omis ; jamais deux fois le même morceau ; un morceau final seul n'est pas joué."""
    exclude = exclude or {}
    roles = roles_for(settings)
    ending, evolution = settings.get("ending"), settings.get("evolution", "constante")
    chosen, used = {}, set()
    for role in PICK_ORDER:
        t = (keep or {}).get(role)
        if (role in roles and t and t["id"] not in used and usable(t)
                and allowed(t, tones, role == "final", ending, evolution)):
            chosen[role] = t
            used.add(t["id"])
    for role in PICK_ORDER:
        if role in roles and role not in chosen:
            t = _pick_role(role, tones, settings, used | set(exclude.get(role) or ()))
            if t:
                chosen[role] = t
                used.add(t["id"])
    if set(chosen) <= {"final"}:  # pas de morceau avant la séquence finale : film sans musique
        return []
    return [{"role": r, "track": chosen[r]} for r in ROLES if r in chosen]


def choose(tones: list[str], settings: dict, exclude=()) -> dict:
    """Ancienne interface (PR 1) : morceau principal et, si la fin est touchante, morceau final."""
    ex = list(exclude)
    got = {p["role"]: p["track"]
           for p in plan_tracks(tones, {**settings, "evolution": "constante"}, {"main": ex, "final": ex})}
    return {"main": got.get("main"), "final": got.get("final")}
