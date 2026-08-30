# Web and desktop authentication boundaries

ParseTrail deliberately has two authentication transports for two different
clients. They use the same short-lived, session-versioned JWT format, but they do
not store or transmit it in the same way.

## Desktop and API clients

The desktop application authenticates at `POST /api/v1/login/access-token`, stores
the returned bearer token in the operating system credential store, and sends it
in the `Authorization` header. This endpoint remains OAuth2-compatible for the
desktop client and direct API tooling. Bearer-authenticated requests do not require
a browser `Origin` header.

## Dashboard browser session

The dashboard authenticates at `POST /api/v1/login/browser-session`. The response
returns the public user record, never the JWT. The API stores the JWT in a
host-only cookie with these attributes:

- `HttpOnly`
- `SameSite=Strict`
- `Path=/`
- `Secure` outside the local environment
- the `__Host-parsetrail_session` name outside the local environment

Local HTTP development uses the unprefixed `parsetrail_session` name because a
`__Host-` cookie requires HTTPS. The frontend fetch client uses
`credentials: "include"`; the API's CORS policy allows credentials only for its
explicit configured origins.

The browser login and logout endpoints require the request `Origin` to equal
`FRONTEND_HOST`. Every state-changing request authenticated by the cookie has the
same check. A bearer token takes precedence when both transports are supplied, so
existing non-browser API clients remain independent of browser CSRF controls.

Logout deletes the cookie but does not maintain a server-side JWT denylist.
Password changes, password resets, and email verification increment the user's
`session_version`, which invalidates previously issued bearer tokens and cookies.
Normal expiry remains two days.

## Security limits

Moving the dashboard token out of Web Storage prevents injected JavaScript from
reading and exporting the credential. It does not make an active cross-site
scripting flaw harmless: code executing in the dashboard origin can still make
requests as the current user. Safe rendering, dependency hygiene, browser security
headers, and bounded server authorization remain necessary defenses.

The production and staging deployment contract is:

- `FRONTEND_HOST` is the exact HTTPS dashboard origin, with no path.
- `BACKEND_HOST` is the public versioned API base and ends in `/api/v1`.
- the dashboard and API are served over HTTPS.
- CORS does not use wildcard origins with credentials.

Backend tests cover cookie attributes, login/logout origin rejection, CSRF rejection,
session use, and unchanged bearer behavior. The Playwright login suite checks the
real production-style frontend/API boundary and verifies that no access token is
written to `localStorage` or `sessionStorage`.
