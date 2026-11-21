from app.pipeline import ai, settings

EV = {"name": "WK Annecy", "type": "weekend", "tone": "drole,festif",
      "start_date": "2026-06-01", "end_date": "2026-06-03", "tz": "Europe/Paris"}


def test_tone_guide_two_tones():
    g = ai.tone_guide(["drole", "tendre"])
    assert ai.TONE_GUIDE["drole"] in g and ai.TONE_GUIDE["tendre"] in g
    assert g.index(ai.TONE_GUIDE["drole"]) < g.index(ai.TONE_GUIDE["tendre"])
    assert "Le premier ton domine" in g


def test_tone_guide_single_has_no_dominance_sentence():
    assert "Le premier ton domine" not in ai.tone_guide(["chill"])


def test_montage_prompt_filled():
    s = settings.normalize({"ending": "betisier"}, "weekend")
    p = ai.montage_prompt(EV, s, 60)
    assert "Les retrouvailles" in p and "Bêtisier" in p and "60 secondes" in p
    assert "WK Annecy" in p and "Drôle + Festif" in p
    assert "{{" not in p and "}}" not in p


def test_montage_prompt_subtitles_off():
    s = settings.normalize({"subtitles": False}, "weekend")
    p = ai.montage_prompt(EV, s, 60)
    assert "Sous-titres : non" in p
    assert "`text` reste une chaîne vide sur les segments `photo` et `video`" in p


def test_context_falls_back_on_corrupt_tone():
    ev = dict(EV, tone="n'importe quoi")
    assert ai.tone_guide(["chill"]) in ai._context(ev)


def test_prompt_mentions_rhythm_and_effects():
    s = settings.normalize({"rhythm": "nerveux", "effects": {"slowmo": True, "speedup": False, "freeze": False, "humor": False}}, "weekend")
    p = ai.montage_prompt(EV, s, 60)
    assert "0,5 à 1,5 s" in p and "slowmo" in p
    assert "speedup" not in p and "freeze" not in p and "punch" not in p
    assert "1,5 à 3 s, coupes" not in p and "3 à 5 s" not in p


def test_prompt_effects_all_on_and_all_off():
    on = settings.normalize({"effects": {"slowmo": True, "speedup": True, "freeze": True, "humor": True}}, "weekend")
    p = ai.montage_prompt(EV, on, 60)
    assert all(v in p for v in ("slowmo", "speedup", "freeze", "punch"))
    off = settings.normalize({"effects": {"slowmo": False, "speedup": False, "freeze": False, "humor": False}}, "weekend")
    p = ai.montage_prompt(EV, off, 60)
    assert not any(v in p for v in ("slowmo", "speedup", "freeze", "punch"))
    assert "`effect` vaut toujours `none`" in p


def test_prompt_aucun_titles():
    s = settings.normalize({"title_style": "aucun"}, "weekend")
    assert "aucun segment `title`" in ai.montage_prompt(EV, s, 60)
    s = settings.normalize({"title_style": "pop"}, "weekend")
    assert "aucun segment `title`" not in ai.montage_prompt(EV, s, 60)


def test_prompt_vertical():
    s = settings.normalize({"framing": "9:16"}, "weekend")
    assert "médias en portrait et les plans serrés" in ai.montage_prompt(EV, s, 60)
    s = settings.normalize({"framing": "16:9"}, "weekend")
    assert "médias en portrait" not in ai.montage_prompt(EV, s, 60)


def test_prompt_no_placeholder_left_for_any_combination():
    for framing in ("16:9", "9:16", "1:1"):
        for style in ("carnet", "sobre", "pop", "aucun"):
            for rhythm in ("pose", "dynamique", "nerveux"):
                s = settings.normalize({"framing": framing, "title_style": style, "rhythm": rhythm}, "weekend")
                p = ai.montage_prompt(EV, s, 60)
                assert "{{" not in p and "}}" not in p


def test_prompt_user_placeholder_not_substituted():
    s = settings.normalize({}, "weekend")
    p = ai.montage_prompt(dict(EV, name="Fête {{duree}}"), s, 60)
    assert "Fête {{duree}}" in p
