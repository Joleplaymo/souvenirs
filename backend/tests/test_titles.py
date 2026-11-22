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


# « Aucun » : plus de cartons, mais les débuts de séquence restent marqués (évolution de la musique, morceau final)
SEQ_PLAN = {"segments": [{"type": "title", "text": "Ouverture"},
                         {"type": "photo", "item_id": 1, "duration": 5},
                         {"type": "photo", "item_id": 3, "duration": 5},
                         {"type": "title", "text": "Samedi"},
                         {"type": "photo", "item_id": 1, "duration": 5},
                         {"type": "photo", "item_id": 3, "duration": 5},
                         {"type": "title", "text": "Dimanche"},
                         {"type": "photo", "item_id": 1, "duration": 5},
                         {"type": "title", "text": "Le soir"},
                         {"type": "title", "text": "Doublon"},
                         {"type": "photo", "item_id": 3, "duration": 5},
                         {"type": "photo", "item_id": 1, "duration": 5},
                         {"type": "title", "text": "Sans suite"}]}
AUCUN = video.Style(rhythm="pose", title_style="aucun")


def test_aucun_keeps_sequence_markers(stub):
    segs = video.normalize(SEQ_PLAN, stub, 0, AUCUN)
    assert [s["type"] for s in segs] == ["photo"] * 7
    # l'ouverture (début du film) ne marque rien ; deux titres de suite : une seule marque ; titre final : rien
    assert [bool(s.get("section")) for s in segs] == [False, False, True, False, True, True, False]
    assert video.section_starts(segs) == [10.0, 20.0, 25.0]
    # avec des cartons : les cartons marquent les séquences, aucun drapeau
    with_titles = video.normalize(SEQ_PLAN, stub, 0, video.Style(rhythm="pose", title_style="sobre"))
    assert not any(s.get("section") for s in with_titles)


def test_section_marker_moves_when_segment_removed():
    segs = [{"type": "photo", "item_id": 1, "duration": 5.0},
            {"type": "photo", "item_id": 2, "duration": 5.0, "section": True},
            {"type": "photo", "item_id": 3, "duration": 5.0}]
    kept = video.keep_segments(segs, lambda s: s["item_id"] != 2)
    assert [s["item_id"] for s in kept] == [1, 3] and kept[1].get("section")
    assert video.section_starts(kept) == [5.0]
    assert not segs[2].get("section")  # liste d'origine inchangée


def test_normalize_trim_keeps_markers(stub):
    """Durée cible courte : des plans du milieu sont retirés, les marques de séquence restent."""
    plan = {"segments": [{"type": "photo", "item_id": 1, "duration": 5}] * 4 + [{"type": "title", "text": "B"}]
            + [{"type": "photo", "item_id": 3, "duration": 5}] * 4 + [{"type": "title", "text": "C"}]
            + [{"type": "photo", "item_id": 1, "duration": 5}] * 4}
    segs = video.normalize(plan, stub, 25, AUCUN)
    assert sum(s["duration"] for s in segs) <= 25 * 1.1
    assert len(video.section_starts(segs)) == 2


def test_aucun_render_records_sections_and_plays_evolution(stub, tmp_path, monkeypatch):
    """Film sans cartons en montée + fin touchante : les morceaux changent aux débuts de séquence."""
    monkeypatch.setattr(video, "DEFAULT_FRAME", video.Frame(320, 180))
    segs = video.normalize(SEQ_PLAN, stub, 0, AUCUN)
    out = tmp_path / "out" / "video.mp4"
    out.parent.mkdir()
    src = tmp_path / "s.mp3"
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    str(src)], check=True)
    tracks = [{"role": r, "path": src, "credit": f"Musique : {r}"} for r in ("intro", "main", "peak", "final")]
    video.render(segs, stub, out, tracks, 50, style=AUCUN, evolution="montee")
    meta = video.read_meta(out.parent / video.BASE)
    assert [round(s) for s in meta["sections"]] == [10, 20, 25]
    played = video.place_tracks(["intro", "main", "peak", "final"], video.meta_sections(meta), meta["body"], "montee")
    assert len(played) > 1 and "final" in dict(played), played
    assert len(meta["credits"]) == len(played) > 1
