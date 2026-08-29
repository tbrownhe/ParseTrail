# ParseTrail Development Guide

A quick-start for working on ParseTrail locally with Docker. Designed for a skilled hobbyist: minimal steps, clear defaults, no reverse proxy required in dev.

## Prereqs
- Docker: Docker Desktop on Windows/macOS is fine for dev; Docker Engine on Linux.
- A populated `.env` in the repo root (start from `.env.local.example`)

## Run the stack
Local development explicitly combines the production definition with
`docker-compose.dev.yml`. The development file is intentionally not auto-applied,
so a production command cannot accidentally publish local ports or disable
Traefik labels. To start:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm prestart bash scripts/migrate.sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Migration is a separate command by design. Normal service startup never changes
the database schema as a side effect.

Key ports (override file):
- Backend API: http://localhost:8000 (docs at /docs, ReDoc at /redoc)
- Frontend (dev build): http://localhost:8080
- Adminer (DB UI): http://localhost:8090
- Website static: http://localhost:80
- Postgres exposed for tools: localhost:5432

Useful commands:
- Follow logs: `docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f`
- Service logs: `docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f backend`
- Rebuild after code/env changes: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`
- Stop: `docker compose -f docker-compose.yml -f docker-compose.dev.yml down`

## Working on services
- **Backend**: With containers running, code changes auto-reload via volume mounts. To run locally instead of in Docker:
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.dev.yml stop backend prestart
  cd backend
  fastapi dev app/main.py
  ```
- **Frontend**: To use Vite dev server instead of the container:
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.dev.yml stop frontend
  cd frontend
  npm install   # first time
  npm run dev -- --host
  ```
  The default API target in dev is `http://localhost:8000` (set via override build args).
- **Database**: Access psql in the running container:
  ```bash
  docker exec -it parsetrail-db-1 psql -U postgres -d app
  ```

## Env hints
- `DOMAIN=localhost` and `BACKEND_CORS_ORIGINS` in `.env` should include your dev origins (`http://localhost:8000`, `http://localhost:8080`, etc.).
- If you change `.env`, restart the stack
  (`docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`)
  to propagate values.

## Testing without a proxy
Local dev hits containers directly. Reverse proxies are only required for staging/prod; you can ignore proxy setup while developing locally.
If you want an example, `docker-compose.traefik.yml` is included for illustration only - a different version is used by the ParseTrail server. Use it as a reference or starting point if you choose to run Traefik yourself.

## Pre-commit hooks (optional but recommended)
Install and enable hooks to catch lint/format issues before committing:
```bash
uvx pre-commit install
```
Then commit as usual; safe fixes will be applied automatically. To check the
entire repository:
```bash
uvx pre-commit run --all-files
```
