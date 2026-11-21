"""Cadrage du film : 16:9, 9:16 ou 1:1, image entière sur fond flou, jamais recadrée."""
import json
import subprocess

import pytest
from PIL import Image, ImageDraw

from app.pipeline import media, video


def _probe_dims(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)["streams"][0]
    return s["width"], s["height"]


@pytest.fixture
def stub(tmp_path, monkeypatch):
    """Une photo paysage 1600x900 (damier de bandes), une vidéo 1280x720 de 3 s, une photo portrait 900x1600."""
    photo = tmp_path / "land.jpg"
    im = Image.new("RGB", (1600, 900), (240, 240, 240))
    d = ImageDraw.Draw(im)
    for x in range(0, 1600, 100):
        d.rectangle([x, 0, x + 49, 899], fill=(220, 30, 30))
    im.save(photo)
    port = tmp_path / "port.jpg"
    Image.new("RGB", (900, 1600), (30, 120, 220)).save(port)
    vid = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=3",
                    "-pix_fmt", "yuv420p", str(vid)], check=True)
    files = {1: photo, 2: vid, 3: port}
    items = {1: {"id": 1, "event_id": 1, "kind": "photo"},
             2: {"id": 2, "event_id": 1, "kind": "video", "duration": 3.0},
             3: {"id": 3, "event_id": 1, "kind": "photo"}}
    monkeypatch.setattr(media, "derived", lambda eid, iid, kind: files[iid])
    monkeypatch.setattr(media, "raw_path", lambda it: files[it["id"]])
    return items


SEGS = [{"type": "photo", "item_id": 1, "text": "", "duration": 2.0},
        {"type": "video", "item_id": 2, "text": "", "start": 0, "duration": 2.0},
        {"type": "photo", "item_id": 3, "text": "", "duration": 2.0}]


def _render(stub, tmp_path, frame, segs=SEGS):
    out = tmp_path / "out" / "video.mp4"
    out.parent.mkdir()
    video.render(segs, stub, out, {"main": None, "final": None, "credits": []}, 50, frame)
    return out


def test_vertical_output_dims(stub, tmp_path):
    assert _probe_dims(_render(stub, tmp_path, video.frame_for("9:16"))) == (1080, 1920)


def test_square_output_dims(stub, tmp_path):
    assert _probe_dims(_render(stub, tmp_path, video.frame_for("1:1"))) == (1080, 1080)


def test_frame_for_default():
    assert video.frame_for("16:9") == video.Frame(1920, 1080)
    assert video.frame_for("nimporte") == video.Frame(1920, 1080)


def test_landscape_photo_in_vertical_not_cropped(stub, tmp_path):
    out = _render(stub, tmp_path, video.frame_for("9:16"), SEGS[:1])
    png = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(out), "-frames:v", "1", str(png)],
                   check=True)
    im = Image.open(png).convert("RGB")
    w, h = im.size
    assert (w, h) == (1080, 1920)
    # ligne médiane : la photo (bandes rouges nettes) occupe toute la largeur du cadre, ±2 %
    y = h // 2
    xs = [x for x in range(w) if im.getpixel((x, y))[0] > 150]  # le fond flou est assombri
    assert xs and (xs[-1] - xs[0]) / w > 0.96
    # et au-dessus / en dessous de la photo, le fond est flou (pas de bandes nettes)
    top = [im.getpixel((x, 200))[0] for x in range(w)]
    assert max(top) < 150


def test_subtitle_inside_frame_vertical(tmp_path):
    out = tmp_path / "s.png"
    video.subtitle_png("Un très long sous-titre " * 5 + "fin", out, video.frame_for("9:16"))
    im = Image.open(out)
    assert im.size == (1080, 1920)
    box = im.getchannel("A").getbbox()
    assert box and box[0] >= 0 and box[2] <= 1080 and box[3] <= 1920


def test_subtitle_90_chars_fit(tmp_path):
    out = tmp_path / "s.png"
    video.subtitle_png("x" * 8 + " mot" * 20 + " fin", out, video.frame_for("9:16"))
    box = Image.open(out).getchannel("A").getbbox()
    assert box[2] - box[0] <= 1080


def test_title_card_text_inside_vertical(tmp_path):
    out = tmp_path / "t.png"
    video.title_card("Un week-end extraordinaire en Bretagne avec toute la famille", out, video.frame_for("9:16"))
    assert Image.open(out).size == (1080, 1920)


def test_meta_stores_frame_and_recredit_uses_it(stub, tmp_path):
    out = _render(stub, tmp_path, video.frame_for("1:1"), SEGS[:1])
    base = out.parent / video.BASE
    assert video.read_meta(base)["w"] == 1080 and video.read_meta(base)["h"] == 1080
    video.recredit(base, ["Musique : « A » — B"])
    assert _probe_dims(base) == (1080, 1080)
