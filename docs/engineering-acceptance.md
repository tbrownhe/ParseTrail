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
contains acceptance state. Preserve it. The results below include the completed
Move/Leave retention checks and final offline prediction audit.
Sanitized `PATH` does not establish operation on a machine where build
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
preparation; the owner's installed walkthrough and audit follow.

**PASS — owner offline import/model walkthrough, with recorded order variation:**
the owner reported that all checks passed while noting they did not follow the
order precisely. This covers the requested disabled/enabled-update offline
sessions, local responsiveness, installed-parser use, no-model guidance, training,
restart, and prediction. The report does not reconstruct the precise chronology.
The owner clarified that the two files originally proposed for Move and Leave
were imported with **Copy to Archive** instead. Those two retention choices were
therefore tested separately in the final check below, not inferred from this run.

The read-only audit found one synthetic account, **5 statements**, **16 canonical
transactions**, and **60 statement memberships**. Every fixture hash appears in
exactly one statement, with **8/10/12/14/16** memberships and matching end balances
**-39600/-49500/-59400/-69300/-79200 USD minor units**. All synthetic transaction
dates, descriptions, amounts, and running balances match the generated inputs
exactly. SQLite integrity and foreign keys pass at revision
`0003_precise_financial_schema`. The five preserved originals and working files
remain, each managed archive matches its input hash, and the folder-import input
was consumed while its fixture copy remained. This corroborates duplicate and
overlap handling, copy retention, and the reported folder-import move.

The local model is inside staging, uses bundle version `1.0-category-bundle`, and
records **16 training samples and 2 categories**. Independent reload predicted
all 16 saved rows into their stored categories. All 16 rows are categorized,
9 are verified, and automatic update checks are enabled in the saved config.
Because the model contains all initial 16 rows, two final synthetic exports with
new rows were prepared for Move/Leave and prediction without retraining after
another offline restart. They should yield **18/-891.00** and **20/-990.00**.
The final result follows below; the independent reload of the existing training
rows alone was not presented as prediction on unseen transactions.

**PASS — fresh staging backup and test restore:** following the clarified
instructions, the owner's all-checks-passed report includes creation and testing
of the new staging backup. The retained snapshot is inside staging, has the
current schema, and passes integrity/foreign-key checks. It contains the empty
pre-import state (zero accounts/statements/transactions), so row counts correctly
differ from the populated live database. A separate disposable restore matched
every row in every backup table and passed integrity checks. The live database,
snapshot, and earlier non-staging backup were preserved. Switching the installed
app to a new restored path was optional and **NOT RUN**.

**PASS — final Move/Leave and offline saved-model prediction:** the owner reported
following the final checklist precisely, with everything passing. It required
normal quit, network disconnection, native STAGING restart with system-only
`PATH`, importing two new synthetic exports into the existing account, and
categorizing their new rows with the saved model without retraining.

The final read-only audit confirmed:

- **Move to Archive:** the working source disappeared, its managed archive
  matches SHA-256 `ca8066ac1c70ab08e64c7de8f16795afddb433d6e0089783012d61f3426ce9b3`,
  and the preserved original remains. Its statement contains **18 rows** and
  ends at **-89100 USD minor units**.
- **Leave in Place:** the working source remains unchanged, no managed archive
  exists for it, and the preserved original remains. SHA-256 is
  `4779689f33560279261c3258c8ea7e7da27473284b6e5cee7784bae037fee41e`; its statement
  contains **20 rows** and ends at **-99000 USD minor units**.
- The final database has **7 statements**, **20 canonical transactions**, and
  **98 statement memberships**. Every expected synthetic date, description,
  amount, and running balance matches exactly. SQLite integrity and foreign keys
  pass at `0003_precise_financial_schema`; all seven fixture originals remain.
- The saved model still records **16 training samples and 2 categories**. Its
  independently reloaded predictions agree with all saved categories, including
  the **4 new rows** beyond the training export. The earlier **9 verified rows**
  remain verified. Onboarding version 1 and enabled automatic update checks persist.

This completes the approved Intel installed offline and P2.2 walkthrough using
synthetic fixtures. Local verification also reconfirmed the release signature,
original inventory digest, and pinned tag after the final check. No runtime
source change or replacement build was needed. Documentation changes passed
`git diff --check`; no full source-suite rerun or release rebuild was necessary.
The final dry-build source-suite count remains unavailable. Windows native
acceptance, hosted CI results, preserved-artifact publication, the coordinated
1.3-to-1.4 transition, and a machine with build tools physically absent remain
open; optional installed restore-to-new-path and Apple Silicon were not run.

The **404** for the 1.4 Intel installer manifest is a service
prerequisite for the later coordinated transition; no server change was made.
No replacement candidate, artifact activation, tag push, merge, or deployment
was performed.

### Windows tagged build preparation: September 19, 2026

After reviewing the completed Intel handover, the Windows assistant created an
isolated, clean checkout of the existing `client-v1.4.0` tag at
`42a3dac970459327d8f3144f40195f4166a98cc9`. The tag was neither moved nor pushed,
and no merge into `main` was needed. The build started on September 19 local
Pacific time (September 20 UTC), using a new client virtual environment.

- **PASS — bootstrap and locked sync:** native Windows 11 build 26200 / AMD64,
  managed CPython **3.13.15**, uv **0.12.5**, PyInstaller **6.21.0**, NSIS **3.12**.
  The package-free bootstrap ran before installing the locked client dependencies.
- **PASS — full source suite:** **451 passed, 3 skipped in 138.08s**. The skips
  cover Mac Bash integration and two POSIX `flock` cases. Bundled trust-key
  validation also passed.
- **PASS — tagged frozen build:** the unchanged tagged builder produced a
  **PE32+ AMD64** executable, then passed the bounded runtime smoke and all three
  real-entry-point offline modes: `fresh`, `cached`, and `network-failure`.
  These automated Windows checks used `QT_QPA_PLATFORM=offscreen`; installed
  native GUI and physical network-disconnection checks remain separate.
  This completes the Windows O1 frozen-session gate.
- **PASS — installer packaging:** NSIS produced
  `parsetrail_1.4.0_windows-x86_64_setup.exe`, **154450323 bytes**, SHA-256
  `08ee28ce3e64dd44f7efcbedf733fe2e31fda05f044ea8f08b7c8939731ccf07`.
  The frozen application executable SHA-256 is
  `655bfa4492f4fcda935e342e9206ccfbb2a224daf0ba45f06d0b06f19ec4c7ce`.
  Its embedded metadata independently matches version **1.4.0**, the pinned
  source/tag, Python **3.13.15**, and target **windows-x86_64**.

The assistant stopped the builder at its signing boundary so the owner can
enter the encrypted key's passphrase in their own terminal. At that boundary,
the target output directory contained only the installer: **no signed manifest,
detached signature, or release inventory existed yet**. The local handoff checks
the clean checkout, tag, and installer digest before using the tagged
`scripts.client_release sign` / `verify` and `scripts.release_inventory` commands.
It preserves these bytes and does not repeat packaging. At this stage the
candidate awaited signing; the completed signed dry run is recorded below.

The ignored local checkout is `scratch/windows-1.4.0-candidate`; its full build
log is `scratch/windows-1.4.0-build.log`, SHA-256
`6405c67818a9a7973fbfa8c96918a65b2f4e0c2c31510f556d78a1c4166a7936`.
The operator signing handoff is `scratch/sign-windows-1.4.0.ps1`; its PowerShell
syntax check passed. These are local operator files rather than release payloads.

An installed ParseTrail application and a `ParseTrail-Staging` profile already
exist on this Windows account. Preserve both. A separate Windows account can
isolate user data and credentials, but installation state is machine-wide:
the NSIS installer detects and uninstalls a previous installation registered in
HKLM. Neither another account nor an alternate install directory isolates that
installation. Use a disposable VM/second PC for a fresh installation, or prepare
an owner-approved upgrade of the existing installation with retained backups.

The focused `test/windows-native-acceptance` branch was pushed for a draft PR.
SSH Git access works, but no authenticated GitHub API/CLI credential was
available to create the PR automatically. The owner received the prepared PR
link; hosted CI remains pending until it is opened. No installation, artifact
publication, release-tag push, merge, or deployment was performed.

### Signed Windows candidate: September 19, 2026

The owner ran the local signing handoff and reported successful signing,
verification, and inventory generation. A subsequent independent read-only
review accepted the public-key signature, matched the reported inventory digest,
and verified the sizes and SHA-256 digests of all three recorded release files.

| Field | Recorded value |
| --- | --- |
| Client / target | `1.4.0` / `windows-x86_64` |
| Source | `client-v1.4.0` at `42a3dac970459327d8f3144f40195f4166a98cc9` |
| Signed release sequence | `20260920064925` |
| Inventory SHA-256 | `7661e24a9b46edb5709091f8d29271b7b9cea49cf58b8b23275ee6196971b8a1` |
| Installer SHA-256 | `08ee28ce3e64dd44f7efcbedf733fe2e31fda05f044ea8f08b7c8939731ccf07` |
| Installer size | `154450323` bytes |

The installer bytes are identical to the already-tested, pre-signing artifact.
The inventory agrees with the pinned source/tag, target, architecture, manifest
schema **2**, release sequence, version, and recorded build tools. Retain the
complete sibling `parsetrail-resources/clients/windows-x86_64` directory and the
original inventory digest. This completes the Windows tagged signed dry run;
its source tests, native build, and frozen checks are recorded immediately above.
No rebuild or repeated source suite was necessary for this signing follow-up.

The signature is ParseTrail's Ed25519 manifest signature; Windows Authenticode
remains deferred. No installation or publication was performed. This Windows
host reports edition **Core (Home)**, version **25H2**, and no Windows Sandbox
launcher. The owner is choosing a disposable Windows VM/second PC or preparation
of a backed-up upgrade on this PC for the native installed walkthrough; the
owner subsequently selected this PC, as recorded below.

The GitHub read-only check still found no PR or Actions run for
`test/windows-native-acceptance`; hosted CI remains pending. The existing
prepared draft-PR link starts that work without merging into `main`.

### Windows upgrade safeguards: September 20, 2026

The owner approved using this PC after preparing backups. The installed app is
registered as **1.3.0** in the 32-bit HKLM view. No ParseTrail process was running
during preparation. Before installation, the assistant copied and independently
verified **3,654 files / 588511211 bytes** covering the old installed app, both
profiles, the configured financial database, managed statement archive, models,
and reports. It also retained **two registry exports** and created **two SQLite
snapshots**. Each snapshot passed integrity and foreign-key checks and matched
its source's complete logical SQL dump digest.

The private backup is retained locally at
`scratch/windows-1.4.0-upgrade-backup-20260920T065839Z`. Its completion manifest
SHA-256 is `f8307f5fd9c06b5b3720e93d76ecfbb56733bb8c436123ce7a6124edec36aca4`.
The manifest and copied financial files are ignored local material, not Git
artifacts. No OS credentials were exported. Restoring the prior application
and machine registry would require owner administrator action; no rollback was
performed or claimed as tested.

A sandbox-context metadata lookup found no `ParseTrail-Staging` credential;
that lookup did not establish absence in the owner's Credential Locker. After
backup verification, the existing staging folder was preserved beside its original
location as `ParseTrail-Staging.pre-1.4.0-20260920T065839Z`; the active staging
path is now absent for the fresh-profile walkthrough. The production profile
and its configured data remain in place. This isolates application data for
the walkthrough while allowing the approved machine-wide installer upgrade.

The ignored owner handoffs are `scratch/install-windows-1.4.0.ps1` and
`scratch/launch-windows-1.4.0-staging.ps1`. The installer handoff rechecks every
backup file, the unchanged original sources (including the preserved staging
folder), installed version, and candidate installer hash before showing the
native installer. It then checks the installed executable hash. The separate
launcher uses native Qt, system-only `PATH`, and the staging API/profile.
Both scripts passed PowerShell syntax checks, and the complete backup/source
verification passed again after preserving the staging folder. **The installer
and installed app have not yet been run.** Owner steps are in
[Windows installation and first offline launch](client-offline-acceptance.md#windows-140-candidate-installation-and-first-offline-launch).

**Installer handoff interruption:** the owner's first attempt ended with
`KeyboardInterrupt` while reading a backup file, before launching the installer.
The subsequent read-only registry check still showed **1.3.0**. The local helper
now reports progress and elapsed time every two seconds, handles cancellation
without a Python traceback, and supports `-VerifyOnly` through the same
PowerShell entry point. Its standard-library verifier uses isolated, unbuffered
Python (`-I -u`) and does not require Conda activation. Running that entry point
with `-VerifyOnly` in the owner's normal execution context passed all **7,312
file checks in 34.5 seconds**, followed by the candidate installer hash check.
The backup, original app/data, and prepared fresh staging state still matched.
This follow-up did not launch the installer or change the signed candidate.

### Windows installed offline acceptance: September 20, 2026

The owner completed the prepared installer and staging launcher and reported
the **[STAGING] 1.4.0** window open. Read-only verification confirmed the machine
registry now reports **1.4.0** and all **2,528** packaged application files match
the tagged build exactly. The installed executable SHA-256 remains
`655bfa4492f4fcda935e342e9206ccfbb2a224daf0ba45f06d0b06f19ec4c7ce`.
All **1,091** backed-up production profile/database/archive/report files still
match their original hashes. The prior staging folder remains preserved.

**PASS — fresh offline first start and restart:** the owner explicitly confirmed
networking was disconnected during the initial launch and again for the second
staging launch, and reported that the requested checks all passed. This accepts
the five-page onboarding, offered staging database location, ten-second wait,
responsive local views and Preferences, normal quit, and offline restart with
the database retained, onboarding complete, and no blocking login. No installer
or launch error was reported. The independent config check found onboarding
version **1**, enabled automatic update checks, the staging API URL, an existing
database inside the staging profile, no trained model, and no plaintext token.
Installed-parser/model use and the rest of P2.2 remain pending.

**OPEN — Windows About provenance:** the file comparison also exposed a release
packaging defect. Windows copies the correctly populated metadata into the bundle
under a random `parsetrail-build-<id>.json` filename, while the application's
resource reader requires `parsetrail/build-metadata.json`. Resolving the actual
installed resource directory through that reader returns no metadata and the
About label `development source`. The signature, inventory, and file hashes
remain valid; the defect is the application's access to its embedded provenance.
Correct the Windows resource filename and add a frozen smoke gate before the
next candidate. Preserve the signed 1.4.0 bytes and tag; a replacement must use
a new version/tag. Continue the remaining native workflow checks on this
identified candidate while collecting any additional fixes.

**PASS — source fix and diagnostic frozen gate:** the Windows builder now stages
`build-metadata.json` inside a unique temporary directory, preserving the
canonical bundled filename and cleaning up after early failures. Frozen runtime
smoke requires readable schema-2 metadata whose version and target match the
running client. Source runs continue to work without release metadata. Regression
coverage uses the real resource resolver for the About label and smoke path,
rejects missing/misnamed/mismatched metadata, and exercises PowerShell builder
cleanup before dependency sync. The complete Windows client suite passed
**459 tests, 3 skipped**; Ruff check/format and PowerShell syntax checks passed.

An unsigned diagnostic freeze of the changed source passed runtime smoke with
the canonical resource and a system-only `PATH`. Renaming only that diagnostic
resource to the old filename pattern caused exit **1** with the expected missing
metadata error; the canonical resource was then restored byte-for-byte. This
probe used explicitly synthetic source metadata and is not a release candidate.
The installed app, signed installers, and `client-v1.4.0` tag remain unchanged.
The replacement candidate and its installed About check remain open.

**PASS — signed plugin installation and Windows credentials:** the owner
reconnected, downloaded plugins using staging credentials, and confirmed they
installed correctly. Independent local verification against the installed app's
public keys accepted all **22** artifacts in release **20260829091732**, including
runtime compatibility, sizes, and digests. The manifest SHA-256 is
`4a68f8035cc833f8bdc1e6f70578f84100d308a3eb3337c934eef92c7458a093`.
An owner-context, metadata-only Credential Locker lookup found the staging
credential; no secret was read or exported, and config contained no plaintext
token.

After quitting and restarting online, the owner successfully submitted the
generated one-page PDF containing only `ParseTrail smoke` through the normal
confirmation flow, without another login. This accepts Credential Locker
restoration across restart. The PDF SHA-256 is
`625fa34df0e8181c6421cde3a26ae9c7c7ffb91c62486bb90482c05c28c9826b`.
The owner then signed out and repeated the flow: it requested credentials, and
signing back in allowed a second successful synthetic submission. This accepts
functional sign-out/relogin. The owner completed login rather than cancelling
the dialog, so credential-store absence between those actions was not observed.
No real financial fixture was submitted.

**Fixture preparation correction — offline imports remain pending:** the first
generated MOHELA CSVs reached `NoParserMatchError` because CSV-writer escaping
doubled quotes in the header marker. The earlier preparation check invoked the
parser directly and missed the application's raw-text routing step. Reproducing
the error against the complete installed catalog identified the fixture problem.
Corrected copies preserve the parser's expected export header and pass
`parse_any` against all 22 authenticated plugins, selecting only
`csv_mohela_202411` with no validation diagnostics. The seven files produce
8/10/12/14/16/18/20 transactions and final balances from **−396.00** to **−990.00**
USD. The original attempted fixtures remain unchanged; corrected masters,
working copies, and expected hashes are retained under the ignored local
`scratch/windows-1.4.0-native-fixtures/routing-checked` directory. This routing
check does not substitute for the pending installed-app imports.

**PASS — installed offline one-off imports, duplicates, and overlap:** the owner
successfully imported the corrected first two fixtures and reported the expected
**−495.00 USD** total. Read-only verification found one synthetic account, two
statements, **10 canonical transactions**, and **18 statement memberships**. All
dates, descriptions, integer amounts, running balances, and currencies matched
the synthetic expectations exactly. Both archived statements matched the
expected SHA-256 digests; both working sources and master originals remained
unchanged. SQLite integrity and foreign-key checks passed. The application log
also recorded the repeated first file as a retained duplicate, with no added
statement or transaction. Automatic update checks were disabled.

The owner reported missing-categorization-model errors after each import. The
profile has no model; all 10 transactions remain uncategorized and unverified.
The log contains three missing-model exceptions, consistent with categorization
being attempted after both successful imports and the duplicate retry. The
current UI reports `Auto-categorization Failed` after data has already committed.
This accepts the local import/data-preservation behavior, not the quality of
first-use guidance. Actionable no-model guidance remains part of the unapproved
F1 proposal; no feature implementation was started. Folder import, training and
prediction, Move/Leave choices, enabled-check offline behavior, and database
backup/test restore remain pending.

**PASS — installed offline folder import and training inputs:** the owner
completed **Statements > Import All** for the prepared third fixture, then copied
the fourth and fifth fixtures into the archive through one-off import, reporting
the expected **−792.00 USD** total. Read-only verification found **five statements,
16 canonical transactions, and 60 statement memberships**. Every transaction
matched the synthetic expected dates, descriptions, integer amounts, running
balances, and USD currency. All five archived files matched their expected
SHA-256 digests, and the third fixture no longer existed in the managed input
folder. All seven master and working copies remained unchanged. SQLite integrity
and foreign-key checks passed, and automatic update checks remained disabled.

The 16 imported rows were still uncategorized and unverified at this checkpoint;
no categories or model existed. The last two fixture hashes were absent from the
database, preserving four new transactions for prediction acceptance after
training. Native category assignment, model training/restart/prediction,
Move/Leave choices, enabled-check offline use, and backup/test restore remain
open. This checkpoint does not claim model acceptance.

**PASS — native offline category review and model training:** the owner completed
the category assignment and **Train Model for Deployment** steps and reported a
saved `.mdl` file. Read-only verification found all **16** training rows verified,
with eight payment rows assigned `Synthetic Payment` and eight interest rows
assigned `Synthetic Interest`. The profile-selected model exists inside the
staging profile and loads as bundle version **1.0-category-bundle**, recording
**16 samples and two categories**. Its size is **2923 bytes**, SHA-256
`eaa000e540b85524a8e0c8f9be8d76254ab0a6cc8b88a7ebe143a331092f8894`.
The database retains five statements and 60 memberships; integrity and
foreign-key checks pass. Automatic update checks remain disabled.

Both remaining prediction fixtures still match their original hashes in the
working directory. The model checksum is retained locally for comparison after
restart and prediction, so successful use of this saved model can be separated
from retraining. This accepts native labeling, persistence, and training only;
restart, predictions on new rows under both offline update settings, Move/Leave
choices, and backup/test restore remain pending.

**PASS — installed offline saved-model predictions and Move/Leave choices:**
the owner followed both restart sequences with networking disconnected, first
with automatic checks disabled and then enabled, and imported the final two
fixtures with **Move to Archive** and **Leave in Place**, respectively. The owner
reported **−990.00 USD** and no further errors. Read-only verification found
**seven statements, 20 canonical transactions, and 98 memberships**, with every
financial field matching the synthetic expectations. The four new rows have
the correct payment/interest categories and confidence values and remain
unverified; all 16 original manual labels remain verified. The model SHA-256
is unchanged from training, proving the saved model was used without retraining.

The moved working file is absent and its archive hash matches. The Leave source
remains unchanged without a managed archive copy. All seven masters and the
other six working sources retain their original hashes. SQLite integrity and
foreign-key checks pass. Config now enables automatic checks; the log records
client and plugin update failures during the second restart, while the subsequent
local import and prediction succeeded without a blocking login or model error.

This completes **Windows P1.6 installed offline acceptance**, alongside the
previously accepted Intel walkthrough and automated source/frozen network-denial
checks. Physical disconnection demonstrates local usability; the automated
interception checks provide the evidence for zero network attempts when checks
are disabled. The empty-profile parser starter pack and improved no-model
guidance remain F1 proposals. Windows database backup/test restore remains the
last P2.2 walkthrough item; replacement-candidate provenance, hosted CI, and
publication/transition rehearsal remain separate release gates.

**PASS — native database backup and disposable restore test:** the owner reported
both **Backup Verified** and **Restore Test Passed** for the final synthetic
database. Independent read-only checks accepted the backup's SQLite integrity,
foreign keys, schema revision **0003_precise_financial_schema**, and complete
logical dump equality with the live database. Both contain **one account, seven
statements, 20 transactions, 98 memberships, and two categories**. The active
database path remains unchanged; no switch to a restored database was requested.

The local `windows-native-final.dbb` is **106496 bytes**, SHA-256
`ced63f582732093456380f3d53883ef4e23aee0dc3a9d2b2ae0bca42ffbf9917`.
The matching logical dump SHA-256 is
`4cc4de89780006493529035de6af078720c5f317eb141c5b9a31d724ca059363`.
The backup remains inside the staging profile and contains database data only,
not statement files or the model. This completes the **Windows P2.2 native
walkthrough**. Windows and Intel P1.6/P2.2 acceptance is now recorded; retain the
1.4.0 candidates as evidence and prepare a separately versioned candidate for
the Windows provenance fix. Later cleanup/features remain outside authorization.

### Windows 1.4.1 candidate: September 20, 2026

The complete Windows walkthrough exposed only the already-fixed release
provenance defect within the approved implementation scope. The no-model error
wording remains a recorded F1 proposal. A new **1.4.1** version preserves the
signed 1.4.0 artifacts and tag rather than replacing their bytes.

| Field | Recorded value |
| --- | --- |
| Build branch | `release/client-1.4.1` |
| Exact source / local tag | `0261f1f9d4efc4ba6aa7e7e31df4f421ef628ebd` / `client-v1.4.1` |
| Client / target | `1.4.1` / `windows-x86_64` |
| Installer | `parsetrail_1.4.1_windows-x86_64_setup.exe` |
| Installer size | `154450316` bytes |
| Installer SHA-256 | `7bd95d347c72ce9aebefc9d7741d60b6483c6b400c6c89ff288fcd520c558f0b` |
| Frozen executable SHA-256 | `89712148036e7b7647f3ec44cdfe91fd5e267a8785deb4dea3245cc6684a9bc6` |
| Canonical metadata SHA-256 | `2767ac98f34b7a167804e27cec947670d46e2ca700e70487139e4f87c7c8dbb4` |
| Signed release sequence | `20260921030412` |
| Release inventory SHA-256 | `1883101dd467ae52d35e2c8d892a6dc501560240279f1103922f578490b84584` |

**PASS — tagged build:** an isolated clean checkout at the exact tag completed
the pinned Python **3.13.15** bootstrap and locked sync, **459 tests / 3 skipped
in 91.63 seconds**, public trust-store check, PyInstaller freeze, **PE32+ AMD64**
architecture gate, frozen runtime smoke including provenance, all three frozen
offline modes, and NSIS packaging. The local lock check also passed without any
dependency changes. These automated Qt checks used the offscreen platform;
replacement installed-app acceptance remains separate.

The canonical resource contains the exact source/tag/version/target above, and
the application's resource reader against the actual bundle now returns About
label **`client-v1.4.1 (0261f1f9d4ef)`**. No misnamed metadata file remains. The
complete build log is retained locally as `scratch/windows-1.4.1-build.log`,
SHA-256 `9e8ae2843e8c096f227fbd480936024981a782f08a21812d6a690c1d5410abff`.

The preserved signed candidate is in
`scratch/windows-1.4.1-release/windows-x86_64`; its source checkout is
`scratch/windows-1.4.1-candidate`. The owner completed the separate signing handoff
without rebuilding the installer. **PASS — signing verification:** independent
public-key verification accepted the release, and all three inventory file sizes
and SHA-256 hashes matched. Source, tag, version, target, and sequence matched the
candidate; the installer retained its pre-signing hash above. Local evidence is
`scratch/windows-1.4.1-signed-verification.json`. Signing did not install or publish
the candidate.

The old 1.4.0 installer, manifest, signature, and inventory retain all recorded
hashes. The installed application remains 1.4.0; no replacement installation,
artifact publication, release-tag push, merge, or deployment has occurred. The
1.4.1 tag is local only. Documentation commits may advance the branch after the
pinned build source. The [Intel 1.4.1 handover](intel-mac-1.4.1-handover.md) specifies
that same source and separate artifact/app locations.

Hosted checks run on pull requests or main pushes. The owner opened PR #38 as
recorded below; merging into main is not required for local builds or hosted checks.

### Windows 1.4.1 private database-copy preparation: September 21, 2026

The owner agreed to a short local acceptance check with their existing financial
data before merging. **PASS — preparation:** with ParseTrail closed, the completed
synthetic staging profile was preserved, SQLite's online backup API produced a
consistent snapshot of the live database, and the snapshot matched its source's
table counts, logical digest, integrity, foreign keys, and current schema revision.
The working database, model, managed statement archive, and authenticated staging
plugin catalog were copied into a separate directory inside the staging profile.
Every copied file passed checksum verification; the source database and both
active profile configurations remained unchanged.

The pinned candidate's settings validation accepted the prepared configuration.
All 22 signed plugins loaded, and the copied model loaded without warnings or
missing database categories. Automatic update checks are disabled. No pending
live import files were copied into the working import queue, and OS credentials
were not exported. Private data, file inventories, hashes of financial files, and
model contents remain in ignored local evidence rather than this repository.

The owner handoff `scratch/launch-windows-1.4.1-real-data.ps1` verifies preserved
evidence and the candidate identity before selecting the copied database. Its
`-VerifyOnly` run passed without selecting a profile or opening the GUI. Normal
invocation runs the frozen 1.4.1 executable directly with a system-only `PATH`;
`-RestoreSynthetic`, after closing the app, restores the saved synthetic staging
configuration while retaining both databases and the working copies. This local
launcher is specific to the prepared evidence and is not a distributed tool.

The owner opened the prepared frozen build and reported the desktop regressions
below. Native acceptance remains incomplete; subsequent checks must use the fixes.
Direct execution of a frozen build does not complete installer replacement
acceptance. The installed application remains 1.4.0, and no merge or publication
has occurred.

### Windows desktop control regressions: September 21, 2026

The private-copy walkthrough exposed three failures in the preserved 1.4.1
candidate: Category Spending's Select All could clear but not check items,
Budgets always showed its failure placeholder, and the configured log file was
absent. Local inspection found the budget traceback in the default staging log;
logging had ignored the saved custom path.

Branch `fix/client-desktop-controls` corrects these existing behaviors:

- Both dashboard Select All controls consume the checkbox's boolean `toggled`
  signal. The previous integer `stateChanged` value did not equal PySide6's enum.
- Budget, appreciation, and recurring-input date controls use PySide6's
  `QDate.toPython()`. The old `toPyDate()` raised `AttributeError`.
- Budget spending-share aggregation keeps small-category amounts as `Decimal`
  until chart presentation. Fixing date conversion exposed a second failure when
  a small category was added to the float accumulator for Other.
- Startup logging uses the loaded settings' log path and creates its parent
  directory. Normal and staging profiles honor their saved paths.

**PASS — regression checks:** all ten new synthetic checks failed before the
fixes. The focused UI, budget-service, settings/profile, and offline checks then
passed **40 tests**. The full client run passed **468 tests / 3 skipped**, with one
Windows builder test blocked by the sandbox's PowerShell execution policy; that
single test passed when rerun in the owner's normal context without changing
policy. Ruff lint/format passed. No recurring-analysis algorithm, financial
schema, feature proposal, or infrastructure change is included.

**PASS — confidential read-only check:** the real Budgets widget rendered eight
combinations of month/custom range, category/type grouping, and inactive-category
filtering using the preserved database snapshot. Its checksum and the original
live database checksum remained unchanged. Only aggregate pass/fail evidence is
recorded here; private labels, amounts, dates, and log contents remain local.

**Pending — native and release acceptance:** the owner must recheck selection,
budgets, logging, and offline restart in the fixed source before replacement
packaging. Signed 1.4.0/1.4.1 bytes and existing tags remain unchanged; neither
contains this repair. A new version/tag must identify the replacement builds on
Windows and Intel macOS. The previous Intel 1.4.1 build handover is on hold.

### Hosted client gates and backend test annotations

The owner opened [PR #38](https://github.com/tbrownhe/ParseTrail/pull/38) from
`release/client-1.4.1`. At commit `198339c0cb62c307fd5e52622bfb2aa1921e6c63`, both
the [Windows x64 job](https://github.com/tbrownhe/ParseTrail/actions/runs/35556261970/job/106200377581)
and [Intel macOS x86_64 job](https://github.com/tbrownhe/ParseTrail/actions/runs/35556261970/job/106200377568)
completed successfully. These jobs include native interpreter/target assertions
and the source suite; this closes **R3b hosted architecture acceptance**. Backend,
frontend, Python lint/format, deployment-tooling tests, and Compose validation
also passed. Intentionally skipped workflow jobs are not claimed as executed.

The backend type job found four client-installer API tests missing parameter and
return annotations. Commit `bef7b10af601173fbcfc0482455654170b5dbeed` adds the existing
fixture types (`TestClient`, `Path`, `pytest.MonkeyPatch`), string parameter types,
and `None` returns. Local strict mypy passed all **61 backend files**, and Ruff
lint/format passed. The [hosted backend-types rerun](https://github.com/tbrownhe/ParseTrail/actions/runs/35570356972/job/106240515742)
and Python lint job also passed. Other jobs on that rerun were still running at
this checkpoint; their earlier successful client results apply to unchanged
client source. This test-only correction does not change the pinned 1.4.1 build
source, local tag, or preserved candidate bytes.

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
