"""Rythme du montage (bornes de durée, calage sur le tempo, fondus) et effets (ralenti, accéléré, arrêt sur image,
zoom comique)."""
import subprocess

import pytest
from PIL import Image, ImageChops, ImageStat

from app.pipeline import media, video

SMALL = video.Frame(320, 180)
ALL_FX = {"slowmo": True, "speedup": True, "freeze": True, "humor": True}
NO_FX = {"slowmo": False, "speedup": False, "freeze": False, "humor": False}


@pytest.fixture(autouse=True)
def small(monkeypatch):
    """Rendu minuscule pour des tests rapides."""
    monkeypatch.setattr(video, "DEFAULT_FRAME", SMALL)


def style(rhythm="dynamique", effects=None, bpm=None):
    return video.Style(rhythm=rhythm, effects=dict(ALL_FX if effects is None else effects),
                       title_style="carnet", bpm=bpm)


# ------------------------------------------------------------------ normalize

ITEMS = {i: {"id": i, "event_id": 1, "kind": "photo"} for i in range(1, 9)}
ITEMS.update({i: {"id": i, "event_id": 1, "kind": "video", "duration": 20.0} for i in range(11, 19)})


def _plan():
    segs = [{"type": "title", "item_id": 0, "text": "Week-end", "duration": 5, "effect": "none"}]
    for n, d in enumerate([1, 2.5, 4, 8, 0.3, 3, 6, 2]):
        segs.append({"type": "photo", "item_id": n + 1, "text": "", "duration": d,
                     "effect": "punch" if n % 3 == 0 else "slowmo"})
        segs.append({"type": "video", "item_id": n + 11, "text": "", "start": n, "end": n + [1.2, 2, 4, 9, 3, 7, 12, 2.5][n],
                     "effect": ["none", "slowmo", "speedup", "freeze"][n % 4]})
        if n == 3:
            segs.append({"type": "title", "item_id": 0, "text": "Dimanche", "duration": 0.5, "effect": "none"})
    return {"segments": segs}


SHOT = {"pose": (3.0, 5.0), "dynamique": (1.5, 3.0), "nerveux": (0.5, 1.5)}


def _check_bounds(segs, rhythm):
    shots = [s for s in segs if s["type"] != "title"]
    assert shots
    for s in segs:
        d = s["duration"]
        if s["type"] == "title":
            assert 1.5 - 1e-6 <= d <= 3.0 + 1e-6, s
            continue
        lo, hi = SHOT[rhythm]
        if rhythm == "dynamique" and s["type"] == "video":
            hi = 6.0
        if rhythm == "nerveux":
            hi = 3.0
        assert lo - 1e-6 <= d <= hi + 1e-6, (rhythm, s)
    if rhythm == "nerveux":  # au plus un plan sur quatre au-delà de 1,5 s
        long = [s["duration"] > 1.5 + 1e-6 for s in shots]
        for i in range(len(long)):
            assert sum(long[i:i + 4]) <= 1, [s["duration"] for s in shots]


@pytest.mark.parametrize("rhythm", ["pose", "dynamique", "nerveux"])
def test_normalize_rhythm_bounds(rhythm):
    segs = video.normalize(_plan(), ITEMS, 0, style(rhythm))
    assert len([s for s in segs if s["type"] == "video"]) == 8
    _check_bounds(segs, rhythm)
    # réduction à une durée cible courte : les planchers sont ceux du rythme
    _check_bounds(video.normalize(_plan(), ITEMS, 15, style(rhythm)), rhythm)


def test_normalize_nerveux_shrinks_below_old_floors():
    segs = video.normalize(_plan(), ITEMS, 15, style("nerveux"))
    assert min(s["duration"] for s in segs if s["type"] != "title") < 1.5


def test_normalize_strips_disabled_effects():
    segs = video.normalize(_plan(), ITEMS, 0, style(effects=NO_FX))
    assert {s["effect"] for s in segs} == {"none"}


def test_normalize_effect_rules():
    segs = video.normalize(_plan(), ITEMS, 0, style("dynamique"))
    for s in segs:
        if s["type"] == "photo":  # ralenti, accéléré, arrêt sur image : vidéo seulement
            assert s["effect"] in ("none", "punch"), s
        if s["type"] == "title":
            assert s["effect"] == "none"
    assert {s["effect"] for s in segs if s["type"] == "video"} >= {"slowmo", "speedup", "freeze"}
    assert "punch" in {s["effect"] for s in segs if s["type"] == "photo"}
    segs = video.normalize(_plan(), ITEMS, 0, style("dynamique", {**ALL_FX, "humor": False}))
    assert "punch" not in {s["effect"] for s in segs}
    assert "slowmo" in {s["effect"] for s in segs}
    segs = video.normalize({"segments": [{"type": "photo", "item_id": 1, "text": "", "duration": 3,
                                          "effect": "explosion"}]}, ITEMS, 0, style())
    assert segs[0]["effect"] == "none"


def test_normalize_video_source_fits_effect():
    """L'extrait source demandé par l'effet tient dans la vidéo source."""
    items = {5: {"id": 5, "event_id": 1, "kind": "video", "duration": 4.0}}
    plan = {"segments": [{"type": "video", "item_id": 5, "text": "", "start": 3.0, "end": 4.0, "effect": e}
                         for e in ("none", "slowmo", "speedup", "freeze")]}
    segs = video.normalize(plan, items, 0, style("dynamique"))
    need = {"none": 1, "slowmo": 0.5, "speedup": 2, "freeze": 1}
    for s in segs:
        src = s["duration"] * need[s["effect"]] - (1 if s["effect"] == "freeze" else 0)
        assert s["start"] >= 0 and s["start"] + src <= 4.0 + 1e-6, s


@pytest.mark.parametrize("rhythm", ["dynamique", "nerveux"])
def test_normalize_snaps_to_beat(rhythm):
    beat = 0.5 if rhythm == "dynamique" else 0.25
    segs = video.normalize(_plan(), ITEMS, 0, style(rhythm, bpm=120))
    for s in segs:
        assert abs(s["duration"] / beat - round(s["duration"] / beat)) < 1e-6, s
    _check_bounds(segs, rhythm)


def test_normalize_pose_not_snapped():
    segs = video.normalize({"segments": [{"type": "photo", "item_id": 1, "text": "", "duration": 3.7,
                                          "effect": "none"}]}, ITEMS, 0, style("pose", bpm=120))
    assert segs[0]["duration"] == 3.7


def test_normalize_without_style_keeps_previous_bounds():
    plan = {"segments": [{"type": "title", "item_id": 0, "text": "T", "duration": 5},
                         {"type": "photo", "item_id": 1, "text": "", "duration": 1, "effect": "punch"},
                         {"type": "photo", "item_id": 2, "text": "", "duration": 9},
                         {"type": "video", "item_id": 11, "text": "", "start": 0, "end": 12, "effect": "slowmo"}]}
    segs = video.normalize(plan, ITEMS, 0)
    assert [s["duration"] for s in segs] == [3.5, 2.0, 6.0, 12.0]
    assert {s["effect"] for s in segs} == {"none"}


# ------------------------------------------------------------------ rendu

@pytest.fixture
def clip(tmp_path, monkeypatch):
    """Une vidéo de 3 s (mire animée + son) et une photo claire."""
    vid = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(vid)], check=True)
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (320, 180), (235, 235, 235)).save(photo)
    files = {1: photo, 2: vid}
    monkeypatch.setattr(media, "derived", lambda eid, iid, kind: files[iid])
    monkeypatch.setattr(media, "raw_path", lambda it: files[it["id"]])
    return {1: {"id": 1, "event_id": 1, "kind": "photo"}, 2: {"id": 2, "event_id": 1, "kind": "video", "duration": 3.0}}


def _seg(effect, dur, start=0.0):
    return {"type": "video", "item_id": 2, "text": "", "start": start, "duration": dur, "effect": effect}


def _render(clip, tmp_path, seg, st):
    out = video._render_segment(seg, clip[seg["item_id"]], tmp_path, 0, SMALL, st)
    return out, media.probe(out)


def _frames(path, tmp_path, start=0.0, name="f"):
    d = tmp_path / name
    d.mkdir()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start}", "-i", str(path), str(d / "%03d.png")],
                   check=True)
    return [Image.open(p).convert("RGB") for p in sorted(d.glob("*.png"))]


def _diff(a, b):
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


def _bright(im):
    return sum(ImageStat.Stat(im).mean) / 3


def test_slowmo_near_source_end(clip, tmp_path):
    out, info = _render(clip, tmp_path, _seg("slowmo", 2.0, start=2.5), style())
    assert abs(info["duration"] - 2.0) <= 0.1
    last = _frames(out, tmp_path, 1.7)
    assert last and min(_bright(im) for im in last[:-5]) > 40  # pas d'images noires en fin de source


def test_freeze_adds_held_frame(clip, tmp_path):
    out, info = _render(clip, tmp_path, _seg("freeze", 2.0, start=0.5), style("nerveux"))
    assert abs(info["duration"] - 2.0) <= 0.1
    frames = _frames(out, tmp_path)
    held = frames[-27:]  # 0,9 s à 30 i/s
    assert max(_diff(held[0], im) for im in held) < 1.0
    assert _diff(frames[0], frames[15]) > 1.0  # avant l'arrêt, la mire bouge


def test_speedup_duration(clip, tmp_path):
    out, info = _render(clip, tmp_path, _seg("speedup", 1.4, start=2.0), style())
    assert abs(info["duration"] - 1.4) <= 0.1
    assert info["has_audio"]
    last = _frames(out, tmp_path, 1.0)
    assert last and min(_bright(im) for im in last[:-6]) > 40


@pytest.mark.parametrize("item_id", [1, 2])
def test_punch_renders(clip, tmp_path, item_id):
    seg = ({"type": "photo", "item_id": 1, "text": "Ha !", "duration": 1.5, "effect": "punch"} if item_id == 1
           else {**_seg("punch", 1.5), "text": "Ha !"})
    out, info = _render(clip, tmp_path, seg, style())
    assert abs(info["duration"] - 1.5) <= 0.1


def test_punch_zooms_at_the_end(clip, tmp_path):
    """Même plan avec et sans zoom comique (sans fondu) : identiques au début, différents à la fin."""
    got = {}
    for effect in ("none", "punch"):
        d = tmp_path / effect
        d.mkdir()
        out = video._render_segment(_seg(effect, 1.5), clip[2], d, 0, SMALL, style("nerveux"))
        got[effect] = _frames(out, d)
    assert _diff(got["none"][5], got["punch"][5]) < 2.0
    assert _diff(got["none"][-1], got["punch"][-1]) > 5.0


def test_fades_follow_rhythm(clip, tmp_path):
    """Pas de fondu en rythme nerveux : la première image est déjà claire ; fondu au noir en posé."""
    seg = {"type": "photo", "item_id": 1, "text": "", "duration": 1.5, "effect": "none"}
    firsts = {}
    for rhythm in ("nerveux", "pose"):
        out = tmp_path / rhythm / "video.mp4"
        out.parent.mkdir()
        video.render([seg], clip, out, {"main": None, "final": None, "credits": []}, 50, SMALL, style(rhythm))
        firsts[rhythm] = _bright(_frames(out, tmp_path, 0, "f" + rhythm)[0])
    assert firsts["nerveux"] > 150
    assert firsts["pose"] < 60


def _row(**cols):
    """Un élément tel que le renvoie la base (sqlite3.Row, sans .get)."""
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    names = ", ".join(f"? AS {k}" for k in cols)
    return con.execute(f"SELECT {names}", list(cols.values())).fetchone()


@pytest.mark.parametrize("effect", ["none", "slowmo", "speedup", "freeze", "punch"])
def test_video_segment_from_db_row(clip, tmp_path, effect):
    item = _row(id=2, event_id=1, kind="video", duration=3.0)
    seg = _seg(effect, 2.0, start=2.5)
    out = video._render_segment(seg, item, tmp_path, 0, SMALL, style())
    assert abs(media.probe(out)["duration"] - 2.0) <= 0.1


def test_render_keeps_video_from_db_row(clip, tmp_path):
    """Un extrait vidéo venu de la base n'est pas ignoré par render (2 s de photo + 2 s de vidéo)."""
    items = {1: _row(id=1, event_id=1, kind="photo", duration=None),
             2: _row(id=2, event_id=1, kind="video", duration=3.0)}
    segs = [{"type": "photo", "item_id": 1, "text": "", "duration": 2.0, "effect": "none"}, _seg("speedup", 2.0, 0.5)]
    out = tmp_path / "o" / "video.mp4"
    out.parent.mkdir()
    total = video.render(segs, items, out, {"main": None, "final": None, "credits": []}, 50, SMALL, style())
    assert abs(total - 4.0) <= 0.2
