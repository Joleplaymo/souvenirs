import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.pipeline import versions as versions_mod

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
    assert {"endings", "genres", "durations", "types", "tones", "moods"} <= set(c)
    assert c["moods"]["melancolique"] == "Mélancolique" and len(c["moods"]) == 7


@pytest.mark.parametrize("tone", ["inconnu", [], None, ""])
def test_create_event_rejects_bad_tones(tone):
    r = client.post("/api/events", json=_body(tone=tone), headers=ADMIN)
    assert r.status_code == 400
    assert "ton" in r.json()["detail"].lower()


def _legacy_event(tone, typ, slug):
    """Insère directement une ligne à l'ancien format, sans passer par la migration."""
    eid = db.insert("events", slug=slug, admin_token="adm-" + slug, name="Ancien", start_date="2026-01-01",
                    end_date="2026-01-02", type=typ, tone=tone, tz="Europe/Paris", created_at=db.now(),
                    published_at=db.now())
    return eid, slug, {"x-admin-token": "adm-" + slug}


def test_legacy_rows_display_without_migration():
    eid, slug, adm = _legacy_event("sportif", "voyage", "legacy-a")
    ev = client.get(f"/api/events/{slug}")
    assert ev.status_code == 200 and ev.json()["tone_label"] == "Motivant + Documentaire"
    vid = db.insert("versions", event_id=eid, label="v", tone="emotion", type="fete", created_at=db.now(),
                    shared=1, text_md="x")
    r = client.get(f"/api/events/{slug}/versions", headers=adm)
    assert r.status_code == 200 and r.json()["versions"][0]["tone_label"] == "Tendre + Nostalgique"
    assert client.get(f"/api/events/{slug}/versions/{vid}", headers=adm).status_code == 200
    db.report(eid)
    db.update("reports", "event_id", eid, published_from=vid)
    pub = client.get(f"/api/events/{slug}/published")
    assert pub.status_code == 200
    assert pub.json()["versions"][0]["tone_label"] == "Tendre + Nostalgique"
    one = client.get(f"/api/events/{slug}/published/versions/{vid}")
    assert one.status_code == 200 and one.json()["tone_label"] == "Tendre + Nostalgique"


def test_corrupt_tone_falls_back_and_logs(caplog):
    _, slug, _ = _legacy_event("zzz", "mariage", "legacy-b")
    with caplog.at_level("WARNING", logger="souvenirs"):
        ev = client.get(f"/api/events/{slug}")
    assert ev.status_code == 200
    assert ev.json()["tones"] == ["tendre", "cinema"]
    assert any("Ton invalide" in m for m in caplog.messages)


def test_snapshot_labels_legacy_tone():
    eid, _, _ = _legacy_event("detendu", "voyage", "legacy-c")
    db.report(eid)
    db.update("reports", "event_id", eid, text_md="Du texte")
    vid = versions_mod.snapshot(eid)
    assert db.one("SELECT label FROM versions WHERE id=?", vid)["label"] == "Chill + Drôle"
