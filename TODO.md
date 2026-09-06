# ParseTrail engineering TODO

Unfinished work only. `[ ]` is pending, `[~]` is in progress, and `[USER]` needs
owner GUI/platform testing or a product decision. Remove an item only after its
acceptance checks pass; preserve lasting behavior and evidence in the
[component guides and acceptance record](docs/engineering-acceptance.md).

Work Windows x64 and Intel macOS first. Apple Silicon is deferred until test
hardware is available. The [client review](docs/client-development-review.md)
contains findings and detailed acceptance criteria for the chunk IDs below.

The owner has approved P1.5, P1.6, and P2.2. Later correctness/cleanup proposals
remain pending, and **Client feature proposals require further discussion before
any implementation**. Native acceptance still requires the prepared owner checks.

## P1.5 — Client release reliability

- [~] **R2 — Intel macOS packaging:** `[USER]` Accept the next native build/audit
  and installed runtime without build-tool paths using the
  [Mac release gates](client/README.md#intel-mac-release-gates).
- [~] **R3b — Architecture gates:** interpreter and frozen-executable gates are
  implemented with explicit Windows x64 / `macos-15-intel` CI selection. Obtain
  the hosted test results and `[USER]` accept both resulting native builds;
  source/header tests alone do not establish frozen-app acceptance.
- [ ] `[USER]` Rehearse the resulting release flow on Windows x64 and Intel
  macOS: fresh bootstrap, native build/frozen smoke, signed dry run, preserved
  artifact publication, install/upgrade, credential store, and plugin update.
  Include the [1.3-to-1.4 manual upgrade and API/website transition](docs/client-release-contract.md)
  on staging before public activation.

Acceptance: one clean tag produces traceable target-specific artifacts; a dry
run does not change public directories, and publish-existing uses exactly the
reviewed bytes. Intel clients start without Homebrew/build tools at runtime.

## P1.6 — Offline session acceptance

- [~] **O1 — Offline harness:** exercise the real entry point and frozen
  resources; run beyond the update timer with checks disabled and enabled with
  network failures. Cover onboarding, signed cached plugins, synthetic
  parse/import, and local model train/predict.
- [ ] `[USER]` Run the installed-app network-disabled first-start/restart
  walkthrough on Windows x64 and Intel macOS, including responsive local use.
  Record empty-profile, installed-plugin, and trained-model behavior separately.

Acceptance: disabled checks attempt no network access; enabled checks fail in the
background after first paint and preserve local use. Parsing/categorization with
their local prerequisites never downloads package data or blocks on the network.
First import from an empty offline profile is the separate F1 proposal.

## P2.2 — Native fresh-user walkthroughs

- [ ] `[USER]` Walk through first run, account login, signed plugin install,
  one-off import, folder import, overlap handling, explicit statement contribution,
  and database backup/test restore on Windows.
- [ ] `[USER]` Repeat on the owner's Intel MacBook. Reserve Jacob's testing for
  official-release usability and product-gap feedback.

Acceptance: both walkthroughs work without source-code knowledge, and each
source-file move/retention choice is explained before the action.

## Client correctness and cleanup proposals

Implement after the release/offline chunks. Each item is a focused change with
the review's acceptance checks, not a broad refactor.

- [ ] **C1 — Recurring-analysis correctness:** make relative dispersion
  independent of debit/credit sign; define zero-mean, mixed-sign, singleton, and
  empty-vocabulary behavior. Equivalent positive/negative series must produce
  equivalent decisions and uninformative descriptions a useful no-result state.
- [ ] **C2a — Responsive local analysis:** move recurring analysis and model
  training to cancellable workers. Verify GUI heartbeat, safe close/cancel,
  worker-owned sessions, and preservation of the prior model on failed training.
- [ ] **C2b — Responsive imports:** move import work to a worker with account and
  warning decisions on the UI thread. Cancellation must preserve commit/archive
  recovery invariants and accurately report committed work.
- [ ] **C3 — Packaging/docs cleanup:** measure the installed/frozen dependency
  graph, separate release/server-devtool dependencies into appropriate extras,
  and include client scripts/migrations in hosted lint. Keep devtools functional
  and pass native frozen/offline checks before removing a dependency.

## Client feature proposals

These require a scoped design before implementation. F1 addresses empty-profile
offline use; C2 should precede larger import/analytics features.

- [ ] **F1 — Signed offline parser starter pack:** choose bundled baseline catalog
  or local signed-catalog import, verify before activation, preserve a newer
  installed release, reject tampered/incompatible bundles, and make no-model
  guidance actionable. Accept with a clean offline synthetic statement import.
- [ ] **F2 — Import history/reconciliation:** persist per-account added/reused
  transaction counts, source/archive states, failures, and pending recovery.
  Accept with overlapping/multi-account fixtures and safe retries after restart.
- [ ] **F3 — Categorization rules with preview:** add ordered local
  merchant/account rules, read-only preview, and atomic bulk application.
  Preserve manual verification unless the user explicitly selects those rows;
  prove deterministic precedence with synthetic merchants.
- [ ] **F4 — Complete local backup set:** optionally bundle a consistent database
  snapshot and managed archive with checksums, missing-source reporting, safe
  extraction, and disposable restore into a new profile. Exclude credentials and
  preserve plain database backup. Test without the original source paths.

## Deferred platform and product work

### Apple Silicon (arm64)

Blocked on access to suitable native test hardware; not a Windows/Intel release
gate.

- [ ] `[USER]` Establish an Apple Silicon development/native acceptance machine.
- [ ] Add the separate arm64 build, architecture-specific CI and installer
  publication after the target contract is in place. Prove Intel/arm64 artifacts
  at the same version coexist and each client selects a compatible installer.
- [ ] `[USER]` Complete native installation, Keychain, no-build-toolchain/offline
  startup, updater selection, and fresh-user walkthroughs before claiming support.
  Record any translation-mode behavior separately.

### P3.1 — Local data-at-rest protection

- [ ] Extend the device-loss threat model into an encryption/recovery design for
  SQLite, managed archives, backups, logs, and OS swap/crash dumps.
- [ ] Prototype platform-backed database/archive encryption with recovery and
  export paths before choosing SQLCipher or an equivalent.
- [ ] `[USER]` Choose the usability/recovery tradeoff and rehearse backup restore
  and lost-key behavior before enabling encryption by default.

### P3.2 — Linux support

- [ ] Add a Linux package, desktop entry, safe file-launch integration,
  sandbox-aware data locations, and CI smoke test.
- [ ] Test on a Debian-family and an immutable/packaged desktop before advertising
  support.

### P3.3 — Dashboard purpose

- [ ] Decide whether to retain a small account/download/admin surface, add
  privacy-safe operational features, or retire the dashboard if it has no clear job.

### P3.4 — Paid platform distribution trust

Defer until adoption or distribution friction justifies recurring vendor costs.

- [ ] Add Windows Authenticode signing and RFC 3161 timestamping for the executable
  and installer.
- [ ] Add macOS Developer ID signing, hardened runtime, and notarization.

## Separate server follow-up

Outside the active client scope.

- [ ] Migrate production bind-mount ownership and run the backend as a non-root
  user. Rehearse file/key/resource permissions and rollback on staging before a
  separately authorized production change.
