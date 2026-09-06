# Client development review and proposed chunks

Review date: 2026-09-05. Source baseline: `1766ceb` on `main`.

This review starts with the remaining P1.5/P1.6 desktop work. The target matrix
is Windows x64, macOS x86_64, and macOS arm64. Server P0 acceptance remains
closed. The installer contract is the one identified client requirement that
needs coordinated API and download-page changes; it needs no infrastructure
redesign.

The existing headless services, exact-money schema, import recovery, signed
plugin store, and database backup workflows provide a useful foundation. Finish
release and offline acceptance before taking on larger product changes. These
are proposals, not completed implementation or native acceptance claims.

## Verified baseline

- Read the root README/TODO, client README/changelog, contributor guide, privacy
  inventory, and desktop release/rollback documentation before tracing the code.
- Windows AMD64, Python 3.13.15, uv 0.12.5: **253 client tests passed** using the
  existing client environment and the suite's temporary profile/null keyring.
  Pytest reported one cache-write permission warning; no test failed.
- Ruff check and format check passed for client source, tests, scripts, and
  migrations: 162 Python files already formatted.
- Synthetic recurring-analysis probes reproduced the two cases described below.
  Private financial fixtures were unnecessary for these findings. They remain
  authorized for later confidential local acceptance, with only redacted results
  committed.
- No installer was built, signed, installed, or published during this review.
  macOS execution, native GUI acceptance, and fresh hosted CI results were not
  obtained here.

## Findings that determine the order

1. **The documented dry-run-to-publication command does not reuse the build.**
   [release.py](../client/scripts/release.py) always dispatches a native builder;
   `--publish` adds publication arguments without selecting an existing artifact.
   Both builders reject an already existing versioned installer. Consequently,
   following the README's instruction to repeat a successful dry run with
   `--publish` hits that guard. Windows has a lower-level `-DeployOnly` path, but
   the common CLI does not expose it and macOS has no equivalent. The common
   config also requires an existing private signing-key file for every operation.

2. **Mac architecture is missing from the artifact identity.**
   [client_manifest.py](../client/src/parsetrail/core/client_manifest.py) admits
   only `macos` and `win64`, requires unique platform/version pairs, and fixes the
   filename from that pair. [settings.py](../client/src/parsetrail/core/settings.py)
   reports every Darwin process as `macos`.
   The [installer API](../backend/app/api/routes/clients.py) and
   [download page](../website/download.html) use the same identity. An Intel and
   an arm64 installer at the same version cannot be represented and selected
   independently by this contract. The universal dependency lock does not prove
   that a built application supports both architectures.

3. **Release bootstrap checks happen too late or are absent.**
   [Windows](../client/build_client_win64.ps1) and
   [macOS](../client/build_client_macos.sh) invoke `uv run` before their explicit
   dependency-sync stage; neither enforces a minimum uv version or explicitly
   provisions and validates the exact interpreter first. The Mac builder checks
   for uv/create-dmg, but has no Intel source-toolchain/static-OpenSSL preflight
   or packaged-library dependency audit. Its frozen smoke invocation also lacks
   the Windows builder's timeout. These are missing gates, not evidence that the
   previously accepted Intel release has a runtime dependency defect.

4. **The offline test covers construction, not the complete first session.**
   [test_offline_startup.py](../client/tests/test_offline_startup.py) denies common
   Python network functions, constructs the real window and a fresh database,
   replaces onboarding, processes events once, and closes. It does not wait
   through the delayed update check or exercise parsing and categorization under
   the network denial. The preference test checks timer scheduling separately.
   [main.py](../client/src/parsetrail/main.py)'s frozen smoke imports a small
   runtime subset and checks keyring availability; it does not initialize the
   full financial workflow. The [CI matrix](../.github/workflows/test-backend.yml)
   already runs the offline test on its Mac job, but names only one generic
   `macos-latest` target and asserts no architecture. Source CI evidence and
   native installed-app evidence need separate records.

5. **A fresh offline profile has no usable parser catalog.**
   [PluginManager](../client/src/parsetrail/core/plugin_manager.py) loads the
   authenticated catalog from the profile. The native builders do not seed that
   store with a signed baseline catalog. Existing users can parse offline with
   installed plugins; an empty profile must acquire a catalog first. Likewise,
   categorization needs a locally trained model. Offline startup acceptance
   should distinguish these states explicitly instead of equating a working
   empty dashboard with a complete offline first import.

6. **Recurring-charge amount filtering is sign-dependent.**
   [filter_by_amount_variance](../client/src/parsetrail/core/cluster.py) divides
   standard deviation by the signed mean. With a 10% threshold, synthetic amounts
   `[10, 100, 1000]` retain zero rows, while `[-10, -100, -1000]` retain all three.
   Thus a varying debit cluster passes the filter. A second probe using only
   stop-word descriptions raises an empty-vocabulary `ValueError`. The UI contains
   the exception, but users receive a generic failure instead of an ordinary
   no-result state.

## First implementation sequence

Each row is a focused branch/PR with its own acceptance gate. Keep native
acceptance open until the actual supported platform passes it.

| Chunk | Concrete change and value | Acceptance |
| --- | --- | --- |
| R1 — Release bootstrap | Add a dependency-light bootstrap that checks uv >= the tested 0.12.5 baseline, validates the requested host target, explicitly provisions `.python-version`, and checks interpreter version/architecture before project sync. Route both native builders through it. | Fake command-runner cases for missing/old uv, unavailable interpreter, wrong architecture, and failed provisioning assert that dependency installation and signing never start. Exercise provisioning from a fresh Windows builder and each Mac architecture. |
| R2 — Portable Mac packaging | Preflight the Intel OpenSSL/Rust/pkg-config toolchain before any dependency resolution. Enforce static OpenSSL build inputs where source builds are needed; record those inputs and inspect packaged native libraries. Give the frozen smoke a bounded timeout. | Missing tools fail early; the artifact's library audit finds no unresolved Homebrew/workstation dependency. On each native Mac, the installed app starts and exercises cryptography, Qt, SQLite, PDF/XLSX parsing, and scientific modules without the build toolchain. |
| R3a — Architecture contract | Use separate native Mac packages. Add authenticated architecture metadata, explicit target identities such as `macos-x86_64` and `macos-arm64`, architecture-bearing filenames, and per-target artifact selection. Preserve Windows x64 as a supported target. Update API validation/listing, download links, inventories, and rollback documentation together. | At one version, both Mac artifacts coexist and each client selects only its compatible artifact. Reject unsupported/mismatched targets and altered signed metadata. Download-page tests always expose explicit Intel/Apple Silicon choices. |
| R3b — Architecture build gates | Teach builders to assert the requested architecture against the interpreter and frozen executable; add explicit Windows x64, Mac x86_64, and Mac arm64 CI entries with an architecture assertion. | All three source suites pass and native binaries report the expected architecture. Choose runner labels verified available when implementing; retain a native owner build gate where hosted coverage is unavailable. Record translation-mode behavior separately from native support. |
| R4 — Publish verified output | Add an explicit publish-existing operation shared by both desktop targets and plugins. Accept an immutable local release directory, reverify its signature/artifacts/inventory/source/target, then confirm and use the existing immutable publisher. Publication should require only public trust keys, not the private signing key or a rebuild. | A fake-transport rehearsal preserves every byte/hash/sequence and never invokes build/sign. Changed bytes, wrong source/target, missing inventory, reused remote sequence, and declined activation cause no pointer change. Keep interrupted-activation reconciliation and public smoke checks. |
| O1 — Offline session acceptance | Extend the offline harness to cover updates disabled beyond the timer delay, enabled checks failing after first paint, preserved local use, onboarding, signed cached plugins, a synthetic parse/import, and local model train/predict. Exercise the real entry point and frozen resources as well as source construction. | With updates disabled, no intercepted network attempt occurs. With updates enabled, only the documented background checks attempt networking; failure leaves the event loop and local operations usable. Repeat installed-app checks with networking disabled on Windows and both Mac architectures. |

R1 precedes build rehearsals; R3a precedes R3b. R4's common verification work and
O1's source harness can be implemented independently, with their final native
gates using the resulting target-specific artifacts. These chunks establish
traceability and repeatable gates; they do not claim byte-for-byte reproducible
NSIS/DMG output.

For R3, use a versioned contract and an explicit transition for existing 1.3
clients. Their schema rejects unknown fields and target names. Document a
one-time manual upgrade if the old endpoint is retired, or retain the old Intel
channel during migration; do not silently relabel an existing signed manifest.

## Further proposals, in recommended order

| Chunk | User value and bounded scope | Acceptance |
| --- | --- | --- |
| C1 — Recurring-analysis correctness | Fix sign-independent relative dispersion and define zero-mean, mixed-sign, singleton, and empty-vocabulary behavior. Preserve input money values. | Positive/negative equivalent series give equivalent decisions; high-variance debits are rejected; mixed/zero cases are explicit; uninformative descriptions produce a useful no-result state. Rehearse the GUI on synthetic data, then an authorized local copy. |
| F1 — Offline parser starter pack | Bundle a previously signed, compatible baseline parser catalog, or add a local signed-catalog import action. Prefer bundling if a first import with no prior network setup is the product promise. | A clean offline installation parses a synthetic supported statement. Verify before copying/activation, preserve a newer installed catalog, reject tampered/incompatible bundles, and keep downloaded catalog updates independent from app releases. Make no-model categorization guidance actionable. |
| C2 — Responsive local analysis | Move recurring analysis and model training behind cancellable workers first. Then use a separate chunk for import workers with UI-thread account/warning decisions. These operations currently execute synchronously in GUI handlers despite the extracted services. | A GUI heartbeat continues during deliberately slow jobs; closing/canceling is safe; worker sessions stay in their owning thread; failed training preserves the previous model. Import cancellation preserves the existing commit/archive invariants and reports committed work accurately. |
| F2 — Import history and reconciliation | Turn the transient import summary into a local history view showing per-account added/reused transactions, retained source/archive state, failures, and pending recovery. Reuse existing statement membership and recovery services. | Overlapping and multi-account synthetic imports have truthful counts; retries do not duplicate rows; archive failures can be located and recovered after restart. No history or statement contents leave the device. |
| F3 — Categorization rules with preview | Add ordered local merchant/account rules before model suggestions, with a preview of affected transactions and explicit bulk application. Start with exact/contains matching and preserve manual verification. | Rule precedence is deterministic; preview is read-only; applying a batch is atomic; verified transactions remain unchanged unless explicitly selected. Test on synthetic merchants and review usefulness on a confidential local copy. |
| F4 — Complete local backup set | Extend the existing database backup service with an optional database-plus-managed-archive bundle, manifest, and disposable restore rehearsal. Keep plain database backup available. | Consistent SQLite snapshot, archive checksums, missing-source reporting, bounded/path-safe extraction, and restore into a new profile all pass. Exclude credentials; keep local plaintext storage visible. Test restoring after original paths are unavailable. |
| C3 — Packaging and documentation cleanup | Separate release tooling and server-devtool dependencies from desktop runtime requirements after measuring the installed/frozen dependency graph. Refresh stale platform descriptions and add client release scripts/migrations to hosted lint coverage. | Local devtools still work with explicit extras; each native frozen smoke and offline workflow passes; record package-size/build-time changes. Avoid removing dependencies solely because no direct import was found. |

C1 is the first correctness fix after the release/offline chunks. F1 resolves
the empty-profile offline limitation if adopted. C2 should precede larger import
or analytics features. F2-F4 are product proposals, not commitments to expand
the scope of the release work.

## Owner involvement and evidence to retain

Prepare the candidate artifacts and isolated profiles before asking the owner
to run these checks. Record the artifact hash, source commit, app/Python/Qt
versions, OS version, machine/process architecture, steps, and pass/fail result.
Keep financial contents, account identifiers, credentials, and private paths out
of the committed evidence.

- **Windows x64:** install/upgrade/uninstall, first-run guide, Credential Locker
  login/sign-out, signed plugin installation, network-disabled restart and local
  use, one-off/folder/overlap import, explicit contribution, and test restore.
- **Intel Mac and Apple Silicon Mac:** repeat the installed-app walkthrough on
  each native architecture, including drag-to-Applications installation, Keychain,
  no-build-toolchain startup, network-disabled startup/local use, and the updater's
  architecture selection. Confirm available hardware before scheduling; success
  on one architecture is not acceptance for the other.
- **Existing P2.2 walkthroughs:** use the owner's Windows machine and MacBook for
  development acceptance. Keep Jacob's testing for official-release usability
  and product-gap feedback as already recorded in TODO.

The existing P1.5/P1.6 checkboxes stay open until their implementation and native
gates pass. The unrelated non-root backend item stays in its existing backlog;
it is not part of this client continuation.
