from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
ADMIN = {"x-admin-code": "test"}


def _body(**kw):
    b = {"name": "Week-end", "start_date": "2026-05-01", "end_date": "2026-05-03", "type": "weekend",
         "tone": ["drole", "festif"]}
    b.update(kw)
    return b


def test_create_event_with_two_tones():
    r = client.post("/api/events", json=_body(), headers=ADMIN)
    assert r.status_code == 200
    ev = client.get(f"/api/events/{r.json()['slug']}").json()
    assert ev["tones"] == ["drole", "festif"]
    assert ev["tone"] == "drole,festif"
    assert ev["tone_label"] == "Drôle + Festif"


def test_create_event_rejects_three_tones():
    r = client.post("/api/events", json=_body(tone=["drole", "festif", "epique"]), headers=ADMIN)
    assert r.status_code == 400
    assert "2 tons" in r.json()["detail"]


def test_create_event_accepts_legacy_type_and_tone():
    r = client.post("/api/events", json=_body(type="voyage", tone="detendu"), headers=ADMIN)
    assert r.status_code == 200
    ev = client.get(f"/api/events/{r.json()['slug']}").json()
    assert ev["type"] == "roadtrip" and ev["tones"] == ["chill", "drole"]


def test_config_exposes_defaults():
    c = client.get("/api/config").json()
    assert c["defaults"]["mariage"]["ending"] == "touchante"
    assert {"endings", "genres", "durations", "types", "tones"} <= set(c)
