"""Produit un docker-compose autonome pour le VPS, sans dépôt Git : tout le code source (texte)
est embarqué dans un Dockerfile intégré, et les fichiers binaires (musiques, médias de démo,
icônes) sont régénérés pendant le build par les scripts de tools/.

    python tools/make_vps_compose.py   →   deploy/docker-compose.vps.yml
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    "backend/requirements.txt", "frontend/package.json", "frontend/package-lock.json",
    "frontend/vite.config.js", "frontend/index.html", "frontend/public/manifest.webmanifest",
    "frontend/public/sw.js", "tools/make_music.py", "tools/make_demo.py", "tools/make_icons.py",
    "music/LISEZMOI.txt",
]
tracked = subprocess.run(["git", "ls-files", "backend/app", "frontend/src"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split()
FILES += sorted(tracked)

parts = ["# syntax=docker/dockerfile:1", "FROM scratch AS src"]
for i, f in enumerate(FILES):
    text = (ROOT / f).read_text()
    tag = f"SOUVENIRS_EOF_{i}"
    assert tag not in text
    if not text.endswith("\n"):
        text += "\n"
    parts.append(f"COPY <<'{tag}' /{f}\n{text}{tag}")

parts.append(r"""
FROM python:3.12-slim-bookworm AS assets
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir numpy pillow
WORKDIR /src
COPY --from=src /tools ./tools
COPY --from=src /music ./music
RUN python tools/make_music.py && python tools/make_demo.py && python tools/make_icons.py /src/icons

FROM node:22-alpine AS web
WORKDIR /web
COPY --from=src /frontend/package.json /frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --from=src /frontend/ ./
COPY --from=assets /src/icons/ ./public/
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
      fonts-lato fonts-dejavu-core fonts-liberation tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=src /backend/requirements.txt .
RUN pip install -r requirements.txt
COPY --from=src /backend/app ./app
COPY --from=assets /src/music ./music
COPY --from=assets /src/demo ./demo
COPY --from=web /web/dist ./static
RUN useradd -u 1000 -m souvenirs && mkdir /data && chown souvenirs /data
USER souvenirs
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]""")
dockerfile = "\n".join(parts) + "\n"

compose = (ROOT / "docker-compose.yml").read_text()
inline = "\n".join(("        " + ln) if ln else "" for ln in dockerfile.replace("$", "$$").split("\n"))
build = "    build:\n      context: .\n      dockerfile_inline: |\n" + inline.rstrip() + "\n    pull_policy: build\n"
head = ("# Généré par tools/make_vps_compose.py — ne pas modifier à la main.\n"
        "# Tout le code est intégré ci-dessous : aucun dépôt Git n'est nécessaire sur le VPS.\n")
compose = re.sub(r"^# Souvenirs.*?\n(?=x-env)", head, compose, flags=re.S)
compose = compose.replace("  app:\n    build: .\n", "  app:\n" + build, 1)
compose = compose.replace("  worker:\n    build: .\n", "  worker:\n    pull_policy: never\n", 1)
compose = compose.replace("    depends_on:\n      - app\n", "    depends_on:\n      app:\n        condition: service_started\n", 1)
out = ROOT / "deploy" / "docker-compose.vps.yml"
out.parent.mkdir(exist_ok=True)
out.write_text(compose)
(ROOT / "deploy" / "Dockerfile.vps").write_text(dockerfile)
print(out, f"{len(compose) // 1024} Ko")
