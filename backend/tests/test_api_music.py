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
                                  {"energy": "9"}, {"energy": "x"}, {"mood": "furieux"}])
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
