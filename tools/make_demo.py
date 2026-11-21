"""Fabrique les médias de l'événement de démonstration (illustrations + voix de synthèse).

    python tools/make_demo.py   →   demo/*.jpg, *.m4a, *.mp4 et demo/manifest.json
Nécessite Pillow, numpy, ffmpeg et espeak-ng. Les fichiers produits sont versionnés : ce script
ne sert qu'à les refaire.
"""
import json
import math
import random
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "demo"
VOICES = {"Léa": "fr+f2", "Camille": "fr+f4", "Tom": "fr+m3", "Max": "fr+m7"}

SKIES = {
    "matin": [(150, 200, 240), (255, 222, 180)], "jour": [(120, 185, 240), (205, 232, 250)],
    "aprem": [(95, 165, 235), (225, 235, 240)], "soir": [(70, 60, 120), (250, 150, 80)],
    "nuit": [(12, 16, 40), (40, 40, 80)], "aube": [(150, 170, 220), (255, 190, 130)],
}


def lerp(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def scene(w, h, sky, parts, seed):
    rnd = random.Random(seed)
    top, bottom = SKIES[sky]
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    horizon = int(h * 0.62)
    for y in range(horizon):
        d.line([(0, y), (w, y)], fill=lerp(top, bottom, y / horizon))
    dark = sky in ("nuit", "soir")
    if "stars" in parts:
        for _ in range(500):
            x, y, r = rnd.randrange(w), rnd.randrange(horizon), rnd.choice([1, 1, 2, 3])
            d.ellipse([x, y, x + r, y + r], fill=(255, 255, rnd.randint(200, 255)))
        d.ellipse([w * .72, h * .1, w * .72 + h * .09, h * .19], fill=(245, 242, 220))
    if "sun" in parts:
        cx, cy, r = int(w * rnd.uniform(.25, .75)), int(horizon * (0.82 if sky in ("soir", "aube") else 0.25)), int(h * .07)
        glow = Image.new("RGB", (w, h), (0, 0, 0))
        ImageDraw.Draw(glow).ellipse([cx - r * 4, cy - r * 4, cx + r * 4, cy + r * 4], fill=(110, 80, 30))
        img = Image.fromarray(np.clip(np.asarray(img).astype(int) + np.asarray(glow.filter(ImageFilter.GaussianBlur(r * 2))), 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 244, 200))
    # crêtes de montagnes
    base = (40, 50, 80) if dark else (110, 135, 150)
    for layer in range(3):
        y0 = horizon - int(h * (0.22 - layer * 0.06))
        pts, y = [(0, h)], y0
        for x in range(0, w + 40, 40):
            y += rnd.randint(-int(h * .03), int(h * .03))
            y = max(int(h * .15), min(horizon, y))
            pts.append((x, y))
        pts.append((w, h))
        k = layer / 3
        col = lerp(base, (25, 40, 35) if dark else (70, 110, 80), k)
        d.polygon(pts, fill=col)
    ground = (30, 45, 35) if dark else (110, 160, 90) if sky != "aube" else (120, 140, 85)
    d.rectangle([0, horizon, w, h], fill=ground)
    for _ in range(900):  # texture d'herbe
        x, y = rnd.randrange(w), rnd.randrange(horizon, h)
        c = lerp(ground, (255, 255, 200) if not dark else (0, 0, 0), rnd.uniform(0, .18))
        d.line([(x, y), (x + rnd.randint(-4, 4), y - rnd.randint(4, 14))], fill=c, width=2)
    if "lake" in parts:
        lt = horizon + int(h * .04)
        water = lerp(SKIES[sky][0], (40, 90, 140), .5)
        d.ellipse([-w * .1, lt, w * 1.1, h * 1.3], fill=water)
        for _ in range(140):
            x, y = rnd.randrange(w), rnd.randrange(lt + 20, h)
            d.line([(x, y), (x + rnd.randint(30, 120), y)], fill=lerp(water, (255, 255, 255), .25), width=2)
    if "road" in parts:
        d.polygon([(w * .42, horizon), (w * .5, horizon), (w * .95, h), (w * .15, h)], fill=(85, 85, 90))
        for i in range(6):
            k0, k1 = i / 6, i / 6 + .07
            d.polygon([(w * (.46 + .09 * k0) - 3 - 14 * k0, horizon + (h - horizon) * k0),
                       (w * (.46 + .09 * k0) + 3 + 14 * k0, horizon + (h - horizon) * k0),
                       (w * (.46 + .09 * k1) + 3 + 14 * k1, horizon + (h - horizon) * k1),
                       (w * (.46 + .09 * k1) - 3 - 14 * k1, horizon + (h - horizon) * k1)], fill=(240, 235, 200))
    if "trees" in parts:
        for _ in range(parts.count("trees") * 9):
            x, s = rnd.randrange(w), rnd.uniform(.5, 1.5)
            by = horizon + rnd.randint(0, int(h * .2))
            th = int(h * .26 * s)
            col = lerp((20, 60, 40), (40, 100, 60), rnd.random()) if not dark else (12, 28, 22)
            d.rectangle([x - 5 * s, by - th * .2, x + 5 * s, by], fill=(70, 50, 35))
            for k in range(4):
                ww = th * (.32 - k * .06)
                yy = by - th * (.15 + k * .22)
                d.polygon([(x - ww, yy), (x + ww, yy), (x, yy - th * .34)], fill=col)
    if "house" in parts:
        x, y, s = int(w * .55), horizon + int(h * .1), h * .22
        d.rectangle([x, y - s, x + s * 1.6, y], fill=(225, 205, 175))
        d.polygon([(x - s * .12, y - s), (x + s * 1.72, y - s), (x + s * .8, y - s * 1.65)], fill=(150, 70, 50))
        d.rectangle([x + s * .25, y - s * .55, x + s * .55, y], fill=(110, 75, 50))
        for k in (0.8, 1.2):
            d.rectangle([x + s * k, y - s * .7, x + s * (k + .25), y - s * .4], fill=(255, 225, 140) if dark else (150, 195, 220))
    if "tent" in parts:
        x, y, s = int(w * .2), horizon + int(h * .2), h * .16
        d.polygon([(x, y), (x + s * 2, y), (x + s, y - s * 1.2)], fill=(225, 120, 60))
        d.polygon([(x + s * .8, y), (x + s * 1.2, y), (x + s, y - s * .8)], fill=(90, 45, 30))
    if "fire" in parts:
        x, y, s = int(w * .5), horizon + int(h * .24), h * .09
        glow = Image.new("RGB", (w, h), (0, 0, 0))
        ImageDraw.Draw(glow).ellipse([x - s * 5, y - s * 5, x + s * 5, y + s * 3], fill=(150, 70, 10))
        img = Image.fromarray(np.clip(np.asarray(img).astype(int) + np.asarray(glow.filter(ImageFilter.GaussianBlur(s * 1.6))), 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        d.polygon([(x - s * .6, y), (x + s * .6, y), (x + s * .2, y - s * 1.2), (x, y - s * .7), (x - s * .25, y - s * 1.5)], fill=(255, 150, 40))
        d.polygon([(x - s * .3, y), (x + s * .3, y), (x, y - s * .8)], fill=(255, 225, 120))
        d.line([(x - s, y + 6), (x + s, y - 6)], fill=(60, 35, 20), width=12)
        d.line([(x - s, y - 6), (x + s, y + 6)], fill=(60, 35, 20), width=12)
    if "blanket" in parts:
        x, y = int(w * .3), horizon + int(h * .2)
        d.polygon([(x, y), (x + w * .4, y - h * .03), (x + w * .46, y + h * .1), (x - w * .04, y + h * .13)], fill=(215, 70, 60))
        for k in range(1, 6):
            d.line([(x + w * .07 * k, y - h * .005 * k), (x + w * .07 * k - w * .02, y + h * .12)], fill=(250, 235, 220), width=6)
        for k in range(4):
            cx = x + w * (.08 + .09 * k)
            d.ellipse([cx, y + h * .03, cx + h * .05, y + h * .07], fill=rnd.choice([(250, 220, 120), (240, 240, 235), (120, 170, 80)]))
    if "balls" in parts:
        d.rectangle([w * .1, horizon + h * .12, w * .9, h], fill=(200, 180, 140))
        for k in range(6):
            cx, cy = w * rnd.uniform(.25, .75), horizon + h * rnd.uniform(.2, .32)
            d.ellipse([cx, cy, cx + h * .035, cy + h * .035], fill=(150, 155, 165))
        cx, cy = w * .5, horizon + h * .25
        d.ellipse([cx, cy, cx + h * .015, cy + h * .015], fill=(235, 120, 40))
    for i in range(parts.count("person")):
        n = parts.count("person")
        x = int(w * (.5 + (i - (n - 1) / 2) * .09 + rnd.uniform(-.01, .01)))
        y, s = horizon + int(h * .27), h * rnd.uniform(.17, .2)
        col = rnd.choice([(200, 60, 60), (60, 110, 190), (240, 190, 60), (70, 150, 110), (150, 80, 160)])
        if dark:
            col = lerp(col, (0, 0, 0), .6)
        d.rectangle([x - s * .1, y - s * .45, x - s * .01, y], fill=(40, 45, 70))
        d.rectangle([x + s * .01, y - s * .45, x + s * .1, y], fill=(40, 45, 70))
        d.rounded_rectangle([x - s * .14, y - s * .85, x + s * .14, y - s * .4], radius=8, fill=col)
        d.line([(x - s * .14, y - s * .8), (x - s * .26, y - s * (1.05 if rnd.random() < .35 else .5))], fill=col, width=int(s * .07))
        d.line([(x + s * .14, y - s * .8), (x + s * .26, y - s * .5)], fill=col, width=int(s * .07))
        d.ellipse([x - s * .09, y - s * 1.05, x + s * .09, y - s * .87], fill=(235, 195, 160) if not dark else (120, 95, 80))
    arr = np.asarray(img.filter(ImageFilter.GaussianBlur(1.2))).astype(int)
    arr += np.random.default_rng(seed).normal(0, 5, arr.shape).astype(int)  # grain photo
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def say(text, who, out, rate=150):
    wav = out.with_suffix(".wav")
    subprocess.run(["espeak-ng", "-v", VOICES[who], "-s", str(rate), "-w", str(wav), text], check=True)
    return wav


def dur(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(path)], capture_output=True, text=True, check=True).stdout)


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def audio(name, lines):
    """lines : [(qui, texte)] → un fichier m4a (les voix se suivent)."""
    wavs = [say(t, who, OUT / f"_{name}_{i}") for i, (who, t) in enumerate(lines)]
    ins = [x for w in wavs for x in ("-i", str(w))]
    chain = "".join(f"[{i}:a]aresample=44100,apad=pad_dur=0.35[a{i}];" for i in range(len(wavs)))
    chain += "".join(f"[a{i}]" for i in range(len(wavs))) + f"concat=n={len(wavs)}:v=0:a=1[a]"
    ff(*ins, "-filter_complex", chain, "-map", "[a]", "-c:a", "aac", "-b:a", "96k", str(OUT / f"{name}.m4a"))
    for w in wavs:
        w.unlink()


def clip(name, who, text, sky, parts, seed, vertical=False):
    w, h = (1080, 1920) if vertical else (1920, 1080)
    still = OUT / f"_{name}.png"
    scene(int(w * 1.3), int(h * 1.3), sky, parts, seed).save(still)
    wav = say(text, who, OUT / f"_{name}")
    t = dur(wav) + 1.6
    n = int(t * 30)
    pan = (f"zoompan=z=1.18:x='(iw-iw/zoom)*on/{n}':y='(ih-ih/zoom)/2+12*sin(on/9)':d={n}:s={w // 1.5:.0f}x{h // 1.5:.0f}:fps=30")
    ff("-i", str(still), "-i", str(wav), "-filter_complex",
       f"[0:v]{pan},format=yuv420p[v];[1:a]adelay=600:all=1,apad[a]", "-map", "[v]", "-map", "[a]",
       "-t", f"{t:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "24", "-c:a", "aac", "-b:a", "96k",
       str(OUT / f"{name}.mp4"))
    still.unlink()
    wav.unlink()


def photo(name, sky, parts, seed, portrait=False):
    w, h = (1500, 2000) if portrait else (2400, 1600)
    scene(w, h, sky, parts, seed).save(OUT / f"{name}.jpg", quality=86)


ITEMS = []


def add(day, time, who, kind, file=None, text=None):
    ITEMS.append({"day": day, "time": time, "author": who, "kind": kind, **({"file": file} if file else {}),
                  **({"text": text} if text else {})})


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    add(0, "09:05", "Léa", "note", text="Départ de Lyon, la voiture est pleine à craquer. Max a encore oublié son sac de couchage.")
    photo("01-route", "matin", ["sun", "road", "trees"], 1); add(0, "09:40", "Léa", "photo", "01-route.jpg")
    audio("02-arrivee", [("Léa", "On vient d'arriver au gîte, dans le Vercors. Il fait grand soleil, et la vue sur la vallée est incroyable. Tom a déjà repéré le lac pour la baignade de cet après-midi.")])
    add(0, "11:30", "Léa", "dictee", "02-arrivee.m4a")
    photo("03-gite", "jour", ["sun", "house", "trees", "person", "person"], 3); add(0, "11:40", "Tom", "photo", "03-gite.jpg")
    photo("04-sapins", "jour", ["trees", "trees", "trees"], 4, portrait=True); add(0, "11:42", "Tom", "photo", "04-sapins.jpg")
    clip("05-montee", "Max", "Regardez-moi ça ! Deux heures de montée, et on y est presque. Camille dit qu'elle voit déjà le sommet. Moi, je vois surtout le pique-nique.", "jour", ["sun", "trees", "person", "person", "person"], 5)
    add(0, "13:15", "Max", "video", "05-montee.mp4")
    photo("06-sommet", "aprem", ["sun", "person", "person", "person", "person"], 6); add(0, "14:00", "Camille", "photo", "06-sommet.jpg")
    audio("07-pain", [("Camille", "Qui a pris le pain ?"), ("Tom", "C'était Max qui devait le prendre."),
                      ("Max", "Ah non ! Moi, j'avais les fromages !"),
                      ("Camille", "Bon. Eh bien ce sera un pique-nique sans pain. On s'en souviendra, de celui-là.")])
    add(0, "14:20", "Camille", "conversation", "07-pain.m4a")
    photo("08-pique-nique", "aprem", ["blanket", "trees", "person", "person"], 8); add(0, "14:25", "Léa", "photo", "08-pique-nique.jpg")
    clip("09-lac", "Tom", "L'eau est à quinze degrés, à peine. Léa a plongé la première, sans hésiter. Chapeau !", "aprem", ["sun", "lake", "trees", "person"], 9, vertical=True)
    add(0, "16:30", "Tom", "video", "09-lac.mp4")
    photo("10-lac", "aprem", ["sun", "lake", "trees"], 10); add(0, "16:40", "Max", "photo", "10-lac.jpg")
    photo("11-baignade", "aprem", ["lake", "person"], 11, portrait=True); add(0, "16:45", "Camille", "photo", "11-baignade.jpg")
    photo("12-feu", "soir", ["sun", "fire", "tent", "person", "person", "person", "person"], 12); add(0, "20:30", "Tom", "photo", "12-feu.jpg")
    audio("13-soiree", [("Max", "Soirée barbecue. Tom a sorti la guitare, et on a chanté faux pendant deux heures. Les saucisses étaient un peu brûlées, mais personne ne s'est plaint. Meilleure soirée de l'année.")])
    add(0, "21:00", "Max", "dictee", "13-soiree.m4a")
    photo("14-etoiles", "nuit", ["stars", "tent", "trees"], 14); add(0, "23:10", "Léa", "photo", "14-etoiles.jpg")
    photo("15-lever", "aube", ["sun", "lake", "trees"], 15); add(1, "06:45", "Camille", "photo", "15-lever.jpg")
    add(1, "06:50", "Camille", "note", text="Lever de soleil à 6 h 45. J'étais la seule debout, et ça valait le coup.")
    clip("16-petanque", "Léa", "Finale de pétanque. Camille contre Tom. Et c'est Camille qui gagne, treize à onze ! Tom demande déjà la revanche.", "jour", ["sun", "balls", "trees", "person", "person"], 16)
    add(1, "10:30", "Léa", "video", "16-petanque.mp4")
    photo("17-boules", "jour", ["balls", "trees", "person", "person", "person"], 17); add(1, "10:45", "Max", "photo", "17-boules.jpg")
    photo("18-depart", "aprem", ["sun", "house", "person", "person", "person", "person"], 18); add(1, "15:00", "Tom", "photo", "18-depart.jpg")
    audio("19-fin", [("Tom", "Voilà, c'est déjà fini. On range les sacs et on reprend la route. On s'est promis de revenir l'année prochaine. Même endroit, mêmes copains. Et cette fois, Max prendra le pain.")])
    add(1, "15:10", "Tom", "dictee", "19-fin.m4a")
    add(1, "15:20", "Max", "note", text="Promis, l'an prochain je prends le pain.")
    (OUT / "manifest.json").write_text(json.dumps({
        "name": "Week-end entre copains", "type": "weekend", "tone": "drole,festif", "days": 2,
        "participants": list(VOICES), "items": ITEMS}, ensure_ascii=False, indent=1))
    print(len(ITEMS), "éléments")
