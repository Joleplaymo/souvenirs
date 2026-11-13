"""Génère les icônes de l'application (écran d'accueil).

    python tools/make_icons.py [dossier]   →   icon-192.png, icon-512.png (défaut : frontend/public)
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "frontend" / "public"
out.mkdir(parents=True, exist_ok=True)
for s in (192, 512):
    im = Image.new("RGB", (s, s), "#c8662b")
    d = ImageDraw.Draw(im)
    u = s / 100
    d.rounded_rectangle([22 * u, 26 * u, 78 * u, 78 * u], radius=5 * u, fill="#fbf5e9")  # page du carnet
    d.rectangle([28 * u, 32 * u, 72 * u, 60 * u], fill="#f0b566")  # photo
    d.ellipse([58 * u, 36 * u, 66 * u, 44 * u], fill="#fff3d0")  # soleil
    d.polygon([(28 * u, 60 * u), (44 * u, 42 * u), (56 * u, 54 * u), (62 * u, 48 * u), (72 * u, 60 * u)], fill="#7a4a2a")
    d.line([(30 * u, 67 * u), (70 * u, 67 * u)], fill="#c9b79a", width=max(1, int(2 * u)))
    d.line([(30 * u, 72 * u), (56 * u, 72 * u)], fill="#c9b79a", width=max(1, int(2 * u)))
    im.save(out / f"icon-{s}.png")
