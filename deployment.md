# ParseTrail Deployment

This repo ships the ParseTrail backend, frontend dashboard, and static site. It no longer bundles a production reverse proxy; bring your own (Caddy, NGINX, or Traefik in a separate repo) to terminate TLS and route to the app containers. A stock `docker-compose.traefik.yml` is included for illustration only (a different one is used in production) but can be a starting point if you want to run Traefik yourself. See the [full-stack-fastapi-template
](https://github.com/fastapi/full-stack-fastapi-template) for thorough details on Traefik setup for a stack like this one.

## What you need
- Docker Engine on the target host (use Docker Desktop only for local dev; production should run Docker Engine on a Linux server or similar).
- A domain or LAN IP and DNS pointing to the host.
- A reverse proxy you control that can forward:
  - `api.${DOMAIN}` → backend container port 8000
  - `dashboard.${DOMAIN}` → frontend container port 80
  - `${DOMAIN}` and `www.${DOMAIN}` → website container port 80
- (Optional) GitHub Actions runner if you want CI/CD.

## Configure `.env`
Edit the root `.env` before running Docker. Key fields:

**Core**
- `ENVIRONMENT`: `local`, `staging`, or `production`.
- `DOMAIN`: `localhost` for local, LAN IP for intranet, public domain for prod.
- `BACKEND_CORS_ORIGINS`: Comma list with scheme/host/port. Examples:
  - Local: `"http://localhost,http://localhost:5173"`
  - Prod: `"https://api.${DOMAIN},https://dashboard.${DOMAIN}"`
- `FRONTEND_HOST`: URL the backend uses in emails. Match your dashboard origin (e.g., `http://localhost:5173` or `https://dashboard.${DOMAIN}`).

**Secrets**
- `MASTER_KEY`, `BACKUP_KEY`, `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD`:
  - Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- `FIRST_SUPERUSER`: email for the initial admin.
- SMTP: `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAILS_FROM_EMAIL`, `SMTP_TLS`, `SMTP_SSL`, `SMTP_PORT`.
- Swagger basic auth: create `SWAGGER_HASH` with `htpasswd -nb admin SWAGGER_PW`.

**Database**
- `POSTGRES_PASSWORD` (required), `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_PORT` (usually 5432). Host is fixed to the `db` service inside Compose.

**Images and permissions**
- `DOCKER_IMAGE_BACKEND`, `DOCKER_IMAGE_FRONTEND`: image names/tags to use or push.
- `DOCKER_GID`: host docker group id if you run a proxy with docker access.

**Data locations**
- Ensure these paths are not in the project folder to prevent accidental `git commit`.
- `STATEMENTS_DIR`: host path for statements received by backend (ensure secure permissions).
- `STATEMENTS_FILE_OWNER`, `STATEMENTS_FILE_GROUP`: numeric ids to chown files to.
- `CLIENTS_DIR`, `PLUGINS_DIR`, `MODELS_DIR`: host paths mounted into the backend for distributing built clients/plugins/models.

**Remote helpers (optional)**
- `REMOTE_HOST`, `REMOTE_USER`, `SSH_KEY_PATH`, `REMOTE_*_DIR`: used by build scripts when pushing artifacts to another host.

## Reverse proxy notes
- Local/dev (`docker compose up`): hit containers directly with `DOMAIN=localhost` and no reverse proxy.
- Staging/prod: bring your own proxy. Either:
  1) Run a proxy separately and point it at the container ports above, or
  2) If you still use Traefik elsewhere, attach this stack to the expected network name (`traefik-public` by default) or strip/replace the Traefik labels and network entries in `docker-compose.yml`.
- In staging/prod, terminate TLS at the proxy and forward plain HTTP to the containers.

## Running locally vs. production
- **Local/dev:** `docker compose up` (includes `docker-compose.override.yml`, exposes dev ports). Use `DOMAIN=localhost` and simple CORS.
- **Production/staging:** `docker compose -f docker-compose.yml up -d` (omit the override). Set real domain, tighten CORS, and run behind your proxy. Ensure the external network and labels are adjusted if you removed Traefik.

## Helpful commands
- Check resolved config: `docker compose -f docker-compose.yml config`
- Start/stop: `docker compose up -d` / `docker compose down`
- Rebuild: `docker compose -f docker-compose.yml up --build -d`
- Logs: `docker compose logs -f backend`
- DB shell: `docker exec -it parsetrail-db-1 psql -U postgres -d app`

## Permissions and security
- On the server, tighten perms: dirs `750`, files `640`, `.env` and sensitive files `600`.
- If you manage secrets outside `.env` (e.g., Docker Swarm secrets), update the compose or runtime env accordingly.

## CI/CD (optional)
You can run GitHub Actions runners on your host. Provide the same `.env` values as secrets, plus any registry credentials. Label runners by environment (e.g., `staging`, `production`) and have workflows target those labels.
