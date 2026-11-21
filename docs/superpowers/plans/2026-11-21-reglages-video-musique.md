# Réglages vidéo et catalogue musical (PR 1) — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** L'organisateur règle le ton (10 choix, 2 max, commun au texte et au film), le type d'événement (10), la fin du film, les genres, l'énergie, le mélange sons réels / musique, la durée et les sous-titres ; la musique vient d'un catalogue étiqueté filtré par l'appli (règle anti-mélancolie), se pré-écoute, se change en relecture, et on peut ajouter ses propres MP3.

**Architecture:** Les listes de choix et les valeurs par défaut vivent dans `config.py` ; un module `pipeline/settings.py` valide et complète les réglages vidéo ; un module `pipeline/music.py` gère la table `tracks` (bibliothèque + ajouts), le filtrage et le choix des morceaux. Le prompt du montage devient un modèle fichier `app/prompts/montage.md`. Le rendu garde une version du film sans musique (`video_base.mp4`) pour pouvoir remixer seulement l'audio.

**Tech Stack:** FastAPI + SQLite (backend/app), FFmpeg, API Claude, React 18 + Vite (frontend), Docker.

**Spec:** `docs/superpowers/specs/2026-11-21-video-parametrable-design.md` (annexe A = réglages et valeurs par défaut, annexe B = modèle de prompt). La PR 2 (rythme, effets, titres, cadrage, évolution multi-morceaux, préréglages) fera l'objet d'un autre plan : ne pas l'anticiper ici, sauf les valeurs par défaut `evolution` et `rythme` déjà stockées par la tâche 1.

## Global Constraints

- Interface et messages entièrement en français ; textes d'interface au ton du reste de l'appli (tutoiement).
- Aucune clé ni secret dans le code ; la clé Claude reste `ANTHROPIC_API_KEY`.
- Ton : 2 choix maximum, le premier domine. Tons : `drole` Drôle · `festif` Festif · `epique` Épique · `tendre` Tendre · `chill` Chill · `nostalgique` Nostalgique · `motivant` Motivant · `decale` Décalé · `cinema` Cinéma · `documentaire` Documentaire.
- Types : `weekend` Week-end copains · `course` Course, trail · `anniversaire` Anniversaire · `mariage` Mariage · `vacances` Vacances famille · `roadtrip` Road-trip · `rando` Rando, montagne · `soiree` Soirée · `evg` EVG, EVJF · `autre` Autre.
- Fins : `festive` Festive · `betisier` Bêtisier · `touchante` Touchante · `epique` Épique.
- Genres : `pop` Pop · `electro` Électro · `rock` Rock · `indie` Indie · `hiphop` Hip-hop · `funk` Funk, disco · `tropical` Tropical · `folk` Folk · `lofi` Lo-fi · `annees80` Années 80 · `chanson` Chanson FR · `jazz` Jazz · `piano` Piano · `orchestral` Orchestral.
- Humeurs des morceaux : `joyeux` `festif` `epique` `tendre` `calme` `melancolique` `triste`.
- Énergie 1 à 5 ; mélange 0 (sons réels) à 100 (musique), défaut 55 ; durées 30, 60, 120, 180, 300 s (défaut 120) ; sous-titres oui par défaut.
- **Règle anti-mélancolie** : aucun morceau d'humeur `melancolique` ou `triste`, sauf si un des tons est `tendre` ou `nostalgique`. Seule exception : le morceau de la séquence finale quand la fin est `touchante`.
- Valeurs par défaut par type : tableau de l'annexe A de la spec, recopié à l'identique (effets humoristiques désactivés pour `mariage` : concerne la PR 2, stocker quand même).
- Morceaux de la bibliothèque : Incompetech (Kevin MacLeod), CC BY 4.0 ; crédit obligatoire en fin de film : `Musique : « <titre> » — Kevin MacLeod (incompetech.com), licence CC BY 4.0`.
- **Aucun téléchargement de musique avant que l'organisateur ait validé la liste** du catalogue (tâche 5).
- Tests backend : `docker build -t souvenirs:dev .` une fois, puis
  `docker run --rm -v "$PWD/backend/app:/app/app" -v "$PWD/backend/tests:/app/tests" -e DATA_DIR=/tmp/data -e ADMIN_CODE=test souvenirs:dev sh -c "pip install -q --user pytest httpx && python -m pytest -q tests"`.
- Frontend : `cd frontend && npm ci && npm run build` doit passer sans erreur.

## Review Focus

- Événements, versions et démo existants avec les anciens tons (`detendu`, `sportif`, `humour`, `emotion`) et types (`voyage`, `fete`) : ils doivent s'ouvrir, s'afficher et se régénérer sans erreur après migration (test en tâche 2).
- Catalogue vide ou aucun morceau compatible (genres rares + énergie extrême) : le film se génère quand même, sans musique, avec un message clair à la pré-écoute ; la règle anti-mélancolie n'est jamais relâchée (test en tâche 4).
- Fichier ajouté qui n'est pas un MP3 lisible, ou de plus de 30 Mo : refus avec message, rien n'est enregistré (test en tâche 6).
- « Changer la musique » sur un brouillon généré avant cette PR (pas de `video_base.mp4`) : message demandant de régénérer le film, pas de plantage (test en tâche 7).
- Ton à 3 valeurs, valeur inconnue ou liste vide envoyée à l'API : refus 400 avec message en français (test en tâche 1).

---

### Task 1: Listes de choix, valeurs par défaut et validation des réglages

**Files:**
- Modify: `backend/app/config.py` (remplace `EVENT_TYPES`, `TONES` ; ajoute `ENDINGS`, `GENRES`, `MOODS`, `DURATIONS`, `TYPE_DEFAULTS`, `LEGACY_TONES`, `LEGACY_TYPES`)
- Create: `backend/app/pipeline/settings.py`
- Create: `backend/tests/conftest.py`, `backend/tests/test_settings.py`

**Interfaces:**
- Produces: `config.TYPE_DEFAULTS: dict[str, dict]` (clés `tones: list[str]`, `genres: list[str]`, `energy: int`, `evolution: str`, `ending: str`, `rhythm: str`, `humor_fx: bool`) ; `config.LEGACY_TONES = {"detendu": ["chill", "drole"], "sportif": ["motivant", "documentaire"], "humour": ["drole"], "emotion": ["tendre", "nostalgique"]}` ; `config.LEGACY_TYPES = {"voyage": "roadtrip", "fete": "anniversaire"}`.
- Produces: `settings.parse_tones(value: str | list) -> list[str]` (accepte CSV `"drole,festif"`, liste, ou ancien ton ; lève `ValueError` en français si vide, > 2, ou inconnu) ; `settings.tones_csv(tones: list[str]) -> str` ; `settings.tones_label(value) -> str` (ex. `"Drôle + Festif"`) ; `settings.defaults(event_type: str) -> dict` ; `settings.normalize(raw: dict | None, event_type: str) -> dict` qui renvoie toujours un dict complet `{"ending", "genres", "energy", "mix", "duration", "subtitles"}` en complétant par les défauts du type et en bornant les valeurs (énergie 1-5, mix 0-100, durée dans `DURATIONS` sinon 120, genres inconnus retirés, liste vide → défauts).

- [ ] **Step 1: Write the failing tests** — `conftest.py` met `backend/` dans `sys.path` et `DATA_DIR` sur un dossier temporaire. Tests :
  - `test_parse_tones_accepts_csv_list_and_legacy` : `parse_tones("drole,festif") == ["drole", "festif"]`, `parse_tones(["tendre"]) == ["tendre"]`, `parse_tones("detendu") == ["chill", "drole"]`.
  - `test_parse_tones_rejects` : `pytest.raises(ValueError)` pour `""`, `["drole","festif","epique"]`, `"inconnu"`.
  - `test_tones_label` : `tones_label("drole,festif") == "Drôle + Festif"`, `tones_label("emotion") == "Tendre + Nostalgique"`.
  - `test_defaults_weekend` : `defaults("weekend")` a `tones == ["drole","festif"]`, `genres == ["pop","electro","funk"]`, `energy == 4`, `ending == "festive"`, `evolution == "montee"`, `rhythm == "dynamique"`.
  - `test_type_defaults_cover_every_type` : `set(config.TYPE_DEFAULTS) == set(config.EVENT_TYPES)` et chaque genre/ton/fin cité existe dans sa liste.
  - `test_normalize_fills_and_clamps` : `normalize({"energy": 9, "mix": -5, "duration": 45, "genres": ["pop", "zzz"]}, "course")` → `energy == 5`, `mix == 0`, `duration == 120`, `genres == ["pop"]`, `ending == "epique"`, `subtitles is True`.
- [ ] **Step 2: Run** la commande de test globale → FAIL (`ModuleNotFoundError: app.pipeline.settings`).
- [ ] **Step 3: Implement** `config.py` (valeurs exactes de « Global Constraints » et de l'annexe A ; clés `evolution` : `constante`, `montee`, `calme_explosion`, `festif_emotion` ; `rhythm` : `pose`, `dynamique`, `nerveux`) puis `pipeline/settings.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: listes de tons, types et réglages vidéo avec valeurs par défaut`

### Task 2: Migration des données et ton multiple dans l'API

**Files:**
- Modify: `backend/app/db.py` (`MIGRATIONS` + fonction `migrate_values()` appelée à la fin de `init()`)
- Modify: `backend/app/main.py:79-152` (`event_public`, `get_config`, `_settings`), `:555-760` (tous les `config.TONES.get(...)` → `settings.tones_label(...)`)
- Modify: `backend/app/pipeline/versions.py:38` (libellé de version via `tones_label`)
- Modify: `demo/manifest.json`, `tools/make_demo.py` (ton `drole,festif`)
- Test: `backend/tests/test_migration.py`, `backend/tests/test_api_settings.py`

**Interfaces:**
- Consumes: `settings.parse_tones`, `settings.tones_csv`, `settings.tones_label`, `settings.defaults`, `config.LEGACY_*`.
- Produces: colonnes `reports.video_settings TEXT`, `reports.music TEXT`, `versions.video_settings TEXT`, `versions.music TEXT` ; `events.tone` et `versions.tone` contiennent un CSV de 1 ou 2 tons. `GET /api/config` renvoie en plus `endings`, `genres`, `durations`, `defaults` (= `TYPE_DEFAULTS`). `event_public` renvoie `tones: list[str]` en plus de `tone` (CSV) et `tone_label`.

- [ ] **Step 1: Write the failing tests**
  - `test_migrate_values` : insérer directement un événement `type="voyage", tone="detendu"` et une version `tone="emotion"`, appeler `db.migrate_values()` → événement `type == "roadtrip"`, `tone == "chill,drole"` ; version `tone == "tendre,nostalgique"` ; un second appel ne change rien.
  - `test_create_event_with_two_tones` (TestClient, en-tête `x-admin-code: test`) : POST `/api/events` avec `tone: ["drole","festif"]`, `type: "weekend"` → 200 ; GET `/api/events/{slug}` renvoie `tones == ["drole","festif"]`, `tone_label == "Drôle + Festif"`.
  - `test_create_event_rejects_three_tones` : 400 et message contenant « 2 tons ».
  - `test_config_exposes_defaults` : `GET /api/config` contient `defaults["mariage"]["ending"] == "touchante"`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** : `_settings` accepte `tone` en liste ou CSV via `parse_tones` (ValueError → `err(400, ...)`), stocke `tones_csv`. Ajoute les 4 colonnes à `MIGRATIONS`. `migrate_values()` convertit `LEGACY_TYPES` / `LEGACY_TONES` dans `events` et `versions`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: ton multiple, nouveaux types et migration des anciens événements`

### Task 3: Ton du récit et modèle de prompt du montage

**Files:**
- Modify: `backend/app/pipeline/ai.py:17-23` (`TONE_GUIDE` → 10 tons), `:99-103` (`_context`), `:230-259` (`plan_montage`)
- Create: `backend/app/prompts/montage.md`
- Test: `backend/tests/test_prompts.py`

**Interfaces:**
- Consumes: `settings.parse_tones`, `settings.normalize`.
- Produces: `ai.tone_guide(tones: list[str]) -> str` ; `ai.montage_prompt(ev, settings: dict, target: int) -> str` (remplit le modèle) ; `ai.plan_montage(ev, report_md, media, target, wishes="", settings=None)`.

`montage.md` reprend l'annexe B de la spec **en ne gardant que ce qui est rendu dans cette PR** : sections « Ton » (tableau des 10 tons), « Séquences » (tableau par type), « Fin du film », et une section « Montage » réduite (sélection, alternance des plans, sous-titres `{{sous_titres}}`, fidélité aux faits). Pas de rythme, d'effets, de cadrage ni de bande-son (la musique est choisie par l'appli). Les champs `{{nom}}`, `{{type}}`, `{{ton}}`, `{{fin}}`, `{{duree}}`, `{{sous_titres}}` sont remplacés par `str.replace` ; aucune accolade ne doit rester.

- [ ] **Step 1: Write the failing tests**
  - `test_tone_guide_two_tones` : `tone_guide(["drole","tendre"])` contient la consigne de `drole` puis celle de `tendre`, et la phrase « Le premier ton domine ».
  - `test_montage_prompt_filled` : pour un événement `weekend`, réglages `normalize({"ending": "betisier"}, "weekend")`, cible 60 → contient « Les retrouvailles », « Bêtisier », « 60 secondes » et `"{{" not in prompt`.
  - `test_montage_prompt_subtitles_off` : `subtitles=False` → le prompt demande des `text` vides sur les segments `photo` et `video`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**. `plan_montage` envoie `montage_prompt(...)` + la liste des médias (bloc actuel `timeline.render`) + le format des segments (texte actuel des lignes 238-249) + les consignes (bloc actuel 251-258, inchangé).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: dix tons pour le récit et modèle de prompt du montage`

### Task 4: Catalogue musical et choix des morceaux

**Files:**
- Create: `backend/app/pipeline/music.py`
- Modify: `backend/app/db.py` (table `tracks` dans `SCHEMA`)
- Create: `music/catalogue.json` (pour l'instant : les 4 morceaux synthétisés existants, étiquetés)
- Test: `backend/tests/test_music.py`

**Interfaces:**
- Produces: table `tracks(id INTEGER PRIMARY KEY, key TEXT UNIQUE, title, artist, license, source_url, credit, genres TEXT /*CSV*/, energy INTEGER, mood TEXT, bpm INTEGER, duration REAL, file TEXT, origin TEXT /*library|upload*/, created_at TEXT)`.
- Produces: `music.sync_catalogue() -> int` (charge `MUSIC_DIR/catalogue.json` dans `tracks` par `key`, sans toucher aux `upload`) ; `music.path(track) -> Path | None` (fichier existant ou None) ; `music.allowed(track, tones: list[str], final: bool, ending: str) -> bool` (règle anti-mélancolie) ; `music.candidates(tones, settings, final=False, exclude=()) -> list[track]` ; `music.choose(tones, settings, exclude=()) -> {"main": track | None, "final": track | None}` (`final` seulement si `ending == "touchante"` : humeur `tendre`, `calme` ou `melancolique`, énergie ≤ 2) ; `music.public(track) -> dict` (`id`, `title`, `artist`, `credit`, `url` = `/api/music/{id}.mp3`).

Format d'une entrée de `catalogue.json` : `{"key", "title", "artist", "license", "source_url", "credit", "genres": [...], "energy", "mood", "bpm", "file"}`. Les 4 morceaux synthétisés : `detendu` (lofi+piano, énergie 2, `calme`), `sportif` (electro+rock, 4, `epique`), `humour` (funk+pop, 3, `joyeux`), `emotion` (piano, 1, `melancolique`) ; `credit` vide.

Ordre de `candidates` : morceaux avec fichier présent, autorisés par la règle, avec au moins un genre commun et `|énergie − cible| ≤ 1`, triés par écart d'énergie puis nombre de genres communs (décroissant) puis `id`. S'il n'y en a aucun : relâcher les genres, puis l'énergie à ±2 ; **ne jamais relâcher la règle anti-mélancolie**.

- [ ] **Step 1: Write the failing tests** (catalogue de test écrit dans `tmp_path`, fichiers MP3 factices)
  - `test_weekend_never_gets_melancholy` : tons `drole,festif`, réglages par défaut du `weekend`, catalogue avec un morceau `melancolique` pop énergie 4 et un `joyeux` funk énergie 4 → `choose(...)["main"]` est le `joyeux` et aucun candidat n'est `melancolique`.
  - `test_tendre_allows_melancholy` : tons `tendre` → le morceau `melancolique` fait partie des candidats.
  - `test_touchante_gets_final_track` : fin `touchante`, tons `drole` → `final` est un morceau `calme` ou `tendre` d'énergie ≤ 2 ; `melancolique` est accepté pour `final` uniquement.
  - `test_relaxes_genre_then_energy_never_mood` : seuls morceaux disponibles = un `jazz` énergie 2 `joyeux` et un `triste` → pour genres `["rock"]`, énergie 4, on obtient le `jazz`.
  - `test_empty_catalogue_returns_none` : `choose(...) == {"main": None, "final": None}`.
  - `test_exclude_gives_next` : `candidates(..., exclude=[premier.id])[0]` est le deuxième.
  - `test_sync_keeps_uploads` : un `upload` existant survit à `sync_catalogue()`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** ; appeler `music.sync_catalogue()` au démarrage de l'app (`main.py`) et du worker (`worker.main`).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: catalogue musical étiqueté et règle anti-mélancolie`

### Task 5: Sélection Incompetech (validation obligatoire) et téléchargement

**Files:**
- Modify: `music/catalogue.json` (ajout d'environ 40 morceaux)
- Create: `tools/fetch_music.py`
- Modify: `backend/app/pipeline/music.py` (`sync_catalogue` télécharge les fichiers manquants dans `DATA_DIR/music/library` via `fetch`) ; `music/LISEZMOI.txt` ; `README.md`
- Test: `backend/tests/test_music.py::test_catalogue_json_is_valid`

- [ ] **Step 1: Proposer la liste** : sur incompetech.com, choisir environ 40 morceaux couvrant chaque genre de la liste et chaque énergie (au moins 3 morceaux par énergie, au moins 2 par genre quand Incompetech en a, au moins 12 `joyeux` ou `festif` d'énergie ≥ 3). Pour chacun : titre, URL de la page, URL du MP3, genres, énergie, humeur, BPM. Présenter le tableau à l'organisateur. **S'arrêter et attendre sa validation explicite avant le moindre téléchargement.**
- [ ] **Step 2: Write the failing test** `test_catalogue_json_is_valid` : chaque entrée a toutes les clés, genres/humeur dans les listes de `config`, énergie 1-5, `license == "CC BY 4.0"` et `credit` non vide pour `artist == "Kevin MacLeod"`, `key` unique.
- [ ] **Step 3: Implement** : ajouter les entrées validées. `tools/fetch_music.py [--dest DIR]` télécharge les MP3 manquants (urllib, délai d'une seconde entre deux fichiers, User-Agent générique `souvenirs-app`). Au démarrage du worker, `sync_catalogue()` lance le même téléchargement en tâche de fond (un échec est journalisé, il ne bloque rien). `music.path()` cherche d'abord dans `DATA_DIR/music/library`, puis dans `MUSIC_DIR`.
- [ ] **Step 4: Run** les tests, puis `python tools/fetch_music.py --dest /tmp/m` dans le conteneur → environ 40 fichiers téléchargés, aucune erreur.
- [ ] **Step 5: Commit** `feat: bibliothèque Incompetech (CC BY 4.0) téléchargée au démarrage`

### Task 6: Ajout de ses propres musiques (API + écran)

**Files:**
- Modify: `backend/app/main.py` (routes musique)
- Create: `frontend/src/Music.jsx` ; Modify: `frontend/src/App.jsx` (route `/musiques`), `frontend/src/Home.jsx` (lien « Musiques » à côté de la liste des événements, visible avec le code organisateur)
- Test: `backend/tests/test_api_music.py`

**Interfaces:**
- Produces: `GET /api/music` (en-tête `x-admin-code`) → liste de `music.public(t)` + `genres`, `energy`, `mood`, `origin` ; `POST /api/music` (multipart : `file`, `title`, `artist`, `genres` CSV, `energy`, `mood`, `license`) → 201 + morceau ; `DELETE /api/music/{id}` (seulement `origin == "upload"`) ; `GET /api/music/{id}.mp3` (public, `FileResponse`, `audio/mpeg`).

Fichier enregistré dans `DATA_DIR/music/uploads/<id>.mp3` ; refus si > 30 Mo ou si `media.probe` ne trouve pas d'audio ; durée remplie par `probe`. Écran : liste (titre, artiste, puces de genres, énergie, humeur, origine, lecteur `<audio>`), formulaire d'ajout avec les mêmes puces que l'écran Génération, champ licence obligatoire (« Tu dois avoir le droit d'utiliser ce morceau dans une vidéo partagée »).

- [ ] **Step 1: Write the failing tests** : `test_upload_valid_mp3` (MP3 d'1 s généré par `ffmpeg -f lavfi -i sine` dans le test) → 201, apparaît dans `GET /api/music` ; `test_upload_rejects_non_audio` (fichier texte) → 400, aucune ligne ni fichier créé ; `test_upload_rejects_too_big` (en-tête `content-length` > 30 Mo, ou fichier tronqué à la lecture) → 413 ; `test_cannot_delete_library_track` → 403 ; `test_requires_admin_code` → 401/403.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** l'API puis l'écran.
- [ ] **Step 4: Run** les tests → PASS ; `npm run build` → OK.
- [ ] **Step 5: Commit** `feat: ajout de ses propres musiques au catalogue`

### Task 7: Musique dans le rendu, crédit, mélange et « Changer la musique »

**Files:**
- Modify: `backend/app/pipeline/video.py:180-229` (`pick_music` supprimé ; `render` garde `video_base.mp4`)
- Modify: `backend/app/pipeline/generate.py` (réglages, choix musique, partie `music`)
- Modify: `backend/app/pipeline/versions.py` (`FILES` + `video_base.mp4` ; copie `video_settings` et `music`)
- Modify: `backend/app/main.py:415-470` (`/generate` accepte `video_settings`, `music` et `parts` ⊂ {text, video, album, music} ; `/draft` renvoie `video_settings` normalisés et `music`)
- Test: `backend/tests/test_render_music.py`

**Interfaces:**
- Consumes: `music.choose`, `music.path`, `music.public`, `settings.normalize`.
- Produces: `video.render(segs, items, out, tracks: dict, mix: int, on_progress=None) -> float` où `tracks = {"main": Path | None, "final": Path | None, "credits": list[str]}` ; `video.mix_music(base: Path, out: Path, tracks: dict, mix: int, final_from: float | None) -> None` ; `generate.remix(ev, prog)` ; `reports.music` = `{"main_id": int | None, "final_id": int | None}`.

Règles : `reports.video_settings` est enregistré à chaque `/generate` (comme `video_prompt`) ; `video_settings.duration` remplace `video_duration` dans le corps de `/generate`, et la colonne `reports.video_duration` reste remplie avec la même valeur (versions, relecture, « Régénérer » existant) ; si `reports.music` a des ids valides (choisis à la pré-écoute), ils sont utilisés, sinon `music.choose`. Mélange : volume de la musique = `0.15 + 0.85 * mix / 100`, la compression latérale actuelle (sidechain) reste. Morceau final : démarre au début du dernier segment de titre si `fin == touchante` (fondu enchaîné de 2 s avec le morceau principal), sinon pas de morceau final. Crédits : si au moins un morceau a un `credit`, un carton de titre final de 3 s « Musique » + lignes de crédit est ajouté avant `mix_music`. `video_base.mp4` = film monté sans musique, crédit compris. Partie `music` : refait seulement `mix_music` à partir de `video_base.mp4` ; s'il n'existe pas, erreur « Ce film date d'avant le choix des musiques : régénère le film une fois. »

- [ ] **Step 1: Write the failing tests** (petits médias générés par ffmpeg lavfi : photo 2 s, catalogue de 2 morceaux sinus) : `test_render_keeps_base_and_adds_music` (la sortie a une piste audio, `video_base.mp4` existe, même durée ± 0,1 s) ; `test_credit_card_added_for_cc_by` (le plan rendu se termine par un titre contenant « Kevin MacLeod ») ; `test_remix_changes_track_only` (après `remix`, `video_base.mp4` est inchangé (même taille) et `reports.music.main_id` est le nouvel id) ; `test_remix_without_base_errors` (message attendu ci-dessus) ; `test_no_track_renders_silent_music` (catalogue vide → film rendu, pas d'exception).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: musique choisie par réglages, crédit CC BY et remixage seul`

### Task 8: Pré-écoute

**Files:**
- Modify: `backend/app/main.py` (route)
- Test: `backend/tests/test_api_music.py::test_preview_*`

**Interfaces:**
- Produces: `POST /api/events/{slug}/music/pick` (en-tête `x-admin-token`), corps `{"tones": [...] | null, "video_settings": {...}, "exclude": [ids]}` → `{"main": public | null, "final": public | null, "message": str}` ; enregistre le choix dans `reports.music`. `message` = « Aucune musique ne correspond à ces réglages : le film sera sans musique. » si `main` est vide.

- [ ] **Step 1: Write the failing tests** : `test_preview_returns_and_stores_pick` ; `test_preview_other_title_uses_exclude` (deux appels, le second avec `exclude=[premier]` → autre id) ; `test_preview_empty_catalogue_message`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: pré-écoute et choix du morceau avant génération`

### Task 9: Écrans Génération, création, réglages et relecture

**Files:**
- Create: `frontend/src/Chips.jsx` (`<Chips options={[[key,label]]} value={[keys]} max={n} onChange disabled />` ; `max=1` = choix unique)
- Modify: `frontend/src/Generate.jsx`, `frontend/src/Home.jsx`, `frontend/src/Settings.jsx`, `frontend/src/Review.jsx`, `frontend/src/Published.jsx`, `frontend/src/Versions.jsx`, `frontend/src/styles.css`

Écran Génération (maquette validée, PR 1) : sections repliables `<details open>` **Histoire** (type, ton 2 max, fin), **Musique** (genres multiples, curseur énergie « Calme » → « Survolté », curseur mélange « Sons réels » → « Musique »), **Format** (durée 30 s à 5 min en puces, interrupteur « Sous-titres des citations », consignes existantes). Les sections Montage et Cadrage arrivent en PR 2 : ne pas afficher de réglage inactif. Changer le type pré-remplit tons, genres, énergie et fin depuis `config.defaults` (en gardant ce que l'organisateur a déjà modifié à la main depuis l'ouverture de l'écran). Le ton modifié ici est enregistré sur l'événement (`PUT /settings`) au moment de générer, avec la mention « Le ton s'applique au récit et au film ». En bas : pré-écoute (`<audio>` 15 s via `#t=0,15`, titre, artiste, bouton « Autre titre », message s'il n'y a rien), puis « Générer ». Création (Home) et Réglages : ton en puces (2 max) pré-rempli selon le type. Relecture : bouton « Changer la musique » sous le film, qui ouvre la même pré-écoute puis lance `parts: ["music"]`. Publication et versions : afficher le crédit musique sous le lecteur.

- [ ] **Step 1:** `npm run build` → OK.
- [ ] **Step 2: Vérification dans le navigateur** (`docker compose` local avec `DOMAIN=localhost`, `ADMIN_CODE=test`, démo activée, et un `docker-compose.override.yml` **non commité** qui publie `8000:8000` sur le service `app`, puisqu'en local il n'y a pas de Traefik) : sur la démo « Week-end entre copains », l'écran Génération affiche Drôle + Festif, Pop/Électro/Funk, énergie 4, fin Festive ; la pré-écoute propose un morceau non mélancolique ; « Autre titre » en change ; passer en Tendre + fin Touchante fait apparaître un morceau final ; à 375 px de large, rien ne déborde.
- [ ] **Step 3: Commit** `feat: écran Génération par sections, ton en puces et changer la musique`

### Task 10: Vérification de bout en bout

- [ ] **Step 1:** Tous les tests backend → PASS ; `npm run build` → OK.
- [ ] **Step 2:** Sur la démo locale, générer un film de 1 min (`ANTHROPIC_API_KEY` si disponible, sinon mode local) : la vidéo a une musique du catalogue, le crédit en fin de film, aucun morceau `melancolique` ; « Changer la musique » produit un nouveau film en moins d'une minute avec les mêmes plans.
- [ ] **Step 3:** Ouvrir un événement créé avant la PR (copie de la base de production si disponible, sinon base de démo de `main`) : s'affiche, se régénère.
- [ ] **Step 4:** Mettre à jour `README.md` (réglages, catalogue, ajout de musiques, crédit CC BY) ; commit `docs: réglages vidéo et catalogue musical` ; ouvrir la PR vers `main`.
