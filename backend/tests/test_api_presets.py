from fastapi.testclient import TestClient

from app import db
from app.main import app

client = TestClient(app)
ADMIN = {"x-admin-code": "test"}


def _event(typ="weekend"):
    r = client.post("/api/events", json={"name": "Week-end", "start_date": "2026-05-01", "end_date": "2026-05-03",
                                         "type": typ, "tone": ["drole"]}, headers=ADMIN)
    d = r.json()
    return d["slug"], {"x-admin-token": d["admin_token"]}


def _clean():
    db.run("DELETE FROM presets")


def test_preset_roundtrip_across_events():
    _clean()
    a, ha = _event()
    b, hb = _event("mariage")
    body = {"name": "Mon style", "tones": ["drole", "festif"],
            "video_settings": {"energy": 4, "duration": 60, "music": {"main_id": 3}, "instructions": "x"}}
    r = client.post(f"/api/events/{a}/presets", json=body, headers=ha)
    assert r.status_code == 200, r.text
    lst = client.get(f"/api/events/{b}/presets", headers=hb).json()
    assert len(lst) == 1
    p = lst[0]
    assert p["name"] == "Mon style" and p["tones"] == ["drole", "festif"] and p["created_at"]
    assert p["video_settings"]["energy"] == 4 and p["video_settings"]["duration"] == 60
    assert "music" not in p["video_settings"] and "instructions" not in p["video_settings"]
    assert "framing" in p["video_settings"]
    d = client.delete(f"/api/events/{b}/presets/{p['id']}", headers=hb)
    assert d.status_code == 200
    assert client.get(f"/api/events/{a}/presets", headers=ha).json() == []


def test_preset_same_name_replaces():
    _clean()
    a, ha = _event()
    client.post(f"/api/events/{a}/presets", json={"name": " Style ", "tones": ["drole"], "video_settings": {"energy": 1}}, headers=ha)
    client.post(f"/api/events/{a}/presets", json={"name": "Style", "tones": ["epique"], "video_settings": {"energy": 5}}, headers=ha)
    lst = client.get(f"/api/events/{a}/presets", headers=ha).json()
    assert len(lst) == 1 and lst[0]["tones"] == ["epique"] and lst[0]["video_settings"]["energy"] == 5


def test_preset_requires_admin_token():
    _clean()
    a, ha = _event()
    body = {"name": "X", "tones": ["drole"], "video_settings": {}}
    assert client.get(f"/api/events/{a}/presets").status_code == 403
    assert client.post(f"/api/events/{a}/presets", json=body).status_code == 403
    assert client.delete(f"/api/events/{a}/presets/1", headers={"x-admin-token": "nope"}).status_code == 403
    assert client.get(f"/api/events/{a}/presets", headers=ha).status_code == 200


def test_preset_invalid_tones_400():
    _clean()
    a, ha = _event()
    for tones in (["inconnu"], [], ["drole", "festif", "epique"]):
        r = client.post(f"/api/events/{a}/presets", json={"name": "X", "tones": tones, "video_settings": {}}, headers=ha)
        assert r.status_code == 400
    assert client.get(f"/api/events/{a}/presets", headers=ha).json() == []


def test_preset_invalid_name_or_settings_400():
    _clean()
    a, ha = _event()
    for name in ("", "   ", "x" * 61, None, 5):
        r = client.post(f"/api/events/{a}/presets", json={"name": name, "tones": ["drole"], "video_settings": {}}, headers=ha)
        assert r.status_code == 400, name
    r = client.post(f"/api/events/{a}/presets", json={"name": "X", "tones": ["drole"], "video_settings": 3}, headers=ha)
    assert r.status_code == 400
    r = client.post(f"/api/events/{a}/presets", json={"name": "x" * 60, "tones": ["drole"], "video_settings": {}}, headers=ha)
    assert r.status_code == 200
