import json
import secrets
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app
from app.pipeline import music

client = TestClient(app)
ADMIN = {"x-admin-code": "test"}
META = {"title": "Mon morceau", "artist": "Moi", "genres": "pop,funk", "energy": "4", "mood": "joyeux",
        "license": "CC BY 4.0"}


@pytest.fixture(scope="module")
def mp3(tmp_path_factory):
    f = tmp_path_factory.mktemp("mp3") / "a.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    str(f)], check=True)
    return f.read_bytes()


def _post(data, headers=None, **over):
    params = {**META, **over}
    return client.post("/api/music", params=params, content=data, headers={**ADMIN, **(headers or {})})


def _uploads_dir():
    return config.DATA_DIR / "music" / "uploads"


def _count():
    return db.one("SELECT COUNT(*) c FROM tracks")["c"]


def _files():
    d = _uploads_dir()
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def test_upload_valid_mp3(mp3):
    r = _post(mp3)
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["title"] == "Mon morceau" and t["origin"] == "upload" and t["genres"] == ["pop", "funk"]
    assert t["credit"] == "Musique : « Mon morceau » — Moi"
    assert t["url"] == f"/api/music/{t['id']}.mp3"
    assert t["id"] in [x["id"] for x in client.get("/api/music", headers=ADMIN).json()]
    assert (_uploads_dir() / f"{t['id']}.mp3").is_file()
    assert music.get(t["id"])["duration"] > 0
    # lecture publique, sans code
    a = client.get(t["url"])
    assert a.status_code == 200 and a.headers["content-type"].startswith("audio/mpeg")
    assert a.content == mp3


def test_credit_without_artist(mp3):
    r = _post(mp3, artist="")
    assert r.status_code == 201
    assert r.json()["credit"] == "Musique : « Mon morceau »"


def test_upload_rejects_non_audio():
    n, files = _count(), _files()
    r = _post(b"ceci n'est pas un mp3" * 100)
    assert r.status_code == 400
    assert _count() == n and _files() == files


def test_upload_rejects_too_big_by_header(mp3):
    n, files = _count(), _files()
    r = _post(mp3, headers={"content-length": str(31 * 1024 * 1024)})
    assert r.status_code == 413
    assert _count() == n and _files() == files


def test_upload_rejects_too_big_while_streaming():
    n, files = _count(), _files()

    def gen():
        for _ in range(31):
            yield b"\0" * (1024 * 1024)

    r = client.post("/api/music", params=META, content=gen(), headers=ADMIN)
    assert r.status_code == 413
    assert _count() == n and _files() == files


@pytest.mark.parametrize("over", [{"title": " "}, {"license": ""}, {"genres": ""}, {"genres": "pop,nimportequoi"},
                                  {"energy": "9"}, {"energy": "x"}, {"energy": "²"}, {"mood": "furieux"}])
def test_upload_rejects_bad_metadata(mp3, over):
    n, files = _count(), _files()
    r = _post(mp3, **over)
    assert r.status_code == 400
    assert _count() == n and _files() == files


def test_requires_admin_code(mp3):
    assert client.get("/api/music").status_code in (401, 403)
    assert client.post("/api/music", params=META, content=mp3).status_code in (401, 403)
    assert client.delete("/api/music/1").status_code in (401, 403)


def test_delete_upload(mp3):
    t = _post(mp3).json()
    p = _uploads_dir() / f"{t['id']}.mp3"
    assert p.is_file()
    assert client.delete(f"/api/music/{t['id']}", headers=ADMIN).status_code == 200
    assert not p.exists() and music.get(t["id"]) is None
    assert client.get(t["url"]).status_code == 404
    assert client.delete(f"/api/music/{t['id']}", headers=ADMIN).status_code == 404


def test_cannot_delete_library_track():
    tid = db.insert("tracks", key="lib-test", title="Lib", artist="K", license="CC BY 4.0", source_url="",
                    credit="c", genres="pop", energy=3, mood="joyeux", file="lib-test.mp3", origin="library",
                    created_at=db.now())
    assert client.delete(f"/api/music/{tid}", headers=ADMIN).status_code == 403
    assert music.get(tid) is not None


def test_mp3_route_unknown_and_missing_file():
    assert client.get("/api/music/999999.mp3").status_code == 404
    tid = db.insert("tracks", key="lib-nofile", title="X", artist="", license="", source_url="", credit="",
                    genres="pop", energy=3, mood="joyeux", file="absent.mp3", origin="library", created_at=db.now())
    assert client.get(f"/api/music/{tid}.mp3").status_code == 404


# ------------------------------------------------------------------ pré-écoute
NO_MUSIC = "Aucune musique ne correspond à ces réglages : le film sera sans musique."


@pytest.fixture
def pick_lib(tmp_path, monkeypatch, mp3):
    mdir = tmp_path / "music"
    mdir.mkdir()
    monkeypatch.setattr(config, "MUSIC_DIR", mdir)
    db.init()
    db.run("DELETE FROM tracks")

    def make(keys):
        entries = []
        for k in keys:
            (mdir / f"{k}.mp3").write_bytes(mp3)
            entries.append(dict(key=k, title=k, artist="A", license="CC BY 4.0", source_url="", credit="",
                                genres=["funk"], energy=4, mood="joyeux", bpm=100, file=f"{k}.mp3"))
        (mdir / "catalogue.json").write_text(json.dumps(entries), encoding="utf-8")
        music.sync_catalogue()

    return make


def _event(tone="drole,festif", typ="weekend"):
    slug = "pk-" + secrets.token_hex(4)
    db.insert("events", slug=slug, admin_token="adm-" + slug, name="Week-end", start_date="2026-05-01",
              end_date="2026-05-01", type=typ, tone=tone, tz="Europe/Paris", created_at=db.now())
    return slug, {"x-admin-token": "adm-" + slug}


def _pick(slug, headers, **body):
    return client.post(f"/api/events/{slug}/music/pick", json=body, headers=headers)


def _rep(slug):
    return db.report(db.one("SELECT * FROM events WHERE slug=?", slug)["id"])


STORED = json.dumps({"main_id": 987654, "final_id": None})


def _event_with_music(**kw):
    """Événement dont reports.music contient déjà un choix (celui du dernier rendu)."""
    slug, h = _event(**kw)
    db.update("reports", "event_id", _rep(slug)["event_id"], music=STORED)
    return slug, h


def test_preview_returns_pick_without_storing_it(pick_lib):
    pick_lib(["p1", "p2"])
    slug, h = _event_with_music()
    r = _pick(slug, h, tones=None, video_settings={"duration": 60, "genres": ["funk"]}, exclude=[])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["main"]["id"] and j["main"]["url"] == f"/api/music/{j['main']['id']}.mp3" and j["message"] == ""
    assert _rep(slug)["music"] == STORED  # la pré-écoute ne change pas la musique des rendus suivants


def test_preview_other_title_uses_exclude(pick_lib):
    pick_lib(["p1", "p2"])
    slug, h = _event_with_music()
    first = _pick(slug, h, video_settings={}, exclude=[]).json()["main"]["id"]
    second = _pick(slug, h, video_settings={}, exclude=[first]).json()["main"]["id"]
    assert second != first
    assert _rep(slug)["music"] == STORED


def test_preview_empty_catalogue_message(pick_lib):
    pick_lib([])
    slug, h = _event_with_music()
    r = _pick(slug, h, video_settings={}, exclude=[])
    assert r.status_code == 200
    assert r.json() == {"main": None, "final": None, "message": NO_MUSIC}
    assert _rep(slug)["music"] == STORED


def test_preview_validation_and_auth(pick_lib):
    pick_lib(["p1"])
    slug, h = _event()
    assert _pick(slug, {}, video_settings={}).status_code == 403
    assert _pick(slug, {"x-admin-token": "nope"}, video_settings={}).status_code == 403
    assert _pick(slug, h, tones=[1, 2]).status_code == 400
    assert _pick(slug, h, tones=["a", "b", "c"]).status_code == 400
    assert _pick(slug, h, exclude="1").status_code == 400
    assert _pick(slug, h, exclude=[True]).status_code == 400
    assert _pick(slug, h, video_settings="x").status_code == 400
    assert _pick(slug, h, tones=["festif"], video_settings={}).status_code == 200


def test_preview_incompatible_catalogue_gives_no_music(pick_lib, mp3):
    pick_lib(["p1"])
    db.run("UPDATE tracks SET mood='melancolique'")
    slug, h = _event_with_music(tone="drole,festif")
    r = _pick(slug, h, video_settings={}, exclude=[])
    assert r.status_code == 200
    assert r.json() == {"main": None, "final": None, "message": NO_MUSIC}
    assert _rep(slug)["music"] == STORED


def test_preview_touchante_returns_final(pick_lib):
    pick_lib(["p1", "p2"])
    db.run("UPDATE tracks SET mood='joyeux', energy=4 WHERE key='p1'")
    db.run("UPDATE tracks SET mood='tendre', energy=1 WHERE key='p2'")
    slug, h = _event_with_music(tone="tendre,festif")
    r = _pick(slug, h, video_settings={"ending": "touchante", "genres": []}, exclude=[])
    j = r.json()
    assert r.status_code == 200 and j["main"] and j["final"] and j["final"]["id"] != j["main"]["id"]
    assert _rep(slug)["music"] == STORED


def test_preview_does_not_touch_video_settings(pick_lib):
    pick_lib(["p1"])
    slug, h = _event()
    before = _rep(slug)["video_settings"]
    _pick(slug, h, video_settings={"duration": 300})
    assert _rep(slug)["video_settings"] == before


def test_preview_refused_while_generating(pick_lib):
    pick_lib(["p1"])
    slug, h = _event()
    db.enqueue(db.one("SELECT id FROM events WHERE slug=?", slug)["id"], "generate", parts=["music"])
    r = _pick(slug, h, video_settings={})
    assert r.status_code == 409 and r.json()["detail"] == "Une génération est déjà en cours."
