# Threat model

## Scope and priorities

ParseTrail handles two distinct classes of sensitive data:

1. the complete local finance dataset on a user's device; and
2. statements explicitly contributed to the server for parser development.

The primary server-side threat is an attacker gaining access to the self-hosted
server and recovering contributed statement plaintext. The primary desktop threat
is loss or compromise of a device containing the unencrypted SQLite database and
statement archive. Artifact integrity is a separate priority because a modified
parser executes inside the trusted desktop process.

The desired order of protection is:

- prevent silent execution of modified plugins or installers;
- keep ordinary financial data off the server;
- prevent plaintext statement files from being left on server or developer disks;
- limit and accurately disclose server metadata;
- preserve recoverability without turning backups into an untracked disclosure.

## Trust boundaries and assets

| Boundary | Sensitive assets | Trusted components |
| --- | --- | --- |
| Desktop | SQLite database, statement archive, backups, reports, logs, API token | installed client, OS account, OS credential store, signed plugins |
| Contribution transit | selected statement bytes, per-upload key, account token, plaintext metadata | client process, HTTPS endpoint, active RSA submission key |
| Server | PostgreSQL, ciphertext files, AES master key, RSA private generations, SMTP/API secrets, logs | Linux host, Docker/Traefik, backend process, operator |
| Release | Ed25519 private key, trusted public-key store, immutable manifests, source tags | offline builder, reviewed source, local release tools |

The public artifact server, network, and registry are not trusted to author a
release. They are trusted only for availability because the client verifies the
offline signature and every artifact digest.

## Threats and current controls

### Malicious or compromised artifact host

An attacker can replace, remove, replay, or partially serve public files. The
client verifies the signed manifest, safe names, sizes, compatibility, hashes,
release sequence, and complete staged catalog before activation. Existing verified
plugins remain active on failure. Availability attacks remain possible.

### Offline release-key compromise

Possession of the Ed25519 private key permits creation of a catalog or installer
manifest that existing clients trust. The key is encrypted, kept outside the
repository/server/CI, and its passphrase is entered interactively. This is a
high-severity incident that requires a client trust-store update and removal of the
old public key; merely cleaning the server is insufficient.

### Live server compromise

The running backend can access the PostgreSQL database, RSA submission keyring,
AES master key, and stored ciphertext. A live attacker with equivalent access may
decrypt contributed statements. At-rest envelope encryption is not a defense
against this case. Host patching, least-access storage, key separation in backups,
bounded endpoints, reconciliation, and incident response reduce likelihood and
impact but do not make the server zero knowledge.

### Copied disk or backup

Statement ciphertext is useful only with the AES master key; an incoming payload
also needs the RSA private key during its short transit lifetime. PostgreSQL and
logs still reveal plaintext account and operational metadata. Backups must keep
the database/ciphertext and keys access-controlled and should be encrypted by the
backup system.

### Cross-site scripting and request forgery

Untrusted website metadata is inserted as text. The dashboard JWT is held in a
host-only HttpOnly `SameSite=Strict` cookie, never Web Storage. Browser login,
logout, and cookie-authenticated mutations require the exact configured dashboard
origin, and CORS uses explicit credentialed origins. XSS in the dashboard origin
could still act as the user while the page is open; HttpOnly prevents reading and
exporting the credential, not same-origin actions.

### Malicious, ambiguous, or malformed statements

Statement files are untrusted parser input. Size limits, deterministic unique
routing, typed validation, bounded user messages, transactional imports, duplicate
fingerprints, and archive recovery reduce corruption and disclosure. Parser code
is still trusted application code and receives statement plaintext in memory.

### Local device loss or malware

ParseTrail currently leaves the database, archive, backups, logs, and models
plaintext. Device encryption and OS access controls are the current control.
Application-level database/archive encryption is intentionally a future design
decision because key loss and restore behavior must be solved first.

### Maintainer/operator error

This is a single-maintainer project, so mistaken releases, migrations, key copies,
or restore assumptions are realistic threats. Clean/tagged builds, immutable
records, explicit migrations, staging/rollback gates, dry-run release modes,
checksums, and restore evidence are designed to turn memory-dependent operations
into reviewed procedures.

## Explicitly accepted current risks

- Windows installers are not Authenticode-signed and macOS packages are not
  notarized; users must bypass initial operating-system warnings.
- Local finance data is not application-encrypted.
- A live server/operator compromise can decrypt contributed statements.
- Contribution metadata, account data, download audit data, and logs are plaintext.
- Account deletion does not currently erase historical contribution ciphertext,
  contribution rows, download rows, logs, or backups.
- Linux packaging and secure-keyring behavior are not release-tested.
- The project has one active maintainer and no staffed security response SLA.

These are constraints to disclose and revisit, not reasons to weaken the controls
that already exist.

## Out of scope

ParseTrail does not connect directly to bank APIs, hold bank login credentials,
move money, provide tax/legal/investment advice, or protect a device already
controlled by malware running as the user. Institution parsers cannot establish
that a supplied document is authentic; they validate expected structure and
financial consistency.

See [Privacy and data flow](privacy-and-data-flow.md) for the exact persistence
inventory and [Release and incident response](release-and-incident-response.md)
for operational actions.
