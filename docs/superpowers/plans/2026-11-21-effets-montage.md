# Effets de montage, cadrage, évolution musicale et préréglages (PR 2) — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compléter l'écran Génération de la spec : rythme du montage, effets (ralentis, accélérés, arrêts sur image, effets humoristiques), style des titres, cadrage (16:9, 9:16, 1:1), évolution de la musique sur plusieurs morceaux, et préréglages enregistrables.

**Architecture:** Repart de la PR 1 (branche `claude/reglages-video-musique`, PR Joleplaymo/souvenirs#9). `settings.normalize` gagne les nouveaux réglages ; `video.py` reçoit un objet `Frame` (dimensions) et un `Style` (rythme, effets, titres) au lieu de constantes globales ; `music.plan_tracks` remplace `music.choose` par une liste de morceaux à rôles (`intro`, `main`, `peak`, `final`) placés aux débuts de séquence ; une table `presets` stocke les préréglages.

**Tech Stack:** FastAPI + SQLite, FFmpeg, Pillow, API Claude, React 18 + Vite, Docker.

**Spec:** `docs/superpowers/specs/2026-11-21-video-parametrable-design.md` (annexe A : réglages ; annexe B : modèle de prompt, sections 4 « Montage » et 5 « Bande-son »). Plan précédent : `docs/superpowers/plans/2026-11-21-reglages-video-musique.md`.

## Global Constraints

- Tout ce qui est dans « Global Constraints » du plan PR 1 reste valable (français, tutoiement, règle anti-mélancolie, crédit CC BY, commande de test Docker, `npm run build`).
- Rythmes : `pose` Posé (plans de 3 à 5 s, fondus) · `dynamique` Dynamique (1,5 à 3 s, coupes sur les temps) · `nerveux` Clip nerveux (0,5 à 1,5 s, coupes franches, quelques plans plus longs jusqu'à 3 s pour respirer).
- Effets (interrupteurs, tous activés par défaut, sauf `humor` désactivé pour `mariage` = `humor_fx` de `TYPE_DEFAULTS`) : `slowmo` Ralentis · `speedup` Accélérés · `freeze` Arrêts sur image · `humor` Effets humoristiques. `subtitles` reste l'interrupteur de la PR 1.
- Styles de titres : `carnet` Carnet manuscrit (défaut) · `sobre` Sobre · `pop` Pop coloré · `aucun` Aucun.
- Cadrages : `16:9` Horizontal 1920×1080 (défaut) · `9:16` Vertical 1080×1920 · `1:1` Carré 1080×1080. **Jamais d'étirement ni de visage coupé** : image entière sur fond flou (le principe actuel), jamais de recadrage destructif.
- Évolutions : `constante` Constante · `montee` Montée progressive · `calme_explosion` Calme puis explosion · `festif_emotion` Festif puis émotion. L'exception anti-mélancolie de la séquence finale vaut pour `ending == "touchante"` **et** pour `evolution == "festif_emotion"` (spec, annexe B §5).
- Le carton de crédit musique reste affiché même avec le style de titres `aucun` (licence CC BY).
- Toute police ajoutée est sous licence libre (OFL) et accompagnée de sa licence dans le dépôt. **Demander l'accord de l'utilisateur avant de télécharger un fichier de police.**

## Review Focus

- Film vertical ou carré fait de photos et vidéos horizontales (et l'inverse) : image entière, fond flou, aucun visage coupé, sous-titres et cartons lisibles dans le cadre (test en tâche 2).
- Ralenti ou arrêt sur image demandé sur un extrait proche de la fin de la vidéo source : l'extrait est raccourci pour tenir dans la source, sans erreur FFmpeg ni image noire (test en tâche 3).
- Film de 30 s avec l'évolution `montee` (3 morceaux) et seulement une ou deux séquences : on retombe proprement sur 1 ou 2 morceaux, jamais un morceau de moins de 4 s (test en tâche 5).
- Brouillons, versions et choix de musique enregistrés par la PR 1 (`reports.music = {"main_id", "final_id"}`, réglages sans les nouvelles clés) : relus sans erreur, valeurs par défaut appliquées (test en tâche 1 et en tâche 5).
- Style `aucun` avec une fin Bêtisier : plus aucun carton de séquence, mais le carton de crédit reste (test en tâche 4).

---

### Task 1: Nouveaux réglages (config + normalisation + API)

**Files:**
- Modify: `backend/app/config.py` (ajoute `RHYTHMS`, `EFFECTS`, `TITLE_STYLES`, `FRAMINGS`, `EVOLUTIONS` avec les libellés ci-dessus)
- Modify: `backend/app/pipeline/settings.py` (`normalize`)
- Modify: `backend/app/main.py` (`GET /api/config` expose les 5 listes)
- Test: `backend/tests/test_settings.py`

**Interfaces:**
- Produces: `normalize(raw, event_type)` renvoie en plus `rhythm: str`, `evolution: str`, `effects: {"slowmo": bool, "speedup": bool, "freeze": bool, "humor": bool}`, `title_style: str`, `framing: str` (défauts : `rhythm`/`evolution` de `TYPE_DEFAULTS`, effets tous vrais sauf `humor = humor_fx`, `carnet`, `16:9`).

- [ ] **Step 1: Write the failing tests** : `test_normalize_new_defaults_weekend` (rythme `dynamique`, évolution `montee`, 4 effets vrais, `carnet`, `16:9`) ; `test_normalize_mariage_humor_off` ; `test_normalize_rejects_unknown_values` (`rhythm: "x"`, `framing: "4:3"`, `title_style: 3` → défauts ; `effects: {"slowmo": "non"}` → booléen strict, une valeur non booléenne donne le défaut) ; `test_normalize_old_settings_still_valid` (un dict PR 1 sans nouvelles clés → complété, anciennes clés inchangées).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: réglages de rythme, effets, titres, cadrage et évolution`

### Task 2: Cadrage (dimensions paramétrables)

**Files:**
- Modify: `backend/app/pipeline/video.py` (constantes `W, H` → `Frame`)
- Modify: `backend/app/pipeline/generate.py` (`render_video` passe le cadrage)
- Test: `backend/tests/test_render_framing.py`

**Interfaces:**
- Produces: `video.Frame` (dataclass gelée `w: int`, `h: int`) ; `video.frame_for(framing: str) -> Frame` ; toutes les fonctions de rendu (`title_card`, `subtitle_png`, `photo_canvas`, `_render_segment`, `credit_segment`, `render`) prennent `frame: Frame` ; `render(segs, items, out, tracks, mix, frame=Frame(1920, 1080), style=None, on_progress=None)`.

Les tailles de police, marges et la toile du zoom (`photo_canvas`, actuellement 2880×1620) sont proportionnelles au petit côté du cadre (1080 = taille actuelle). Recadrage vidéo identique à l'actuel (image entière + fond flou).

- [ ] **Step 1: Write the failing tests** (médias lavfi générés : photo 1600×900, vidéo 1280×720 de 3 s, photo 900×1600) : `test_vertical_output_dims` (`ffprobe` → 1080×1920) ; `test_square_output_dims` (1080×1080) ; `test_landscape_photo_in_vertical_not_cropped` (sur une image extraite du film, la bande centrale de l'image source est présente en entier : comparer la largeur du contenu non flou à la largeur du cadre ±2 %) ; `test_subtitle_inside_frame_vertical` (la boîte de sous-titre de `subtitle_png` tient dans 1080 px de large avec 90 caractères).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS (tous les tests PR 1 de `test_render_music.py` passent toujours).
- [ ] **Step 5: Commit** `feat: cadrage horizontal, vertical ou carré sans recadrage destructif`

### Task 3: Rythme et effets dans le rendu

**Files:**
- Modify: `backend/app/pipeline/video.py` (`normalize`, `_render_segment`)
- Modify: `backend/app/pipeline/ai.py` (`MONTAGE_SCHEMA` : champ `effect`)
- Test: `backend/tests/test_render_effects.py`

**Interfaces:**
- Consumes: `Frame` (tâche 2).
- Produces: `video.Style` (dataclass : `rhythm: str`, `effects: dict`, `title_style: str`, `bpm: int | None`) ; `video.normalize(plan, items, target, style: Style | None = None) -> list[dict]` ; chaque segment peut porter `effect` ∈ `none | slowmo | speedup | freeze | punch` ; `MONTAGE_SCHEMA` ajoute `"effect": {"type": "string", "enum": ["none", "slowmo", "speedup", "freeze", "punch"]}`.

Règles de `normalize` : bornes de durée par rythme (photo et vidéo) : `pose` 3–5 s, `dynamique` 1,5–3 s (vidéo jusqu'à 6 s), `nerveux` 0,5–1,5 s (au plus un plan sur quatre jusqu'à 3 s) ; carton de titre 1,5–3 s quel que soit le rythme. Un `effect` dont l'interrupteur est coupé devient `none` ; `slowmo`, `speedup` et `freeze` seulement sur `video` (sur une photo → `none`) ; `punch` sur photo ou vidéo, seulement si `humor`. Si `bpm` est connu et le rythme n'est pas `pose`, chaque durée est arrondie au multiple de temps le plus proche (`60/bpm`, demi-temps pour `nerveux`), sans sortir des bornes.

Rendu : `slowmo` = source de `duration/2` secondes, `setpts=2*PTS`, son d'origine coupé ; `speedup` = source de `2*duration`, `setpts=0.5*PTS`, `atempo=2.0` ; `freeze` = extrait de `duration-1` s puis dernière image tenue 1 s (`tpad=stop_mode=clone`), son complété en silence ; `punch` = zoom rapide jusqu'à 1,25 sur les 0,2 dernières secondes, centré. L'extrait source est toujours ramené dans `[0, durée source]`. Fondus : 0,3 s en `pose`, 0,15 s en `dynamique`, aucun en `nerveux`.

- [ ] **Step 1: Write the failing tests** : `test_normalize_rhythm_bounds` (même plan normalisé en `pose`, `dynamique` et `nerveux` → toutes les durées dans leurs bornes) ; `test_normalize_strips_disabled_effects` (effets coupés → tous `none`) ; `test_normalize_snaps_to_beat` (bpm 120, `dynamique` → durées multiples de 0,5 s) ; `test_slowmo_near_source_end` (vidéo de 3 s, `start=2.5`, `slowmo`, 2 s demandées → rendu sans erreur, durée 2 s ± 0,1) ; `test_freeze_adds_held_frame` (durée rendue = durée demandée ± 0,1, les 0,9 dernières secondes ont des images identiques) ; `test_speedup_duration`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: rythme du montage et effets (ralenti, accéléré, arrêt sur image, zoom comique)`

### Task 4: Styles de titres

**Files:**
- Modify: `backend/app/pipeline/video.py` (`title_card(text, out, frame, style)`)
- Create (après accord de l'utilisateur pour le téléchargement) : `backend/app/fonts/Caveat-Bold.ttf`, `backend/app/fonts/OFL.txt` ; Modify: `Dockerfile` (copie des polices), `font_path` (cherche aussi `app/fonts`)
- Test: `backend/tests/test_titles.py`

**Interfaces:**
- Consumes: `Style.title_style`, `Frame`.
- Produces: `video.normalize` retire tous les segments `title` quand `title_style == "aucun"` (le carton de crédit, ajouté plus tard par `render`, n'est pas concerné).

Styles : `carnet` = fond chaud actuel + police manuscrite Caveat Bold (repli : police serif actuelle si le fichier manque) ; `sobre` = fond noir, sans-serif blanche, fine, pas de filets ; `pop` = fond uni pris dans une palette de 5 couleurs vives (selon l'index du carton), sans-serif grasse, texte légèrement incliné (−3°) ; `aucun` = pas de carton de séquence.

- [ ] **Step 1: Demander à l'utilisateur** l'autorisation de télécharger `Caveat-Bold.ttf` depuis le dépôt GitHub `google/fonts` (licence OFL, environ 400 Ko). S'il refuse, le style `carnet` utilise la police serif actuelle (pas de nouveau fichier).
- [ ] **Step 2: Write the failing tests** : `test_title_styles_differ` (les 3 styles produisent 3 images différentes pour le même texte) ; `test_aucun_drops_titles_keeps_credit` (plan avec cartons + morceau CC BY, style `aucun` → le film contient exactement 1 carton : le crédit) ; `test_carnet_fallback_without_font` (police absente → rendu sans erreur).
- [ ] **Step 3: Run** → FAIL. **Step 4: Implement.** **Step 5: Run** → PASS.
- [ ] **Step 6: Commit** `feat: styles de titres carnet, sobre, pop ou aucun`

### Task 5: Évolution de la musique sur plusieurs morceaux

**Files:**
- Modify: `backend/app/pipeline/music.py` (`allowed`, nouveau `plan_tracks`, `choose` devient un alias compatible)
- Modify: `backend/app/pipeline/video.py` (`mix_music` : enchaînement de N morceaux)
- Modify: `backend/app/pipeline/generate.py` (`pick_tracks`, `stored_tracks`, `store_music`, `_credits`, `remix`)
- Modify: `backend/app/main.py` (`/music/pick` renvoie la liste des rôles ; accepte `exclude` par rôle)
- Test: `backend/tests/test_music.py`, `backend/tests/test_render_music.py`

**Interfaces:**
- Produces: `music.allowed(track, tones, final, ending, evolution="constante") -> bool` ; `music.plan_tracks(tones, settings, exclude: dict[str, list[int]] | None = None) -> list[{"role": str, "track": dict}]` avec les rôles :
  - `constante` → `main` (énergie cible) ;
  - `montee` → `intro` (cible − 1), `main` (cible), `peak` (cible + 1) ;
  - `calme_explosion` → `intro` (énergie 1 ou 2), `peak` (5) ;
  - `festif_emotion` → `main` (cible), `final` (humeur `tendre`, `calme` ou `melancolique`, énergie ≤ 2) ;
  - et `final` ajouté à toute évolution quand `ending == "touchante"` (s'il n'y est pas déjà).
  Un rôle sans candidat est omis ; jamais deux fois le même morceau.
- Produces: `reports.music = {"roles": {role: id}}` ; la lecture accepte encore l'ancien format `{"main_id", "final_id"}`. `video.mix_music(base, out, tracks: list[{"path": Path, "start": float}], mix, ...)`.
- Produces: `video.section_starts(segs) -> list[float]` (débuts des cartons de titre) ; placement : `intro` à 0, `main` au début de séquence le plus proche de 1/3 du film (`montee`) ou à 0, `peak` au début de séquence le plus proche de 2/3 (`montee`) ou de 40 % (`calme_explosion`), `final` au début de la dernière séquence. Fondu enchaîné de 2 s entre deux morceaux. Si un morceau durerait moins de 4 s, il est retiré, et le précédent continue.

- [ ] **Step 1: Write the failing tests** : `test_plan_tracks_montee_three_roles` (énergies croissantes) ; `test_festif_emotion_final_may_be_melancholic` (seul le rôle `final` accepte `melancolique`, tons `drole`) ; `test_plan_tracks_never_repeats` ; `test_old_music_format_still_read` (`{"main_id": 3, "final_id": null}` → rôle `main` = 3) ; `test_short_film_collapses_tracks` (film de 30 s, un seul carton → au plus 2 morceaux, aucun de moins de 4 s) ; `test_mix_three_tracks_duration` (le film mixé garde la durée de `video_base.mp4` ± 0,1 s) ; `test_credits_list_every_played_track`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: évolution de la musique sur plusieurs morceaux enchaînés`

### Task 6: Modèle de prompt complet

**Files:**
- Modify: `backend/app/prompts/montage.md`, `backend/app/pipeline/ai.py` (`montage_prompt`)
- Test: `backend/tests/test_prompts.py`

Ajouter au modèle, depuis l'annexe B de la spec : la règle de rythme (`{{rythme}}`, avec les durées de plan de « Global Constraints »), les effets autorisés (`{{effets}}` : n'utiliser le champ `effect` qu'avec les valeurs activées, seulement quand les images s'y prêtent, `punch` réservé aux moments drôles), le style des titres (`{{style_titres}}` : si `aucun`, ne produire aucun segment `title`), et le cadrage (`{{cadrage}}` : en vertical, privilégier les médias en portrait et les plans serrés). La bande-son reste choisie par l'appli : ne pas ajouter la section 5 de l'annexe B.

- [ ] **Step 1: Write the failing tests** : `test_prompt_mentions_rhythm_and_effects` (`nerveux`, effets `slowmo` seul → le prompt contient « 0,5 à 1,5 s » et `slowmo`, mais pas `speedup`) ; `test_prompt_aucun_titles` ; `test_prompt_vertical` (contient « portrait ») ; `"{{" not in prompt` pour toutes les combinaisons de cadrage et de style.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: rythme, effets, titres et cadrage dans le prompt du montage`

### Task 7: Préréglages

**Files:**
- Modify: `backend/app/db.py` (table `presets(id INTEGER PRIMARY KEY, name TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL)`)
- Modify: `backend/app/main.py` (routes)
- Test: `backend/tests/test_api_presets.py`

**Interfaces:**
- Produces: `GET /api/events/{slug}/presets`, `POST /api/events/{slug}/presets` (`{"name", "tones", "video_settings"}`), `DELETE /api/events/{slug}/presets/{id}` — tous avec `x-admin-token` de l'événement ; les préréglages sont communs à tous les événements (un seul organisateur par installation). `data` = `{"tones": [...], "video_settings": normalize(...)}` (sans type, sans consignes, sans morceaux choisis). Nom : 1 à 60 caractères ; même nom → remplace.

- [ ] **Step 1: Write the failing tests** : `test_preset_roundtrip_across_events` (créé sur l'événement A, visible depuis l'événement B) ; `test_preset_same_name_replaces` ; `test_preset_requires_admin_token` ; `test_preset_invalid_tones_400`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: préréglages de génération réutilisables`

### Task 8: Écran Génération complet

**Files:**
- Create: `frontend/src/Toggle.jsx` (`<Toggle label checked onChange disabled />`, interrupteur accessible `role="switch"`)
- Modify: `frontend/src/Generate.jsx`, `frontend/src/MusicPreview.jsx`, `frontend/src/Review.jsx`, `frontend/src/styles.css`

Ajouts à l'écran (maquette validée) : en haut, les préréglages (puces « Appliquer », × pour supprimer avec confirmation) ; **Musique** + « Évolution » (puces) ; nouvelle section **Montage** (rythme en puces, 4 interrupteurs d'effets + l'interrupteur sous-titres déplacé ici, style des titres en puces) ; **Format** + « Cadrage » (puces) ; en bas, « Enregistrer comme préréglage » (champ nom + bouton). Changer le type pré-remplit aussi rythme, évolution et effets (même règle que la PR 1 : ne pas écraser ce qui a été modifié à la main). La pré-écoute affiche un morceau par rôle (« Début », « Cœur », « Sommet », « Final »), chacun avec son bouton « Autre titre ». Le lecteur de relecture et de publication s'adapte au cadrage (vertical : hauteur max 80 vh).

- [ ] **Step 1:** `npm run build` → OK.
- [ ] **Step 2: Vérification dans le navigateur** (démo locale comme en PR 1) : appliquer un préréglage remplit tous les réglages ; la section Montage est présente ; `montee` affiche 3 morceaux en pré-écoute ; un film 9:16 de 30 s se génère et se lit en vertical en relecture ; à 375 px de large, rien ne déborde.
- [ ] **Step 3: Commit** `feat: écran Génération complet (montage, cadrage, évolution, préréglages)`

### Task 9: Vérification de bout en bout et PR

- [ ] **Step 1:** Tous les tests backend → PASS ; `npm run build` → OK.
- [ ] **Step 2:** Sur la démo locale, générer trois films de 1 min et les regarder : (a) week-end par défaut ; (b) `nerveux`, tous effets, `pop`, 9:16 ; (c) Tendre + Cinéma, `pose`, `carnet`, fin Touchante, `festif_emotion`. Vérifier : bornes de durée des plans, au moins un effet visible en (b), pas de carton de séquence avec `aucun` (essai rapide), morceau final doux en (c), crédits complets.
- [ ] **Step 3:** Ouvrir un brouillon et une version créés avec la PR 1 : ils s'affichent, et « Changer la musique » fonctionne.
- [ ] **Step 4:** README mis à jour ; commit `docs: effets de montage, cadrage, évolution musicale et préréglages` ; pousser la branche et ouvrir la PR. Si la PR #9 n'est pas encore fusionnée, la PR 2 vise la branche `claude/reglages-video-musique` (à rebasculer vers `main` après la fusion de #9) ; sinon, elle vise `main`.
