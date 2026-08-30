# Pin the multi-platform manifest so a release rebuild cannot silently change
# its web server base.
FROM nginx:1.28.0-alpine@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284

LABEL org.opencontainers.image.source="https://github.com/tbrownhe/ParseTrail" \
      org.opencontainers.image.description="ParseTrail public website" \
      org.opencontainers.image.licenses="MIT"

# Copy website files to the appropriate directory
COPY ./website /usr/share/nginx/html
COPY ./website/nginx.conf /etc/nginx/conf.d/default.conf
COPY ./deployment/web-runtime-config.sh /docker-entrypoint.d/40-parsetrail-runtime-config.sh

RUN chmod -R 755 /usr/share/nginx/html \
    && chmod 0555 /docker-entrypoint.d/40-parsetrail-runtime-config.sh
