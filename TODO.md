# ParseTrail engineering TODO

Unfinished work only. `[ ]` is pending, `[~]` is in progress, and `[USER]` needs
owner GUI/platform testing or a product decision. Remove an item only after its
acceptance checks pass; preserve lasting behavior and evidence in the
[component guides and acceptance record](docs/engineering-acceptance.md).

Work Windows x64 and Intel macOS first. Apple Silicon native support remains
deferred; a bounded experimental GitHub CI/build feasibility check is welcome
without making it a Windows/Intel release gate. The [client review](docs/client-development-review.md)
contains findings and detailed acceptance criteria for the chunk IDs below.

The owner has approved the client roadmap below on September 26, 2026, following
P1.5, P1.6, and P2.2 acceptance. Unselected proposals remain suggestions, not
blanket implementation approval. Windows and Intel installed offline/P2.2 walkthroughs are
accepted. The owner also accepted the existing feature set after the Windows
private-copy retests and closed this development effort; see the
[closeout record](docs/engineering-acceptance.md#client-development-closeout-september-21-2026).
Client 1.4.2 is published for Windows x64 and Intel macOS; the
[production acceptance record](docs/engineering-acceptance.md#client-142-production-release-september-26-2026)
preserves release, recovery, and verification evidence.

The completed Mac results are in the [Intel return note](docs/intel-mac-return-note.md).
The [signed Windows candidate record](docs/engineering-acceptance.md#signed-windows-candidate-september-19-2026)
identifies the preserved installer used for Windows native acceptance.

## Active client roadmap — local spending and cash planning

Start from `main`, checkpoint `stable-1.4.2` (`effced9`), on the long-running
`feature/client-financial-insights` branch. Keep changes in small, tested,
reviewable commits on this branch. Stop when a product decision is ambiguous or
owner native GUI/platform acceptance is needed; prepare isolated profiles,
candidate code/artifacts, and concrete walkthroughs before that handoff.

This branch contains client features and their supporting tests/documentation.
Server P0 stays closed. If a client feature requires a server interface change,
stop at that boundary, merge the accepted client work first, and use a separate
short-lived server branch. The owner's locally hosted server is not part of
routine client development or automated tests.

### Agreed product behavior

- All financial analysis and ML stay local. Prioritize understanding spending,
  cash flow, and upcoming obligations ahead of categorization automation.
- Present spending separately from account cash movement. A card purchase counts
  as spending once; its repayment transfers money to the card account and still
  reduces available checking cash on its payment date. Exclude internal transfers
  from consolidated income/spending; show savings/investment contributions
  separately. Show loan obligations, separating principal/interest when supported
  by the data. Preserve unresolved classifications instead of guessing.
- Compare the latest fully covered comparable periods across selected accounts;
  default to month versus preceding month, with year-over-year when available.
  Explain category/merchant contributions and retain transaction drill-down and
  uncategorized amounts in reconciled totals.
- Start recurring detection with fixed and variable monthly bills. Display
  evidence-backed suggestions immediately; allow confirmation, correction, and
  dismissal. Only confirmed schedules feed the first cash-balance forecast.
- Reuse Statements > Completeness Grid's per-account intervals. Distinguish
  historical coverage from freshness: the owner's history is generally complete
  through August 2026 but imports happen in batches with a one-to-two-month lag.
  Never interpret unimported periods as zero spending or a stopped/missed bill.
- Forecast per funding account, showing its lowest projected balance and date,
  as well as recorded versus estimated values. Start upcoming obligations with
  a visible 30-day horizon. An available-to-spend scenario must disclose its
  horizon, reserved obligations, chosen cash buffer, and stale/missing inputs;
  stale records cannot support an unqualified current disposable-cash figure.
- Before offering available-to-spend estimates, capture confirmed card autopay
  account, due date, and payment basis (statement balance/minimum/fixed amount).
  A payment is not necessarily the card's current total balance. Later allow
  dated checking/card balance observations without rewriting transaction history;
  these refresh the forecast starting point but do not fill missing spending.
- SQLite can evolve incrementally with migration/recovery checks. Preserve exact
  money and original transactions; store confirmed interpretations/provenance
  separately and keep derived insights reproducible. Prepare full backup/restore
  support before substantial schema expansion.

### Approved implementation sequence

Each service/calculation chunk precedes its GUI chunk. Windows x64 owner GUI
acceptance is sufficient for routine client features; do not require a separate
Intel walkthrough for every feature. Retain supported-platform automated checks
and request targeted native cross-platform testing when dependencies, packaging,
OS integration, or evidence of platform-specific behavior warrants it. Record
only platforms actually tested; this does not claim Intel acceptance by inference.

- [~] **C2a-1 — Background recurring analysis:** cancellable worker, responsive
  heartbeat, worker-owned sessions, safe close, and no stale result after cancel.
- [ ] **C2a-2 — Background model training:** separate worker chunk; failed or
  cancelled training preserves the last usable model.
- [ ] **CF1 — Coverage and freshness service:** extract/reuse per-account coverage
  intervals for the existing grid and new analytics. Test overlap, gaps, empty
  accounts, different account cutoffs, and fully covered comparison periods.
- [ ] **CF2 — Cash-flow calculation contract:** define account scope, income,
  purchases, refunds, internal transfers, card payments, and loan treatment.
  Synthetic transfers/card payments cannot double-count consolidated spending;
  unresolved matches stay visible. Establish reviewed transfer interpretations
  before forecasts rely on them.
- [ ] **CF3a — Spending comparison service:** exact totals, comparable periods,
  merchant/category drivers, uncategorized rows, and source transaction evidence.
- [ ] **CF3b — Spending overview UI:** account/date filters, coverage/freshness,
  reconciled totals, and drill-down; owner Windows workflow acceptance, with
  targeted Intel checks under the testing policy above.
- [ ] **CF4a — Upcoming-obligation detector:** fixed/variable monthly patterns,
  expected dates/amount ranges, supporting history, and abstention on insufficient
  evidence. Backtest using earlier data only; cover refunds, irregular purchases,
  sparse history, calendar variation, and missing statement periods.
- [ ] **CF4b — Obligations UI and feedback:** persisted confirm/correct/dismiss
  decisions; distinguish estimates from recorded transactions. Native acceptance.
- [ ] **CF5 — Cash-planning design and implementation:** separately scoped chunks
  for confirmed income/bills/card autopay, dated balance observations, exact
  account-level projections, and scenario UI. Backtest forecasts, reserve each
  obligation once, expose assumptions/uncertainty and lowest-balance dates, and
  gate available-to-spend on input freshness and the selected horizon/buffer.

F2 import history supports later coverage/recovery explanations; old added/reused
counts that were never stored remain unknown. C2b precedes larger import flows.
F3 rules remain behind the first insights; split deterministic read-only preview
from atomic application/provenance. F4 should split verified bundle creation from
disposable restore. F1 offline onboarding and C3 dependency cleanup remain lower
priority proposals. New/unscoped features still require a design discussion.

## P1.5 — Client release reliability

- [~] **R2 — Intel macOS packaging:** `[USER]` Accept operation on a machine
  where build tools are physically absent when that environment is available.
  The signed candidate's installation, synthetic runtime/offline probes,
  and owner offline first start/restart with system-only `PATH` passed; see the
  [installed candidate record](docs/engineering-acceptance.md#intel-installed-candidate-verification-september-19-2026).

Acceptance: one clean tag produces traceable target-specific artifacts; a dry
run does not change public directories, and publish-existing uses exactly the
reviewed bytes. Intel clients start without Homebrew/build tools at runtime.

## Client correctness and cleanup proposals

Implement after the release/offline chunks. Each item is a focused change with
the review's acceptance checks, not a broad refactor.

- [~] **C2a — Responsive local analysis:** move recurring analysis and model
  training to cancellable workers. Verify GUI heartbeat, safe close/cancel,
  worker-owned sessions, and preservation of the prior model on failed training.
- [ ] **C2b — Responsive imports:** move import work to a worker with account and
  warning decisions on the UI thread. Cancellation must preserve commit/archive
  recovery invariants and accurately report committed work.
- [ ] **C3 — Packaging/docs cleanup:** measure the installed/frozen dependency
  graph, separate release/server-devtool dependencies into appropriate extras,
  and include client scripts/migrations in hosted lint. Keep devtools functional
  and pass native frozen/offline checks before removing a dependency.
- [ ] **W1 — Website theme script order:** remove the duplicate asynchronous
  `main.js` loader from the download page and review matching pages. It can run
  before jQuery, producing a console error even though the normal theme and both
  installer downloads work. Verify with delayed dependency loads and a public
  browser check. This pre-existing issue was recorded during 1.4.2 publication;
  its fix requires a separately tested website release, not new client installers.

## Client feature proposals

These remain follow-on proposals unless selected in the active roadmap. F1
addresses empty-profile offline use; C2 should precede larger import/analytics
features. Scope and acceptance must be settled before implementing each proposal.

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

Native acceptance is blocked on access to suitable test hardware; experimental
CI feasibility can proceed separately and is not a Windows/Intel release gate.

- [ ] **ARM-CI — Bounded feasibility check:** inspect native GitHub ARM runners,
  exact interpreter/dependency availability, and the existing Intel-only build,
  target, and binary-audit assumptions. Start with source tests, then propose
  separate experimental build artifacts if practical. Do not publish installers
  or claim support from hosted tests; retain native acceptance below.
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
