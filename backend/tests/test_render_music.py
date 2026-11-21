"""Musique dans le rendu : choix par réglages, crédit, mélange, « Changer la musique »."""
import json
import re
import secrets
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, db
from app.main import app
from app.pipeline import generate, media, music, settings, versions, video

client = TestClient(app)
ADMIN = {"x-admin-code": "test"}
CREDIT = "Musique : « Carefree » — Kevin MacLeod (incompetech.com), licence CC BY 4.0"
NO_BASE = "Ce film date d'avant le choix des musiques : régénère le film une fois."


def noop(*a, **k):
    pass


@pytest.fixture(scope="module")
def sines(tmp_path_factory):
    d = tmp_path_factory.mktemp("sines")
    for name, freq in (("a.mp3", 440), ("b.mp3", 660), ("c.mp3", 330)):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency={freq}:duration=2", str(d / name)], check=True)
    return d


@pytest.fixture(autouse=True)
def small(monkeypatch):
    """Rendu minuscule pour des tests rapides."""
    monkeypatch.setattr(video, "W", 320)
    monkeypatch.setattr(video, "H", 180)


@pytest.fixture
def lib(tmp_path, monkeypatch, sines):
    mdir = tmp_path / "music"
    mdir.mkdir()
    monkeypatch.setattr(config, "MUSIC_DIR", mdir)
    db.init()
    db.run("DELETE FROM tracks")

    def make(entries):
        for e in entries:
            shutil.copy(sines / e.pop("src", "a.mp3"), mdir / e["file"])
        (mdir / "catalogue.json").write_text(json.dumps(entries), encoding="utf-8")
        music.sync_catalogue()
        return {e["key"]: music.get_by_key(e["key"])["id"] for e in entries}

    return make


def entry(key, mood="joyeux", genres=("funk",), energy=4, src="a.mp3", credit=""):
    return dict(key=key, title=key, artist="Kevin MacLeod" if credit else "A", license="CC BY 4.0",
                source_url="", credit=credit, genres=list(genres), energy=energy, mood=mood, bpm=100,
                file=f"{key}.mp3", src=src)


def make_event(tone="drole,festif", typ="weekend", photos=1):
    slug = "rm-" + secrets.token_hex(4)
    eid = db.insert("events", slug=slug, admin_token="adm-" + slug, name="Week-end", start_date="2026-05-01",
                    end_date="2026-05-01", type=typ, tone=tone, tz="Europe/Paris", created_at=db.now())
    pid = db.insert("participants", event_id=eid, name="Léa", token="tok-" + slug, created_at=db.now())
    for n in range(photos):
        iid = db.insert("items", event_id=eid, participant_id=pid, kind="photo",
                        captured_at=f"2026-05-01T{10 + n:02d}:00:00Z", created_at=db.now(),
                        width=320, height=180, status="ready")
        Image.new("RGB", (320, 180), (200, 120 + 30 * n, 40)).save(media.derived(eid, iid, "d"))
    db.report(eid)
    db.update("reports", "event_id", eid, text_md="# Week-end\n\nUn super week-end.")
    return db.one("SELECT * FROM events WHERE id=?", eid)


def run_job(ev, **params):
    params.setdefault("ai", True)
    jid = db.enqueue(ev["id"], "generate", **params)
    try:
        generate.generate(db.one("SELECT * FROM jobs WHERE id=?", jid))
    finally:  # comme le worker : la tâche n'est plus active
        db.update("jobs", "id", jid, status="done")


def draft(ev):
    return generate.out_dir(ev["id"])


def stored_music(ev):
    return json.loads(db.report(ev["id"])["music"])


def spy_titles(monkeypatch):
    calls = []
    orig = video.title_card

    def spy(text, out):
        calls.append(text)
        return orig(text, out)

    monkeypatch.setattr(video, "title_card", spy)
    return calls


# ------------------------------------------------------------------ rendu

def test_render_keeps_base_and_adds_music(lib, tmp_path):
    lib([entry("a")])
    ev = make_event()
    item = db.one("SELECT * FROM items WHERE event_id=?", ev["id"])
    segs = [{"type": "title", "item_id": 0, "text": "Week-end", "duration": 2.0},
            {"type": "photo", "item_id": item["id"], "text": "", "duration": 2.0}]
    out = tmp_path / "video.mp4"
    tracks = {"main": music.path(music.get_by_key("a")), "final": None, "credits": []}
    total = video.render(segs, {item["id"]: item}, out, tracks, 55)
    base = tmp_path / "video_base.mp4"
    assert base.is_file() and out.is_file()
    info, binfo = media.probe(out), media.probe(base)
    assert info["has_audio"] and info["has_video"]
    assert abs(info["duration"] - binfo["duration"]) <= 0.1
    assert abs(total - binfo["duration"]) <= 0.1


def test_final_track_crossfades_on_last_title(lib, tmp_path):
    lib([entry("a")])
    ev = make_event(photos=2)
    items = {it["id"]: it for it in db.q("SELECT * FROM items WHERE event_id=?", ev["id"])}
    a, b = list(items)
    segs = [{"type": "title", "item_id": 0, "text": "Début", "duration": 2.0},
            {"type": "photo", "item_id": a, "text": "", "duration": 2.0},
            {"type": "title", "item_id": 0, "text": "Fin", "duration": 2.0},
            {"type": "photo", "item_id": b, "text": "", "duration": 3.0}]
    out = tmp_path / "video.mp4"
    p = music.path(music.get_by_key("a"))
    video.render(segs, items, out, {"main": p, "final": p, "credits": []}, 100)
    meta = json.loads((tmp_path / "video_base.json").read_text(encoding="utf-8"))
    assert abs(meta["final_from"] - 4.0) <= 0.15
    info = media.probe(out)
    assert info["has_audio"] and abs(info["duration"] - media.probe(tmp_path / "video_base.mp4")["duration"]) <= 0.1


def test_credit_card_added_for_cc_by(lib, monkeypatch):
    lib([entry("carefree", credit=CREDIT)])
    ev = make_event()
    calls = spy_titles(monkeypatch)
    run_job(ev, parts=["video"])
    assert db.report(ev["id"])["video_ready"] == 1
    assert calls[-1].startswith("Musique") and "Kevin MacLeod" in calls[-1]
    assert "« Carefree »" in calls[-1] and "licence CC BY 4.0" in calls[-1]
    # le carton de crédit n'entre pas dans le plan de montage enregistré
    assert all("Kevin" not in s["text"] for s in json.loads(db.report(ev["id"])["montage"]))


def test_no_credit_card_without_credit(lib, monkeypatch):
    lib([entry("a")])
    ev = make_event()
    calls = spy_titles(monkeypatch)
    run_job(ev, parts=["video"])
    assert not any(c.startswith("Musique") for c in calls)


def test_no_track_renders_silent_music(lib):
    lib([])
    ev = make_event()
    run_job(ev, parts=["video"])
    rep = db.report(ev["id"])
    assert rep["video_ready"] == 1 and (draft(ev) / "video.mp4").is_file()
    assert stored_music(ev) == {"main_id": None, "final_id": None}


def test_uses_stored_pick_and_replaces_missing_one(lib):
    ids = lib([entry("a"), entry("b", src="b.mp3")])
    ev = make_event()
    db.update("reports", "event_id", ev["id"], music=json.dumps({"main_id": ids["b"], "final_id": None}))
    run_job(ev, parts=["video"])
    assert stored_music(ev)["main_id"] == ids["b"]
    # morceau supprimé depuis : pas de plantage, un autre est choisi
    db.update("reports", "event_id", ev["id"], music=json.dumps({"main_id": 999999, "final_id": 888888}))
    run_job(ev, parts=["video"])
    assert stored_music(ev)["main_id"] in ids.values()


def test_stored_pick_not_allowed_anymore_is_replaced(lib):
    ids = lib([entry("gai"), entry("triste", mood="melancolique", src="b.mp3")])
    ev = make_event(tone="drole,festif")
    db.update("reports", "event_id", ev["id"], music=json.dumps({"main_id": ids["triste"], "final_id": None}))
    run_job(ev, parts=["video"])
    assert stored_music(ev)["main_id"] == ids["gai"]


def test_touchante_stores_final_track(lib):
    ids = lib([entry("gai"), entry("doux", mood="calme", genres=("piano",), energy=1, src="c.mp3")])
    ev = make_event()
    db.update("reports", "event_id", ev["id"],
              video_settings=json.dumps({**settings.defaults("weekend"), "ending": "touchante"}))
    run_job(ev, parts=["video"])
    assert stored_music(ev) == {"main_id": ids["gai"], "final_id": ids["doux"]}
    assert (draft(ev) / "video.mp4").is_file()


def test_legacy_report_without_settings_generates(lib):
    """Données d'avant cette PR : ton et type anciens migrés, video_settings et music à NULL."""
    lib([entry("a")])
    ev = make_event(tone="detendu", typ="voyage")
    db.migrate_values()
    ev = db.one("SELECT * FROM events WHERE id=?", ev["id"])
    rep = db.report(ev["id"])
    assert rep["video_settings"] is None and rep["music"] is None
    run_job(ev, parts=["video"], video_duration=60)
    rep = db.report(ev["id"])
    assert rep["video_ready"] == 1 and (draft(ev) / "video.mp4").is_file()
    assert stored_music(ev)["main_id"] is not None


# ------------------------------------------------------------------ changer la musique

def test_remix_changes_track_only(lib):
    ids = lib([entry("a"), entry("b", src="b.mp3")])
    ev = make_event()
    db.update("reports", "event_id", ev["id"], music=json.dumps({"main_id": ids["a"], "final_id": None}))
    run_job(ev, parts=["video"])
    base = draft(ev) / "video_base.mp4"
    size, mtime = base.stat().st_size, base.stat().st_mtime_ns
    db.update("reports", "event_id", ev["id"], music=json.dumps({"main_id": ids["b"], "final_id": None}))
    generate.remix(db.one("SELECT * FROM events WHERE id=?", ev["id"]), noop)
    assert base.stat().st_size == size and base.stat().st_mtime_ns == mtime
    assert stored_music(ev)["main_id"] == ids["b"]
    out = media.probe(draft(ev) / "video.mp4")
    assert out["has_audio"] and abs(out["duration"] - media.probe(base)["duration"]) <= 0.1


def test_remix_job_uses_body_pick_without_ai(lib, monkeypatch):
    ids = lib([entry("a"), entry("b", src="b.mp3")])
    ev = make_event()
    run_job(ev, parts=["video"])

    def boom(*a, **k):
        raise AssertionError("pas d'appel IA pour changer la musique")

    monkeypatch.setattr(generate.ai, "plan_montage", boom)
    monkeypatch.setattr(generate.ai, "describe", boom)
    monkeypatch.setattr(generate.video, "_render_segment", boom)
    other = ids["b"] if stored_music(ev)["main_id"] == ids["a"] else ids["a"]
    r = client.post(f"/api/events/{ev['slug']}/generate", json={"parts": ["music"], "music": {"main_id": other}},
                    headers={"x-admin-token": ev["admin_token"]})
    assert r.status_code == 200, r.text
    generate.generate(db.one("SELECT * FROM jobs WHERE id=?", r.json()["job_id"]))
    assert stored_music(ev)["main_id"] == other


def test_remix_updates_credit_card(lib, monkeypatch):
    ids = lib([entry("a"), entry("carefree", credit=CREDIT, src="b.mp3")])
    ev = make_event()
    db.update("reports", "event_id", ev["id"], music=json.dumps({"main_id": ids["a"], "final_id": None}))
    run_job(ev, parts=["video"])
    before = media.probe(draft(ev) / "video_base.mp4")["duration"]
    calls = spy_titles(monkeypatch)
    db.update("reports", "event_id", ev["id"], music=json.dumps({"main_id": ids["carefree"], "final_id": None}))
    generate.remix(db.one("SELECT * FROM events WHERE id=?", ev["id"]), noop)
    assert calls and "Kevin MacLeod" in calls[-1]
    after = media.probe(draft(ev) / "video_base.mp4")["duration"]
    assert abs(after - before - 3.0) <= 0.2
    assert abs(media.probe(draft(ev) / "video.mp4")["duration"] - after) <= 0.1
    # retour à un morceau sans crédit : le carton disparaît
    db.update("reports", "event_id", ev["id"], music=json.dumps({"main_id": ids["a"], "final_id": None}))
    generate.remix(db.one("SELECT * FROM events WHERE id=?", ev["id"]), noop)
    assert abs(media.probe(draft(ev) / "video_base.mp4")["duration"] - before) <= 0.2


def test_remix_without_base_errors(lib):
    lib([entry("a")])
    ev = make_event()
    with pytest.raises(RuntimeError, match=re.escape(NO_BASE)):
        generate.remix(ev, noop)
    jid = db.enqueue(ev["id"], "generate", parts=["music"], ai=True)
    with pytest.raises(RuntimeError, match=re.escape(NO_BASE)):
        generate.generate(db.one("SELECT * FROM jobs WHERE id=?", jid))


# ------------------------------------------------------------------ versions

def test_versions_keep_base_and_music(lib):
    ids = lib([entry("a"), entry("b", src="b.mp3")])
    ev = make_event()
    db.update("reports", "event_id", ev["id"], music=json.dumps({"main_id": ids["a"], "final_id": None}),
              video_settings=json.dumps({**settings.defaults("weekend"), "mix": 80}))
    run_job(ev, parts=["video"])
    vid = db.report(ev["id"])["current_version"]
    v = db.one("SELECT * FROM versions WHERE id=?", vid)
    assert json.loads(v["music"])["main_id"] == ids["a"] and json.loads(v["video_settings"])["mix"] == 80
    assert (versions.vdir(ev["id"], vid) / "video_base.mp4").is_file()
    assert (versions.vdir(ev["id"], vid) / "video_base.json").is_file()
    db.update("reports", "event_id", ev["id"], music=None, video_settings=None)
    (draft(ev) / "video_base.mp4").unlink()
    assert versions.restore(ev["id"], vid)
    rep = db.report(ev["id"])
    assert json.loads(rep["music"])["main_id"] == ids["a"] and json.loads(rep["video_settings"])["mix"] == 80
    assert (draft(ev) / "video_base.mp4").is_file()


# ------------------------------------------------------------------ API

def _api_event():
    r = client.post("/api/events", json={"name": "Mariage", "start_date": "2026-06-01", "end_date": "2026-06-01",
                                         "type": "mariage", "tone": ["tendre", "cinema"]}, headers=ADMIN)
    slug, tok = r.json()["slug"], r.json()["admin_token"]
    return slug, {"x-admin-token": tok}


def test_draft_returns_default_settings_and_no_music():
    slug, adm = _api_event()
    d = client.get(f"/api/events/{slug}/draft", headers=adm).json()
    assert d["video_settings"] == settings.normalize(None, "mariage")
    assert d["music"] == {"main": None, "final": None}


def test_generate_stores_settings_and_music(lib):
    ids = lib([entry("a"), entry("doux", mood="calme", genres=("piano",), energy=1, src="c.mp3")])
    slug, adm = _api_event()
    body = {"parts": ["video"], "video_settings": {"duration": 60, "mix": 80, "genres": ["rock", "zzz"]},
            "music": {"main_id": ids["a"], "final_id": ids["doux"]}}
    r = client.post(f"/api/events/{slug}/generate", json=body, headers=adm)
    assert r.status_code == 200, r.text
    eid = db.one("SELECT id FROM events WHERE slug=?", slug)["id"]
    rep = db.report(eid)
    vs = json.loads(rep["video_settings"])
    assert vs == settings.normalize(body["video_settings"], "mariage") and vs["genres"] == ["rock"]
    assert rep["video_duration"] == 60
    assert json.loads(rep["music"]) == {"main_id": ids["a"], "final_id": ids["doux"]}
    job = db.one("SELECT * FROM jobs WHERE id=?", r.json()["job_id"])
    assert json.loads(job["params"])["video_duration"] == 60
    d = client.get(f"/api/events/{slug}/draft", headers=adm).json()
    assert d["video_settings"] == vs
    assert d["music"]["main"]["id"] == ids["a"] and d["music"]["final"]["id"] == ids["doux"]
    db.run("UPDATE jobs SET status='done' WHERE event_id=?", eid)


def test_generate_accepts_legacy_video_duration():
    slug, adm = _api_event()
    r = client.post(f"/api/events/{slug}/generate", json={"parts": ["video"], "video_duration": 90}, headers=adm)
    assert r.status_code == 200
    job = db.one("SELECT * FROM jobs WHERE id=?", r.json()["job_id"])
    assert json.loads(job["params"])["video_duration"] == 90
    db.run("UPDATE jobs SET status='done' WHERE id=?", job["id"])


@pytest.mark.parametrize("body", [{"parts": ["video", "zzz"]}, {"parts": "video"},
                                  {"parts": ["music"], "music": {"main_id": "x"}},
                                  {"parts": ["video"], "video_settings": "rapide"}])
def test_generate_rejects_bad_body(body):
    slug, adm = _api_event()
    r = client.post(f"/api/events/{slug}/generate", json=body, headers=adm)
    assert r.status_code == 400
    assert r.json()["detail"]


def test_music_credits_on_published_and_versions(lib):
    lib([entry("carefree", credit=CREDIT)])
    ev = make_event()
    adm = {"x-admin-token": ev["admin_token"]}
    run_job(ev, parts=["video"])
    vid = db.report(ev["id"])["current_version"]
    assert client.get(f"/api/events/{ev['slug']}/versions/{vid}", headers=adm).json()["music_credits"] == [CREDIT]
    assert client.post(f"/api/events/{ev['slug']}/publish", headers=adm).status_code == 200
    pub = client.get(f"/api/events/{ev['slug']}/published").json()
    assert pub["has_video"] and pub["music_credits"] == [CREDIT]
    # publication d'avant la copie de video_base.json : crédits de la version publiée
    (generate.out_dir(ev["id"], "published") / video.META).unlink()
    assert client.get(f"/api/events/{ev['slug']}/published").json()["music_credits"] == [CREDIT]
    client.post(f"/api/events/{ev['slug']}/versions/{vid}/share", json={"shared": True}, headers=adm)
    shared = client.get(f"/api/events/{ev['slug']}/published/versions/{vid}").json()
    assert shared["music_credits"] == [CREDIT]


def test_music_credits_empty_without_credit(lib):
    lib([entry("a")])
    ev = make_event()
    adm = {"x-admin-token": ev["admin_token"]}
    run_job(ev, parts=["video"])
    assert client.post(f"/api/events/{ev['slug']}/publish", headers=adm).status_code == 200
    assert client.get(f"/api/events/{ev['slug']}/published").json()["music_credits"] == []
