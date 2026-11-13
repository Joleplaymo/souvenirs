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
| `frontend/` | interface React (Vite), installable sur l'écran d'accueil |
| `music/` | musiques de fond synthétisées, libres de droits (`tools/make_music.py`) |
| `demo/` | médias de l'événement de démonstration (`tools/make_demo.py`) |

## Déploiement sur le VPS Hostinger

Le projet Docker `souvenirs` du VPS est créé depuis l'adresse de ce dépôt
(`https://github.com/Joleplaymo/souvenirs`) : le Docker Manager de Hostinger clone le dépôt,
construit l'image avec `docker-compose.yml` et la lance derrière le Traefik du VPS. Les variables
(`DOMAIN`, `ADMIN_CODE`, `ANTHROPIC_API_KEY`…) sont stockées dans l'environnement du projet.
Pour déployer une nouvelle version : pousser sur `main`, puis recréer le projet avec la même adresse
(les données restent dans le volume `souvenirs_data`).
