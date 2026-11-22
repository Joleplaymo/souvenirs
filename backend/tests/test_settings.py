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
                 "energy": 4, "mix": 55, "duration": 120, "subtitles": True,
                 "rhythm": "dynamique", "evolution": "montee",
                 "effects": {"slowmo": True, "speedup": True, "freeze": True, "humor": True},
                 "title_style": "carnet", "framing": "16:9"}
    n = settings.normalize({"ending": "x", "genres": ["zzz"], "subtitles": False}, "mariage")
    assert n["ending"] == "touchante"
    assert n["genres"] == ["piano", "folk", "orchestral"]
    assert n["subtitles"] is False


def test_normalize_new_defaults_weekend():
    n = settings.normalize({}, "weekend")
    assert n["rhythm"] == "dynamique"
    assert n["evolution"] == "montee"
    assert n["effects"] == {"slowmo": True, "speedup": True, "freeze": True, "humor": True}
    assert n["title_style"] == "carnet"
    assert n["framing"] == "16:9"


def test_normalize_mariage_humor_off():
    n = settings.normalize({}, "mariage")
    assert n["rhythm"] == "pose"
    assert n["effects"]["humor"] is False
    assert n["effects"]["slowmo"] is True


def test_normalize_rejects_unknown_values():
    n = settings.normalize({"rhythm": "x", "framing": "4:3", "title_style": 3,
                            "evolution": "zzz",
                            "effects": {"slowmo": "non", "humor": 1, "inconnu": True}},
                           "weekend")
    assert n["rhythm"] == "dynamique"
    assert n["framing"] == "16:9"
    assert n["title_style"] == "carnet"
    assert n["evolution"] == "montee"
    assert n["effects"] == {"slowmo": True, "speedup": True, "freeze": True, "humor": True}
    n = settings.normalize({"effects": "pas un dict"}, "mariage")
    assert n["effects"]["humor"] is False


def test_normalize_accepts_valid_new_values():
    n = settings.normalize({"rhythm": "nerveux", "evolution": "constante", "title_style": "aucun",
                            "framing": "9:16", "effects": {"slowmo": False, "humor": False}},
                           "weekend")
    assert (n["rhythm"], n["evolution"], n["title_style"], n["framing"]) == (
        "nerveux", "constante", "aucun", "9:16")
    assert n["effects"] == {"slowmo": False, "speedup": True, "freeze": True, "humor": False}


def test_normalize_old_settings_still_valid():
    old = {"ending": "epique", "genres": ["rock"], "energy": 2, "mix": 10,
           "duration": 60, "subtitles": False}
    n = settings.normalize(old, "weekend")
    for k, v in old.items():
        assert n[k] == v
    assert n["rhythm"] == "dynamique" and n["framing"] == "16:9"


def test_config_lists_exposed():
    assert set(config.RHYTHMS) == {"pose", "dynamique", "nerveux"}
    assert set(config.EFFECTS) == {"slowmo", "speedup", "freeze", "humor"}
    assert set(config.TITLE_STYLES) == {"carnet", "sobre", "pop", "aucun"}
    assert set(config.FRAMINGS) == {"16:9", "9:16", "1:1"}
    assert set(config.EVOLUTIONS) == {"constante", "montee", "calme_explosion", "festif_emotion"}
    for d in config.TYPE_DEFAULTS.values():
        assert d["rhythm"] in config.RHYTHMS and d["evolution"] in config.EVOLUTIONS


def test_normalize_survives_wrong_types():
    """Listes, objets ou nombres infinis à la place des valeurs attendues : valeurs par défaut, jamais d'erreur."""
    d = settings.normalize(None, "weekend")
    n = settings.normalize({"ending": ["festive"], "genres": [["pop"], {"a": 1}, "funk"], "energy": float("inf"),
                            "mix": float("-inf"), "duration": float("nan")}, "weekend")
    assert n["ending"] == d["ending"] and n["genres"] == ["funk"]
    assert (n["energy"], n["mix"], n["duration"]) == (d["energy"], d["mix"], d["duration"])
    n = settings.normalize({"ending": {"x": 1}, "genres": {"pop": True}}, "weekend")
    assert n["ending"] == d["ending"] and n["genres"] == d["genres"]
