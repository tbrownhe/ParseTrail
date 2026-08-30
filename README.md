# ParseTrail

ParseTrail is a local-first personal-finance desktop application for Windows and
macOS. It parses PDF, CSV, and XLSX statements into a local SQLite database,
supports overlapping exports and multi-account statements, categorizes
transactions with a local model, and provides account, budget, recurring-charge,
and reporting workflows.

The public service at [parsetrail.com](https://parsetrail.com/) distributes the
desktop installers and signed parser catalog. An account is needed for plugin
downloads and for the optional statement-contribution workflow. Normal statement
imports and financial analysis do not require the server.

## The three data boundaries

ParseTrail is easiest to understand as three systems with deliberately different
data:

```text
ordinary statement ──> desktop parser ──> local SQLite database
        │                                      + local statement archive
        │
        └─ only after explicit confirmation ─> encrypted contribution ─> API

public website/dashboard ─> account, artifact, and submission API ─> PostgreSQL
                                                              └──> ciphertext files
```

1. **Local finance data.** Transactions, balances, account identifiers,
   categories, models, imported source statements, and database backups remain on
   the user's device. ParseTrail does not encrypt the SQLite database, managed
   statement archive, backups, or application logs. Use device encryption and an
   appropriate backup system.
2. **Explicit statement contributions.** A statement is uploaded only after the
   user selects **Statements > Send for Plugin Development**, completes the
   metadata form, and confirms. The client encrypts the selected bytes in memory.
   The server decrypts them in memory and immediately re-encrypts them for storage;
   no plaintext compatibility file is created. The original filename,
   institution, frequency, comments, account association, IP address, user agent,
   and timing remain visible to the service as plaintext metadata.
3. **Public account and artifact service.** The FastAPI/PostgreSQL service stores
   dashboard accounts, password hashes, session/version state, artifact-download
   audit data, contribution metadata, and encrypted contribution files. It does
   not receive the desktop SQLite database or ordinary imports.

The detailed inventory and the limits of the encryption design are in
[Privacy and data flow](docs/privacy-and-data-flow.md). The security assumptions
and response priorities are in the [threat model](docs/threat-model.md).

## Artifact trust

Parser plugins and desktop installers are described by immutable manifests whose
exact bytes are signed with an offline Ed25519 key. Distributed clients contain
only public keys. Before activation, the client verifies the manifest signature,
release sequence, compatibility metadata, filenames, sizes, and SHA-256 digests.
The public server is therefore an artifact host, not a signing authority.

The entire plugin catalog is installed as one authenticated release. Python
bytecode is neither encryption nor obfuscation; signatures detect modification
but do not prevent inspection or decompilation.

## Parser architecture

Source parsers live in `client/src/parsetrail/plugins` and implement the stable
`IParser` interface. Routing is deterministic: suffix, optional PDF metadata,
optional page-header markers, then a normalized body-text expression. Parsing
fails safely if zero or multiple plugins remain.

Routing expressions support `&&`, `||`, parentheses, and quoted literals. A
plugin can add a classification rule when statement generations share the same
body marker:

```python
ROUTING_RULE = {
    "pdf_metadata_keys": ["Creator", "Producer"],
    "pdf_metadata": {"Creator": '"statement engine"'},
    "header": '"Sale Post Description Amount"',
}
```

Extracted statement text and PDF metadata values stay in memory and are excluded
from routing diagnostics.

## Repository map

- `client/` — PySide6 desktop application, SQLite schema, parsers, artifact release tooling
- `backend/` — FastAPI account, artifact, and encrypted-contribution service
- `frontend/` — React dashboard for account and administrative workflows
- `website/` — static public site and download/plugin listings
- `devtools/` — local-only parser and acceptance tools; not distributed
- `scripts/deployment/` — immutable server build, deploy, smoke, and rollback tooling
- `docs/` — privacy, security, migration, rollback, and operator runbooks

## Start here

- [Contributor setup and local development](development.md)
- [Desktop architecture, tests, and releases](client/README.md)
- [Backend operations and tests](backend/README.md)
- [Server deployment runbook](deployment.md)
- [Security policy](SECURITY.md)

Official desktop releases support Windows x64 and macOS. Linux source execution
is experimental: there is no tested Linux installer yet.

## Contributing

Bug reports, parser fixtures, and pull requests are welcome. Do not commit real
statements, client databases, credentials, signing keys, decrypted server
submissions, or generated Playwright authentication state. Parser pull requests
should include synthetic or sanitized tests whenever possible.

To request a parser for a real statement without publishing it, use the explicit
encrypted contribution workflow in the desktop app. The project is maintained as
a public personal project; response times and institution coverage are not a
commercial service commitment.

## License and origins

ParseTrail is released under the MIT License. The server/dashboard began from
the [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template),
and the public site's visual design began from an
[HTML5 UP](https://html5up.net/) template. The application architecture and both
templates have since been substantially modified.
