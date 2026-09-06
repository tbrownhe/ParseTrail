# Engineering acceptance record

This document preserves durable acceptance evidence previously embedded in the
July-September 2026 TODO. It records completed work, not a new live-system audit.
Dates, release IDs, and evidence locations are retained as recorded; old runtime
identifiers are historical references, not instructions to reactivate them.
Current unfinished work belongs in [TODO](../TODO.md).

## Where the lasting contracts live

| Completed work | Maintained documentation |
| --- | --- |
| P0.1 test isolation and CI boundaries | [Development contracts/checks](../development.md), [backend tests](../backend/README.md#tests-and-static-checks), [deployment CI boundary](../deployment.md#ci-boundary). |
| P0.2/P0.4 memory-only contributions, limits, reconciliation, key ownership | [Privacy inventory](privacy-and-data-flow.md), [backend guide](../backend/README.md), [server-statement devtool](../devtools/server_statements/README.md). |
| P0.3 artifact trust and completed P1.5 release gates | [Desktop release guide](../client/README.md#signed-plugin-releases), [artifact rollback](artifact-rollback.md), [release/incident response](release-and-incident-response.md). |
| P0.5/P1.2 import recovery and exact financial schema | [Client data/import guide](../client/README.md#local-database-and-exact-financial-values), [import acceptance sandbox](../devtools/import_acceptance/README.md). |
| P0.6 runtime/dependency baseline and PostgreSQL cutover | [Contributor setup](../development.md), [client requirements](../client/README.md#requirements), [PostgreSQL runbook](postgresql-17-upgrade.md). |
| P0.7 deployment, staging isolation, rollback, proxy and backup boundaries | [Deployment](../deployment.md), [staging](staging.md), [release/incident response](release-and-incident-response.md). |
| P1.1 deterministic headless parser routing | [Parser architecture](../README.md#parser-architecture), [client plugin architecture](../client/README.md#plugin-architecture), [local batch tool](../devtools/local_statements/README.md). |
| P1.3 authentication and P2.3 web cleanup | [Backend account guarantees](../backend/README.md#account-state-guarantees), [web authentication](web-authentication.md), [dashboard guide](../frontend/README.md). |
| P1.4/P2.1 responsive networking and application service ownership | [Client service boundaries](../client/README.md#application-service-boundaries), [desktop login](../client/README.md#desktop-login-storage). |
| Completed P1.6/P2.2 startup, onboarding, and backup behavior | [Offline startup](../client/README.md#offline-startup-and-update-checks), [first run and backups](../client/README.md#first-run-and-database-backups). Native fresh-user acceptance remains in TODO. |
| P2.4 documentation/privacy alignment | [Root guide](../README.md), [privacy](privacy-and-data-flow.md), [threat model](threat-model.md), component guides and operational runbooks. |

Transient audit counts, bundle sizes, and module line counts from earlier
checkpoints remain in Git history. They are not current dependency-health or
performance guarantees. Locks, tests, and fresh release checks are authoritative.

## Desktop releases and financial-data acceptance

- **Windows client 1.3.0 and Intel macOS client 1.3.1** passed native build,
  regression tests, frozen-runtime smoke, offline signing, independent
  verification, immutable publication, public download, installation,
  credential-store, and signed-plugin update gates. These results do not establish
  Apple Silicon support or close the later P1.6/P2.2 fresh-user walkthroughs.
- The Windows signing rehearsal included the **22-plugin catalog**. The encrypted
  offline Ed25519 key and its passphrase have separate password-manager recovery
  copies. Only public trust keys ship with the application.
- **18 authorized statements** routed uniquely through the in-memory headless
  batch and imported through the signed 1.3.0 desktop build. The server-statement
  UI also decrypted and parsed an authorized encrypted contribution through
  `ParseInput.data`, with no new plaintext file outside its original fixture
  location.
- A temporary copy of the **18,668-row client database** passed shadow migration,
  redacted structural checks, and populated-GUI review of exact money, duplicates,
  and overlapping statement membership. The owner reported no visible correctness
  concerns. The precise schema is intentionally not downgradable in place;
  recovery uses the validated pre-migration `.dbb` copy.
- Import acceptance exercised overlapping and multi-account statements, one
  canceled batch, and an injected archive failure followed by safe recovery.
  The repeatable procedure lives in the linked sandbox guide.
- Parser work accepted during this period included Citi `202511` accessible-PDF
  layouts (obscured and continuation rows, single-date payments, multiline fees),
  Chase Sapphire against all five supplied statements, LendingClub LevelUp/Happen
  Bank against seven supplied statements, and the corrected Synchrony/Amazon
  plugin identity without the erroneous `.py.pyc` suffix. Earlier Citi routing
  signatures remained distinct.
- The source client review at **`1766ceb`** ran **253 tests on Windows** and passed
  Ruff check/format for source, scripts, migrations, and tests. Its limits and
  new findings are in [the client review](client-development-review.md).

## Release bootstrap follow-up

The R1 implementation passed **283 client tests on Windows**, client-wide Ruff
check/format, and PowerShell/Bash syntax checks. The tests include package-free
startup, uv's inline minimum-version enforcement, Windows builder failure
propagation, and rejection before project sync for invalid uv, Python pins,
hosts, and interpreter properties.

The real Windows bootstrap passed against both the existing managed interpreter
and a new temporary uv installation directory. Both inspections identified
standard 64-bit CPython 3.13.15 on Windows x64 with uv 0.12.5. No client packages,
installer, signing operation, or public artifact activation were needed for
these checks.

The owner pulled `fix/client-release-bootstrap` on the Intel Mac and ran
`uv run --no-env-file --script scripts/release_bootstrap.py check --platform macos`.
It returned the success report with `interpreter`, `python_version`, `target`,
`uv`, and `uv_version`. That report is emitted only after uv, the exact pinned
CPython interpreter, and the native 64-bit Intel target pass validation. This
completes R1 bootstrap acceptance on both active platforms; native packaging and
installed-app checks remain separate gates.

## Intel Mac packaging implementation follow-up

R2's implementation passed **326 client tests on Windows**, with the one native
Mac Bash integration test skipped. Client-wide Ruff check/format and the Mac
builder's Bash syntax check passed. Synthetic tests cover missing toolchain
inputs, old Rust, wrong archive architecture, static-build environment overrides,
cached-wheel avoidance, release-launcher failure propagation, unresolved/external
library references, dynamic OpenSSL rejection, inventory evidence validation,
and frozen-process timeout/failure. The native dependency smoke exercised the
installed Windows Python libraries with network connections denied.

The audit parser uses synthetic `otool` output in these tests. This evidence does
not claim a real Mac `.app` was audited or installed. The remaining
[Intel Mac release gates](../client/README.md#intel-mac-release-gates) cover the
packaged Mach-O, frozen smoke, and installed app. Source-build inputs,
dependency-audit results, and the bounded smoke
result are preserved under `native_build` in each new Mac release inventory.

On **2026-09-06**, the owner ran the tool-only preflight from
`fix/intel-macos-packaging` successfully on a **2020 Intel MacBook Air**. It reported:

| Input | Accepted preflight observation |
| --- | --- |
| Target | `macos`, `x86_64` |
| Running macOS (separately reported) | **15.7.9**, build **24G830** |
| OpenSSL | Homebrew `openssl@3`, OpenSSL **3.6.3** (9 Jun 2026), static inputs enabled |
| Rust / Cargo | **1.98.0**; Cargo Homebrew build `797e8a9bc` (2026-08-05) |
| clang | Apple clang **12.0.5**, `clang-1205.0.22.9` |
| macOS SDK | **11.3** |
| pkg-config | **3.0.6**, resolving OpenSSL **3.6.3** |
| create-dmg | **1.2.3** |

The verified Intel static archive SHA-256 values were
`libcrypto.a`: `71f4297ec46ebb05962f1d58d616d80812d26103dd249c7b9a457b928ff62987`
and `libssl.a`:
`aa542ff72245c61b2e16d3e369caed549cf4e0f6d139dfdb5e90267759bb852a`.

This accepts the original tool-presence/static-input preflight, not a native
dependency build or frozen artifact. That report did not include the running
macOS version; SDK 11.3 cannot establish it. The owner separately confirmed
**macOS 15.7.9 (24G830)**, meeting the client's macOS 13 minimum. The follow-up
preflight records the running OS and rejects older or unknown hosts; **80 focused
release tests passed on Windows**, with the native Mac Bash test skipped, and
Ruff check/format passed.
The owner is open to updating the Apple tools after checking OS compatibility;
no update has been reported yet. Keep tool updates compatible with Sequoia on
this machine: Apple's [Tahoe compatibility list](https://support.apple.com/en-us/122867)
includes the M1 2020 Air, not the Intel 2020 Air. An Apple Silicon replacement is
not an active project prerequisite. As checked on 2026-09-06, Apple's
[Xcode matrix](https://developer.apple.com/xcode/system-requirements) lists Xcode
26.3 for macOS 15.6 or newer and 26.4.1 for macOS 26.2 or newer; do not assume
the latest tools support this host. Inspect the active developer directory and
Software Update's compatible offerings before selecting an update.

## Staging migration and recovery: August 2026

The PostgreSQL 12-to-17 rehearsal preserved the source volume and matched every
public-table count in a new isolated volume. Initial restore target
`parsetrail_app-db-data-pg17-staging-20260829T1927Z` exposed a mount-depth mismatch
when started through Compose. The helper and regression contract were corrected,
then the checksum-verified dump was restored with count parity into
`parsetrail_app-db-data-pg17-staging-20260830T065841Z` under the authoritative
`PGDATA` mount. Fourteen copied submission rows were removed after preserving the
restore evidence.

Owner testing demonstrated that changing staging `SECRET_KEY` invalidates tokens
but does not disable copied production password hashes. The guarded sanitizer
therefore preserves audit UUIDs while anonymizing/disabling copied users,
invalidating hashes/token generations, and removing copied submissions before
application traffic. This requirement is now in the staging runbook.

The isolated staging stack reached Alembic `3b7a1f4c2d91` at `fedd236` image
digests and passed all seven authenticated proxy checks. The owner completed
signup, captured-email verification, explicit sign-out/login, plugin download,
statement contribution, memory-only admin retrieval/parsing, and password recovery
using Mailpit. Staging mail had no relay or SMTP host port, no Mailpit egress,
a constrained loopback UI proxy, and a staging-domain recipient allowlist.

The independent restore drill matched public-table counts, resource contents and
modes, and submission-key hashes across:

- `staging-pg17-restore-20260830T204123Z`;
- `staging-files-restore-20260830T204123Z`;
- `staging-keys-restore-20260830T204123Z`.

The `580b4cc` deployment record `20260830T204303Z-580b4cc2aad7` passed its smoke
gate. Rollback record `rollback-20260830T204722Z-fedd236fb82a` restored the prior
images and passed all seven checks. The full recovery rehearsal required the
real migration command to reject `restore_drill_missing_revision`, activated
`fedd236` against the independently restored database/resources/keys, matched
table counts, and passed all seven checks. It then restored the untouched normal
staging mounts and passed again. Evidence was preserved under
`recovery-rehearsal/20260830Towner-acceptance`.

### Staging secret incident closure

A recovery-helper logging defect exposed staging container environment values
in the 2026-08-30 operator transcript. Staging JWT, PostgreSQL, and smoke-account
credentials were rotated immediately and verified; production secrets were not
exposed. The master key was initially retained to avoid stranding ciphertext.

After the owner authorized abandonment of staging submissions, the guarded reset
found zero rows and zero files, rotated `MASTER_KEY`, restored the recorded
immutable release, and passed all seven smoke checks. Obsolete restore/recovery
volumes, retired-key backups, bulky archives, and stale evidence were removed
after preserving nonsecret acceptance records under
`release-state/acceptance/20260830`. Historical restore target names above do not
imply that those disposable targets still exist. New deployments require new
restore evidence; the closed incident is not a standing credential-rotation task.

## Production hardening and backup acceptance: September 2026

- The application deployment initially retained PostgreSQL 12.22 and its original
  volume, migrated to `39e1c1c2a803`, and activated the signed client/plugin
  releases. Owner acceptance covered login, a fresh plugin store, multiple
  statement contributions, encrypted devtool retrieval, and parsing. The stale
  bootstrap password was rotated; release smoke uses a dedicated account.
- Production then moved by logical dump/restore to **PostgreSQL 17.11** on
  **`parsetrail_app-db-data-pg17`**. The newer server never opened the PostgreSQL
  12 data directory. The release dump recorded on **2026-09-06** was
  checksum-verified and restored in a disposable, network-isolated PostgreSQL 17
  container with all seven user tables and table-data sections present.
- The dedicated production smoke credential at
  `/srv/parsetrail-production/secrets/smoke.json` was mode `0600` and independently
  verified through the frontend. The guarded `0ec65f2` production release and
  post-certificate-cutover rerun passed all eight public checks without bootstrap
  credentials.
- Public production hostnames passed through Cloudflare Full (strict), including
  authenticated artifacts and bounded statement submission. A disposable DNS-01
  proof preceded migration of all eight production/staging ParseTrail certificates
  into the private Cloudflare ACME store. The proof and five obsolete DuckDNS
  certificates were removed. Turing's certificate remained in its separate
  HTTP-01 store; public staging apex/wildcard A records were removed after LAN
  HTTPS and DNS-01 renewal verification.
- The Docker-aware origin firewall and repeated five-minute repair cycles passed
  on `eno2`. Production passed all eight public checks and staging remained
  healthy over the LAN. From a Mac on a phone hotspot, a direct connection pinned
  to the historical origin timed out after seven seconds while the normal
  Cloudflare route was healthy. Rollback removes only the component-owned chains.
- `silicide`'s LAN address **`192.168.1.89`** was reserved in DHCP; staging smoke
  and owner-machine hosts entries agreed and all seven staging checks passed
  without command-line overrides.
- The unused host Postfix listener was restricted to `127.0.0.1:25` and
  `[::1]:25`. `postfix check` and restart passed; restart also refreshed the stale
  chroot resolver copy and the files matched afterward.
- The sibling infrastructure backup script gained pipeline failure propagation,
  encrypted-device cleanup traps, and passphrase handling outside process
  arguments. The **2026-09-05 scheduled encrypted USB backup** and automatic
  restore drill verified checksums, memory-backed decryption, file/mode
  boundaries, all five submission-key files, and all seven user tables in an
  isolated PostgreSQL 17 restore without changing live state.

Server P0 is accepted. Deployment remains manual and non-deploying CI retains no
production credentials. The non-root backend ownership migration remains a
separate unfinished item; these records do not claim it was performed.
