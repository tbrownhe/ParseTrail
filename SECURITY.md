# Security policy

## Supported versions

Only the latest published ParseTrail desktop, plugin catalog, and server release
receive security fixes. Keep the client and plugin catalog current.

## Reporting a vulnerability

Email `security@parsetrail.com`. Do not open a public issue for an unpatched
vulnerability and do not submit real financial statements as a proof of concept.

Include, when available:

- the affected version, release sequence, or Git commit;
- impact and the boundary involved (desktop, contribution, server, or release);
- minimal reproduction steps using synthetic/redacted data;
- relevant response headers, log excerpts, or hashes with credentials, tokens,
  keys, personal information, and statement content removed.

The project has one active maintainer and no guaranteed response SLA. A report
will be acknowledged as promptly as practical, then tracked privately through
triage, remediation, and coordinated disclosure.

## Security design

ParseTrail keeps ordinary financial data local but does not application-encrypt
the local SQLite database, statement archive, backups, or logs. Statement
contribution is a separate explicit encrypted workflow; its metadata is visible
to the service, and a live server with its keys can decrypt contributed files.
Plugins and installers use offline Ed25519 release signatures, which do not
replace Windows Authenticode or Apple notarization.

Read the exact claims and accepted risks before testing:

- [Privacy and data flow](docs/privacy-and-data-flow.md)
- [Threat model](docs/threat-model.md)
- [Release and incident response](docs/release-and-incident-response.md)

## Disclosure

Please avoid public discussion until the issue has been confirmed and a fix or
mitigation is available. Disclosure timing will be coordinated based on impact,
affected releases, and the availability of a safe update path.
