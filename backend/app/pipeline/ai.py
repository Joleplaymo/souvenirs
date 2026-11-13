"""Appels à l'API Claude : description des images, récit, plan d'album, plan de montage.

Sans clé ANTHROPIC_API_KEY, un mode local très simple (sans IA) prend le relais pour
permettre de tester la chaîne complète ; le résultat est alors signalé comme tel.
"""
import base64
import io
import json

from PIL import Image

from .. import config
from . import timeline

FALLBACK_BETA = "server-side-fallback-2026-07-01"

TONE_GUIDE = {
    "detendu": "Ton de souvenir détendu : chaleureux, complice, tutoiement du groupe (« on »), humour léger.",
    "sportif": "Ton de bilan sportif : précis, factuel et enthousiaste ; mets en avant l'effort, les temps, "
               "les distances, les sensations et les enseignements.",
    "humour": "Ton humoristique : taquin et plein d'autodérision, sans jamais être blessant envers quelqu'un.",
    "emotion": "Ton émouvant et nostalgique : sensible, attentif aux petits moments et aux liens entre les gens.",
}

SYSTEM = (
    "Tu es l'auteur des carnets de souvenirs d'un groupe d'amis. Tu écris en français, à partir de ce que le "
    "groupe a réellement enregistré pendant un événement (dictées, conversations, vidéos, photos, notes). "
    "Tu restes fidèle aux faits : tu n'inventes ni lieu, ni personne, ni anecdote, ni citation. Les "
    "transcriptions viennent d'une reconnaissance vocale automatique : corrige en silence les erreurs "
    "évidentes, et ignore les passages incompréhensibles plutôt que de les deviner. Les conversations ne "
    "distinguent pas les voix : n'attribue une phrase à une personne que si le contexte le rend certain."
)


def enabled() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=4)


def _call(content, schema=None, effort="high", max_tokens=32000):
    kwargs = dict(
        model=config.CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
    )
    if schema:
        kwargs["output_config"]["format"] = {"type": "json_schema", "schema": schema}
    m = config.CLAUDE_MODEL
    if m.startswith(("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5")):
        # En cas de refus d'un filtre de sécurité, l'API relance la requête sur un modèle de repli.
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"
    import anthropic

    try:
        with _client().beta.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()
    except anthropic.BadRequestError:
        if "fallbacks" not in kwargs:
            raise
        # le repli automatique n'est pas disponible partout : on réessaie sans lui
        kwargs.pop("fallbacks")
        kwargs.pop("betas")
        with _client().beta.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude a refusé de traiter cette demande.")
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if msg.stop_reason == "max_tokens" and schema:
        raise RuntimeError("Réponse de Claude tronquée (trop d'éléments d'un coup).")
    if not text:
        raise RuntimeError("Réponse vide de Claude.")
    return json.loads(text) if schema else text


def _image_block(path, max_px=768):
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def _obj(props, required=None):
    return {"type": "object", "properties": props, "required": required or list(props),
            "additionalProperties": False}


def _context(ev) -> str:
    return (
        f"Événement : « {ev['name']} » ({config.EVENT_TYPES.get(ev['type'], ev['type'])}), "
        f"du {ev['start_date']} au {ev['end_date']}.\n{TONE_GUIDE.get(ev['tone'], TONE_GUIDE['detendu'])}"
    )


# ---------------------------------------------------------------- images

DESCRIBE_SCHEMA = _obj({"items": {"type": "array", "items": _obj({
    "id": {"type": "integer"}, "description": {"type": "string"}, "score": {"type": "integer"}})}})


def describe(ev, batch) -> dict:
    """batch : liste de (item, [chemins d'images]). Retourne {id: {description, score}}."""
    if not enabled():
        return {it["id"]: {"description": "", "score": 5} for it, _ in batch}
    content = [{"type": "text", "text": (
        _context(ev) + "\n\nVoici des photos et des images extraites de vidéos. Pour chaque élément, donne "
        "une description factuelle d'une ou deux phrases (qui, quoi, où, ambiance) et une note de 1 à 10 "
        "sur son intérêt comme souvenir (netteté, émotion, moment clé ; note bas les images floues, "
        "ratées ou en double).")}]
    for it, paths in batch:
        content.append({"type": "text", "text": (
            f"Élément #{it['id']} — {timeline.LABELS[it['kind']]} de {it['author']}, "
            f"{timeline.fr_stamp(it['captured_at'], ev['tz'])} :")})
        content += [_image_block(p) for p in paths]
    res = _call(content, DESCRIBE_SCHEMA, effort="low", max_tokens=16000)
    known = {it["id"] for it, _ in batch}
    return {r["id"]: {"description": r["description"], "score": max(1, min(10, r["score"]))}
            for r in res["items"] if r["id"] in known}


# ---------------------------------------------------------------- récit

def write_report(ev, items) -> str:
    if not enabled():
        return _local_report(ev, items)
    prompt = (
        _context(ev) + "\n\nVoici, dans l'ordre chronologique, tout ce que le groupe a enregistré :\n\n"
        + timeline.render(ev, items, with_segments=False)
        + "\n\nRédige le compte rendu de l'événement en Markdown :\n"
        "- un titre (#) et un court chapô qui donne envie ;\n"
        "- le déroulé chronologique, découpé en sections (##) par moment (ex. « Samedi matin — départ ») ;\n"
        "- des citations exactes tirées des dictées et des conversations, entre guillemets français « », "
        "placées dans le récit (en bloc de citation Markdown quand elles méritent d'être mises en valeur) ;\n"
        "- une section « Moments forts » (liste courte) et une section « Anecdotes » s'il y en a.\n"
        "Proportionne la longueur à la matière : n'étire pas un événement peu documenté. N'écris que le "
        "compte rendu, sans commentaire avant ou après, et sans mentionner les numéros d'éléments (#)."
    )
    return _call([{"type": "text", "text": prompt}], effort="high", max_tokens=32000)


def _local_report(ev, items) -> str:
    out = [f"# {ev['name']}", "",
           "*Compte rendu assemblé automatiquement sans IA (aucune clé API Claude configurée).*", ""]
    current = None
    for it in items:
        d = timeline.local_dt(it["captured_at"], ev["tz"])
        key = f"{timeline.fr_day(d).capitalize()} — {timeline.day_part(d)}"
        if key != current:
            out += ["", f"## {key}", ""]
            current = key
        text = it["text"] if it["kind"] == "note" else " ".join(s["t"] for s in (json.loads(it["transcript"] or "[]")))
        if text:
            out.append(f"**{d:%H:%M} — {it['author']}** : « {text.strip()} »\n")
        elif it["kind"] in ("photo", "video"):
            out.append(f"*{d:%H:%M} — {timeline.LABELS[it['kind']]} de {it['author']}*\n")
    return "\n".join(out)


# ---------------------------------------------------------------- album

ALBUM_SCHEMA = _obj({
    "title": {"type": "string"}, "subtitle": {"type": "string"}, "cover_photo": {"type": "integer"},
    "pages": {"type": "array", "items": _obj({
        "layout": {"type": "string", "enum": ["full", "duo", "trio", "text", "quote"]},
        "photos": {"type": "array", "items": {"type": "integer"}},
        "heading": {"type": "string"}, "text": {"type": "string"}, "caption": {"type": "string"}})}})


def page_range(n_photos: int) -> tuple[int, int]:
    hi = max(4, min(40, n_photos + 6))
    return min(20, hi), hi


def plan_album(ev, report_md, photos) -> dict:
    if not photos:
        return {"title": ev["name"], "subtitle": "", "cover_photo": 0, "pages": []}
    if not enabled():
        return _local_album(ev, photos)
    lo, hi = page_range(len(photos))
    prompt = (
        _context(ev) + "\n\nCompte rendu de l'événement :\n\n" + report_md
        + "\n\nPhotos disponibles (ordre chronologique) :\n\n" + timeline.render(ev, photos)
        + f"\n\nCompose un album photo imprimé au format A4 paysage, de {lo} à {hi} pages intérieures "
        "(la couverture et la page de fin sont ajoutées automatiquement). Choisis `cover_photo` : la "
        "meilleure photo en paysage. Chaque page a une mise en page :\n"
        "- `full` : 1 photo pleine page (les plus belles, de préférence en paysage) ; `caption` = légende courte ;\n"
        "- `duo` : 2 photos côte à côte (idéal pour les portraits) ; `caption` commune ;\n"
        "- `trio` : 3 photos (une grande, deux petites) ; `caption` commune ;\n"
        "- `text` : page de texte, `heading` = titre de séquence, `text` = extrait du compte rendu "
        "(600 caractères au plus), `photos` vide ;\n"
        "- `quote` : une citation marquante dans `text`, son auteur dans `caption` s'il est certain, `photos` vide.\n"
        "Suis la chronologie, ouvre chaque grande séquence par une page `text`, alterne les mises en page, "
        "écarte les photos mal notées ou redondantes, et n'utilise chaque photo qu'une fois. Les champs "
        "inutilisés d'une page restent vides. Identifie les photos par leur numéro (#)."
    )
    return _call([{"type": "text", "text": prompt}], ALBUM_SCHEMA, effort="medium", max_tokens=32000)


def _local_album(ev, photos) -> dict:
    land = [p for p in photos if (p["width"] or 1) >= (p["height"] or 1)]
    cover = (land or photos)[0]["id"]
    pages = []
    for p in photos:
        d = timeline.local_dt(p["captured_at"], ev["tz"])
        pages.append({"layout": "full", "photos": [p["id"]], "heading": "", "text": "",
                      "caption": f"{p['author']} — {timeline.fr_day(d)}, {d:%H:%M}"})
    return {"title": ev["name"], "subtitle": "", "cover_photo": cover,
            "pages": pages}


# ---------------------------------------------------------------- montage

MONTAGE_SCHEMA = _obj({"segments": {"type": "array", "items": _obj({
    "type": {"type": "string", "enum": ["title", "photo", "video"]},
    "item_id": {"type": "integer"}, "text": {"type": "string"},
    "start": {"type": "number"}, "end": {"type": "number"}, "duration": {"type": "number"}})}})


def plan_montage(ev, report_md, media, target: int) -> dict:
    if not enabled():
        return _local_montage(ev, media, target)
    prompt = (
        _context(ev) + "\n\nCompte rendu de l'événement :\n\n" + report_md
        + "\n\nVidéos et photos disponibles, avec les paroles horodatées (en secondes) et, pour mémoire, "
        "les dictées et conversations dont tu peux tirer des citations :\n\n" + timeline.render(ev, media)
        + f"\n\nÉtablis le plan de montage d'un film souvenir d'environ {target} secondes au total "
        "(tolérance ±10 %). Le plan est une suite de segments :\n"
        "- `title` : carton de titre de séquence, court (ex. « Samedi matin — départ »), dans `text` ; "
        "`duration` 2 à 3 s ; `item_id` = 0. Commence par un carton portant le nom de l'événement.\n"
        "- `video` : extrait d'une vidéo (`item_id`), de `start` à `end` en secondes dans la vidéo source, "
        "3 à 12 s en général ; coupe sur des phrases entières en t'aidant des horodatages ; `text` = "
        "sous-titre : la phrase marquante réellement prononcée dans l'extrait, sinon chaîne vide.\n"
        "- `photo` : photo (`item_id`) affichée pendant `duration` (2,5 à 4 s) ; `text` = courte citation "
        "tirée d'une dictée ou d'une conversation du même moment (entre « », suivie de « — Prénom » si "
        "l'auteur est certain), ou légende très courte, ou chaîne vide.\n"
        "Suis la chronologie, garde les meilleurs moments (images bien notées, rires, paroles fortes), "
        "varie photos et vidéos, et termine sur une image forte. Pour un segment, les champs qui ne "
        "s'appliquent pas valent 0 ou une chaîne vide. Les sous-titres font 90 caractères au plus."
    )
    return _call([{"type": "text", "text": prompt}], MONTAGE_SCHEMA, effort="medium", max_tokens=32000)


def _local_montage(ev, media, target: int) -> dict:
    segs = [{"type": "title", "item_id": 0, "text": ev["name"], "start": 0, "end": 0, "duration": 3}]
    current = None
    visual = [m for m in media if m["kind"] in ("photo", "video")]
    for it in visual:
        d = timeline.local_dt(it["captured_at"], ev["tz"])
        key = f"{timeline.fr_day(d).capitalize()} — {timeline.day_part(d)}"
        if key != current:
            segs.append({"type": "title", "item_id": 0, "text": key, "start": 0, "end": 0, "duration": 2.5})
            current = key
        if it["kind"] == "photo":
            segs.append({"type": "photo", "item_id": it["id"], "text": "", "start": 0, "end": 0, "duration": 3.5})
        else:
            tr = json.loads(it["transcript"] or "[]")
            end = min(it["duration"] or 6, 8)
            segs.append({"type": "video", "item_id": it["id"], "text": tr[0]["t"][:90] if tr else "",
                         "start": 0, "end": end, "duration": end})
    return {"segments": segs}
