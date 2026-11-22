import pytest

from app import config
from app.pipeline import settings


def test_parse_tones_accepts_csv_list_and_legacy():
    assert settings.parse_tones("drole,festif") == ["drole", "festif"]
    assert settings.parse_tones(["tendre"]) == ["tendre"]
    assert settings.parse_tones("detendu") == ["chill", "drole"]


@pytest.mark.parametrize("bad", ["", ["drole", "festif", "epique"], "inconnu"])
def test_parse_tones_rejects(bad):
    with pytest.raises(ValueError):
        settings.parse_tones(bad)


def test_parse_tones_too_many_message():
    with pytest.raises(ValueError, match="2 tons"):
        settings.parse_tones("drole,festif,epique")


def test_tones_label():
    assert settings.tones_label("drole,festif") == "Drôle + Festif"
    assert settings.tones_label("emotion") == "Tendre + Nostalgique"


def test_defaults_weekend():
    d = settings.defaults("weekend")
    assert d["tones"] == ["drole", "festif"]
    assert d["genres"] == ["pop", "electro", "funk"]
    assert d["energy"] == 4
    assert d["ending"] == "festive"
    assert d["evolution"] == "montee"
    assert d["rhythm"] == "dynamique"


def test_defaults_legacy_and_unknown_type():
    assert settings.defaults("voyage")["ending"] == "festive"
    assert settings.defaults("fete")["ending"] == "touchante"
    assert settings.defaults("zzz") == config.TYPE_DEFAULTS["autre"]


def test_type_defaults_cover_every_type():
    assert set(config.TYPE_DEFAULTS) == set(config.EVENT_TYPES)
    for d in config.TYPE_DEFAULTS.values():
        assert all(t in config.TONES for t in d["tones"])
        assert all(g in config.GENRES for g in d["genres"])
        assert d["ending"] in config.ENDINGS


def test_normalize_fills_and_clamps():
    n = settings.normalize(
        {"energy": 9, "mix": -5, "duration": 45, "genres": ["pop", "zzz"]}, "course"
    )
    assert n["energy"] == 5
    assert n["mix"] == 0
    assert n["duration"] == 120
    assert n["genres"] == ["pop"]
    assert n["ending"] == "epique"
    assert n["subtitles"] is True


def test_normalize_empty_and_invalid():
    n = settings.normalize(None, "weekend")
    assert n == {"ending": "festive", "genres": ["pop", "electro", "funk"],
                 "energy": 4, "mix": 55, "duration": 120, "subtitles": True}
    n = settings.normalize({"ending": "x", "genres": ["zzz"], "subtitles": False}, "mariage")
    assert n["ending"] == "touchante"
    assert n["genres"] == ["piano", "folk", "orchestral"]
    assert n["subtitles"] is False
