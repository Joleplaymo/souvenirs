# --- Interface (PWA React) ---
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Application + tâches de fond (FFmpeg, Whisper, WeasyPrint) ---
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
      fonts-playfair-display fonts-lato fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY music ./music
COPY demo ./demo
COPY --from=web /web/dist ./static
RUN useradd -u 1000 -m souvenirs && mkdir /data && chown souvenirs /data
USER souvenirs
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
