# syntax=docker/dockerfile:1

# ─── Stage 1 : build du frontend (SPA Vue) ───────────────────────────────────
FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ─── Stage 2 : backend Python + SPA buildé ───────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="FontSync" \
      org.opencontainers.image.description="Font manager self-hosted avec sync multi-machines temps réel" \
      org.opencontainers.image.source="https://github.com/leodurandfr/FontSync" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

# Version affichée dans l'interface (Réglages → Serveur). Injectée par la CI
# depuis le tag ou le nom de branche ; « dev » pour un build local, ce qui est
# la vérité — l'interface ne prétend pas connaître une version qu'on ne lui a
# pas donnée.
ARG FONTSYNC_VERSION=dev
ENV FONTSYNC_VERSION=${FONTSYNC_VERSION}

# Watchtower ne surveille que les conteneurs portant ce label (`--label-enable`),
# de sorte qu'installer FontSync ne fasse pas de Watchtower le gestionnaire de
# tout ce qui tourne sur le NAS.
LABEL com.centurylinklabs.watchtower.enable="true"

WORKDIR /app

# Dépendances Python (couche cachée séparément du code applicatif)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Migrations + code applicatif
COPY alembic.ini .
COPY alembic/ alembic/
COPY backend/ backend/

# SPA buildé (stage 1)
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

# Entrypoint : applique `alembic upgrade head` avant de lancer Uvicorn (P2.1)
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

# Healthcheck sans dépendance externe : python:slim n'embarque ni curl ni wget,
# mais /health est public (aucun token requis).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
