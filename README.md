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

## Déploiement sans dépôt Git

`python tools/make_vps_compose.py` produit `deploy/docker-compose.vps.yml`, un fichier Compose
autonome : le code source y est intégré, et les musiques, médias de démo et icônes sont
régénérés pendant le build. C'est ce fichier qui est déployé sur le VPS par le connecteur Hostinger.
