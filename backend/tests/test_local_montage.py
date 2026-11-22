from app.pipeline import ai, settings

EV = {"name": "WK Annecy", "type": "weekend", "tone": "drole",
      "start_date": "2026-06-01", "end_date": "2026-06-03", "tz": "Europe/Paris"}


def _media():
    items = []
    for i in range(1, 13):
        if i % 2:
            items.append({"id": i, "kind": "video", "captured_at": f"2026-06-01T10:{i:02d}:00+00:00",
                          "duration": 20, "transcript": "[]"})
        else:
            items.append({"id": i, "kind": "photo", "captured_at": f"2026-06-01T10:{i:02d}:00+00:00",
                          "duration": None, "transcript": None})
    return items


def _plan(effects, rhythm="dynamique"):
    s = settings.normalize({"rhythm": rhythm, "effects": effects}, "weekend")
    return ai._local_montage(EV, _media(), 60, s)["segments"]


ALL = {"slowmo": True, "speedup": True, "freeze": True, "humor": True}
NONE = {"slowmo": False, "speedup": False, "freeze": False, "humor": False}


def test_local_effects_all_on():
    segs = _plan(ALL)
    assert all("effect" in s for s in segs)
    assert any(s["type"] == "video" and s["effect"] in ("slowmo", "speedup", "freeze") for s in segs)
    assert any(s["effect"] == "punch" for s in segs)
    assert all(s["effect"] == "none" for s in segs if s["type"] == "title")


def test_local_effects_all_off():
    assert all(s["effect"] == "none" for s in _plan(NONE))


def test_local_photo_duration_follows_rhythm():
    photos = lambda r: {s["duration"] for s in _plan(NONE, r) if s["type"] == "photo"}
    assert photos("pose") == {4} and photos("nerveux") == {1}


def test_local_without_settings_still_has_effect_key():
    segs = ai._local_montage(EV, _media(), 60)["segments"]
    assert all(s["effect"] == "none" for s in segs)


def test_segments_prompt_defers_to_rhythm():
    p = ai._segments_prompt(60)
    assert "3 à 12 s" not in p and "2,5 à 4 s" not in p
    assert "`effect`" in p and "rythme" in p
