from app import db


def _event(**kw):
    vals = dict(slug="s-" + kw.get("name", "x"), admin_token="t", name="x", start_date="2026-01-01",
                end_date="2026-01-02", type="voyage", tone="detendu", tz="Europe/Paris", created_at=db.now())
    vals.update(kw)
    return db.insert("events", **vals)


def test_migrate_values():
    db.init()
    eid = _event(name="mig")
    vid = db.insert("versions", event_id=eid, label="v", tone="emotion", type="voyage", created_at=db.now())
    db.migrate_values()
    ev = db.one("SELECT * FROM events WHERE id=?", eid)
    assert (ev["type"], ev["tone"]) == ("roadtrip", "chill,drole")
    v = db.one("SELECT * FROM versions WHERE id=?", vid)
    assert (v["tone"], v["type"]) == ("tendre,nostalgique", "roadtrip")
    db.migrate_values()
    assert dict(db.one("SELECT * FROM events WHERE id=?", eid)) == dict(ev)
    assert dict(db.one("SELECT * FROM versions WHERE id=?", vid)) == dict(v)


def test_new_columns_exist():
    db.init()
    for table in ("reports", "versions"):
        cols = {r["name"] for r in db.q(f"PRAGMA table_info({table})")}
        assert {"video_settings", "music"} <= cols
