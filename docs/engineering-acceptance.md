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
| R4 preserved release publication | [Public-key-only publication](artifact-publication.md), [artifact rollback](artifact-rollback.md). |
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
The owner agreed to update the Apple tools after checking OS compatibility.
Keep tool updates compatible with Sequoia on
this machine: Apple's [Tahoe compatibility list](https://support.apple.com/en-us/122867)
includes the M1 2020 Air, not the Intel 2020 Air. An Apple Silicon replacement is
not an active project prerequisite. As checked on 2026-09-06, Apple's
[Xcode matrix](https://developer.apple.com/xcode/system-requirements) lists Xcode
26.3 for macOS 15.6 or newer and 26.4.1 for macOS 26.2 or newer; do not assume
the latest tools support this host. Inspect the active developer directory and
Software Update's compatible offerings before selecting an update.

The owner subsequently confirmed that `xcode-select --print-path` returns
`/Library/Developer/CommandLineTools` and `softwareupdate --list` reports no new
software. The old SDK therefore comes from the selected standalone tools, rather
than an older Xcode application selected in their place. After following the
manual **Command Line Tools for Xcode 26.3** update path, the owner reran preflight
successfully. It now reports **Apple clang 17.0.0 (`clang-1700.6.4.2`)**, **macOS
SDK 26.2**, and **running macOS 15.7.9**. The Intel target, OpenSSL 3.6.3 static
archive hashes above, Rust/Cargo 1.98.0, pkg-config 3.0.6, and create-dmg 1.2.3
remain the same. This accepts the tools update and the complete preflight on
the owner's Intel Mac; the native build/audit, frozen smoke, and installed-app
walkthrough remain open.

## Client installer architecture contract follow-up

R3a introduces the [version-2 installer target contract](client-release-contract.md)
for the prepared client **1.4.0** source. Windows x64 and Intel Mac now have
explicit signed targets and architecture, target-specific filenames/channels,
and matching API/website selection. Legacy channels return manual-upgrade
instructions after deployment. The transition and rollback runbooks preserve
existing signed 1.3 artifacts and require coordinated staging acceptance.

The implementation passed **352 client tests on Windows**, with the native Mac
Bash test skipped, **31 isolated installer API tests**, and **8 website JavaScript
tests**. The client and changed backend modules passed Ruff check/format; the
API module passed mypy, and both native builders passed syntax parsing. After
the source version became 1.4.0, **91 focused client/release tests** passed and
`uv lock --offline --check` confirmed the existing lock remains valid.

Coverage includes both active targets at one version, missing/mismatched
architecture, unsupported/legacy targets, altered signed target/filename bytes,
wrong-channel manifests, no network request on unsupported client processes,
legacy HTTP 410 guidance, and explicit website labels without browser CPU
guessing. These are source/interface results: no native installer, release tag,
public activation, API deployment, or 1.3 profile upgrade was performed. R3b and
the native release/offline walkthroughs remain open in TODO.

## Frozen executable architecture gates follow-up

R3b's portable header checks and bootstrap/target/toolchain regressions passed
**106 focused tests on Windows**, with the Mac Bash integration test skipped.
The checks inspected the real Windows CPython executable as PE32+ AMD64 and
rejected synthetic ARM, 32-bit, DLL, universal, cross-platform, and truncated
candidates without executing them. Mac header fixtures are synthetic; no real
Mac frozen binary was inspected here.

Both builders now gate the frozen executable before smoke/packaging, and Mac
PyInstaller explicitly targets x86_64. Hosted source CI selects Windows x64 and
`macos-15-intel`, provisions/verifies exact native CPython before dependencies,
and checks the resulting client environment target. The Intel runner label was
verified against GitHub's published runner matrix. The new hosted run and final
native frozen builds remain pending; this record does not mark R3b complete.

The owner then ran the requested Intel bootstrap, `macos_release.py sync
--fresh-cryptography`, and the offscreen full client suite. The clean cryptography
**49.0.0** source build completed in **2m 22s** and the editable client reported
**1.4.0**. The suite passed **371 tests with 2 Windows-specific skips in 128.87s**.
This accepts the locked Intel dependency build and source-test gate on the
updated macOS 15.7.9 machine. The transcript did not record a Git commit; the final
tagged native build must retain its inventory/source commit. Static build inputs
and successful source tests do not replace the final bundle library audit,
frozen smoke, installed Keychain, and offline walkthrough.

## Preserved artifact publication follow-up

R4 adds the shared [publish-existing operation](artifact-publication.md) for
Windows x64, Intel Mac, and plugins. Native builders now stop after signing and
recording a dry run. Publication uses public keys and the recorded inventory
digest, validates saved source/target identity, confirms the displayed release,
and uploads a verified temporary copy without changing the saved output. The
old build/publication switches are retired.

The implementation passed **441 full client tests on Windows**, with three
platform-specific skips: the native Mac Bash builder and two Linux/POSIX `flock`
integration cases. Client-wide Ruff check/format and both native builder syntax
checks passed. Real temporary Ed25519 signatures cover both installer targets
and plugin catalogs; fake transport checks preserved bytes, changed/missing
evidence, source/target mismatch, declined publication, reused sequences,
concurrent activation, post-move SSH interruption, unknown outcomes, and public
smoke failure. The compare/move shell condition also ran in Windows Git Bash;
the native Linux locking primitive still needs staging acceptance.

No release signing key, financial fixture, SSH destination, or public artifact
directory was accessed. These local checks complete R4's implementation gate;
the staged publication and resulting native walkthroughs remain in TODO.

## Offline entry-point and frozen-session follow-up

O1's [diagnostic and owner procedure](client-offline-acceptance.md) cover fresh,
cached, and failing-network sessions through the real entry point/event loop.
The implementation passed **446 full client tests on Windows**, with the native
Mac Bash builder and two POSIX `flock` cases skipped. Client-wide Ruff
check/format and both native builder syntax checks passed.

An **unsigned Windows x64 diagnostic freeze** built with PyInstaller **6.21.0**,
CPython **3.13.15**, and the locked dependencies passed all three modes using its
actual bundled resources. The executable passed PE32+ AMD64 inspection and had
SHA-256 `a945140fb53bbd137f724696f29cef73f186614e46c2c1cd2b16fe51ea13f697`.
Each report showed `frozen: true`, five onboarding pages, and **151 heartbeat
ticks**. Fresh/cached runs attempted **zero** requests; the failure case attempted
only the **two** documented background manifest GETs. Cached/failure runs both
parsed/imported exact synthetic amounts, retained the copied source, detected
duplicate import, predicted with an existing model, and trained/saved/reloaded
a new local model.

The source tests also supplied hostile profile/settings/credential environment
overrides and verified that an existing canary file and surrounding profile were
untouched. The diagnostic uses its own temporary profile and ephemeral signing
key, never the release key or financial fixtures. Reports refuse to overwrite an
existing file. This is a diagnostic build from the working branch, not a tagged
release installer, installation/upgrade acceptance, or native credential test.
Intel source diagnostic acceptance was subsequently completed below. Both final
tagged frozen builds, hosted CI, and the installed offline/P2.2 walkthroughs
remain open.

### Intel offline timeout follow-up: September 19, 2026

The owner ran the source probes on `test/client-offline-session` and reported
**3 timeouts and 2 passing guard tests in 228.00s**. Each real-entry-point mode
hit the 75-second subprocess limit. This did not invalidate the earlier native
dependency-build/suite result; it exposed a separate offline-harness failure.

The harness identified the new-database message by its window title.
[Qt 6.11.2 ignores that title on macOS](https://github.com/qt/qtbase/blob/v6.11.2/src/widgets/dialogs/qmessagebox.cpp#L2509).
An untitled-message simulation reproduced the incorrect rejection on Windows.
Additionally, the failure path stopped its timer and called `app.exit()` during
a startup modal, allowing a later main event loop to wait indefinitely.
The harness now checks the expected message's temporary database path, parent,
icon, and buttons; failures unwind subsequent modals and prevent another main
event loop from starting.

Elapsed stage messages and a 60-second independent Python stack dump now survive
a blocked GUI. Source pytest failures and Mac build errors expose the captured
diagnostics; windowed Windows probes retain a separate diagnostic log on failure.
The 35-second GUI deadline and 75-second outer timeout are unchanged.

The revised full Windows client suite passed **451 tests with 3 skips in
103.59s** (native Mac Bash integration and two POSIX `flock` cases). Regressions
cover untitled messages, unexpected messages/dialogs followed by another modal,
stack capture without a Qt event loop, and preservation of existing log files.
Client-wide Ruff check/format and the Windows builder syntax check passed.

A rebuilt unsigned Windows diagnostic freeze also passed PE32+ AMD64 inspection
and all three offline modes. Its executable SHA-256 was
`358894fedb6d8b3a3c02ef0c3689f7094142e09a31244c64e440ca945d85e7a6`.
Fresh/cached/network-failure reports had five onboarding pages, respectively
153/152/153 heartbeat ticks, and 0/0/2 intercepted network requests; cached modes
completed the synthetic import/model checks. Successful windowed runs removed
their temporary diagnostic logs. This remains a diagnostic freeze rather than
a tagged installer or native installation test.

After the `fc273e5` fix was pushed, the owner reran
`pytest -q -x tests/test_offline_session.py` on the Intel Mac and reported
**10 passed**. This accepts the Intel source offline diagnostic, including all
three session modes and the modal-failure/diagnostic regressions, on the
previously recorded macOS 15.7.9 environment. The reply did not include elapsed
time or a separate commit report; `fc273e5` identifies the fix supplied for that
retry. The final native bundle audit/frozen probes and installed-app walkthrough
are separate acceptance gates; the Intel build result follows below. The
[offline procedure](client-offline-acceptance.md)
retains a single-case command for future investigation.

### Signed Intel Mac candidate: September 19, 2026

The owner completed the tagged Intel Mac dry build and reported:

| Field | Recorded value |
| --- | --- |
| Client / target | `1.4.0` / `macos-x86_64` |
| Requested source candidate | `client-v1.4.0` at `42a3dac970459327d8f3144f40195f4166a98cc9` |
| Signed release sequence | `20260919222343` |
| Signature verification | Passed; one installer artifact |
| Inventory SHA-256 | `dff66e320cf2d97c3e8924707f1104de13f693926a7735808fd827c87776a655` |
| Release files | Three: DMG, client manifest, and detached signature; inventory retained alongside them |

The owner used the sibling `parsetrail-resources/clients/macos-x86_64` output
directory configured on that machine.
Retain that complete directory and the recorded inventory digest for later
verification/publication. The candidate tag remains pinned to its build source;
documentation-only acceptance commits do not change the built artifact.

Completion of the unchanged guarded Mac builder means the locked dependency
sync, full client tests, bundled public-key check, thin Intel executable check,
native library audit, 30-second runtime smoke, and all three 75-second offline
session probes passed before DMG creation and manifest signing. This accepts
the Intel tagged build/audit and O1 frozen-session gates. The supplied transcript
contains the final success lines rather than the complete inventory or test
summary; no precise test count, Mach-O file count, or DMG hash is asserted here.

The installer manifest is signed with ParseTrail's existing Ed25519 release key.
Apple Developer ID signing/notarization remains deferred. No artifact publication
was performed. Installed GUI first start/restart without networking or build-tool
paths, Keychain persistence, and the P2.2 walkthrough remain open, along with the
Windows tagged build and hosted CI results. Use the installed-app procedure in
[offline acceptance](client-offline-acceptance.md) with this preserved DMG. The
owner confirmed that the Intel Mac's staging profile was new before starting
the installed-app first-launch check.

### Intel installed candidate verification: September 19, 2026

The Mac assistant fetched and fast-forwarded the clean handover checkout from
`42a3dac` to `1f69b6e`, then created `test/intel-macos-native-acceptance`.
The existing ignored release configuration and preserved artifacts were retained.
Direct checks confirmed macOS **15.7.9 (24G830)** and **x86_64**.

- **PASS — preserved release:** `client-v1.4.0` still resolves to
  `42a3dac970459327d8f3144f40195f4166a98cc9`. The inventory SHA-256 remains
  `dff66e320cf2d97c3e8924707f1104de13f693926a7735808fd827c87776a655`.
  Public-key verification accepted release **20260919222343**, with one artifact.
- **PASS — installer identity:** the verified DMG is **126452768 bytes**, SHA-256
  `679b1e431cda4711146394a17662f70c19040142a006255dbd815d4d6c04b781`.
  The saved inventory records **379 Mach-O files**, one cryptography extension,
  a passing system-only-PATH runtime smoke, and passing `fresh`, `cached`, and
  `network-failure` frozen probes. Its actual build tools include **uv 0.12.7**,
  CPython **3.13.15**, and PyInstaller **6.21.0**; uv 0.12.5 in the earlier record
  was the preflight baseline. An exact final source-suite count was not recovered.
- **PASS — separate installation:** mounted the preserved DMG read-only, created
  the previously absent `~/Applications/ParseTrail-1.4.0-candidate` directory,
  copied `ParseTrail.app` with `ditto`, and compared bundle files with `diff -qr`
  successfully before ejecting the DMG. This was a command-line installation;
  Finder drag-and-drop and owner launch-prompt observations remain separate.
  The installed executable passed thin x86_64 Mach-O inspection. Its embedded
  version, source commit, tag, and target match the preserved candidate.
- **PASS — installed native diagnostics:** reran all three probes against the
  installed executable with native Qt and system-only `PATH`. All reported
  `frozen: true`, `passed: true`, and five onboarding pages. Fresh/cached/failing
  network modes recorded **190/189/190 heartbeat ticks** and **0/0/2 intercepted
  requests**, respectively. Both cached modes completed synthetic local import
  and model operations. Each diagnostic owned a temporary profile; the staging
  profile remained absent afterward. These checks do not establish physical
  network disconnection, actual staging catalog access, or Keychain persistence.
- **FAIL — offscreen diagnostic attempt:** an initial sandboxed run with
  `QT_QPA_PLATFORM=offscreen` aborted in Qt's Mac wizard with
  `NSInvalidArgumentException` (`-[NSBundle initWithURL:]: nil URL argument`).
  The subsequent native Qt runs outside the sandbox all passed. The cause is
  not isolated between platform-plugin and sandbox differences; no runtime fix
  or candidate rebuild is justified by this result alone. Use native Qt for
  the installed-app walkthrough, as specified in the handover.

**PASS — owner offline first start and restart:** after receiving the native,
system-only-PATH launch command and the five-step offline checklist, the owner
reported, "Everything ran fine as [STAGING] with no errors." This accepts the
requested fresh start, five-page guide, ten-second wait, local views/Preferences,
normal quit, and offline restart with database/onboarding persistence and no
blocking login. No launch error was reported; individual macOS prompt wording
was not supplied. A subsequent read-only check confirmed onboarding version 1,
an existing selected database inside the staging profile, automatic update
checks enabled, and no model files. This covers responsive empty-profile use
with enabled checks; supported imports after failed checks remain separate.

The `ParseTrail-Staging` profile was absent before that walkthrough and now
contains acceptance state. Preserve it. Fixture imports, model use, and
current-staging-database backup creation/verification remain
pending. Sanitized `PATH` does not establish operation on a machine where build
tools are physically absent.

**Owner backup report:** the owner reported successful backup creation and the
backup test function, then confirmed a STAGING window and a retained backup.
The supplied file was outside the staging profile and had older revision
`e0ecdd6abcc6`; read-only checks passed SQLite integrity and foreign keys, but
its schema and row counts differ from the current staging database. The latter
also passed integrity/foreign-key checks at `0003_precise_financial_schema`.
This accepts the owner's test of an existing older backup, not creation of a
current staging backup. No second SQLite file was found inside the staging
profile. A fresh **Back Up Database** / **Test Database Backup** check was
requested with a new destination inside the staging profile, preserving both
existing databases. No database was changed by these inspections.

**Staging prerequisites:** unauthenticated checks from this Mac initially failed
with curl exit **6**, HTTP **000** (hostname resolution), for
`https://api.staging.parsetrail.com/api/v1/` routes `plugins/manifest`,
`plugins/manifest-signature`, `clients/macos-x86_64/manifest`, and
`keys/public-key`. The owner confirmed connection to the staging LAN/VPN.
The documented LAN address with curl `--resolve` and normal HTTPS verification
returned **200/200/404/200**, respectively. No system hosts entry existed for the
API hostname; an attempted additive update stopped at `sudo`'s password
requirement without changing the file. The owner was given the local command.
The owner then reported applying it. A subsequent request to
`plugins/manifest` using ordinary hostname resolution and normal HTTPS
verification returned **HTTP 200**, closing the local DNS prerequisite.

The public plugin catalog's signature and schema verified against the installed
candidate's bundled keys, and all **22 artifacts** passed runtime compatibility
checks: release **20260829091732**, manifest SHA-256
`4a68f8035cc833f8bdc1e6f70578f84100d308a3eb3337c934eef92c7458a093`.
**PASS — staging login and signed plugin installation:** the owner subsequently
signed in with the staging account, downloaded the plugins, and confirmed they
appeared in Plugin Manager. A read-only verification of the staging profile's
active release checked its pointer, manifest signature, all **22 artifact sizes
and SHA-256 digests**, and runtime compatibility against the installed app's
public keys. Release sequence and manifest digest match the catalog above.
The native `ParseTrail-Staging` Keychain item exists; the metadata-only lookup
discarded its output and did not retrieve the token. The staging configuration
contains no nonempty plaintext access token.

**PASS — Keychain restoration and synthetic contribution:** after quitting and
reopening the installed staging candidate, the owner submitted the prepared
one-page synthetic PDF through **Statements > Send for Plugin Development** and
its normal confirmation. No second login was requested, and the server-accepted
popup appeared. The generated document contains only "ParseTrail smoke"; SHA-256
`625fa34df0e8181c6421cde3a26ae9c7c7ffb91c62486bb90482c05c28c9826b`.
No real financial fixture was uploaded. This accepts native credential reuse
after restart and the explicit contribution flow against staging.

**PASS — sign-out:** the owner confirmed **File > Sign Out of Server**, then
repeated the synthetic submission flow and canceled the newly displayed login
dialog. No second upload was intended. A subsequent metadata-only Keychain
lookup for the staging service/account returned **44** (item not found),
confirming deletion; the earlier lookup had returned **0**.

Five synthetic cumulative CSV fixtures were prepared locally for the remaining
offline import/model walkthrough. The installed signed MOHELA parser accepted
them without validation errors or warnings. Expected statement rows/balances
are **8/-396.00**, **10/-495.00**, **12/-594.00**, **14/-693.00**, and
**16/-792.00**. Original and working copies are separate. This is fixture
preparation, not completed installed import or model acceptance.

The **404** for the 1.4 Intel installer manifest is a service
prerequisite for the later coordinated transition; no server change was made.
No replacement candidate, artifact activation, tag push, merge, or deployment
was performed.

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
