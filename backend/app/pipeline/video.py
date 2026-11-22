"""Montage vidéo FFmpeg à partir du plan de montage (16:9, 9:16 ou 1:1, H.264 + AAC, lisible partout)."""
import json
import re
import shutil
import textwrap
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import media

FPS = 30


@dataclass(frozen=True)
class Frame:
    """Dimensions du film. Tailles de police et marges sont proportionnelles au petit côté (1080 = référence)."""
    w: int
    h: int

    @property
    def k(self) -> float:
        return min(self.w, self.h) / 1080


DEFAULT_FRAME = Frame(1920, 1080)
FRAMES = {"16:9": Frame(1920, 1080), "9:16": Frame(1080, 1920), "1:1": Frame(1080, 1080)}


def frame_for(framing: str) -> Frame:
    return FRAMES.get(framing, FRAMES["16:9"])


@dataclass(frozen=True)
class Style:
    """Rythme, effets permis, style des cartons et tempo (bpm du morceau principal, None = pas de calage)."""
    rhythm: str = "dynamique"
    effects: dict = field(default_factory=dict)
    title_style: str = "carnet"
    bpm: int | None = None

    @classmethod
    def of(cls, st: dict, bpm=None) -> "Style":
        """Style à partir des réglages vidéo normalisés (settings.normalize)."""
        return cls(rhythm=st.get("rhythm", "dynamique"), effects=dict(st.get("effects") or {}),
                   title_style=st.get("title_style", "carnet"), bpm=bpm or None)


# bornes de durée des plans (photo et vidéo) par rythme ; vidéo jusqu'à 6 s en dynamique ;
# en nerveux, au plus un plan sur quatre jusqu'à 3 s
SHOT_BOUNDS = {"pose": (3.0, 5.0), "dynamique": (1.5, 3.0), "nerveux": (0.5, 1.5)}
VIDEO_MAX = {"dynamique": 6.0}
NERVEUX_LONG = 3.0
TITLE_BOUNDS = (1.5, 3.0)
FADES = {"pose": 0.3, "dynamique": 0.15, "nerveux": 0.0}
EFFECTS = ("none", "slowmo", "speedup", "freeze", "punch")
VIDEO_ONLY = ("slowmo", "speedup", "freeze")
FREEZE_HOLD = 1.0  # image tenue à la fin d'un arrêt sur image
FREEZE_MIN = FREEZE_HOLD + 0.5  # plan le plus court pour un arrêt sur image
PUNCH = (1.25, 0.2)  # zoom final, durée du zoom


def _rhythm(style) -> str | None:
    if style is None:
        return None
    return style.rhythm if style.rhythm in SHOT_BOUNDS else "dynamique"


def fade_for(style) -> float:
    """Durée des fondus d'entrée et de sortie ; sans style : 0,3 s comme avant."""
    r = _rhythm(style)
    return 0.3 if r is None else FADES[r]


def source_need(effect: str, dur: float) -> float:
    """Secondes de vidéo source nécessaires pour `dur` secondes rendues avec l'effet."""
    return {"slowmo": dur / 2, "speedup": dur * 2, "freeze": max(0.0, dur - FREEZE_HOLD)}.get(effect, dur)


def _max_out(effect: str, avail: float) -> float:
    """Durée rendue maximale avec l'effet, quand la source offre `avail` secondes."""
    return {"slowmo": avail * 2, "speedup": avail / 2, "freeze": avail + FREEZE_HOLD}.get(effect, avail)


def _source_start(effect: str, start: float, dur: float, total: float) -> float:
    """Début de l'extrait source ramené dans [0, durée source] (on recule le début si la fin manque)."""
    return round(max(0.0, min(start, total - source_need(effect, dur))), 3)


ENC = ["-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k", "-video_track_timescale", "15360"]
SILENCE = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]


FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"  # polices livrées avec l'appli (Caveat, licence OFL)


@lru_cache
def font_path(kind: str) -> str:
    if kind == "hand":  # écriture manuscrite ; repli : le serif des cartons d'avant
        for name in ("Caveat-Bold.ttf", "Caveat-Variable.ttf"):
            if (FONT_DIR / name).is_file():
                return str(FONT_DIR / name)
        return font_path("serif")
    wanted = {
        "serif": ["PlayfairDisplay-Bold", "Playfair*Bold", "DejaVuSerif-Bold", "LiberationSerif-Bold"],
        "sans": ["Lato-Bold", "Lato-Semibold", "DejaVuSans-Bold", "LiberationSans-Bold"],
        "sans-light": ["Lato-Light", "Lato-Regular", "LiberationSans-Regular", "DejaVuSans-ExtraLight"],
    }[kind]
    roots = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]
    for pat in wanted:
        for root in roots:
            hit = sorted(root.rglob(pat + "*.[ot]tf")) if root.exists() else []
            if hit:
                return str(hit[0])
    raise RuntimeError("Aucune police trouvée pour le montage.")


def _font(kind, size):
    f = ImageFont.truetype(font_path(kind), size)
    if kind == "hand" and "Variable" in font_path(kind):
        try:
            f.set_variation_by_axes([700])  # police variable Caveat : graisse Bold
        except Exception:
            pass
    return f


def _wrap_px(d, text: str, f, maxw: float) -> list[str]:
    """Retour à la ligne au mot près pour que chaque ligne tienne dans maxw pixels."""
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if cur and d.textlength(t, font=f) > maxw:
            lines.append(cur)
            cur = word
        else:
            cur = t
    return lines + ([cur] if cur else [])


TITLE_STYLES = ("carnet", "sobre", "pop")
POP_COLORS = ("#ff3d71", "#ffb400", "#00b8d9", "#7a42f4", "#22c55e")  # palette vive, choisie selon l'index du carton
POP_TILT = -3  # degrés


def _card_style(style) -> str:
    """Style de carton effectif : « aucun » (ou inconnu) ne laisse que les cartons à garder (crédit) → sobre."""
    return style if style in TITLE_STYLES else "sobre"


def _fit_lines(d, text, kind, k, ok, maxw):
    """Lignes et police : on rétrécit la taille (96/76/56 selon la longueur) jusqu'à ce que `ok(lines, size, font)` passe."""
    paras = [ln for par in text.strip().split("\n") for ln in (textwrap.wrap(par, 26) or [""])] or [""]
    size = 96 if len(paras) <= 2 else 76 if len(paras) <= 6 else 56
    while True:
        f = _font(kind, max(12, int(size * k)))
        lines = [sub for ln in paras for sub in (_wrap_px(d, ln, f, maxw) or [""])]
        if size <= 24 or ok(lines, size, f):
            return f, lines, size
        size -= 4


def title_card(text: str, out: Path, frame: Frame = DEFAULT_FRAME, style: str = "carnet", index: int = 0):
    W, H, k = frame.w, frame.h, frame.k
    style = _card_style(style)
    maxw, maxh = W * 0.84, H * 0.7
    if style == "pop":
        img = Image.new("RGB", (W, H), POP_COLORS[index % len(POP_COLORS)])
        d = ImageDraw.Draw(img)
        # texte posé sur un calque incliné de −3° ; on rétrécit jusqu'à ce que le calque incliné tienne dans les marges
        for shrink in (1.0, 0.92, 0.85, 0.78, 0.7, 0.6, 0.5, 0.4):
            kk = k * 1.1 * shrink
            f, lines, size = _fit_lines(d, text, "sans", kk, lambda ls, sz, fo: (
                len(ls) * int(sz * kk * 1.2) <= maxh * 0.9
                and all(d.textlength(ln, font=fo) <= maxw * 0.9 for ln in ls)), maxw * 0.9)
            lh = int(size * kk * 1.2)
            tw = int(max(d.textlength(ln, font=f) for ln in lines)) + 8
            layer = Image.new("RGBA", (tw, lh * len(lines) + lh // 2), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            for i, ln in enumerate(lines):
                ld.text(((tw - ld.textlength(ln, font=f)) / 2, i * lh), ln, font=f, fill="#ffffff")
            layer = layer.rotate(POP_TILT, resample=Image.BICUBIC, expand=True)
            if layer.width <= W * 0.92 and layer.height <= H * 0.8:
                break
        img.paste(layer, ((W - layer.width) // 2, (H - layer.height) // 2), layer)
        img.save(out)
        return
    if style == "sobre":
        img = Image.new("RGB", (W, H), "#000000")
        d = ImageDraw.Draw(img)
        kk = k * 0.9
        f, lines, size = _fit_lines(d, text, "sans-light", kk, lambda ls, sz, fo: (
            len(ls) * int(sz * kk * 1.3) <= maxh and all(d.textlength(ln, font=fo) <= maxw for ln in ls)), maxw)
        lh = int(size * kk * 1.3)
        y = (H - len(lines) * lh) // 2
        for ln in lines:
            d.text(((W - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill="#ffffff")
            y += lh
        img.save(out)
        return
    img = Image.new("RGB", (W, H), "#2a1c14")
    d = ImageDraw.Draw(img)
    for y in range(H):  # léger dégradé chaud
        c = y / H
        d.line([(0, y), (W, y)], fill=(int(58 - 26 * c), int(38 - 16 * c), int(26 - 10 * c)))
    f, lines, size = _fit_lines(d, text, "hand", k, lambda ls, sz, fo: (
        len(ls) * int(sz * k * 1.25) <= maxh and all(d.textlength(ln, font=fo) <= maxw for ln in ls)), maxw)
    lh = int(size * k * 1.25)
    y = (H - len(lines) * lh) // 2
    bar = int(70 * k)
    d.line([(W // 2 - bar, y - int(40 * k)), (W // 2 + bar, y - int(40 * k))], fill="#e0a458", width=max(2, int(4 * k)))
    for ln in lines:
        w = d.textlength(ln, font=f)
        d.text(((W - w) / 2, y), ln, font=f, fill="#f7ecd9")
        y += lh
    d.line([(W // 2 - bar, y + int(24 * k)), (W // 2 + bar, y + int(24 * k))], fill="#e0a458", width=max(2, int(4 * k)))
    img.save(out)


def subtitle_png(text: str, out: Path, frame: Frame = DEFAULT_FRAME):
    W, H, k = frame.w, frame.h, frame.k
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = _font("sans", max(10, int(46 * k)))
    pad = 72 * k
    lines = textwrap.wrap(text.strip(), 52)[:3]
    if any(d.textlength(ln, font=f) + pad > W * 0.94 for ln in lines):  # cadre étroit : on recoupe à la largeur
        lines = _wrap_px(d, text.strip(), f, W * 0.94 - pad)[:4]
    lh = int(60 * k)
    widths = [d.textlength(ln, font=f) for ln in lines]
    bw, bh = max(widths) + pad, lh * len(lines) + 36 * k
    x0, y0 = (W - bw) / 2, H - 90 * k - bh
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=22 * k, fill=(20, 14, 10, 175))
    for i, ln in enumerate(lines):
        d.text(((W - widths[i]) / 2, y0 + 16 * k + i * lh), ln, font=f, fill="#fff8ec")
    img.save(out)


def photo_canvas(src: Path, out: Path, frame: Frame = DEFAULT_FRAME):
    """Photo centrée sur un fond flouté, un peu plus grande que l'image finale pour le zoom lent."""
    cw, ch = frame.w * 3 // 2, frame.h * 3 // 2
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        bg = ImageOps.fit(im, (cw // 8, ch // 8)).filter(ImageFilter.GaussianBlur(6)).resize((cw, ch))
        bg = Image.eval(bg, lambda v: int(v * 0.55))
        fg = ImageOps.contain(im, (cw, ch), Image.LANCZOS)
        bg.paste(fg, ((cw - fg.width) // 2, (ch - fg.height) // 2))
    bg.save(out, "JPEG", quality=92)


def _effect(raw, kind: str, style) -> str:
    """Effet permis : interrupteur coupé → none ; ralenti, accéléré, arrêt sur image : vidéo seulement ;
    zoom comique (punch) : photo ou vidéo, si les effets humoristiques sont permis."""
    if style is None or kind == "title" or raw not in EFFECTS or raw == "none":
        return "none"
    if raw in VIDEO_ONLY:
        return raw if kind == "video" and style.effects.get(raw) else "none"
    return raw if style.effects.get("humor") else "none"


def _snap(d: float, lo: float, hi: float, beat: float) -> float:
    """Durée arrondie au multiple de temps le plus proche, sans sortir de [lo, hi] (inchangée si impossible)."""
    eps = 1e-6
    n = round(d / beat)
    if n * beat < lo - eps:
        n = math.ceil(lo / beat - eps)
    if n * beat > hi + eps:
        n = math.floor(hi / beat + eps)
    return n * beat if n > 0 and lo - eps <= n * beat <= hi + eps else d


def _fit(segs: list[dict], items: dict, style, snap: bool):
    """Ramène chaque segment dans les bornes du rythme (et l'effet dans ce que la source permet),
    puis, si `snap`, cale les durées sur le tempo. Recadre le début des extraits vidéo dans la source."""
    r = _rhythm(style)
    beat = None
    if snap and style.bpm and r != "pose":
        beat = 60 / style.bpm / (2 if r == "nerveux" else 1)
    since_long = 99  # plans depuis le dernier plan long (nerveux)
    for s in segs:
        if s["type"] == "title":
            lo, hi = TITLE_BOUNDS
        else:
            lo, hi = SHOT_BOUNDS[r]
            if s["type"] == "video":
                hi = VIDEO_MAX.get(r, hi)
            if r == "nerveux" and s["duration"] > hi and since_long >= 3:
                hi = NERVEUX_LONG
        total = None
        if s["type"] == "video":
            total = float(items[s["item_id"]]["duration"])
            if s["effect"] == "freeze":
                lo = max(lo, FREEZE_MIN)  # au moins 0,5 s d'extrait avant l'image tenue
            if s["effect"] != "none" and (_max_out(s["effect"], total) < lo or lo > hi):
                s["effect"] = "none"  # source trop courte ou plan trop court pour cet effet
                lo = SHOT_BOUNDS[r][0]
            hi = min(hi, _max_out(s["effect"], total))
            lo = min(lo, hi)  # source plus courte que le plancher : on garde ce qu'elle offre
        d = min(hi, max(lo, s["duration"]))
        if beat:
            d = _snap(d, lo, hi, beat)
        s["duration"] = round(d, 3)
        if total is not None:
            s["start"] = _source_start(s["effect"], s["start"], s["duration"], total)
        if s["type"] != "title":
            since_long = 0 if s["duration"] > SHOT_BOUNDS["nerveux"][1] + 1e-6 else since_long + 1


def keep_segments(segs: list[dict], keep) -> list[dict]:
    """Segments pour lesquels keep(s) est vrai. La marque de début de séquence (« section », posée quand les
    cartons sont retirés) d'un segment écarté passe au suivant gardé, sauf si c'est un carton (il marque déjà)."""
    out, carry = [], False
    for s in segs:
        if not keep(s):
            carry = carry or bool(s.get("section"))
            continue
        if carry and s["type"] != "title" and not s.get("section"):
            s = {**s, "section": True}
        carry = False
        out.append(s)
    return out


def _trim(segs: list[dict], target: int) -> bool:
    """Encore trop long : retire des plans depuis le milieu (marques de séquence gardées). Vrai si retrait."""
    cut = False
    while sum(s["duration"] for s in segs) > target * 1.1 and len(segs) > 2:
        mids = [i for i, s in enumerate(segs) if s["type"] != "title" and 0 < i < len(segs) - 1]
        if not mids:
            break
        victim = segs[mids[len(mids) // 2]]
        segs[:] = keep_segments(segs, lambda s: s is not victim)
        cut = True
    return cut


def normalize(plan: dict, items: dict, target: int, style: Style | None = None) -> list[dict]:
    """Valide le plan de Claude et l'ajuste à la durée demandée.
    Sans style : bornes d'avant les rythmes (titre 2–3,5 s, photo 2–6 s, vidéo jusqu'à 30 s), aucun effet.
    Style « aucun » : les cartons de séquence sont retirés, mais le premier plan de chaque séquence (sauf au
    début du film) porte "section": True, pour placer les morceaux de l'évolution comme sur un carton."""
    r = _rhythm(style)

    def asked(s, default, lo, hi):  # avec un rythme, la durée demandée est bornée ensuite par _fit
        d = float(s.get("duration") or default)
        return d if r is not None else min(hi, max(lo, d))

    segs = []
    pending = False  # un carton de séquence vient d'être retiré (style « aucun »)
    for s in (plan or {}).get("segments", []):
        t = s.get("type")
        text = (s.get("text") or "").strip()
        if t == "title" and text:
            if style is not None and style.title_style == "aucun":
                # pas de carton (le crédit musical, ajouté par render, reste) ; le plan suivant marque la séquence
                pending = pending or bool(segs)
                continue
            segs.append({"type": "title", "item_id": 0, "text": text[:80], "effect": "none",
                         "duration": asked(s, 2.5, 2.0, 3.5)})
            continue
        it = items.get(s.get("item_id"))
        if it is None:
            continue
        if t == "photo" and it["kind"] == "photo":
            segs.append({"type": "photo", "item_id": it["id"], "text": text[:140],
                         "effect": _effect(s.get("effect"), "photo", style), "duration": asked(s, 3.5, 2.0, 6.0)})
        elif t == "video" and it["kind"] == "video" and it["duration"]:
            total = float(it["duration"])
            start = min(max(0.0, float(s.get("start") or 0)), max(0.0, total - 1.5))
            end = float(s.get("end") or 0)
            end = min(total, end if end > start else start + 8)
            if end - start < (1.0 if r is None else min(1.0, SHOT_BOUNDS[r][0])):
                continue
            segs.append({"type": "video", "item_id": it["id"], "text": text[:140],
                         "effect": _effect(s.get("effect"), "video", style),
                         "start": round(start, 2), "duration": round(min(end - start, 30.0), 2)})
        else:
            continue
        if pending:
            segs[-1]["section"] = True
            pending = False
    # un carton de titre sans rien derrière n'a pas de sens
    while segs and segs[-1]["type"] == "title":
        segs.pop()
    if r is not None:
        _fit(segs, items, style, snap=False)

    def total():
        return sum(s["duration"] for s in segs)

    if target and total() > target * 1.08:
        k = target / total()
        for s in segs:
            if r is None:
                floor = {"title": 2.0, "photo": 2.0, "video": 2.5}[s["type"]]
            else:  # planchers du rythme (sinon le rythme nerveux serait impossible)
                floor = TITLE_BOUNDS[0] if s["type"] == "title" else SHOT_BOUNDS[r][0]
            s["duration"] = round(max(floor, s["duration"] * k), 2)
        _trim(segs, target)  # encore trop long : on retire depuis le milieu
    if r is not None:
        _fit(segs, items, style, snap=True)
        # le calage sur le tempo arrondit au temps le plus proche sans passer sous le plancher : il peut
        # rallonger le film ; on retire encore des plans du milieu, puis on recale (retirer un plan peut
        # rapprocher deux plans longs du rythme nerveux)
        if target and _trim(segs, target):
            _fit(segs, items, style, snap=True)
    return segs


def _punch(dur: float, var: str) -> str:
    """Facteur de zoom comique : 1 puis montée rapide jusqu'à 1,25 sur les 0,2 dernières secondes."""
    zmax, d = PUNCH
    t0 = max(0.0, dur - d)
    return f"(1+{zmax - 1}*clip(({var}-{t0:.3f})/{d},0,1))"


def _render_segment(seg, item, tmp: Path, idx: int, frame: Frame = DEFAULT_FRAME, style=None,
                    card_style=None) -> Path:
    W, H = frame.w, frame.h
    out = tmp / f"seg{idx:04d}.mp4"
    dur = seg["duration"]
    effect = seg.get("effect") or "none"
    fd = fade_for(style)
    if seg["type"] == "video" and item is not None and item["duration"]:
        # jamais plus long que ce que la source permet avec l'effet (sinon : silence et image manquante)
        dur = min(dur, round(_max_out(effect, float(item["duration"])), 3))
    fade = (f"fade=t=in:st=0:d={fd},fade=t=out:st={max(0, dur - fd):.2f}:d={fd}," if fd else "") + "format=yuv420p"
    sub = None
    if seg["type"] != "title" and seg.get("text"):
        sub = tmp / f"sub{idx:04d}.png"
        subtitle_png(seg["text"], sub, frame)
    if seg["type"] == "title":
        card = tmp / f"card{idx:04d}.png"
        title_card(seg["text"], card, frame,
                   _card_style(card_style or (style.title_style if style else "carnet")), idx)
        media.sh(["ffmpeg", "-y", "-loop", "1", "-t", f"{dur}", "-i", str(card), *SILENCE,
                  "-vf", fade, "-t", f"{dur}", *ENC, str(out)])
    elif seg["type"] == "photo":
        src = media.derived(item["event_id"], item["id"], "d")
        canvas = tmp / f"canvas{idx:04d}.jpg"
        photo_canvas(src, canvas, frame)
        n = int(dur * FPS)
        z = f"(1+0.07*on/{n})" + ("*" + _punch(dur, f"on/{FPS}") if effect == "punch" else "")
        zoom = (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS}")
        args = ["ffmpeg", "-y", "-i", str(canvas)]
        if sub:
            args += ["-i", str(sub)]
        args += SILENCE
        fc = f"[0:v]{zoom}[z];" + ("[z][1:v]overlay[o];[o]" if sub else "[z]") + fade + "[v]"
        args += ["-filter_complex", fc, "-map", "[v]", "-map", f"{2 if sub else 1}:a", "-t", f"{dur}", *ENC, str(out)]
        media.sh(args)
    else:
        src = media.raw_path(item)
        if src is None:
            raise RuntimeError("vidéo source absente")
        info = media.probe(src)
        has_audio = info["has_audio"] and effect != "slowmo"  # ralenti : son d'origine coupé
        total = float(item["duration"] or info["duration"] or 0)  # item : sqlite3.Row en production (pas de .get)
        start = float(seg.get("start") or 0)
        if total:  # extrait toujours ramené dans [0, durée source]
            start = _source_start(effect, start, dur, total)
        args = ["ffmpeg", "-y", "-ss", f"{start}", "-t", f"{source_need(effect, dur):.3f}", "-i", str(src)]
        if sub:
            args += ["-i", str(sub)]
        args += SILENCE
        sil = 2 if sub else 1
        speed = {"slowmo": "setpts=2*(PTS-STARTPTS),", "speedup": "setpts=0.5*(PTS-STARTPTS),"}.get(effect, "")
        hold = f",tpad=stop_mode=clone:stop_duration={FREEZE_HOLD}" if effect == "freeze" else ""
        punch = (f",zoompan=z='{_punch(dur, f'on/{FPS}')}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                 f":d=1:s={W}x{H}:fps={FPS}") if effect == "punch" else ""
        fc = (f"[0:v]{speed}fps={FPS}{hold},split[a][b];"
              f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:4,eq=brightness=-0.12[bg];"
              f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1{punch}[c];"
              + ("[c][1:v]overlay[o];[o]" if sub else "[c]") + fade + "[v];")
        if has_audio:
            a_len = dur - FREEZE_HOLD if effect == "freeze" else dur  # arrêt sur image : complété en silence
            if style is None:  # fondus d'avant les rythmes
                afade = f",afade=t=in:d=0.15,afade=t=out:st={max(0, a_len - 0.2):.2f}:d=0.2"
            else:
                afade = f",afade=t=in:d={fd},afade=t=out:st={max(0, a_len - fd):.2f}:d={fd}" if fd else ""
            tempo = "atempo=2.0," if effect == "speedup" else ""
            fc += (f"[0:a]{tempo}aresample=48000{afade}[a0];"
                   f"[a0][{sil}:a]amix=inputs=2:duration=longest:normalize=0[au]")
        else:
            fc += f"[{sil}:a]anull[au]"
        args += ["-filter_complex", fc, "-map", "[v]", "-map", "[au]", "-t", f"{dur}", *ENC, str(out)]
        media.sh(args)
    return out


BASE = "video_base.mp4"  # film monté sans musique (carton de crédit compris), pour changer la musique seule
# {"sections", "final_from", "body", "credits", "w", "h", "title_style"} : ce qu'il faut pour refaire le mélange
META = "video_base.json"

CROSSFADE = 2.0  # fondu enchaîné entre deux morceaux
MIN_TRACK = 4.0  # un morceau qui durerait moins longtemps n'est pas joué (le précédent continue)


def credit_lines(credits) -> list[str]:
    seen = []
    for c in credits or []:
        c = (c or "").strip()
        if c and c not in seen:
            seen.append(c)
    return seen


def section_starts(segs: list[dict]) -> list[float]:
    """Débuts prévus des séquences, d'après les durées du plan : cartons de titre (ouverture comprise) et
    plans marqués "section" (style « aucun »)."""
    out, t = [], 0.0
    for s in segs:
        if s["type"] == "title" or s.get("section"):
            out.append(round(t, 3))
        t += float(s["duration"])
    return out


def meta_sections(meta: dict) -> list[float]:
    """Débuts réels des cartons enregistrés au rendu ; film d'avant (PR 1) : seulement le dernier (final_from)."""
    if isinstance(meta.get("sections"), list):
        return meta["sections"]
    return [meta["final_from"]] if meta.get("final_from") is not None else []


def core_role(roles) -> str | None:
    """Rôle qui porte le film et joue toujours : main (constante, montée, festif puis émotion),
    peak (calme puis explosion, qui n'a pas de main) ; à défaut, intro. Jamais le morceau final."""
    return next((r for r in ("main", "peak", "intro") if r in roles), None)


def place_tracks(roles: list[str], sections, body, evolution: str = "constante") -> list[tuple[str, float]]:
    """Début de chaque morceau joué : [(rôle, début)] dans l'ordre.
    - final : au début réel de la dernière séquence (dernier carton après l'ouverture), seulement s'il laisse
      4 s de part et d'autre ; sinon pas de morceau final (il ne remonte jamais sur une séquence d'avant).
    - rôle principal (core_role) : toujours joué. main au début de séquence le plus proche du tiers du film
      (montée) ou à 0 ; peak au plus proche de 40 % (calme puis explosion). S'il tombe sur le début du final,
      il passe à 0 à la place de l'intro.
    - autres (intro à 0, peak de la montée au plus proche des 2/3) : seulement sur un début libre.
    Seuls comptent les débuts qui laissent 4 s de part et d'autre ; le premier morceau commence à 0.
    Un morceau de moins de 4 s est retiré (le précédent continue), sauf le rôle principal : c'est alors le morceau
    d'avant qui est retiré et le principal prend son début. Priorité : final > principal > autres."""
    body = float(body or 0)
    secs = [round(float(s), 3) for s in (sections or []) if s is not None]

    def fits(s):
        return MIN_TRACK <= s <= body - MIN_TRACK

    starts = sorted({0.0, *(s for s in secs if fits(s))})

    def near(frac):
        return min(starts, key=lambda s: (abs(s - body * frac), s))

    core = core_role(roles)
    if core is None:  # morceau final seul : pas de musique
        return []
    at = {}  # début → rôle
    inner = [s for s in secs if s > 0]
    if "final" in roles and inner and fits(max(inner)):
        at[max(inner)] = "final"
    want = {"intro": 0.0, "main": near(1 / 3) if evolution == "montee" else 0.0,
            "peak": near(0.4 if evolution == "calme_explosion" else 2 / 3)}
    at[0.0 if want[core] in at else want[core]] = core
    for r in ("intro", "main", "peak"):
        if r in roles and r != core and want[r] not in at:
            at[want[r]] = r
    placed = sorted(at.items())
    if placed[0][0] > 0:  # pas de silence au début du film (le premier n'est jamais le final : core le précède)
        placed[0] = (0.0, placed[0][1])
    while len(placed) > 1:
        ends = [s for s, _ in placed[1:]] + [body]
        i = next((i for i, (s, _) in enumerate(placed) if ends[i] - s < MIN_TRACK), None)
        if i is None:
            break
        role = placed[i][1]
        if role == core and i > 0 and placed[i - 1][1] != "final":
            placed[i] = (placed[i - 1][0], role)  # le principal prend le début du morceau d'avant
            del placed[i - 1]
        elif role == core and i + 1 < len(placed) and placed[i + 1][1] != "final":
            del placed[i + 1]  # le principal continue
        elif i > 0:
            del placed[i]  # le précédent continue
        else:
            del placed[1]
    return [(r, s) for s, r in placed]


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


def _as_tracks(tracks) -> tuple[list[dict], list[str]]:
    """Morceaux [{"role", "path", "credit"}] et crédits imposés ; accepte l'ancien format
    {"main", "final", "credits"} (crédits alors toujours affichés)."""
    if isinstance(tracks, dict):
        return ([{"role": r, "path": tracks[r], "credit": ""} for r in ("main", "final") if tracks.get(r)],
                list(tracks.get("credits") or []))
    return [t for t in tracks or [] if t.get("path")], []


def render(segs: list[dict], items: dict, out: Path, tracks, mix: int, frame: Frame | None = None,
           style: Style | None = None, on_progress=None, evolution: str = "constante") -> float:
    """Assemble les segments (+ carton de crédit) dans video_base.mp4, puis y mélange la musique dans `out`.
    tracks = [{"role", "path", "credit"}] : placés sur les débuts réels des séquences (place_tracks) ;
    seuls les morceaux joués sont crédités. Retourne la durée finale.
    `style` règle les fondus (rythme) ; les effets sont portés par chaque segment (normalize)."""
    frame = frame or DEFAULT_FRAME
    title_style = style.title_style if style else "carnet"
    tracks, fixed_credits = _as_tracks(tracks)
    if not segs:
        raise RuntimeError("Le plan de montage est vide : il faut au moins une photo ou une vidéo.")
    tmp = out.parent / "tmp_video"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        files, t, sections = [], 0.0, []
        carry = False  # plan marqué "section" ignoré : la marque passe au plan suivant monté
        for i, seg in enumerate(segs):
            try:
                f = _render_segment(seg, items.get(seg["item_id"]), tmp, i, frame, style)
            except Exception as e:  # un extrait illisible ne doit pas faire échouer tout le montage
                print(f"[montage] segment {i} ignoré : {e}", flush=True)
                f = None
            if f is None:
                carry = carry or bool(seg.get("section"))
            else:
                # début réel d'un carton, ou du premier plan d'une séquence sans carton (style « aucun ») ;
                # durées sondées, segments ignorés exclus
                if seg["type"] == "title" or seg.get("section") or carry:
                    sections.append(round(t, 3))
                carry = False
                files.append(f)
                t += media.probe(f)["duration"] or seg["duration"]
            if on_progress:
                on_progress((i + 1) / (len(segs) + 1))
        if not files:
            raise RuntimeError("Aucun extrait n'a pu être monté.")
        body = round(t, 3)
        by_role = {tr["role"]: tr for tr in tracks}
        play = [{**by_role[r], "start": s} for r, s in place_tracks(list(by_role), sections, body, evolution)]
        credits = credit_lines([p.get("credit") for p in play] + fixed_credits)  # morceaux joués seulement
        if credits:
            files.append(_render_segment(credit_segment(credits), None, tmp, len(segs), frame,
                                         card_style=title_style))
        joined = tmp / "joined.mp4"
        _concat(files, tmp / "list.txt", joined)
        base = out.parent / BASE
        joined.replace(base)
        inner = [s for s in sections if s > 0]
        (out.parent / META).write_text(json.dumps({"sections": sections, "final_from": inner[-1] if inner else None,
                                                   "body": body, "credits": credits, "w": frame.w, "h": frame.h,
                                                   "title_style": title_style},
                                                  ensure_ascii=False), encoding="utf-8")
        mix_music(base, out, play, mix)
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
            files.append(_render_segment(credit_segment(credits), None, tmp, 0,
                                            Frame(meta.get("w") or 1920, meta.get("h") or 1080),
                                         card_style=meta.get("title_style") or "carnet"))
        new = tmp / "base.mp4"
        _concat(files, tmp / "list.txt", new)
        new.replace(base)
        meta["credits"] = credits
        (base.parent / META).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def mix_music(base: Path, out: Path, tracks: list[dict], mix: int) -> None:
    """Mélange la musique sous le son du film (compression latérale) ; sans morceau, copie le film tel quel.
    tracks = [{"path", "start"}] : chaque morceau (en boucle) entre à son début par un fondu enchaîné de 2 s
    avec le précédent. Le film mixé garde la durée de `base`."""
    total = media.probe(base)["duration"] or 0
    tmp = out.with_name(out.stem + ".mix.mp4")
    tracks = sorted((t for t in tracks or [] if t.get("path")), key=lambda t: float(t.get("start") or 0))
    if not tracks:
        media.sh(["ffmpeg", "-y", "-i", str(base), "-c", "copy", "-movflags", "+faststart", str(tmp)])
        tmp.replace(out)
        return
    vol = 0.15 + 0.85 * max(0, min(100, int(mix))) / 100
    fmt = "aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS"
    args = ["ffmpeg", "-y", "-i", str(base)]
    bed = ""
    for i, t in enumerate(tracks):
        args += ["-stream_loop", "-1", "-i", str(t["path"])]
        bed += f"[{i + 1}:a]{fmt}[t{i}];"
    first = float(tracks[0].get("start") or 0)
    cur = "t0"
    if first > 0:  # par sécurité : silence avant le premier morceau
        bed += f"[t0]adelay={int(first * 1000)}:all=1[d0];"
        cur = "d0"
    for i in range(1, len(tracks)):
        cut = float(tracks[i]["start"]) + CROSSFADE  # le fondu occupe [début, début + 2 s]
        bed += f"[{cur}]atrim=0:{cut:.3f}[h{i}];[h{i}][t{i}]acrossfade=d={CROSSFADE}[x{i}];"
        cur = f"x{i}"
    bed += f"[{cur}]anull[bed];"
    fc = ("[0:a]asplit[voice][key];" + bed
          + f"[bed]volume={vol:.3f},afade=t=in:d=1.5,afade=t=out:st={max(0, total - 3):.2f}:d=3[m];"
          "[m][key]sidechaincompress=threshold=0.02:ratio=10:attack=150:release=900[duck];"
          "[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    media.sh([*args, "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
              "-c:a", "aac", "-b:a", "192k", "-t", f"{total}", "-movflags", "+faststart", str(tmp)])
    tmp.replace(out)
