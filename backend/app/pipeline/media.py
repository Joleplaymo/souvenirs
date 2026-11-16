"""Préparation des médias : sondes ffprobe, vignettes, images d'aperçu, horodatage."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

from .. import config, db

DISPLAY_PX = 3000
THUMB_PX = 480


def sh(args, timeout=3600):
    p = subprocess.run(args, capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{args[0]} a échoué : {p.stderr.decode(errors='replace')[-600:]}")
    return p.stdout


def probe(path) -> dict:
    out = sh(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], 120)
    d = json.loads(out)
    info = {"duration": None, "has_audio": False, "has_video": False, "width": None, "height": None, "created": None}
    try:
        info["duration"] = float(d["format"]["duration"])
    except (KeyError, ValueError):
        pass
    info["created"] = (d.get("format", {}).get("tags") or {}).get("creation_time")
    for s in d.get("streams", []):
        if s.get("codec_type") == "audio":
            info["has_audio"] = True
        elif s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1:
            info["has_video"] = True
            w, h = s.get("width"), s.get("height")
            rot = 0
            for sd in s.get("side_data_list", []) or []:
                rot = sd.get("rotation", rot) or rot
            if abs(int(rot)) in (90, 270):
                w, h = h, w
            info["width"], info["height"] = w, h
    return info


def derived(event_id: int, item_id: int, variant: str) -> Path:
    d = config.event_dir(event_id) / "derived"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{item_id}_{variant}.jpg"


def raw_path(item) -> Path | None:
    if not item["path"]:
        return None
    p = config.event_dir(item["event_id"]) / item["path"]
    return p if p.exists() else None


def _save_variants(img: Image.Image, event_id: int, item_id: int):
    img = img.convert("RGB")
    d = img.copy()
    d.thumbnail((DISPLAY_PX, DISPLAY_PX), Image.LANCZOS)
    d.save(derived(event_id, item_id, "d"), "JPEG", quality=88, optimize=True)
    t = img.copy()
    t.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
    t.save(derived(event_id, item_id, "t"), "JPEG", quality=80)
    return d.size


def _exif_time(img: Image.Image, tz: str) -> str | None:
    try:
        exif = img.getexif()
        sub = exif.get_ifd(0x8769)
        for tag, off_tag in ((0x9003, 0x9011), (0x9004, 0x9012)):  # prise de vue, numérisation
            if sub.get(tag):
                raw, offset = sub.get(tag), sub.get(off_tag)
                break
        else:
            raw, offset = exif.get(0x0132), sub.get(0x9010)
        if not raw:
            return None
        naive = datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S")
        try:  # décalage horaire enregistré par l'appareil (« +01:00 »), sinon fuseau de l'événement
            when = datetime.strptime(f"{naive:%Y-%m-%dT%H:%M:%S}{str(offset).strip()}", "%Y-%m-%dT%H:%M:%S%z")
        except (TypeError, ValueError):
            when = naive.replace(tzinfo=ZoneInfo(tz))
        return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def prepare(item_id: int):
    """Calcule vignette, aperçu, durée et (pour les imports) la vraie date de prise de vue."""
    item = db.one("SELECT * FROM items WHERE id=?", item_id)
    if item is None:
        return
    ev = db.one("SELECT * FROM events WHERE id=?", item["event_id"])
    src = raw_path(item)
    vals = {"status": "ready"}
    try:
        if src is None:
            raise RuntimeError("fichier introuvable")
        if item["kind"] == "photo":
            with Image.open(src) as im:
                when = _exif_time(im, ev["tz"])
                im = ImageOps.exif_transpose(im)
                vals["width"], vals["height"] = _save_variants(im, item["event_id"], item_id)
            if when and item["source"] == "import":
                vals["captured_at"] = when
        else:
            info = probe(src)
            vals["duration"] = info["duration"]
            if item["kind"] == "video":
                if not info["has_video"]:
                    raise RuntimeError("aucune piste vidéo")
                vals["width"], vals["height"] = info["width"], info["height"]
                poster = derived(item["event_id"], item_id, "p")
                at = min(1.0, (info["duration"] or 1) / 3)
                sh(["ffmpeg", "-y", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1", "-q:v", "3", str(poster)], 300)
                with Image.open(poster) as im:
                    _save_variants(im, item["event_id"], item_id)
                poster.unlink(missing_ok=True)
                if info["created"] and item["source"] == "import":
                    vals["captured_at"] = info["created"][:19] + "Z"
    except Exception as e:  # le fichier reste listé, marqué en erreur
        vals = {"status": "error", "text": f"Fichier illisible : {e}"[:300]}
    db.update("items", "id", item_id, **vals)


def video_frames(item, count=3) -> list[Path]:
    """Extrait quelques images d'une vidéo pour que Claude puisse la « voir »."""
    src = raw_path(item)
    out = []
    if src is None or not item["duration"]:
        return out
    for i in range(count):
        p = derived(item["event_id"], item["id"], f"f{i}")
        if not p.exists():
            at = item["duration"] * (i + 0.5) / count
            try:
                sh(["ffmpeg", "-y", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1",
                    "-vf", "scale=768:768:force_original_aspect_ratio=decrease", "-q:v", "4", str(p)], 300)
            except Exception:
                continue
        if p.exists():
            out.append(p)
    return out
