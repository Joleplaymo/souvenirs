# Souvenirs

Application web (PWA) qui transforme ce qu'un groupe enregistre pendant un événement — dictées,
conversations, vidéos, photos, notes — en compte rendu écrit, en film monté et en album photo PDF.

## Lancement

```bash
cp .env.example .env    # puis renseigner DOMAIN, ADMIN_CODE, ANTHROPIC_API_KEY
docker compose up -d --build
```

Deux services derrière le Traefik du VPS (qui gère HTTPS) : `app` (API FastAPI + interface) et
`worker` (Whisper, FFmpeg, appels Claude, PDF, purge). Toutes les données sont dans le volume `data`.

L'événement de démonstration « Week-end entre copains » est créé au premier démarrage ; on le
retrouve sur la page d'accueil, dans « Mes événements », après saisie du code administrateur.

## Organisation du code

| Dossier | Contenu |
|---|---|
| `backend/app/main.py` | API HTTP, liens secrets, envois par morceaux, publication |
| `backend/app/worker.py` | file de tâches de fond, purge des fichiers bruts |
| `backend/app/pipeline/` | `transcribe` (Whisper), `ai` (Claude), `video` (FFmpeg), `album` (PDF), `generate` (enchaînement) |
| `backend/tests/` | tests du backend (pytest) |
| `frontend/` | interface React (Vite), installable sur l'écran d'accueil |
| `music/` | catalogue musical : 4 morceaux synthétisés libres de droits (`tools/make_music.py`) et ~40 morceaux Kevin MacLeod (Incompetech, CC BY 4.0) téléchargés au démarrage dans le volume de données (`tools/fetch_music.py`) ; le crédit est ajouté en fin de film |
| `demo/` | médias de l'événement de démonstration (`tools/make_demo.py`) |

## Réglages vidéo et musique

L'écran « Générer » est rangé en quatre sections : Histoire, Musique, Montage, Format. Tout est
pré-rempli selon le type d'événement ; ce que tu as modifié à la main n'est pas écrasé quand tu changes
de type.

- **Ton** : 10 choix, 2 au maximum. Le même ton sert au compte rendu écrit et au film ; le changer à
  la génération le change pour l'événement entier. Il est pré-rempli selon le type d'événement
  (10 types). Les anciens tons et types sont convertis automatiquement au démarrage.
- **Rythme du montage** : Posé (plans de 3 à 5 s, fondus), Dynamique (1,5 à 3 s, coupes calées sur
  les temps de la musique), Clip nerveux (0,5 à 1,5 s, coupes franches, quelques plans plus longs).
- **Effets** (interrupteurs) : ralentis, accélérés, arrêts sur image, effets humoristiques (zoom
  comique), sous-titres des citations. Un effet coupé n'est jamais utilisé.
- **Style des titres** : Carnet manuscrit (police Caveat, licence OFL, dans `backend/app/fonts`),
  Sobre, Pop coloré, ou Aucun (plus de cartons de séquence ; le carton de crédit musique reste).
- **Cadrage** : horizontal 16:9, vertical 9:16 ou carré 1:1. L'image est toujours entière, sur un
  fond flou : jamais d'étirement ni de recadrage qui couperait un visage.
- **Évolution de la musique** : Constante, Montée progressive (début, cœur, sommet), Calme puis
  explosion, Festif puis émotion. Les morceaux s'enchaînent en fondu de 2 s au début des séquences ;
  un morceau qui durerait moins de 4 s est retiré, et le morceau principal est toujours joué.
- **Préréglages** : « Enregistrer comme préréglage » garde les tons et les réglages du film (pas le
  type ni les consignes) ; ils sont proposés en haut de l'écran pour tous les événements.
- **Catalogue musical** (`music/catalogue.json`) : chaque morceau est étiqueté par genre, énergie
  (1 à 5) et humeur. L'appli filtre le catalogue d'après les réglages, sans laisser l'IA interpréter
  librement. Règle anti-mélancolie : aucun morceau mélancolique ou triste, sauf si le ton contient
  Tendre ou Nostalgique (exception : la séquence finale d'une fin Touchante ou de l'évolution
  « Festif puis émotion »). Les fichiers
  téléchargés trop petits ou illisibles sont refusés, et un morceau illisible n'est jamais choisi.
- **Pré-écoute** : 15 s de chaque morceau proposé (Début, Cœur, Sommet, Final selon l'évolution),
  chacun avec « Autre titre » pour en changer avant de générer.
- **Relecture** : « Changer la musique » remplace la bande-son sans refaire le montage.
- **Bibliothèque Incompetech** (Kevin MacLeod, CC BY 4.0) : téléchargée au démarrage du worker dans
  le volume de données, une seule fois. Pour le faire à la main : `python tools/fetch_music.py
  [--dest DOSSIER]`. Le crédit est ajouté automatiquement en fin de film.
- **Tes propres MP3** : écran « Musiques » (30 Mo maximum par fichier, licence à renseigner).

## Tests

Les tests du backend tournent dans Docker (Git Bash sous Windows ; sous Linux ou macOS, remplacer
`$(pwd -W)` par `$PWD` et supprimer `MSYS_NO_PATHCONV=1`) :

```bash
docker build -t souvenirs:dev .
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/backend/app:/app/app" -v "$(pwd -W)/backend/tests:/app/tests" -v "$(pwd -W)/music:/app/music" -e DATA_DIR=/tmp/data -e ADMIN_CODE=test souvenirs:dev sh -c "pip install -q --user pytest httpx && python -m pytest -q -p no:cacheprovider tests"
```

## Déploiement sur le VPS Hostinger

Le projet Docker `souvenirs` du VPS est créé depuis l'adresse de ce dépôt
(`https://github.com/Joleplaymo/souvenirs`) : le Docker Manager de Hostinger clone le dépôt,
construit l'image avec `docker-compose.yml` et la lance derrière le Traefik du VPS. Les variables
(`DOMAIN`, `ADMIN_CODE`, `ANTHROPIC_API_KEY`…) sont stockées dans l'environnement du projet.
Pour déployer une nouvelle version : pousser sur `main`, puis recréer le projet avec la même adresse
(les données restent dans le volume `souvenirs_data`).
