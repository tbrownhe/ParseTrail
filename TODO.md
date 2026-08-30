# ParseTrail engineering TODO

This is the working remediation plan from the July 2026 codebase review. It is
ordered by risk, not by component. Each numbered item is intended to be small
enough to implement, test, and commit independently.

## How to use this file

- `[ ]` is not started, `[~]` is in progress, and `[x]` is verified.
- `[USER]` means the final verification needs GUI interaction, a private fixture,
  production observation, or a product decision from the project owner.
- Do not mark a chunk complete until its acceptance checks pass.
- Breaking API, schema, plugin, and client changes are permitted. Prefer a clear
  migration or compatibility error over silently accepting incompatible data.

## Non-negotiable invariants

- A decrypted submitted statement exists only in process memory. It is never
  written to the client temp directory, the server filesystem, logs, error
  reports, or the developer workstation.
- A downloaded plugin, model, or installer is untrusted until it has been
  authenticated by a signing key that is not stored on the public server.
- A failed import must not both move the source statement and roll back its
  database transaction.
- Automated tests must never discover or connect to the production database from
  the repository `.env` file.
- Currency values must not acquire binary floating-point rounding errors.

## Review baseline

- [x] Trace the local parse/import path, plugin loading, statement submission,
  artifact download/update, backend authentication, and deployment topology.
- [x] Confirm that current devtool parsing supplies decrypted content as an
  in-memory `ParseInput`; the temp-file description is stale documentation.
- [x] Run static Python checks: Ruff passes for `backend/app` and for the client
  source, migrations, and tests.
- [x] Build the dashboard frontend successfully. The production bundle reports a
  roughly 763 kB main JavaScript chunk.
- [x] Record dependency audit baselines: backend lock export reports 48 known
  vulnerabilities across 13 packages; the frontend production tree reports 57
  advisories, including 2 critical findings.
- [x] Identify test-environment hazards: backend tests inherit the repository
  database URL and have destructive table cleanup; the checked-in backend virtual
  environment is stale; the desktop client has no automated regression suite or
  reproducible lock file.
- [x] Review the current Traefik configuration in the sibling `infra` repository.
  No Traefik redesign is included in this plan.

## P0 - establish safe change and release boundaries

### P0.1 Isolate automated tests from real data

- [x] Add a dedicated test-settings path that refuses non-test database names and
  ignores the repository `.env` unless explicitly requested.
- [x] Start Postgres 17 for backend integration tests under a unique Compose
  project and non-external disposable volume. All migrations and 116 backend tests
  pass against the isolated database.
- [x] Replace global user/item deletion in backend test teardown with baseline-aware
  cleanup that removes only records created by the suite. A pre-existing sentinel
  user survives the complete run.
- [x] Add a smoke test proving that the test command aborts before connecting when
  given a production-looking database URL.
- [x] Remove duplicate deployment-workflow `if` keys so the disabled state cannot
  be superseded by the repository-owner condition.
- [x] Restore and enable backend static CI on Python 3.13; Ruff check/format and
  strict mypy now pass locally against the refreshed lock.
- [x] Enable non-mutating Python lint, backend tests, client tests, frontend
  checks/build, and Compose smoke tests on GitHub-hosted runners. Remove stale
  MailCatcher/port assumptions and make the jobs required on `main` only after
  they are stable. The full hosted Windows/macOS/Linux matrix passed on the
  merged application PR, and the solo-maintainer branch rules were exercised.
- [x] Keep CI non-deploying initially: do not give hosted or self-hosted runners
  production SSH credentials, the offline release key, or a production `.env`.
  Retain an explicit manual approval boundary until the release path below has
  been rehearsed and rollback is reliable.

Acceptance: a fresh checkout can run its default checks without a root `.env`, and
a sentinel row in a separately configured database survives the complete suite.

### P0.2 Preserve the memory-only plaintext invariant

- [x] Correct the devtool documentation so it describes `ParseInput.data` and no
  longer claims that plaintext is written to a temporary file.
- [x] Add regression tests that monkeypatch or deny temporary-file creation while
  the devtool and batch parser successfully process in-memory bytes.
- [x] Search every statement-submission and parser entry point for filesystem
  fallbacks. None materializes decrypted bytes; the backend `.tmp` path contains
  only newly encrypted ciphertext and is atomically renamed.
- [x] Configure error reporting and logging so statement bytes, extracted text,
  encryption keys, and submitted metadata cannot be attached automatically.
- [x] `[USER]` Exercise one authorized statement fixture through the development
  tool and confirm that no new plaintext file appears outside its original
  fixture location. The server-statement UI successfully decrypted and parsed an
  authorized encrypted submission through the in-memory handoff.

Acceptance: the regression test fails if `NamedTemporaryFile`, `mkstemp`, or an
equivalent plaintext write is introduced into either parse path.

### P0.3 Authenticate every executable artifact

- [x] Define a versioned plugin release manifest with artifact type, safe
  filename, version, minimum client version, Python bytecode identity, byte size,
  SHA-256 digest, monotonic release sequence, and one detached Ed25519 signature.
- [x] Extend the signed manifest vocabulary and offline release process to client
  installers on Windows and macOS.
- [x] Remove the unused unsigned model API, client download helper, and backend
  model bind mount. Models remain local-only unless a real distribution workflow
  justifies adding signed releases later.
- [x] Make signed manifests authoritative for installer listing and download.
  Stop deriving metadata by globbing mutable server directories, and never
  advertise temporary, partial, or unsigned installers.
- [x] Expose no server model listing or download while signed model releases do
  not exist.
- [x] Implement and document an encrypted offline signing-key procedure. The
  client build embeds only a public-key trust store and refuses to build while it
  is empty. The encrypted private key and its passphrase have separate
  password-manager recovery copies; only the public key ships with clients.
- [x] Apply containment/suffix checks to desktop plugin destinations and preserve
  the previous plugin until a complete download is atomically renamed.
- [x] Apply containment/suffix checks to installer destinations and reject
  unsupported platforms before constructing a path.
- [x] Remove remote model destinations along with the unused download workflow.
- [x] Apply root containment, plain-filename, and suffix checks to backend plugin
  and model downloads, with cross-platform traversal regression tests.
- [x] Download the complete plugin catalog into an immutable staging release,
  enforce bounded manifest/plugin reads and network timeouts, authenticate all
  completed bytes, then atomically activate one release pointer.
- [x] Authenticate every plugin on startup and immediately before dynamic import.
  Unsigned legacy plugins are ignored by the normal application; cancellation or
  any failed artifact preserves the previously verified release.
- [x] Authenticate signed size and SHA-256 in staging before atomically publishing
  and launching an installer; cancellation or failure preserves the prior file.
- [x] Confirm every current `joblib.load` path is a locally trained or
  user-selected model; remove the unused remote model source.
- [x] Upload installers into unique immutable release directories, independently
  verify exact remote sizes and digests, then atomically activate them. A failed
  or interrupted `scp` leaves the previous release active and undiscoverable.
- [x] Remove model publication configuration until a signed consumer workflow is
  deliberately introduced.
- [x] Enforce remote plugin-release immutability: fail if a release sequence
  already exists, verify every uploaded byte against the signed manifest, and
  change `current-release.json` only after that independent verification passes.
- [x] Add plugin negative tests for altered bytes, altered manifest fields, wrong
  and unknown signing keys, malformed/oversized manifests, truncation, traversal
  names, rollback and sequence reuse, cancellation midway through a download,
  unsigned legacy plugins, and post-install tampering.
- [x] Add installer trust tests for altered metadata/signatures, semantic version
  selection, unsafe names, altered/truncated/oversized downloads, cancellation,
  sequence reuse, and preservation of a prior installer.
- [x] Add remote-publication failure tests for partial upload visibility, remote
  hash mismatch, and interrupted activation.
- [x] Add a backend regression test proving unsigned model distribution remains
  unrouted.
- [x] `[USER]` Decide where the offline release key and recovery copy will live,
  then perform a signed Windows release rehearsal. The encrypted local key has a
  password-manager recovery copy, and client 1.3.0 plus the 22-plugin catalog
  completed the offline signing and verification path.

Acceptance: compromising the download server alone is insufficient to make an
existing client import or execute attacker-supplied bytes.

### P0.4 Bound and make statement submission recoverable

- [x] Bound the application-level ciphertext read to 36 MiB and return HTTP 413
  before decryption when it is exceeded.
- [x] Enforce the total request-body limit before multipart spooling; do not rely
  on either the handler read limit or the desktop's 25 MB check.
- [x] Add per-user pending-statement quotas and rate limits with useful client
  errors and an administrative cleanup path.
- [x] Replace truncated free-form metadata JSON with a validated schema and
  per-field limits. Bound filename, institution, comments, IP, and user-agent
  values before persistence or logging.
- [x] Stop returning raw cryptographic, filesystem, and database exception text
  from the statement-submission endpoint.
- [x] Audit exception logging/error reporting and retain only non-sensitive
  correlation details.
- [x] Delete temporary/final ciphertext when file finalization or database
  registration fails, without ever writing decrypted bytes.
- [x] Add safe reconciliation for legacy orphan statement files/rows, with
  read-only reporting by default and explicit encrypted-file quarantine.
- [x] Move RSA submission-key provisioning out of module import. Create the pair
  atomically under a single startup/maintenance owner, load a matching pair, and
  make rotation explicit and overlap-safe across multiple workers.
- [x] Document that server-side envelope encryption protects offline disks and
  backups, but not a live server compromise that can read both ciphertext and the
  master key.
- [x] Test oversized multipart bodies, malformed envelopes, corrupted tags,
  non-provisioning worker startup, key rotation with an in-flight upload,
  database failure after file creation, and filesystem failure before row
  creation.

Acceptance: hostile requests have bounded memory/disk impact, and every completed
request leaves either one consistent encrypted-file/row pair or neither.

### P0.5 Prevent importer data loss and silent corruption

- [x] Refactor import coordination so database commit and source-file movement
  cannot leave a rolled-back import whose only source was moved. Use a recoverable
  staging/state transition and report recovery actions on next startup.
- [x] Fix duplicate insertion at flush time using a savepoint, conflict-aware
  insert, or precomputed set; catching `IntegrityError` around `session.add()` is
  ineffective.
- [x] Treat the physical file hash and canonical archive filename as the import
  identity while retaining one `Statements` row per account. Multi-account retry
  accepts multiple statement IDs when they resolve to that one archive.
- [x] Add failure-injection tests at source retention, parse, flush/commit, archive move,
  and cleanup boundaries.
- [x] `[USER]` Import overlapping and multi-account fixture statements into a copy
  of an existing SQLite database, cancel once, and force one archive failure.

Acceptance: after every injected failure, the original or staged statement is
recoverable, committed data agrees with the import state, and a retry is safe.

### P0.6 Refresh vulnerable and obsolete foundations

- [x] Upgrade backend security-sensitive packages and regenerate the lock. The
  production audit is clear, the environment installs on Python 3.13, all modules
  compile, and the complete static lint command passes.
- [x] Remove the unused direct frontend `form-data` dependency, upgrade Axios and
  affected transitive production dependencies, and refresh the lock file. The
  production audit is now clear and the dashboard production build passes.
- [x] Upgrade the development-only OpenAPI generator and frontend build chain to
  maintained Node 22 tooling. Generation now exports the schema reproducibly from
  the locked backend, isolates generated code behind a compatibility facade, the
  full npm audit is clear, and regeneration plus the production build pass.
- [x] Add one universal client lock that requires Windows x64 plus macOS arm64/x64
  resolution, and make both release scripts sync/use it with `--frozen`.
- [x] Make uv the sole owner of the client Python environment, pin release builds
  to an exact Python patch version, remove the Conda build dependency, and require
  frozen executables to pass a bootstrap smoke test before packaging.
- [x] Raise the client cryptography and PDF parsing stack to patched versions; the
  installed locked Windows dependency environment has no known vulnerabilities.
- [x] Move Windows and macOS to the exact Python 3.13.15 baseline and PySide6
  Essentials 6.11.2. The universal lock resolves both macOS architectures, all
  71 client tests pass on Windows, Qt-heavy imports pass headlessly, and the
  PyInstaller executable passes its frozen-runtime smoke test. Hosted macOS
  execution remains part of the non-deploying CI gate.
- [~] Upgrade PostgreSQL 12 using a dump/restore into a new volume. The guarded
  helper has completed a synthetic 12-to-17 rehearsal with whole-schema table
  count comparison; staging and production still use PostgreSQL 12. Do not point
  a newer server at the old data directory.
- [x] `[USER]` After review and merge, take a verified production backup and
  deploy the current application release while explicitly retaining both the
  PostgreSQL 12 image and existing PostgreSQL 12 volume. Confirm the new Alembic
  head, database health, expected table counts, login, artifact downloads, and
  statement submission before treating the application release as healthy. The
  deployment retained PostgreSQL 12.22 and its original volume, migrated to
  `39e1c1c2a803`, activated the signed client/plugin releases, and passed owner
  login, fresh plugin-store download, multi-statement submission, encrypted
  devtool retrieval, and parser execution. The stale bootstrap password was
  rotated after confirming it no longer represented the current account password.
- [x] Restore a fresh production PostgreSQL 12 dump into a uniquely named,
  isolated PostgreSQL 17 staging volume; preserve the source volume and compare
  every public-table count before allowing application traffic to the restore.
  The production rehearsal created a checksum-verified dump, retained the
  PostgreSQL 12 source unchanged, and matched every table in the isolated
  `parsetrail_app-db-data-pg17-staging-20260829T1927Z` volume. Live startup then
  exposed a mount-depth mismatch in the helper: its verified cluster was nested
  below Compose's `PGDATA` mount. The helper and regression contract were fixed,
  and the retained checksum-verified dump was restored again with exact count
  parity into `parsetrail_app-db-data-pg17-staging-20260830T065841Z`. PostgreSQL
  17.11 starts healthy through the authoritative Compose mount. Restore evidence
  was preserved before the 14 copied `statement_uploads` rows were explicitly
  removed from staging; production and both earlier volumes remain untouched.
  Owner testing then exposed that a distinct staging `SECRET_KEY` does not disable
  copied production password hashes. A guarded post-restore sanitizer now preserves
  audit UUIDs while anonymizing and disabling copied users, revoking their token
  generations, invalidating their hashes, and removing copied submissions.
- [~] `[USER]` Verify account/login, plugin download, statement submission, admin
  retrieval, email, and backup/restore against the upgraded staging stack before
  the production PostgreSQL 17 cutover. The isolated owner profile completed
  signup, captured-email verification, explicit sign-out/login, plugin download,
  statement submission, and memory-only admin retrieval/parser execution. The
  independent restore drill matched PostgreSQL table counts, resource contents
  and modes, and submission-key hashes in three new targets: database restore
  `staging-pg17-restore-20260830T204123Z`, file restore
  `staging-files-restore-20260830T204123Z`, and key restore
  `staging-keys-restore-20260830T204123Z`. It then restored the exact staging
  backend container to healthy service. The password-recovery flow remains to be
  exercised through captured staging email.

Acceptance: supported runtime versions are documented, lock files reproduce on CI,
dependency audits have no known critical/high production finding without a written
temporary exception, and the Postgres restore drill preserves expected row counts.

### P0.7 Make production deployment recoverable and observable

- [x] Choose Docker Compose as the one authoritative deployment path. Remove or
  archive the stale Docker Swarm scripts and disabled template deployment
  workflows once their behavior has been accounted for.
- [x] Build backend/frontend/website images from a clean commit, tag them with the
  Git commit rather than `latest`, pin external production images, and deploy the
  recorded immutable tags without rebuilding source on the production host.
- [x] Add a pre-deploy gate that records the current image tags and schema revision,
  verifies a recent restorable database/file backup, renders and validates the
  production Compose configuration, and aborts before migration on any failure.
- [x] Separate database migration from service replacement. Capture migration
  output, require backward-compatible expand/contract migrations where practical,
  and document when an application rollback also requires a database restore.
- [x] Deploy with health waiting and bounded timeouts, then smoke-test health,
  login, plugin manifest/download, client listing/download, statement submission,
  dashboard, and website routes through the public proxy.
- [x] Automatically reactivate the previous immutable image tags when service
  health or post-deploy smoke checks fail; never claim success merely because
  `docker compose up -d` returned zero.
- [x] Write an append-only release record containing timestamp, operator, Git
  commit, schema revision, image digests, artifact versions/hashes, smoke results,
  and the exact rollback target.
- [x] Make development Compose overrides explicitly opt-in. Do not keep a tracked
  `docker-compose.override.yml` that production can auto-load and use to expose
  local ports, remove Traefik labels, or redirect the default network.
- [x] Treat staging as a configuration-only deployment target using the same
  Compose definition, images, migrations, and signed artifacts as production;
  do not introduce staging-only application behavior. Preflight now compares the
  exact staging and production signed-artifact inventories before adoption or
  deployment.
- [x] Parameterize the external submission-key volume and validate that staging
  uses a distinct `STACK_NAME`, PostgreSQL volume, submission-key volume, secrets,
  bind-mount directories, release state, and smoke credentials. Refuse a staging
  deployment whose protected storage resolves to a production target. The release
  tool requires the production environment/state/smoke references and rejects each
  reused boundary independently.
- [x] Move the dashboard API origin from build-time `VITE_API_URL` to validated
  container-startup configuration so the exact frontend image digest can be
  promoted from staging to production. Dashboard and website images now share an
  atomic, fail-closed `runtime-config.js` generator and serve it with `no-store`;
  public URLs are no longer compiled into either image.
- [x] Add an isolated desktop staging profile and process-local launcher for the
  installed client. Separate AppData, SQLite/import paths, OS credential-store
  entry, cached submission public key, plugin store, logs, and reports; show a
  persistent `STAGING` marker and never modify the production profile. Managed
  staging output paths are constrained to `ParseTrail-Staging`, and `--staging`
  is consumed before settings, logging, database, or keyring imports.
- [x] Let the server-statement devtool select an explicit environment file,
  recognize staging, display its target prominently, and retain the memory-only
  plaintext invariant. Both GUI and batch paths select `--env-file` before
  settings-dependent imports; SSH-vs-local key, database, and ciphertext access is
  now explicit rather than inferred from the environment label.
- [x] Provision a LAN/VPN-only `parsetrail-staging` Compose project behind the
  existing Traefik instance with private staging hostnames and trusted HTTPS.
  The pinned, separate Mailpit definition now has no SMTP host port or relay, a
  loopback-only UI through a constrained proxy, no Mailpit egress route, and an
  explicit staging-domain recipient allowlist. The live PostgreSQL 17 stack is
  isolated, migrated to `3b7a1f4c2d91`, healthy at exact `fedd236` image digests,
  and adopted after all seven authenticated proxy smoke checks passed. Confirm
  captured email and isolated desktop/devtool flows passed during the live owner
  rehearsal. The source client now exposes an explicit OS-keyring-backed sign-out
  action. Dashboard HTML is revalidated while fingerprinted assets remain
  immutable, preventing stale app-shell failures after image replacement.
- [x] `[USER]` Rehearse one successful staging deployment, one application rollback,
  and one migration/restore rollback before enabling any deployment runner. The
  digest-pinned `580b4cc` deployment (`20260830T204303Z-580b4cc2aad7`) passed its
  full smoke gate, and explicit rollback record
  `rollback-20260830T204722Z-fedd236fb82a` restored the prior images with all seven
  checks passing. The full-boundary recovery rehearsal then required the real
  migration command to reject `restore_drill_missing_revision`, activated release
  `fedd236` against the independently restored PostgreSQL, resource, and key
  targets, matched database table counts, and passed all seven checks. Its final
  path restored the untouched normal staging mounts and passed all seven checks
  again; evidence is in `recovery-rehearsal/20260830Towner-acceptance`.
- [x] `[USER]` Reserve `silicide`'s LAN address in DHCP, then put that address in
  the staging smoke configuration and owner test-machine hosts entries. A changed
  address fails the smoke gate safely but makes staging unavailable until updated.
  `192.168.1.89` is reserved and the active staging smoke config resolves all three
  HTTPS staging names to it; all seven checks pass without command-line overrides.
- [ ] `[USER]` Create and verify a dedicated production deployment-smoke account,
  then replace `/srv/parsetrail-production/secrets/smoke.json`. A direct check on
  2026-08-30 confirmed that the rotated `.env` bootstrap password is not the live
  production account password (HTTP 401); do not treat bootstrap credentials as an
  operational login or cut over production until its independent smoke passes.
- [ ] `[USER]` Decide whether to discard and resubmit the staging statement
  ciphertext or preserve it through a separately designed in-memory re-encryption,
  then rotate the staging `MASTER_KEY`. A recovery-helper logging defect exposed
  staging container environment values in the 2026-08-30 operator transcript.
  The staging JWT, PostgreSQL, and smoke-account credentials were immediately
  rotated and passed smoke; production secrets were not exposed. The master key
  was intentionally retained because replacing it alone would strand ciphertext.

Acceptance: a production release either passes its public smoke checks with a
traceable record or restores the documented prior state, and no deploy depends on
an unrecorded mutable image, workstation file, or database assumption.

## P1 - correct behavior and harden trust boundaries

### P1.1 Make parser routing consistent and headless

- [x] Fix CSV and XLSX routers to evaluate parser candidates the same way the PDF
  router does; they currently pass the candidate list as though it were one parser.
- [x] Extract format-independent feature classification into a headless helper;
  CSV, XLSX, and PDF adapters now produce the same routing contract.
- [x] Specify and test conventional precedence for search expressions:
  parentheses, then `&&`, then `||`; validate strict expressions at plugin build
  and load time.
- [x] Route by a deterministic feature tree: suffix, optional PDF document
  metadata, normalized per-page headers, then body expressions. Require exactly
  one match without exposing raw routing inputs in diagnostics.
- [x] Remove Qt dialogs from core parsing. Return typed errors/results for GUI,
  batch, and future CLI adapters to present independently.
- [x] Add unit tests for zero, one, and multiple matching plugins; CSV/XLSX/PDF
  routing; malformed output; validation warnings; and hard-fail behavior.
- [x] `[USER]` Run the authorized statement collection against source and built
  plugins entirely in memory, review redacted diffs, and bless expected outputs.
  All 18 supplied statements routed uniquely in the headless batch and imported
  successfully through the signed ParseTrail 1.3.0 desktop build.
- [x] Adapt the Citi `202511` layout family to its 2026 accessible-PDF rendering,
  including obscured rows, continuation-page rows, single-date payments, and
  multiline fees, without weakening older Citi routing signatures.
- [x] Add and validate a Chase Sapphire credit-card parser against all five
  authorized statements.
- [x] Update or version the LendingClub LevelUp Savings parser for the seven
  authorized statements and the Happen Bank rename/layout transition.
- [x] Correct and version the Synchrony/Amazon plugin whose declared name currently
  produces a `.py.pyc` artifact; migrate or remove the malformed filename.

Acceptance: all supported formats share the same tested routing contract and the
batch runner can execute with no Qt application or display server.

### P1.2 Make the local financial schema precise

- [x] Store currency as integer minor units or exact decimal values end to end;
  eliminate `Float` columns and float-based validation/rounding.
- [x] Replace string dates with typed dates and define timezone handling for actual
  timestamps.
- [x] Enable SQLite foreign-key enforcement on every connection and define delete
  behavior for statements, accounts, transactions, balances, and categories.
- [x] Replace ambiguous MD5 concatenation with a versioned canonical fingerprint
  using a collision-resistant digest and explicit field framing.
- [x] Decide whether overlapping statements require a statement-transaction join
  table so transaction membership and statement counts remain truthful.
- [x] Validate an unversioned database before stamping an Alembic baseline; remove
  `create_all()` behavior that can conceal migration drift.
- [x] Make pre-migration backup names collision-safe and test upgrade, downgrade
  where supported, interrupted migration, and restore on copied real databases.
  The precise schema is deliberately non-downgradable; recovery restores the
  validated automatic backup. A redacted migration and populated-GUI rehearsal
  passed on a temporary copy of the 18,668-row production client database.
- [x] `[USER]` Review rounding, duplicate, and overlapping-statement results in the
  GUI before accepting the data migration. A migrated copy of the populated live
  database passed review with no visible correctness concerns.

Acceptance: schema constraints are enforced, exact-money round trips pass property
tests, and every existing copied database either migrates successfully or stops
with actionable recovery instructions.

### P1.3 Harden authentication and account state

- [x] Return the same password-recovery response and timing envelope whether an
  email exists or not.
- [x] Require verification after an email-address change before granting the new
  address normal account privileges.
- [x] Invalidate reset links after use and revoke existing sessions after password,
  email, activation, or privilege changes using token/session versioning.
- [x] Return a deliberate 404 for a missing admin-selected user.
- [x] Normalize authorization status codes without leaking existence
  unnecessarily.
- [x] Review password policy and replace the aging password-hash dependency stack
  with a supported algorithm and migration-on-login strategy.
- [x] Test enumeration resistance, token replay, privilege changes, deleted users,
  concurrent reset requests, and old-hash migration.

Acceptance: account-state changes invalidate inappropriate credentials and the API
does not provide a reliable user-existence oracle.

### P1.4 Make client networking responsive and explicit

- [x] Put connect/read timeouts and bounded retries on every HTTP call; centralize
  API error translation and never retry non-idempotent operations implicitly.
- [x] Move submission encryption, uploads, plugin sync, model sync, and installer
  downloads off the Qt UI thread with truthful progress and cancellation.
  There is currently no remote model-sync workflow; any future implementation
  must use the same worker boundary.
- [x] Fix plugin synchronization when progress UI is disabled.
- [x] Ensure cancelled installer downloads are reported as incomplete rather than
  successful and never launch their staging file.
- [x] Replace Windows `shell=True` launching; use platform-specific safe launch
  adapters for Windows, macOS, and Linux, and quit only after a confirmed launch.
- [x] Store long-lived desktop credentials in an OS credential store rather than
  beside their decrypting key in the user profile.
- [x] Add fake-server tests for timeouts, slow streams, disconnects, cancellation,
  401 refresh/login paths, and error-body redaction.
- [x] When an artifact update rejects stored credentials, prompt for replacement
  credentials immediately and resume the original update after successful login.
  Plugin synchronization now reports authentication separately from artifact
  failures, preserves the selected signed release, and permits exactly one
  UI-thread credential retry before failing safely.

Acceptance: the interface remains responsive during network failure, cancellation
never installs partial data, and no command shell interprets downloaded filenames.

### P1.5 Make releases reproducible

- [x] Refuse release builds from a dirty worktree, untagged commit, or version/tag
  mismatch. Record the source commit in client metadata and every release record.
- [x] Provide one dry-run-capable release command that sequences checks, builds,
  signing, verification, upload, activation, and smoke tests while preserving the
  offline passphrase prompt and explicit publish approval.
- [x] Replace import-time `.env` reads in build scripts with validated CLI/config
  inputs and clear missing-directory errors.
- [x] Use semantic version parsing on the installer endpoint; reject invalid
  platforms with a 4xx response instead of a `KeyError`/500.
- [x] Build plugins in a clean pinned interpreter, record source and Python bytecode
  compatibility in the signed manifest, and test minimum-client rejection.
- [~] Replace mutable/broad container inputs with pinned supported bases, run the
  backend as a non-root user, and use frozen installs (`uv sync --frozen`,
  `npm ci`) in images. Base manifests and installs are pinned/frozen; the
  production bind-mount ownership migration required for a non-root backend
  remains.
- [x] Complete the equivalent macOS frozen-runtime smoke test and add a release
  dry-run that creates signed manifests without publishing them. Windows 1.3.0
  and Intel macOS 1.3.1 passed their full native build, test, frozen-runtime,
  signing, immutable publication, public-download, install, credential-store, and
  plugin-update gates.
- [x] Record the uv, Python, PyInstaller, NSIS/create-dmg, compiler, and operating
  system versions used for each platform artifact; generate checksums and a small
  machine-readable release inventory.
- [ ] Pin or enforce a tested minimum uv release in the client-release bootstrap,
  explicitly provision the `.python-version` interpreter, and fail before syncing
  dependencies when uv cannot resolve that exact interpreter for the host.
- [ ] Preflight and document the Intel macOS source-build toolchain for packages
  without x86_64 wheels (`openssl@3`, Rust, and pkg-config). Build cryptography
  against static OpenSSL so distributed clients do not require Homebrew at runtime.
- [ ] Make macOS artifact architecture explicit in manifests, API responses, and
  filenames; choose universal2 or separate x86_64/arm64 releases before claiming
  native Apple Silicon support.
- [ ] Allow a successfully built, signed, and verified dry-run artifact to be
  published without rebuilding it, while preserving immutable-version and explicit
  activation checks.
- [x] Document artifact rollback for client, plugin, and model releases; keep API
  and database rollback in the production deployment runbook from P0.7.

Acceptance: the same tag produces traceable artifacts from a clean builder, and a
dry run cannot mutate the public download directories.

### P1.6 Keep startup offline and deterministic

- [x] Remove the import-time `nltk.download("stopwords")` retry loop. Bundle a
  reviewed corpus or use an internal stable stop-word set.
- [x] Audit imports and normal application startup for DNS/HTTP access; allow
  network activity only after an explicit user action or documented update check.
- [~] Test first startup in a network-denied environment on Windows and macOS.
  The automated Windows test constructs the real GUI, migrates a fresh SQLite
  database, and denies socket/HTTP access; the equivalent macOS run remains.

Acceptance: parsing, categorization, and database startup work on a clean machine
with networking disabled and never pause for an implicit package-data download.

## P2 - reduce complexity and make the product understandable

### P2.1 Introduce application boundaries incrementally

- [x] Add characterization tests around the current import, category, account,
  verification, plugin-sync, and budget behavior before moving code. Import
  persistence/recovery, plugin synchronization, category CRUD/migration, and account
  CRUD/number assignment are covered, as are budget range, grouping, sign, proration,
  and inactive-category semantics. Verification coverage locks down filtering,
  archived-category state, atomic edits, missing references, and model-category retry.
- [x] Define small application services for parse/import, transaction querying,
  categories, accounts, artifact updates, and statement submission. The headless
  `StatementImportService` now owns import persistence, deduplication, and archive
  state while `StatementImportController` owns Qt decisions and progress;
  `CategoryService` now owns category queries, validation, and atomic rename/merge
  transactions; `AccountService` now owns account queries, mutations, deletion
  constraints, and account-number assignment; `BudgetQueryService` now owns budget
  range queries and report calculations; `TransactionReviewService` now owns review
  queries, atomic edits, and model-category compatibility retry; `TransactionService`
  now owns common account/balance/range queries and atomic manual entry. Artifact
  updates have an `ArtifactService`; `DashboardQueryService` owns balances,
  checklists, chart inputs, discrepancy inputs, and verified training data for the
  main window; `StatementSubmissionService` owns validation, memory-only encryption,
  cancellation checkpoints, upload, response cleanup, and server confirmation.
- [x] Introduce repositories or explicit query services so GUI code does not manage
  SQLAlchemy sessions directly. Category, account, budget, verification, transaction,
  dashboard, and artifact workflows now delegate every query and mutation to
  headless services; a source audit confirms no GUI module opens a session or issues
  an ORM query.
- [x] Split the largest GUI modules by workflow while preserving behavior; avoid a
  full rewrite. Category and account persistence and budget reporting moved out of
  their GUI modules without changing their interaction flows; transaction-review
  persistence moved out of its window and its module shrank by roughly 130 lines.
  Transaction-browser persistence also moved out without changing its primary flows.
  Dashboard canvas/table models and review table/filter models now live in focused
  modules, reducing `main_window.py` to about 1,080 lines and `verification.py` to
  about 590 while keeping their public model imports compatible.
- [x] Replace broad exception catches with typed boundary errors and user-safe
  messages while retaining exception chains for local diagnostics. Category input,
  lookup, duplicate, and persistence failures and account validation, duplicate,
  assignment, in-use, and persistence failures are now typed at service boundaries;
  invalid budget reports and query failures are typed, as are invalid or stale review
  edits and auto-categorization failures. Manual-entry validation, missing accounts,
  and transaction query/persistence failures are typed, as are dashboard data and
  persistence failures and artifact query/write failures. Normal GUI workflow
  boundaries now log chained diagnostics and display bounded messages; intentional
  broad containment remains in batch import, rendering, and parser developer tools.

Acceptance: core application tests run without Qt, each extracted service has one
clear transaction owner, and module size trends downward without feature drift.

### P2.2 Clarify desktop workflows

- [x] Make one-off import semantics explicit before moving an original file; offer
  copy, archive, and leave-in-place behavior with a safe default. One-off imports
  default to retaining the selected original and creating a managed archive copy;
  files already placed in the managed import folder retain its move-to-archive contract.
- [x] Add a first-run path explaining local storage, plugin installation, supported
  institutions, statement submission, backups, and what the server can observe. The
  local, repeatable guide lists installed support and accurately distinguishes ordinary
  local imports from explicit encrypted contributions and their plaintext metadata.
- [x] Turn parser failures into actionable messages that identify format/plugin
  compatibility without exposing statement content. Normal imports now distinguish
  unsupported formats, missing or ambiguous matches, changed layouts, incompatible
  plugin output, and failed safety checks while keeping extracted values out of messages.
- [x] Report a recovered committed archive as recovery in the import summary,
  rather than counting the hash match as an ordinary duplicate.
- [x] Add visible backup/restore and database-location guidance, including a test
  restore action. SQLite's online backup API creates consistent copies; test restore
  uses a disposable database, and real restore selects a new path without overwriting
  the active database. The UI states that database backups are local, plaintext, and
  exclude statement archives.
- [ ] `[USER]` Walk through first run, account login, plugin install, one-off import,
  folder import, overlap handling, statement contribution, and restore on Windows.
- [ ] `[USER]` Repeat the fresh-user walkthrough on the owner's MacBook. Reserve
  Jacob's macOS testing for official-release usability and product-gap feedback.

Acceptance: both walkthroughs can be completed without source-code knowledge and
every action that moves or retains a statement is explained before it occurs.

### P2.3 Remove unused template surface and web injection risks

- [x] Replace plugin table `innerHTML` construction on the public website with safe
  DOM text insertion.
- [x] Add a malicious plugin-metadata regression fixture for the public website.
  The public renderer is shared with a dependency-free Node regression that verifies
  hostile tags and event handlers remain inert cell text; frontend CI runs the fixture.
- [x] Remove or deliberately repurpose the template Items API/UI, sample branding,
  placeholder search, and unused dashboard routes. The Items router, schemas,
  persistence helpers, generated client, React route, and PostgreSQL table are gone;
  the remaining home route is a small ParseTrail account/download/plugin landing
  page, and the FastAPI/Vite branding and inert search control have been removed.
- [x] Choose one canonical public/runtime API configuration path; remove the stale
  checked-in localhost/GitHub values from the static website deployment flow. Both
  web surfaces consume the same validated `runtime-config.js` contract generated
  from `BACKEND_HOST`, `FRONTEND_HOST`, and `GITHUB_URL` at container startup.
- [x] Exclude generated API/route files appropriately from formatting checks and
  make the normal lint command non-mutating. `npm run lint` and the frontend
  pre-commit hook now check only; `npm run lint:fix` is the explicit rewrite path,
  and CI fails if normal checks dirty generated or handwritten sources.
- [x] Split or lazy-load heavy dashboard routes to address the oversized bundle.
  Every page and the authenticated layout now use TanStack lazy route modules while
  guards and search validation remain eager. The monolithic 714 kB entry became a
  106 kB entry plus route/shared chunks; no chunk exceeds the 500 kB warning limit.
- [x] Review localStorage bearer-token exposure and choose an HttpOnly-cookie or
  documented hardened-token strategy appropriate to the deployed origins. The
  dashboard now uses a host-only HttpOnly `SameSite=Strict` session cookie and
  includes credentials explicitly; cookie-authorized mutations and browser login/
  logout require the exact configured dashboard origin. Desktop/API clients retain
  bearer auth with OS credential storage, and production/staging cookies use the
  `__Host-` prefix plus `Secure`. Browser tests assert no token reaches Web Storage.

Acceptance: untrusted server metadata renders only as text, the dashboard contains
no unused template CRUD surface, and build/check commands leave Git clean.

### P2.4 Align documentation with the deployed system

- [x] Rewrite the root architecture and privacy documentation around three clear
  boundaries: local finance database, encrypted statement contribution, and public
  account/artifact service.
- [x] Document exactly which metadata the server stores in plaintext, the limits of
  server-side encryption, artifact signature verification, and local plaintext
  statement archives.
- [x] Correct stale repository names, ports, commands, encodings, screenshots, and
  devtool temp-file language.
- [x] Add Windows and macOS contributor setup from a clean checkout, with Linux
  marked experimental until it has a tested package.
- [x] Add a concise threat model and release/incident runbook. The accompanying
  audit also corrected environment examples that failed typed settings, aligned
  the Node baseline, and replaced the web-account deletion overclaim with the
  endpoint's actual local-data and retention boundaries.

Acceptance: every command in the setup docs is exercised from a clean checkout and
the privacy claims match observable code and deployment behavior. Locked Windows
commands, devtool entry points, both example Compose configurations, all component
checks, and internal links passed locally; the documented Intel macOS build path
was exercised by the 1.3.1 release and the hosted macOS CI gate.

## P3 - deliberate future work

### P3.1 Local data-at-rest protection

- [ ] Threat-model local device loss separately from server compromise, including
  the SQLite database, successful-import archive, backups, logs, and OS swap/crash
  dumps.
- [ ] Prototype platform-backed database/archive encryption with recovery and
  export paths before selecting SQLCipher or an equivalent design.
- [ ] `[USER]` Choose the usability/recovery tradeoff; do not enable encryption by
  default until backup restore and lost-key behavior have been rehearsed.

### P3.2 Linux support

- [ ] After the Qt/Python baseline is settled, add a Linux build, desktop entry,
  safe file-launch adapter, sandbox-aware data locations, and CI smoke test.
- [ ] Test on at least one Debian-family and one immutable/packaged desktop before
  advertising support.

### P3.3 Dashboard purpose

- [ ] Decide whether the dashboard should remain a small account/download/admin
  surface or gain privacy-safe operational features. Delete it if it has no clear
  job rather than carrying template code indefinitely.

### P3.4 Paid platform distribution trust

Defer paid OS-vendor signing until external adoption or distribution friction
justifies recurring developer-program costs. The application-level Ed25519
release signatures remain the required update-channel trust boundary.

- [ ] Add Windows Authenticode signing and RFC 3161 timestamping for the frozen
  executable and installer.
- [ ] Add macOS Developer ID signing, hardened runtime, and notarization.

## Sibling infrastructure follow-up

These findings are outside this repository and should be changed in the `infra`
repository only as a separate, reviewed task.

- [ ] Add pipeline failure propagation to the USB backup script so a failed
  `pg_dump` cannot be mistaken for a successful encrypted backup.
- [ ] Add traps that unmount and close the encrypted device on every exit path.
- [ ] Stop placing the GPG passphrase in process arguments.
- [ ] `[USER]` Perform and document a full Postgres/file restore drill from the USB
  backup before relying on it for the database major-version migration.
