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
