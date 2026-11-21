"""Chaîne de génération : transcription → chronologie → récit → montage → album."""
import json
import shutil

from .. import config, db
from . import ai, album, media, timeline, transcribe, video


class Progress:
    def __init__(self, job_id):
        self.job_id = job_id

    def __call__(self, step: str, progress: float, message: str = ""):
        db.update("jobs", "id", self.job_id, step=step, progress=round(progress, 3), message=message)


def out_dir(event_id: int, which="draft"):
    d = config.event_dir(event_id) / "out" / which
    d.mkdir(parents=True, exist_ok=True)
    return d


def fr_dates(ev) -> str:
    def fmt(s):
        y, m, d = (int(x) for x in s.split("-"))
        return f"{d} {timeline.MOIS[m - 1]} {y}"

    return fmt(ev["start_date"]) if ev["start_date"] == ev["end_date"] else f"{fmt(ev['start_date'])} – {fmt(ev['end_date'])}"


def _transcribe_all(ev, prog, lo, hi):
    todo = [it for it in timeline.load_items(ev["id"])
            if it["kind"] in ("dictee", "conversation", "video") and it["transcript"] is None]
    for n, it in enumerate(todo):
        src = media.raw_path(it)
        label = f"{timeline.LABELS[it['kind']]} de {it['author']} ({n + 1}/{len(todo)})"

        def cb(frac, n=n, label=label):
            prog("transcription", lo + (hi - lo) * (n + frac) / len(todo), label)

        cb(0)
        segs = []
        if src is not None and (it["kind"] != "video" or media.probe(src)["has_audio"]):
            segs = transcribe.transcribe(src, cb, it["duration"])
        db.update("items", "id", it["id"], transcript=json.dumps(segs, ensure_ascii=False),
                  transcript_text=" ".join(s["t"] for s in segs))


def _describe_all(ev, prog, lo, hi):
    todo = [it for it in timeline.load_items(ev["id"]) if it["kind"] in ("photo", "video") and it["vision"] is None]
    entries = []
    for it in todo:
        paths = [media.derived(ev["id"], it["id"], "d")] if it["kind"] == "photo" else media.video_frames(it)
        paths = [p for p in paths if p.exists()]
        if paths:
            entries.append((it, paths))
    batches, cur, n_img = [], [], 0
    for e in entries:  # lots d'une vingtaine d'images par appel
        if cur and n_img + len(e[1]) > 20:
            batches.append(cur)
            cur, n_img = [], 0
        cur.append(e)
        n_img += len(e[1])
    if cur:
        batches.append(cur)
    for n, batch in enumerate(batches):
        prog("analyse", lo + (hi - lo) * n / len(batches), f"Analyse des images ({n + 1}/{len(batches)})")
        res = ai.describe(ev, batch)
        for it, _ in batch:
            v = res.get(it["id"], {"description": "", "score": 5})
            db.update("items", "id", it["id"], vision=json.dumps(v, ensure_ascii=False))


def _people(event_id):
    return [r["name"] for r in db.q(
        "SELECT DISTINCT p.name FROM participants p JOIN items i ON i.participant_id=p.id "
        "WHERE i.event_id=? ORDER BY p.name", event_id)]


def render_video(ev, rep, prog, lo, hi):
    items = {it["id"]: it for it in timeline.load_items(ev["id"])}
    segs = [s for s in db.jl(rep["montage"], []) if s["item_id"] == 0 or s["item_id"] in items]
    while segs and segs[-1]["type"] == "title":
        segs.pop()
    out = out_dir(ev["id"]) / "video.mp4"
    video.render(segs, items, ev["tone"], out, lambda f: prog("montage", lo + (hi - lo) * f, "Montage de la vidéo"))
    db.update("reports", "event_id", ev["id"], video_ready=1, montage=json.dumps(segs, ensure_ascii=False))


def render_album(ev, rep, prog, at):
    prog("album", at, "Mise en page de l'album")
    photos = {it["id"]: it for it in timeline.load_items(ev["id"]) if it["kind"] == "photo"}
    alb = db.jl(rep["album"])
    if not alb or not album.photo_ids(alb):
        db.update("reports", "event_id", ev["id"], album_ready=0)
        return
    album.render(alb, photos, ev, _people(ev["id"]), out_dir(ev["id"]) / "album.pdf", fr_dates(ev))
    db.update("reports", "event_id", ev["id"], album_ready=1)


def generate(job):
    """parts ⊂ {text, video, album} ; ai=False ne fait que refaire le rendu à partir des plans existants."""
    ev = db.one("SELECT * FROM events WHERE id=?", job["event_id"])
    params = db.jl(job["params"], {})
    parts = set(params.get("parts") or ["text", "video", "album"])
    use_ai = params.get("ai", True)
    prog = Progress(job["id"])
    rep = db.report(ev["id"])
    if params.get("video_duration"):
        db.update("reports", "event_id", ev["id"], video_duration=int(params["video_duration"]))
    if "video_prompt" in params:  # consignes pour le film, gardées pour les générations suivantes
        db.update("reports", "event_id", ev["id"], video_prompt=str(params["video_prompt"] or "").strip()[:4000])
        rep = db.report(ev["id"])
    target = int(params.get("video_duration") or rep["video_duration"] or 120)

    if use_ai:
        from . import versions

        if versions.dirty(ev["id"]):  # corrections pas encore enregistrées : on les garde avant de tout refaire
            versions.snapshot(ev["id"], origin="auto", suffix=" · corrigée (avant régénération)")
        _transcribe_all(ev, prog, 0.0, 0.35)
        _describe_all(ev, prog, 0.35, 0.47)
        items = timeline.load_items(ev["id"])
        if not items:
            raise RuntimeError("Aucun souvenir à raconter pour l'instant.")
        report_md = rep["text_md"]
        if "text" in parts or not report_md:
            prog("redaction", 0.48, "Rédaction du compte rendu")
            report_md = ai.write_report(ev, items)
            db.update("reports", "event_id", ev["id"], text_md=report_md, updated_at=db.now(),
                      ai_mode="claude" if ai.enabled() else "local")
        by_id = {it["id"]: it for it in items}
        if "video" in parts:
            prog("montage", 0.6, "Choix des meilleurs moments")
            plan = ai.plan_montage(ev, report_md, items, target, rep["video_prompt"] or "")
            segs = video.normalize(plan, by_id, target)
            db.update("reports", "event_id", ev["id"], montage=json.dumps(segs, ensure_ascii=False), video_ready=0)
        if "album" in parts:
            prog("album", 0.62 if "video" not in parts else 0.61, "Sélection des photos de l'album")
            photos = [it for it in items if it["kind"] == "photo"]
            plan = album.normalize(ai.plan_album(ev, report_md, photos), {p["id"]: p for p in photos})
            db.update("reports", "event_id", ev["id"], album=json.dumps(plan, ensure_ascii=False), album_ready=0,
                      selection=json.dumps(album.photo_ids(plan)))
    rep = db.report(ev["id"])
    if "video" in parts:
        if db.jl(rep["montage"]):
            render_video(ev, rep, prog, 0.63, 0.92)
        else:
            db.update("reports", "event_id", ev["id"], video_ready=0)
    if "album" in parts:
        render_album(ev, rep, prog, 0.93)
    if use_ai:  # chaque génération devient une version, pour comparer les tons et revenir en arrière
        from . import versions

        versions.snapshot(ev["id"], origin="generation")
    prog("termine", 1.0, "Terminé")


def publish(event_id: int):
    """Fige la version visible par les participants (copie des résultats finaux)."""
    rep = db.report(event_id)
    draft, pub = out_dir(event_id), out_dir(event_id, "published")
    sel = db.jl(rep["selection"], [])
    photos_dir = pub / "photos"
    shutil.rmtree(photos_dir, ignore_errors=True)
    photos_dir.mkdir(parents=True)
    kept = []
    for i in sel:
        it = db.one("SELECT id FROM items WHERE id=? AND event_id=? AND excluded=0", i, event_id)
        src = media.derived(event_id, i, "d")
        if it and src.exists():
            shutil.copy2(src, photos_dir / f"{i}.jpg")
            shutil.copy2(media.derived(event_id, i, "t"), photos_dir / f"{i}_t.jpg")
            kept.append(i)
    has = {}
    for name, ready in (("video.mp4", rep["video_ready"]), ("album.pdf", rep["album_ready"])):
        if ready and (draft / name).exists():
            shutil.copy2(draft / name, pub / name)
            has[name] = 1
        else:
            (pub / name).unlink(missing_ok=True)
            has[name] = 0
    ev = db.one("SELECT published_at FROM events WHERE id=?", event_id)
    if not ev["published_at"]:
        db.update("events", "id", event_id, published_at=db.now())
    db.update("reports", "event_id", event_id, pub_text_md=rep["text_md"], pub_selection=json.dumps(kept),
              published_from=rep["current_version"],
              pub_has_video=has["video.mp4"], pub_has_album=has["album.pdf"], pub_version=rep["pub_version"] + 1)
