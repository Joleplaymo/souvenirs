import json
import shutil
import subprocess

import pytest

from app import config, db
from app.pipeline import music, settings


def entry(key, mood, genres, energy, **kw):
    d = dict(key=key, title=key, artist="A", license="L", source_url="", credit="", genres=genres,
             energy=energy, mood=mood, bpm=100, file=f"{key}.mp3")
    d.update(kw)
    return d


@pytest.fixture(scope="module")
def tiny_mp3(tmp_path_factory):
    """Vrai MP3 d'une seconde (les morceaux illisibles sont écartés du choix)."""
    f = tmp_path_factory.mktemp("tiny") / "tiny.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    str(f)], check=True)
    return f


@pytest.fixture
def lib(tmp_path, monkeypatch, tiny_mp3):
    monkeypatch.setattr(config, "MUSIC_DIR", tmp_path)
    db.init()
    db.run("DELETE FROM tracks")

    def make(entries):
        for e in entries:
            shutil.copy(tiny_mp3, tmp_path / e["file"])
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


def test_unreadable_library_file_is_never_chosen(lib, tmp_path):
    lib([entry("casse", "joyeux", ["funk"], 4), JOYEUX])
    (tmp_path / "casse.mp3").write_bytes(b"<html>erreur</html>")
    db.run("UPDATE tracks SET duration=NULL")
    music.sync_catalogue()
    casse = music.get_by_key("casse")
    assert casse["duration"] == 0 and not music.usable(casse)
    assert music.usable(music.get_by_key("joyeux-funk"))
    assert [t["key"] for t in music.candidates(["drole"], settings.defaults("weekend"))] == ["joyeux-funk"]
    # fichier réparé : de nouveau sondé et choisi au démarrage suivant
    shutil.copy(tmp_path / "joyeux-funk.mp3", tmp_path / "casse.mp3")
    music.sync_catalogue()
    assert music.usable(music.get_by_key("casse"))


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


def test_fetch_missing(tmp_path, monkeypatch, tiny_mp3):
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setattr(config, "MUSIC_DIR", src)
    entries = [entry(k, "joyeux", ["pop"], 3, mp3_url=f"https://incompetech.com/{k}.mp3")
               for k in ("a", "b", "c", "html", "petit")]
    entries.append(entry("local", "joyeux", ["pop"], 3))  # sans mp3_url : ignoré
    (src / "catalogue.json").write_text(json.dumps(entries), encoding="utf-8")
    dest = tmp_path / "lib"
    dest.mkdir()
    (dest / "a.mp3").write_bytes(b"old")
    seen = []
    good = tiny_mp3.read_bytes()

    def opener(req, timeout=None):
        seen.append((req.full_url, req.get_header("User-agent")))
        if req.full_url.endswith("/c.mp3"):
            raise OSError("réseau coupé")
        if req.full_url.endswith("/html.mp3"):  # page d'erreur servie avec un code 200
            return FakeResp(b"<html>" + b" " * len(good) + b"</html>")
        if req.full_url.endswith("/petit.mp3"):
            return FakeResp(good[:100])
        return FakeResp(good)

    # seuil abaissé : le MP3 de test ne fait que quelques kilo-octets
    res = music.fetch_missing(dest=dest, delay=0, opener=opener, min_size=len(good) // 2)
    assert res == {"ok": 1, "skipped": 1, "failed": 3}
    assert (dest / "a.mp3").read_bytes() == b"old"
    assert (dest / "b.mp3").read_bytes() == good
    for k in ("c", "html", "petit"):
        assert not (dest / f"{k}.mp3").exists()
    assert sorted(p.name for p in dest.iterdir()) == ["a.mp3", "b.mp3"]  # aucun fichier temporaire
    assert [u for u, _ in seen] == [f"https://incompetech.com/{k}.mp3" for k in ("b", "c", "html", "petit")]
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


def test_fetch_missing_default_threshold_rejects_small_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MUSIC_DIR", tmp_path)
    (tmp_path / "catalogue.json").write_text(json.dumps(
        [entry("a", "joyeux", ["pop"], 3, mp3_url="https://incompetech.com/a.mp3")]), encoding="utf-8")
    res = music.fetch_missing(dest=tmp_path / "lib", delay=0, opener=lambda req, timeout=None: FakeResp(b"mp3data"))
    assert res == {"ok": 0, "skipped": 0, "failed": 1}
    assert list((tmp_path / "lib").iterdir()) == []


# ------------------------------------------------------------------ évolution sur plusieurs morceaux

def _roles(plan):
    return {p["role"]: p["track"] for p in plan}


def test_plan_tracks_montee_three_roles(lib):
    lib([entry("doux", "joyeux", ["funk"], 3), entry("moyen", "joyeux", ["funk"], 4),
         entry("fort", "festif", ["funk"], 5)])
    st = {**settings.defaults("weekend"), "evolution": "montee", "energy": 4}
    plan = music.plan_tracks(["drole", "festif"], st)
    assert [p["role"] for p in plan] == ["intro", "main", "peak"]
    assert [p["track"]["energy"] for p in plan] == [3, 4, 5]
    # constante : un seul morceau ; calme puis explosion : intro calme (1 ou 2) puis pic à 5
    assert [p["role"] for p in music.plan_tracks(["drole"], {**st, "evolution": "constante"})] == ["main"]
    lib([entry("calme", "calme", ["funk"], 2), entry("moyen", "joyeux", ["funk"], 4),
         entry("fort", "festif", ["funk"], 5)])
    got = _roles(music.plan_tracks(["drole"], {**st, "evolution": "calme_explosion"}))
    assert set(got) == {"intro", "peak"} and got["intro"]["key"] == "calme" and got["peak"]["key"] == "fort"


def test_festif_emotion_final_may_be_melancholic(lib):
    lib([entry("gai", "joyeux", ["funk"], 4), entry("mel-fort", "melancolique", ["funk"], 4),
         entry("mel-doux", "melancolique", ["piano"], 1)])
    tones = ["drole"]
    st = {**settings.defaults("anniversaire"), "evolution": "festif_emotion", "ending": "festive", "energy": 4}
    got = _roles(music.plan_tracks(tones, st))
    assert got["main"]["key"] == "gai" and got["final"]["key"] == "mel-doux"
    # seul le rôle final accepte la mélancolie, et seulement en festif → émotion (ou fin touchante)
    mel = music.get_by_key("mel-doux")
    assert music.allowed(mel, tones, True, "festive", "festif_emotion")
    assert not music.allowed(mel, tones, False, "festive", "festif_emotion")
    assert not music.allowed(mel, tones, True, "festive", "montee")
    for evo in ("constante", "montee", "calme_explosion"):
        plan = music.plan_tracks(tones, {**st, "evolution": evo})
        assert all(p["track"]["mood"] != "melancolique" for p in plan), evo
    # catalogue sans morceau gai : pas de morceau final seul (film sans musique)
    lib([entry("mel-doux", "melancolique", ["piano"], 1)])
    db.run("DELETE FROM tracks WHERE key NOT IN ('mel-doux')")
    assert music.plan_tracks(tones, st) == []


def test_plan_tracks_never_repeats(lib):
    lib([entry("seul", "joyeux", ["funk"], 4)])
    st = {**settings.defaults("weekend"), "evolution": "montee", "ending": "touchante", "energy": 4}
    plan = music.plan_tracks(["drole"], st)
    assert [p["role"] for p in plan] == ["main"]
    lib([entry("a", "joyeux", ["funk"], 4), entry("b", "joyeux", ["funk"], 4), entry("c", "joyeux", ["funk"], 3),
         entry("d", "calme", ["piano"], 1)])
    plan = music.plan_tracks(["drole"], st)
    ids = [p["track"]["id"] for p in plan]
    assert len(ids) == len(set(ids)) == 4
    # exclusion par rôle (« Autre titre »)
    main = _roles(plan)["main"]["id"]
    other = _roles(music.plan_tracks(["drole"], st, exclude={"main": [main]}))
    assert other["main"]["id"] != main
    assert len({t["id"] for t in other.values()}) == len(other)


def _energies(plan):
    return {p["role"]: p["track"]["energy"] for p in plan}


def test_montee_never_inverted(lib):
    """Montée : le début n'est jamais plus énergique que le cœur, le sommet jamais moins ; sinon le rôle est omis."""
    st = {**settings.defaults("weekend"), "evolution": "montee", "energy": 4}
    # seuls des morceaux à 5 en plus du cœur : le début (cible 3, repli ±2) prendrait un 5
    lib([entry("coeur", "joyeux", ["funk"], 4), entry("fort-a", "festif", ["funk"], 5),
         entry("fort-b", "festif", ["funk"], 5)])
    plan = music.plan_tracks(["drole"], st)
    assert [p["role"] for p in plan] == ["main", "peak"] and _energies(plan) == {"main": 4, "peak": 5}
    # seuls des morceaux à 2 en plus du cœur : le sommet (cible 4, repli ±2) prendrait un 2
    lib([entry("coeur", "joyeux", ["funk"], 3), entry("doux-a", "joyeux", ["funk"], 2),
         entry("doux-b", "joyeux", ["funk"], 2)])
    db.run("DELETE FROM tracks WHERE key NOT IN ('coeur', 'doux-a', 'doux-b')")
    plan = music.plan_tracks(["drole"], {**st, "energy": 3})
    assert [p["role"] for p in plan] == ["intro", "main"] and _energies(plan) == {"intro": 2, "main": 3}


def test_montee_prefers_strict_climb(lib):
    """Un début de même énergie que le cœur n'est pris que s'il n'y a rien de plus calme."""
    st = {**settings.defaults("weekend"), "evolution": "montee", "energy": 4}
    lib([entry("coeur", "joyeux", ["funk"], 4), entry("pareil", "joyeux", ["funk"], 4),
         entry("calme", "joyeux", ["funk"], 2), entry("fort", "festif", ["funk"], 5)])
    assert _energies(music.plan_tracks(["drole"], st)) == {"intro": 2, "main": 4, "peak": 5}
    # rien de plus calme : un début à la même énergie reste possible (jamais au-dessus)
    db.run("DELETE FROM tracks WHERE key='calme'")
    assert _energies(music.plan_tracks(["drole"], st)) == {"intro": 4, "main": 4, "peak": 5}
