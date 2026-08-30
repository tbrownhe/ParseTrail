# ParseTrail dashboard

The dashboard is a React/TypeScript account and administration surface built with
Vite, TanStack Query/Router, and Chakra UI. Financial transactions and the desktop
SQLite database are not synchronized to it.

## Development

Use the Node release recorded in `.nvmrc` (Node 22.22.0):

```bash
cd frontend
nvm install
nvm use
npm ci
cp .env.example .env
npm run dev
```

The Vite server is <http://localhost:5173>. `frontend/.env.example` supplies the
local API base `http://localhost:8000/api/v1`. Production-like containers ignore
Vite build-time configuration and generate a validated `runtime-config.js` from
`BACKEND_HOST`, `FRONTEND_HOST`, and `GITHUB_URL` at startup.

Common checks leave handwritten and generated source unchanged:

```bash
npm run lint
npm run test:website
npm run build
```

Use `npm run lint:fix` only when you intend to apply formatting fixes.

## Generated API client

After a backend schema change, run this from the repository root:

```bash
./scripts/generate-client.sh
```

The cross-platform equivalent from `frontend` is:

```bash
npm run generate-client
```

The generator exports OpenAPI from the locked backend and rewrites only
`src/client/generated`. Do not edit that directory by hand. Dashboard-specific
compatibility code belongs in `src/client` above it, and generated changes are
committed with the API change.

## Browser authentication

The dashboard obtains a host-only HttpOnly session cookie from the browser-session
login endpoint. It never writes a bearer token to Local Storage or Session
Storage. Requests include credentials explicitly; unsafe cookie-authenticated
requests must carry the exact configured dashboard origin. Desktop and other API
clients continue to use bearer tokens. Details are in
[docs/web-authentication.md](../docs/web-authentication.md).

## End-to-end tests

Playwright must run against the disposable CI stack, not a developer or production
database. From the repository root:

```bash
docker compose -f docker-compose.ci.yml up -d --build --wait
cd frontend
npm ci
npx playwright install chromium
npx playwright test
cd ..
docker compose -f docker-compose.ci.yml down -v --remove-orphans
```

Tests write authentication state under `frontend/playwright/.auth`; the directory
is ignored and must never be committed. `npx playwright test --ui` is available
for an interactive local run against the same disposable stack.

## Source map

- `src/client/generated` - generated OpenAPI transport and schemas
- `src/client` - stable compatibility facade
- `src/components` - shared account/admin UI
- `src/hooks` - authentication and query hooks
- `src/routes` - eagerly guarded, lazily rendered routes
- `src/theme.tsx` - Chakra theme
