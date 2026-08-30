# Privacy and data flow

This document describes the data the current code can observe and persist. It is
an engineering inventory, not a claim that encryption eliminates every risk.

## 1. Local finance boundary

Ordinary PDF, CSV, and XLSX imports are opened by the desktop process and passed
to a selected parser. Parsed accounts, account-number history, statements,
transactions, categories, budgets, and import fingerprints are stored in the
configured SQLite database. The source file is either retained, copied to the
managed `SUCCESS` archive, or moved there according to the choice shown before
import. Failed and duplicate managed imports use the sibling `FAIL` and
`DUPLICATE` folders.

The following data is local and is not encrypted by ParseTrail:

- the SQLite database and its pre-migration `.dbb` recovery copies;
- user-created database backups and restored copies;
- the managed import/archive folders and the statement files in them;
- exported reports, local classifier models, and application logs;
- `config.json`, which contains paths, preferences, email, server URL, and token
  expiry metadata, but not the API bearer token;
- downloaded signed plugins, manifests, installers, and the cached public
  statement-submission key.

The API bearer token is stored in Windows Credential Locker, macOS Keychain, or a
supported Linux Secret Service/KWallet backend. If Linux has no secure backend,
the token is kept only for the process lifetime. Device encryption, operating
system login controls, filesystem permissions, swap/crash-dump policy, and the
user's backup encryption protect the local boundary.

## 2. Encrypted statement-contribution boundary

Contribution is separate from normal import. It starts only after a user selects
a file in **Statements > Send for Plugin Development**, enters institution,
frequency, and optional comments, and confirms the upload.

The transfer and storage sequence is:

1. The client reads the selected file into memory and generates a unique Fernet
   key.
2. It encrypts the statement in memory, encrypts the Fernet key with the server's
   active RSA public key using OAEP/SHA-256, and sends both over HTTPS.
3. The API authenticates the account, validates bounded metadata and sizes, and
   decrypts the submission key and statement in process memory.
4. The API immediately encrypts the plaintext with AES-GCM under `MASTER_KEY`.
   Only the new ciphertext is written to a same-directory `.tmp` file and
   atomically renamed to a generated `.enc` filename.
5. PostgreSQL records the AES-GCM IV and authentication tag plus the plaintext
   operational metadata listed below. If the database insert fails, the ciphertext
   file is removed.

Neither the desktop contribution path nor the server parse devtools create a
plaintext statement file. Plaintext can still exist in process memory and may be
captured by a compromised process, debugger, swap, hibernation image, or crash
dump.

### Plaintext contribution metadata

PostgreSQL stores:

- generated ciphertext filename;
- user-supplied original filename, institution, frequency, and comments as JSON;
- contributing user ID (or `NULL` after that account record is deleted);
- client IP address, user agent, server timestamp, and parser-development status;
- AES-GCM IV and authentication tag, which are not secret keys.

The service also writes bounded operational logs. The statement log includes IP
and user ID; web-server/proxy logs can include IP, method, path, status, user
agent, and timing. Operators should treat all logs and PostgreSQL backups as
confidential.

### What server-side encryption does and does not do

Envelope encryption helps when ciphertext storage or an offline backup is copied
without the active master key and submission-key material. It does not protect a
statement from a live backend compromise that can read the ciphertext and keys,
from an authorized operator using the decryption devtool, or from compromise of
the operator workstation while plaintext is being parsed. HTTPS remains required
even though the client also encrypts the statement payload.

The RSA submission keyring and AES master key are independent of the offline
Ed25519 artifact-signing key. Losing one does not grant the powers of another.

## 3. Public account and artifact boundary

The public PostgreSQL database stores these plaintext or one-way-derived values:

- account email, pending email, optional full name, active/admin flags, UUID,
  password hash, and token/reset/verification version counters;
- plugin downloads: plugin filename, IP, user agent, timestamp, and user ID;
- client downloads: platform, version, IP, user agent, and timestamp;
- statement public-key requests: key generation ID, IP, user agent, and timestamp;
- historical model-download audit rows with filename, IP, user agent, timestamp,
  and optional user ID;
- the statement-contribution metadata described above.

Artifact manifests, signatures, compiled plugins, and installers are public
files. API and reverse-proxy logs may duplicate request metadata. If Sentry is
enabled, request bodies, cookies, authorization headers, forwarded IP headers,
local variables, tracing, default PII, and log breadcrumbs are explicitly
excluded; event type, stack, route, and scrubbed request context may still leave
the host.

The service does **not** receive the desktop SQLite database, local categories,
budgets, models, reports, ordinary statement archives, or transactions except
when those facts are present inside a statement the user explicitly contributes.

Account deletion currently deletes the account row. Foreign-key-linked download
and contribution audit rows are retained with a null user ID, and encrypted
contribution files are not automatically erased. Backups and logs can also retain
historical data. This behavior must be considered before making an erasure promise.

## Artifact signature boundary

The offline Ed25519 private key signs the exact plugin or installer manifest. The
server stores only release files, detached signatures, and an atomic pointer to an
immutable release directory. A client trusts an artifact only after verifying:

- a signature from a bundled public key;
- a strictly increasing release sequence and non-reused release identity;
- safe filenames, platform/Python/client compatibility, and bounded sizes;
- each downloaded file's exact SHA-256 digest.

Signing detects unauthorized server or transport modification. It does not
encrypt public artifacts, prevent plugin decompilation, establish Windows/macOS
publisher identity, or make signed parser logic correct. Windows Authenticode and
Apple notarization are intentionally deferred.

## Backups and deletion

A complete local backup needs both the SQLite database and any statement archive
the user wants to retain; the in-app database backup excludes statement files. A
complete server recovery needs PostgreSQL, encrypted statement/artifact storage,
the RSA submission-key volume, and separately protected master-key configuration.
The offline Ed25519 private key is not a server recovery secret and must never be
copied to the server.

Restore procedures are security controls only when they are rehearsed. See the
[PostgreSQL upgrade/restore runbook](postgresql-17-upgrade.md),
[deployment runbook](../deployment.md), and
[release/incident runbook](release-and-incident-response.md).
