"""Montage vidéo FFmpeg à partir du plan de montage (1920×1080, H.264 + AAC, lisible partout)."""
import json
import re
import shutil
import textwrap
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import media

W, H, FPS = 1920, 1080, 30
ENC = ["-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k", "-video_track_timescale", "15360"]
SILENCE = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]


@lru_cache
def font_path(kind: str) -> str:
    wanted = {
        "serif": ["PlayfairDisplay-Bold", "Playfair*Bold", "DejaVuSerif-Bold", "LiberationSerif-Bold"],
        "sans": ["Lato-Bold", "Lato-Semibold", "DejaVuSans-Bold", "LiberationSans-Bold"],
    }[kind]
    roots = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]
    for pat in wanted:
        for root in roots:
            hit = sorted(root.rglob(pat + "*.[ot]tf")) if root.exists() else []
            if hit:
                return str(hit[0])
    raise RuntimeError("Aucune police trouvée pour le montage.")


def _font(kind, size):
    return ImageFont.truetype(font_path(kind), size)


def title_card(text: str, out: Path):
    img = Image.new("RGB", (W, H), "#2a1c14")
    d = ImageDraw.Draw(img)
    for y in range(H):  # léger dégradé chaud
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(58 - 26 * k), int(38 - 16 * k), int(26 - 10 * k)))
    lines = [ln for par in text.strip().split("\n") for ln in (textwrap.wrap(par, 26) or [""])] or [""]
    size = 96 if len(lines) <= 2 else 76 if len(lines) <= 6 else 56
    f = _font("serif", size)
    total = len(lines) * int(size * 1.25)
    y = (H - total) // 2
    d.line([(W // 2 - 70, y - 40), (W // 2 + 70, y - 40)], fill="#e0a458", width=4)
    for ln in lines:
        w = d.textlength(ln, font=f)
        d.text(((W - w) / 2, y), ln, font=f, fill="#f7ecd9")
        y += int(size * 1.25)
    d.line([(W // 2 - 70, y + 24), (W // 2 + 70, y + 24)], fill="#e0a458", width=4)
    img.save(out)


def subtitle_png(text: str, out: Path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = _font("sans", 46)
    lines = textwrap.wrap(text.strip(), 52)[:3]
    lh = 60
    widths = [d.textlength(ln, font=f) for ln in lines]
    bw, bh = max(widths) + 72, lh * len(lines) + 36
    x0, y0 = (W - bw) / 2, H - 90 - bh
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=22, fill=(20, 14, 10, 175))
    for i, ln in enumerate(lines):
        d.text(((W - widths[i]) / 2, y0 + 16 + i * lh), ln, font=f, fill="#fff8ec")
    img.save(out)


def photo_canvas(src: Path, out: Path):
    """Photo centrée sur un fond flouté, un peu plus grande que l'image finale pour le zoom lent."""
    cw, ch = 2880, 1620
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        bg = ImageOps.fit(im, (cw // 8, ch // 8)).filter(ImageFilter.GaussianBlur(6)).resize((cw, ch))
        bg = Image.eval(bg, lambda v: int(v * 0.55))
        fg = ImageOps.contain(im, (cw, ch), Image.LANCZOS)
        bg.paste(fg, ((cw - fg.width) // 2, (ch - fg.height) // 2))
    bg.save(out, "JPEG", quality=92)


def normalize(plan: dict, items: dict, target: int) -> list[dict]:
    """Valide le plan de Claude et l'ajuste à la durée demandée."""
    segs = []
    for s in (plan or {}).get("segments", []):
        t = s.get("type")
        text = (s.get("text") or "").strip()
        if t == "title" and text:
            segs.append({"type": "title", "item_id": 0, "text": text[:80],
                         "duration": min(3.5, max(2.0, float(s.get("duration") or 2.5)))})
            continue
        it = items.get(s.get("item_id"))
        if it is None:
            continue
        if t == "photo" and it["kind"] == "photo":
            segs.append({"type": "photo", "item_id": it["id"], "text": text[:140],
                         "duration": min(6.0, max(2.0, float(s.get("duration") or 3.5)))})
        elif t == "video" and it["kind"] == "video" and it["duration"]:
            total = float(it["duration"])
            start = min(max(0.0, float(s.get("start") or 0)), max(0.0, total - 1.5))
            end = float(s.get("end") or 0)
            end = min(total, end if end > start else start + 8)
            if end - start < 1.0:
                continue
            segs.append({"type": "video", "item_id": it["id"], "text": text[:140],
                         "start": round(start, 2), "duration": round(min(end - start, 30.0), 2)})
    # un carton de titre sans rien derrière n'a pas de sens
    while segs and segs[-1]["type"] == "title":
        segs.pop()

    def total():
        return sum(s["duration"] for s in segs)

    if target and total() > target * 1.08:
        k = target / total()
        for s in segs:
            floor = {"title": 2.0, "photo": 2.0, "video": 2.5}[s["type"]]
            s["duration"] = round(max(floor, s["duration"] * k), 2)
        while total() > target * 1.1 and len(segs) > 2:  # encore trop long : on retire depuis le milieu
            mids = [i for i, s in enumerate(segs) if s["type"] != "title" and 0 < i < len(segs) - 1]
            if not mids:
                break
            segs.pop(mids[len(mids) // 2])
    return segs


def _render_segment(seg, item, tmp: Path, idx: int) -> Path:
    out = tmp / f"seg{idx:04d}.mp4"
    dur = seg["duration"]
    fade = f"fade=t=in:st=0:d=0.3,fade=t=out:st={max(0, dur - 0.3):.2f}:d=0.3"
    sub = None
    if seg["type"] != "title" and seg.get("text"):
        sub = tmp / f"sub{idx:04d}.png"
        subtitle_png(seg["text"], sub)
    if seg["type"] == "title":
        card = tmp / f"card{idx:04d}.png"
        title_card(seg["text"], card)
        media.sh(["ffmpeg", "-y", "-loop", "1", "-t", f"{dur}", "-i", str(card), *SILENCE,
                  "-vf", fade + ",format=yuv420p", "-t", f"{dur}", *ENC, str(out)])
    elif seg["type"] == "photo":
        src = media.derived(item["event_id"], item["id"], "d")
        canvas = tmp / f"canvas{idx:04d}.jpg"
        photo_canvas(src, canvas)
        n = int(dur * FPS)
        zoom = (f"zoompan=z='1+0.07*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS}")
        args = ["ffmpeg", "-y", "-i", str(canvas)]
        if sub:
            args += ["-i", str(sub)]
        args += SILENCE
        fc = f"[0:v]{zoom}[z];" + ("[z][1:v]overlay[o];[o]" if sub else "[z]") + fade + ",format=yuv420p[v]"
        args += ["-filter_complex", fc, "-map", "[v]", "-map", f"{2 if sub else 1}:a", "-t", f"{dur}", *ENC, str(out)]
        media.sh(args)
    else:
        src = media.raw_path(item)
        if src is None:
            raise RuntimeError("vidéo source absente")
        has_audio = media.probe(src)["has_audio"]
        args = ["ffmpeg", "-y", "-ss", f"{seg['start']}", "-t", f"{dur}", "-i", str(src)]
        if sub:
            args += ["-i", str(sub)]
        args += SILENCE
        sil = 2 if sub else 1
        fc = (f"[0:v]fps={FPS},split[a][b];"
              f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:4,eq=brightness=-0.12[bg];"
              f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
              "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[c];"
              + ("[c][1:v]overlay[o];[o]" if sub else "[c]") + fade + ",format=yuv420p[v];")
        if has_audio:
            fc += (f"[0:a]aresample=48000,afade=t=in:d=0.15,afade=t=out:st={max(0, dur - 0.2):.2f}:d=0.2[a0];"
                   f"[a0][{sil}:a]amix=inputs=2:duration=longest:normalize=0[au]")
        else:
            fc += f"[{sil}:a]anull[au]"
        args += ["-filter_complex", fc, "-map", "[v]", "-map", "[au]", "-t", f"{dur}", *ENC, str(out)]
        media.sh(args)
    return out


BASE = "video_base.mp4"  # film monté sans musique (carton de crédit compris), pour changer la musique seule
META = "video_base.json"  # {"final_from", "body", "credits"} : ce qu'il faut pour refaire le mélange


def credit_lines(credits) -> list[str]:
    seen = []
    for c in credits or []:
        c = (c or "").strip()
        if c and c not in seen:
            seen.append(c)
    return seen


def credit_segment(credits: list[str]) -> dict:
    """Carton final « Musique » + une ligne par morceau (le préfixe « Musique : » est porté par l'en-tête)."""
    lines = [re.sub(r"^Musique\s*:\s*", "", c) for c in credits]
    return {"type": "title", "item_id": 0, "text": "Musique\n" + "\n".join(lines), "duration": 3.0}


def _concat(files: list[Path], lst: Path, out: Path):
    """Concatène sans réencoder des fichiers rangés dans le même dossier que la liste."""
    lst.write_text("".join(f"file '{f.name}'\n" for f in files))
    media.sh(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])


def read_meta(base: Path) -> dict | None:
    try:
        return json.loads((base.parent / META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def render(segs: list[dict], items: dict, out: Path, tracks: dict, mix: int, on_progress=None) -> float:
    """Assemble les segments (+ carton de crédit) dans video_base.mp4, puis y mélange la musique dans `out`.
    tracks = {"main": Path | None, "final": Path | None, "credits": [str]}. Retourne la durée finale."""
    if not segs:
        raise RuntimeError("Le plan de montage est vide : il faut au moins une photo ou une vidéo.")
    tmp = out.parent / "tmp_video"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        files, t, final_from = [], 0.0, None
        for i, seg in enumerate(segs):
            try:
                f = _render_segment(seg, items.get(seg["item_id"]), tmp, i)
            except Exception as e:  # un extrait illisible ne doit pas faire échouer tout le montage
                print(f"[montage] segment {i} ignoré : {e}", flush=True)
                f = None
            if f is not None:
                if seg["type"] == "title" and t > 0:
                    final_from = t  # début du dernier carton de titre (hors ouverture) : entrée du morceau final
                files.append(f)
                t += media.probe(f)["duration"] or seg["duration"]
            if on_progress:
                on_progress((i + 1) / (len(segs) + 1))
        if not files:
            raise RuntimeError("Aucun extrait n'a pu être monté.")
        credits = credit_lines(tracks.get("credits"))
        if credits:
            files.append(_render_segment(credit_segment(credits), None, tmp, len(segs)))
        joined = tmp / "joined.mp4"
        _concat(files, tmp / "list.txt", joined)
        base = out.parent / BASE
        joined.replace(base)
        (out.parent / META).write_text(json.dumps({"final_from": final_from, "body": round(t, 3),
                                                   "credits": credits}, ensure_ascii=False), encoding="utf-8")
        mix_music(base, out, tracks, mix, final_from)
        return media.probe(base)["duration"] or 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def recredit(base: Path, credits: list[str]):
    """Remplace le carton de crédit de video_base.mp4 si les morceaux crédités ont changé."""
    meta = read_meta(base)
    credits = credit_lines(credits)
    if meta is None or meta.get("credits", []) == credits:
        return
    tmp = base.parent / "tmp_credit"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        body = tmp / "body.mp4"
        if meta.get("credits"):  # on retire l'ancien carton (chaque segment commence sur une image clé)
            media.sh(["ffmpeg", "-y", "-i", str(base), "-t", f"{meta['body']}", "-c", "copy", str(body)])
        else:
            shutil.copy2(base, body)
        files = [body]
        if credits:
            files.append(_render_segment(credit_segment(credits), None, tmp, 0))
        new = tmp / "base.mp4"
        _concat(files, tmp / "list.txt", new)
        new.replace(base)
        meta["credits"] = credits
        (base.parent / META).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def mix_music(base: Path, out: Path, tracks: dict, mix: int, final_from: float | None) -> None:
    """Mélange la musique sous le son du film (compression latérale) ; sans morceau, copie le film tel quel.
    Morceau final : fondu enchaîné de 2 s depuis le principal, à partir de `final_from`."""
    total = media.probe(base)["duration"] or 0
    tmp = out.with_name(out.stem + ".mix.mp4")
    main, final = tracks.get("main"), tracks.get("final")
    if not main:
        media.sh(["ffmpeg", "-y", "-i", str(base), "-c", "copy", "-movflags", "+faststart", str(tmp)])
        tmp.replace(out)
        return
    vol = 0.15 + 0.85 * max(0, min(100, int(mix))) / 100
    fmt = "aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS"
    args = ["ffmpeg", "-y", "-i", str(base), "-stream_loop", "-1", "-i", str(main)]
    if final and final_from is not None and 0 < final_from < total - 2:
        args += ["-stream_loop", "-1", "-i", str(final)]
        bed = (f"[1:a]{fmt},atrim=0:{final_from + 2:.3f}[m1];[2:a]{fmt}[m2];"
               "[m1][m2]acrossfade=d=2[bed];")
    else:
        bed = f"[1:a]{fmt}[bed];"
    fc = ("[0:a]asplit[voice][key];" + bed
          + f"[bed]volume={vol:.3f},afade=t=in:d=1.5,afade=t=out:st={max(0, total - 3):.2f}:d=3[m];"
          "[m][key]sidechaincompress=threshold=0.02:ratio=10:attack=150:release=900[duck];"
          "[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    media.sh([*args, "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
              "-c:a", "aac", "-b:a", "192k", "-t", f"{total}", "-movflags", "+faststart", str(tmp)])
    tmp.replace(out)
