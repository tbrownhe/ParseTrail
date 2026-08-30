# Stage 0, "build-stage", based on Node.js, to build and compile the frontend
FROM node:22.22.0-bookworm-slim@sha256:dd9d21971ec4395903fa6143c2b9267d048ae01ca6d3ea96f16cb30df6187d94 AS build-stage

WORKDIR /app

COPY frontend/package*.json /app/

RUN npm ci

COPY frontend/ /app/

RUN npm run build


# Stage 1, based on Nginx, to have only the compiled app, ready for production with Nginx
FROM nginx:1.28.0-alpine@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284

LABEL org.opencontainers.image.source="https://github.com/tbrownhe/ParseTrail" \
      org.opencontainers.image.description="ParseTrail account dashboard" \
      org.opencontainers.image.licenses="MIT"

COPY --from=build-stage /app/dist/ /usr/share/nginx/html

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/nginx-backend-not-found.conf /etc/nginx/extra-conf.d/backend-not-found.conf
COPY deployment/web-runtime-config.sh /docker-entrypoint.d/40-parsetrail-runtime-config.sh

RUN chmod 0555 /docker-entrypoint.d/40-parsetrail-runtime-config.sh
