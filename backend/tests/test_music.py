import json

import pytest

from app import config, db
from app.pipeline import music, settings


def entry(key, mood, genres, energy, **kw):
    d = dict(key=key, title=key, artist="A", license="L", source_url="", credit="", genres=genres,
             energy=energy, mood=mood, bpm=100, file=f"{key}.mp3")
    d.update(kw)
    return d


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MUSIC_DIR", tmp_path)
    db.init()
    db.run("DELETE FROM tracks")

    def make(entries):
        for e in entries:
            (tmp_path / e["file"]).write_bytes(b"x")
        (tmp_path / "catalogue.json").write_text(json.dumps(entries), encoding="utf-8")
        return music.sync_catalogue()

    return make


MELANCO = entry("triste-pop", "melancolique", ["pop"], 4)
JOYEUX = entry("joyeux-funk", "joyeux", ["funk"], 4)


def test_weekend_never_gets_melancholy(lib):
    lib([MELANCO, JOYEUX])
    st = settings.defaults("weekend")
    tones = ["drole", "festif"]
    assert music.choose(tones, st)["main"]["key"] == "joyeux-funk"
    assert all(t["mood"] != "melancolique" for t in music.candidates(tones, st))


def test_tendre_allows_melancholy(lib):
    lib([MELANCO, JOYEUX])
    st = settings.defaults("weekend")
    keys = [t["key"] for t in music.candidates(["tendre"], st)]
    assert "triste-pop" in keys


def test_touchante_gets_final_track(lib):
    lib([JOYEUX, entry("calme-piano", "calme", ["piano"], 2), entry("mel", "melancolique", ["piano"], 1)])
    st = {**settings.defaults("weekend"), "ending": "touchante"}
    res = music.choose(["drole"], st)
    assert res["final"]["mood"] in ("calme", "tendre", "melancolique")
    assert res["final"]["energy"] <= 2
    assert res["main"]["mood"] not in ("melancolique", "triste")
    st["ending"] = "festive"
    assert music.choose(["drole"], st)["final"] is None


def test_relaxes_genre_then_energy_never_mood(lib):
    lib([entry("jazz", "joyeux", ["jazz"], 2), entry("triste", "triste", ["rock"], 4)])
    st = {**settings.defaults("weekend"), "genres": ["rock"], "energy": 4}
    assert music.choose(["drole"], st)["main"]["key"] == "jazz"


def test_empty_catalogue_returns_none(lib):
    lib([])
    assert music.choose(["drole"], settings.defaults("weekend")) == {"main": None, "final": None}


def test_exclude_gives_next(lib):
    lib([entry("a", "joyeux", ["funk"], 4), entry("b", "joyeux", ["funk"], 4)])
    st = settings.defaults("weekend")
    c = music.candidates(["drole"], st)
    assert len(c) == 2
    assert music.candidates(["drole"], st, exclude=[c[0]["id"]])[0]["id"] == c[1]["id"]


def test_sync_keeps_uploads(lib):
    db.insert("tracks", key="up1", title="Mon morceau", artist="", license="", source_url="", credit="",
              genres="", energy=3, mood="joyeux", bpm=None, duration=None, file="up1.mp3",
              origin="upload", created_at=db.now())
    assert lib([JOYEUX]) == 1
    assert db.one("SELECT * FROM tracks WHERE key='up1'")["origin"] == "upload"


def test_sync_updates_and_public(lib):
    lib([JOYEUX])
    lib([{**JOYEUX, "genres": ["pop", "funk"]}])
    t = music.get_by_key("joyeux-funk")
    assert t["genres"] == ["pop", "funk"]
    assert music.public(t) == {"id": t["id"], "title": "joyeux-funk", "artist": "A", "credit": "",
                               "url": f"/api/music/{t['id']}.mp3"}
    assert music.path(t).name == "joyeux-funk.mp3"
    assert music.path({**t, "file": "absent.mp3"}) is None


def test_allowed_rule():
    m = {"mood": "triste"}
    assert not music.allowed(m, ["drole"], False, "touchante")
    assert music.allowed(m, ["nostalgique"], False, "festive")
    assert music.allowed(m, ["drole"], True, "touchante")
    assert not music.allowed(m, ["drole"], True, "festive")


def test_catalogue_json_is_valid():
    from pathlib import Path

    f = Path(__file__).resolve().parents[2] / "music" / "catalogue.json"
    if not f.is_file():
        f = Path("/app/music/catalogue.json")
    entries = json.loads(f.read_text(encoding="utf-8"))
    keys = [e["key"] for e in entries]
    assert len(keys) == len(set(keys))
    required = {"key", "title", "artist", "license", "source_url", "credit", "genres", "energy", "mood", "bpm", "file"}
    for e in entries:
        assert required <= set(e), e["key"]
        assert e["genres"] and all(g in config.GENRES for g in e["genres"]), e["key"]
        assert e["mood"] in config.MOODS, e["key"]
        assert 1 <= e["energy"] <= 5, e["key"]
        if e["artist"] == "Kevin MacLeod":
            assert e["license"] == "CC BY 4.0"
            assert e["credit"] == f"Musique : « {e['title']} » — Kevin MacLeod (incompetech.com), licence CC BY 4.0"
            assert e["mp3_url"].startswith("https://incompetech.com/")
        else:
            assert e["artist"] == "Souvenirs" and e["credit"] == "" and "mp3_url" not in e


class FakeResp:
    def __init__(self, data):
        self.data = data

    def read(self, *a):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_missing(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setattr(config, "MUSIC_DIR", src)
    entries = [entry(k, "joyeux", ["pop"], 3, mp3_url=f"https://incompetech.com/{k}.mp3") for k in ("a", "b", "c")]
    entries.append(entry("local", "joyeux", ["pop"], 3))  # sans mp3_url : ignoré
    (src / "catalogue.json").write_text(json.dumps(entries), encoding="utf-8")
    dest = tmp_path / "lib"
    dest.mkdir()
    (dest / "a.mp3").write_bytes(b"old")
    seen = []

    def opener(req, timeout=None):
        seen.append((req.full_url, req.get_header("User-agent")))
        if req.full_url.endswith("/c.mp3"):
            raise OSError("réseau coupé")
        return FakeResp(b"mp3data")

    res = music.fetch_missing(dest=dest, delay=0, opener=opener)
    assert res == {"ok": 1, "skipped": 1, "failed": 1}
    assert (dest / "a.mp3").read_bytes() == b"old"
    assert (dest / "b.mp3").read_bytes() == b"mp3data"
    assert not (dest / "c.mp3").exists()
    assert sorted(p.name for p in dest.iterdir()) == ["a.mp3", "b.mp3"]  # aucun fichier temporaire
    assert [u for u, _ in seen] == ["https://incompetech.com/b.mp3", "https://incompetech.com/c.mp3"]
    assert all(ua == "souvenirs-app" for _, ua in seen)


def test_path_prefers_library_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MUSIC_DIR", tmp_path / "m")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "d")
    (tmp_path / "m").mkdir()
    (tmp_path / "d" / "music" / "library").mkdir(parents=True)
    t = {"origin": "library", "file": "x.mp3"}
    assert music.path(t) is None
    (tmp_path / "m" / "x.mp3").write_bytes(b"1")
    assert music.path(t) == tmp_path / "m" / "x.mp3"
    (tmp_path / "d" / "music" / "library" / "x.mp3").write_bytes(b"2")
    assert music.path(t) == tmp_path / "d" / "music" / "library" / "x.mp3"
