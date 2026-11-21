"""Styles de titres : carnet, sobre, pop, aucun."""
import json
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from app.pipeline import video
from test_render_framing import stub, SEGS, _render  # noqa: F401  (fixture et aides communes)

TEXT = "Un week-end à la mer"
FRAME = video.Frame(640, 360)


def _card(tmp_path, style, name=None, index=0, frame=FRAME, text=TEXT):
    out = tmp_path / f"{name or style}.png"
    video.title_card(text, out, frame, style, index)
    return Image.open(out).convert("RGB")


def test_title_styles_differ(tmp_path):
    imgs = {s: _card(tmp_path, s) for s in ("carnet", "sobre", "pop")}
    for a, b in (("carnet", "sobre"), ("carnet", "pop"), ("sobre", "pop")):
        assert ImageChops.difference(imgs[a], imgs[b]).getbbox() is not None, (a, b)
    assert imgs["sobre"].getpixel((5, 5)) == (0, 0, 0)


def test_pop_palette_by_index_and_inside_vertical(tmp_path):
    bgs = {_card(tmp_path, "pop", f"p{i}", index=i, frame=FRAME).getpixel((3, 3)) for i in range(5)}
    assert len(bgs) == 5
    v = video.Frame(1080, 1920)
    im = _card(tmp_path, "pop", "pv", index=2, frame=v, text="Un week-end extraordinaire en Bretagne avec toute la famille")
    bg = im.getpixel((3, 3))
    diff = ImageChops.difference(im, Image.new("RGB", im.size, bg)).convert("L").point(lambda x: 255 if x > 40 else 0)
    x0, y0, x1, y1 = diff.getbbox()
    assert x0 >= 1080 * 0.04 and 1080 - x1 >= 1080 * 0.04 and y0 > 0 and y1 < 1920


def test_carnet_fallback_without_font(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "FONT_DIR", tmp_path / "vide")
    video.font_path.cache_clear()
    try:
        assert _card(tmp_path, "carnet").size == (640, 360)
    finally:
        video.font_path.cache_clear()


def test_carnet_uses_bundled_hand_font():
    video.font_path.cache_clear()
    assert video.font_path("hand").endswith(".ttf") and "fonts" in video.font_path("hand")


PLAN = {"segments": [{"type": "title", "text": "Début"},
                     {"type": "photo", "item_id": 1, "duration": 2},
                     {"type": "title", "text": "Milieu"},
                     {"type": "photo", "item_id": 3, "duration": 2}]}
CC = ["Musique : « Carefree » — Kevin MacLeod (CC BY 4.0)"]


def test_normalize_aucun_drops_titles(stub):
    segs = video.normalize(PLAN, stub, 0, video.Style(title_style="aucun"))
    assert [s["type"] for s in segs] == ["photo", "photo"]
    assert [s["type"] for s in video.normalize(PLAN, stub, 0, video.Style(title_style="sobre"))].count("title") == 2


def test_aucun_drops_titles_keeps_credit(stub, tmp_path, monkeypatch):
    calls = []
    real = video.title_card
    monkeypatch.setattr(video, "title_card", lambda *a, **k: (calls.append((a, k)), real(*a, **k))[1])
    monkeypatch.setattr(video, "DEFAULT_FRAME", video.Frame(320, 180))
    style = video.Style(title_style="aucun")
    segs = video.normalize(PLAN, stub, 0, style)
    out = tmp_path / "out" / "video.mp4"
    out.parent.mkdir()
    video.render(segs, stub, out, {"main": None, "final": None, "credits": CC}, 50, style=style)
    assert len(calls) == 1 and "Musique" in calls[0][0][0]
    args = calls[0][0]
    assert (args[3] if len(args) > 3 else calls[0][1].get("style")) == "sobre"  # crédit : sobre quand aucun
    assert video.read_meta(out.parent / video.BASE)["title_style"] == "aucun"


def test_recredit_keeps_film_title_style(stub, tmp_path, monkeypatch):
    monkeypatch.setattr(video, "DEFAULT_FRAME", video.Frame(320, 180))
    style = video.Style(title_style="pop")
    out = tmp_path / "out" / "video.mp4"
    out.parent.mkdir()
    video.render(SEGS[:1], stub, out, {"main": None, "final": None, "credits": []}, 50, style=style)
    calls = []
    real = video.title_card
    monkeypatch.setattr(video, "title_card", lambda *a, **k: (calls.append((a, k)), real(*a, **k))[1])
    video.recredit(out.parent / video.BASE, CC)
    assert len(calls) == 1 and (calls[0][0] + (calls[0][1].get("style"),))[3 if len(calls[0][0]) > 3 else -1] == "pop"
