# ParseTrail roadmap

This is the authoritative plan for outcomes, dependencies, scope decisions and
release gates. [TODO](TODO.md) identifies selected work; [work records](docs/work/README.md)
hold plans, decisions and verification. Component contracts define financial and
technical behavior. Historical plans do not select new work.

The owner approved this roadmap on October 25, 2026, selected V2-5 account
positions/history first, and authorized continued development until only human
review/action gates remain. Pending product decisions and release actions retain
their explicit boundaries.

## Product direction and boundaries

- Keep ordinary financial data, analysis and ML local. The separate account,
  artifact and explicit contribution service has its own scope and branch.
- Build 2.0 around one fresh authoritative SQLite profile and exact double-entry
  accounting. The owner re-enters authored state; 1.x remains an independent
  fallback. No 1.x migration, aliases or automatic category carry-forward.
- Show spending separately from account movement. Transfers and card repayments
  create no second expense. Unknown facts and unsupported interpretations stay
  visible; no invented balancing movements.
- Keep source capture, arithmetic, allocations, interpretation, reconciliation,
  calendar coverage and freshness distinct. Missing imports are not zero activity.
- Finish usable daily imports, review/correction, reports, account positions,
  budgets, export and recovery before richer forecasts or new ML insights.
- Target Windows x64 and Intel macOS. Preserve the [review policy](AGENTS.md#v2-development-and-human-review),
  [cutover contract](docs/client-v2-cutover.md) and [release contract](docs/client-release-contract.md).
  Version changes, production signing, daily-profile activation, deployment and
  publication require their specifically authorized release scope.

## How to read status

**Implemented** identifies a completed development outcome, not release or owner
acceptance. **Partial** means useful slices exist and named work remains.
**Open** is unfinished program work. **Proposed** is unselected scope requiring
a scope decision; **deferred** is outside the current release. Only TODO marks a
packet active. Tests, platform evidence and human acceptance live in linked records.

## Initial 2.0 milestones

Work in bounded packets. Import/evidence and accounting services precede dependent
UI/report claims. Parser/platform/catalog work can proceed independently where
its dependencies allow; the table is not a requirement to restart completed slices.

| ID | Outcome and current state | Remaining work / dependencies |
| --- | --- | --- |
| <a id="v2-1"></a>V2-1 | **Implemented:** fresh-profile boundary and independent 1.x fallback. | Preserve [cutover rules](docs/client-v2-cutover.md); release validation belongs to V2-7. |
| <a id="v2-2"></a>V2-2 | **Implemented pre-release:** one marked, verified profile; incompatible formats refused before writes. | Freeze the released schema/lifecycle after remaining workflows; follow [single-store rules](docs/client-v2-unified-store.md). |
| <a id="v2-3"></a>V2-3 | **Implemented development within the bounded source policy:** signed-catalog selected-file/batch CSV/PDF imports, immutable snapshots, binding, retry/cancellation, [nearby-date/revised-description occurrence review](docs/work/2026-10-25-v2-wider-source-matching.md), [reviewed account-assignment correction](docs/work/2026-10-25-v2-binding-corrections.md) and [embedded-original recovery](docs/work/2026-10-25-v2-source-recovery.md). | Source-backed opening withdrawal under V2-4 is a prerequisite for correcting an anchored assignment. Changed amounts/signs and unknown dates stay outside candidate matching. Final integrated daily lifecycle belongs to V2-UX/7; selected originals are never moved into a second archive. Coordinate with V2-4 and P2-4/5. |
| <a id="v2-4"></a>V2-4 | **Implemented development within the bounded accounting policy:** accounts/categories/budgets, [explicit cash/card purposes and stable categories](docs/work/2026-10-25-v2-category-purposes.md), [openings/manual values and closure](docs/work/2026-10-25-v2-account-anchors.md), [source closing values, withdrawal and scoped review guards](docs/work/2026-10-25-v2-source-values.md), [ordinary withdrawal/posted-repeat repair](docs/work/2026-10-25-v2-source-interpretation-repair.md), [whole transfer review/correction](docs/work/2026-10-25-v2-transfer-corrections.md), [fees and partial/multiple-receipt settlements](docs/work/2026-10-25-v2-settlements.md), [HSA cash components and owned outflows awaiting receipts](docs/work/2026-10-25-v2-hsa-cash.md), [evidenced loan principal/interest payments](docs/work/2026-10-26-v2-loan-payments.md), [account-total loan registers](docs/work/2026-10-26-v2-liability-register.md) and [durable reconciliation decisions](docs/work/2026-10-25-v2-reconciliation-history.md). | Unsupported/incomplete historical cases stay visibly pending. DEC-1/3 constrain breadth; arbitrary manual journals are excluded. Integrated UX/platform/release gates remain separate. |
| <a id="v2-5"></a>V2-5 | **Implemented development for admitted accounting shapes:** common reviewed spending/income, account movement, monthly budgets, journal workbook export, [explicit-scope cash movement](docs/work/2026-10-25-v2-cash-movement.md), [reviewed-entry drill-down](docs/work/2026-10-25-v2-reviewed-drilldown.md) and [inclusive as-of positions/history](docs/work/2026-10-25-v2-account-positions.md), with opening validity, pending scope and separate live/historical/current saved reconciliation cutoffs; HSA and both loan workflows integrate through V2-4. | Preserve explicit scope/unknown/coverage qualifications through V2-UX/7. Optional presentation remains deferred by DEC-3. |
| <a id="v2-6"></a>V2-6 | **Implemented development:** verified backup/restore-as-new, [explicit New/Open/Restore startup](docs/work/2026-10-25-v2-profile-startup.md), switching, embedded-original recovery and storage/privacy presentation. | Final integrated daily workflow, UX and supported-platform/recovery acceptance through V2-UX/7; backups exclude separate catalog/preferences. No old-profile activation. |
| <a id="v2-ux"></a>V2-UX | **Functional owner walkthrough completed; refinement open:** all stated demo features worked, including the confirmed cash split. The owner finds the interface overwhelming/confusing and requests another [UI/UX pass](docs/work/2026-10-26-v2-integrated-ui-review.md#further-owner-feedback-and-recommended-next-work), perhaps in a future context. | Simplify navigation, information density and wording using observed daily-workflow friction. A small local real-statement pilot is recommended but unselected; supported-platform and exact-candidate release acceptance remain under V2-7. |
| <a id="v2-7"></a>V2-7 | **Partial:** [default V2 startup/isolated diagnostics](docs/work/2026-10-26-v2-runtime-cutover.md), [independent installation identity](docs/work/2026-10-26-v2-installation-identity.md), [exact unsigned starter inputs](docs/work/2026-10-26-v2-catalog-signing-inputs.md) and [frozen Windows verification](docs/work/2026-10-25-v2-frozen-verification.md) completed within development scope; owner V2-UX walkthrough completed. | Intel/installed/no-build-toolchain checks and exact-candidate release checklist remain, including subsequent source UI follow-ups; version/signing/publication retain their separate authorization. Development artifacts do not establish release provenance. |

V2-5 distinguishes newly computed live reconciliation checks from explicitly
saved decisions and their current/stale input versions. The
[durable-history packet](docs/work/2026-10-25-v2-reconciliation-history.md) completed
development and independent verification; owner UX and release gates remain open.
The [candidate starting points](.agents/skills/parsetrail-workflow/references/code-and-checks.md#candidate-starting-points)
link the current contracts, symbols and focused checks for the next packets.

### Parser and catalog track

The [parser contract](docs/client-v2-parsing.md) and [family inventory](docs/client-v2-parser-inventory.md)
define the technical scope. All current parser families, including recent Citi,
remain required for the first 2.0 release.

| ID | Outcome and current state | Remaining work / dependencies |
| --- | --- | --- |
| <a id="p2-1"></a>P2-1 | **Implemented:** engine/family inventory and operation review. | Maintain the family matrix as supported operations change. |
| <a id="p2-2"></a>P2-2 | **Implemented:** strict finite declarations and provenance-preserving evidence design. | Extend only for selected supported source/accounting shapes. |
| <a id="p2-3"></a>P2-3 | **Partial:** client-owned finite handlers, bounded fixed decoder workers, [reviewed family source-fact dispositions](docs/work/2026-10-25-v2-readiness-audit.md#family-source-fact-dispositions) and [final frozen Windows worker/resource verification](docs/work/2026-10-25-v2-frozen-verification.md). | Targeted Intel native resource-limit checks; preserve disclosed capture/unclassified-item limits. XLSX has synthetic decoder evidence only and is not a workspace import format. |
| <a id="p2-4"></a>P2-4 | **Partial:** current family definitions, source-fact disposition inventory, signed routing/import path and successful synthetic admission for all declarations in [source](docs/work/2026-10-25-v2-family-source-admission.md) and the [final frozen Windows probe](docs/work/2026-10-25-v2-frozen-verification.md). | Intel/installed successful family admission remains open; synthetic admission and execution replay are not private-source parity or accounting acceptance. |
| <a id="p2-5"></a>P2-5 | **Partial:** local verifier/cache, atomic activation, signed-release install interaction and [exact final-source unsigned starter inputs](docs/work/2026-10-26-v2-catalog-signing-inputs.md) prepared for review. | Production detached signing and installed offline/rollback/compatibility checks, under explicit signing/release authorization. Unsigned inputs cannot activate. |
| <a id="p2-s"></a>P2-S | **Deferred from first release by DEC-2, separate service handoff:** immutable declaration-catalog API/storage/publication contract. | Reviewed design, accepted client integration and documented separate-branch handoff. Local signed-catalog installation suffices initially; service work remains required later and separately scoped. |

### Release checklist

- Complete or explicitly disposition the selected initial-release V2/P2 outcomes;
  invalid journals and misleading financial claims block release. Incomplete
  historical reconstruction can remain visibly unresolved under the contracts.
- Apply resolved DEC-1/2/3 and retain every remaining 1.x action's disposition in the
  [action inventory](docs/client-v2-menu-inventory.md).
- Complete the required supported-family, signed-starter-catalog and installed
  offline checks, plus Windows/targeted Intel decoder, packaging and OS integration.
  Preserve the R2 no-build-toolchain environment check when that environment is available.
- Complete V2-UX and final supported-platform/native acceptance for the exact
  candidate. Old 1.4.2 acceptance and offscreen V2 success do not accept 2.0.
- Verify fresh-profile reopening/recovery and the independent 1.x fallback.
  Follow the release runbooks for the separately authorized release actions.

Full-page capture remains an evidence dimension requiring honest review and
disclosure; it is not a newly imposed blanket balance-reconciliation blocker.
Forecasting, new ML insights and complete historical loan reconstruction are
outside the initial 2.0 release gate.
The owner's Wells Fargo personal-loan parser-change deferral remains in force;
retained legacy synthetic origination/opening uncertainty is not new source fact
or permission to reconstruct that history.

<a id="unresolved-owner-decisions"></a>

## Owner decisions

| ID | Decision needed | Dependent scope |
| --- | --- | --- |
| <a id="dec-1"></a>DEC-1 | **Resolved October 25:** reviewed openings/dated values only; arbitrary manual journals are outside scope. Owner use cases are missing opening information on new loans and missing final statements on recently closed loans. [Decision record](docs/work/2026-10-25-v2-account-positions.md#scope-and-controlling-decisions). | V2-4/7; retain explicit origin/review and unknown settlement facts; closing metadata cannot invent a payment or zero a balance. |
| <a id="dec-2"></a>DEC-2 | **Resolved October 25:** local signed-catalog installation suffices for first 2.0 release; the catalog service follows separately. [Decision record](docs/work/2026-10-25-v2-account-positions.md#scope-and-controlling-decisions). | P2-5/7 remain initial-release work; P2-S is later separate scope. Production signing/publication remain specifically authorized actions. |
| <a id="dec-3"></a>DEC-3 | **Resolved October 25:** defer the listed legacy capabilities for now, preserving them as important future product work, preferably in a future context run. [Action dispositions](docs/client-v2-menu-inventory.md#approved-initial-release-deferrals). | ML training, recurring detector, appreciation calculator, separate configuration export, standalone backup test, export presets/pivots, dashboard charts, server sign-out/contribution. First-release omission approved; permanent removal is not approved. |

## Later local spending and cash planning

These outcomes remain in the approved long-term client program. They are later
bounded assignments, not currently selected packets or initial-release gates.

| ID | Outcome / dependencies |
| --- | --- |
| <a id="cf2"></a>CF2 | Finish ledger cash-flow semantics under V2-5: account scope, refunds, transfers/payments, loan treatment and unresolved matches before forecasts use those totals. |
| <a id="cf3"></a>CF3a/b | Comparable-period spending service and UI, merchant/category drivers, uncategorized scope and transaction drill-down. Use fully covered comparable periods; default month versus prior month, then year-over-year when available. |
| <a id="cf4"></a>CF4a/b | Fixed/variable monthly obligation suggestions with evidence, abstention and persisted confirm/correct/dismiss feedback. Backtest without future-data leakage; missing/stale imports do not establish missed/stopped bills. |
| <a id="cf5"></a>CF5 | Exact account-level projections using confirmed schedules, income and card autopay account/due date/payment basis. Backtest forecasts, reserve each obligation once, expose assumptions/uncertainty and distinguish recorded/estimated values; show low balance/date and initial 30-day obligations. Available-to-spend discloses horizon, reserved obligations, buffer and freshness. Payment basis is not assumed to be current total card debt. Dated balance observations do not fill missing spending history. |

## Unselected proposals and deferred work

Retain scope decisions before implementation. Similar V2 functionality does not
automatically approve or complete an older proposal's broader/1.x scope.

| ID | State and disposition |
| --- | --- |
| R2 | **Remaining platform check:** Intel operation on a machine physically lacking build tools when available; prior system-only PATH acceptance remains historical evidence. |
| C2b | **Proposed legacy responsive-import work:** V2 already has worker/batch cancellation slices; reassess remaining need under V2-3 rather than open a duplicate implementation. |
| C3 | **Proposed:** measure frozen dependency graph, separate extras and improve scripts/migration lint; preserve devtools and native offline behavior before dependency removal. |
| W1 | **Proposed, separate website scope:** duplicate asynchronous theme loader/jQuery ordering; delayed-load/browser verification and separately authorized website release. |
| F1 | **Proposed broader offline onboarding:** map required V2 starter-catalog work to P2-5; no-model guidance and additional UX need selected scope. |
| F2 | **Proposed import history:** durable added/reused counts, archive/recovery states and restart-safe explanations; unstored historical counts remain unknown. Coordinate with V2-3. |
| F3 | **Proposed categorization rules:** ordered local rules, deterministic read-only preview and atomic application; preserve manual verification unless explicitly selected. After first insights. |
| F4 | **Proposed broader backup GUI:** legacy database/archive bundle and independent restore; V2-6 implements its fresh-profile scope, not automatic approval of all F4 scope. |
| ARM-CI / Apple Silicon | **Deferred native support:** bounded CI feasibility investigation is permitted separately. Native hardware, architecture-specific artifacts, Keychain/install/offline/update checks precede support claims/publication; no Windows/Intel release gate. |
| P3.1 | **Deferred:** device-loss encryption/recovery design for database, archives, backups, logs and swap/crash data; evaluate platform-backed storage and owner recovery tradeoffs before enabling it. |
| P3.2 | **Deferred:** Linux packaging, desktop/file-launch/data-location integration and testing on Debian-family and immutable desktops before advertising support. |
| P3.3 | **Deferred decision:** purpose or retirement of the account/download/admin dashboard; normal finance remains local. |
| P3.4 | **Deferred distribution trust:** Authenticode/timestamping and Developer ID/hardened runtime/notarization when adoption justifies vendor costs. |
| SERVER-1 | **Unselected, separate server scope:** non-root backend/bind-mount ownership hardening; staging permission/recovery rehearsal before separately authorized production changes. Server P0 remains closed. |

## Legacy IDs and historical evidence

L1/L2/L3/L4/L4R/L5b describe accounting audits, recovery, kernel/rebuild and
interpretation work from the earlier development sequence. Their completed
experiments are [historical evidence](docs/work/archive/2026-10-25-TODO.md#existing-ledger-and-insight-implementation-sequence).
Map surviving obligations to V2-2/3/4/5/6; do not reactivate migration or category
carry-forward. C1/C2a and 1.4.2 release acceptance are historical completed work.
V2-3a–c, V2-4a–b, V2-5a–b and V2-6a–b remain recognizable subtracks of the IDs above.

## Maintenance

The primary integrator updates status and dependencies when a packet closes,
links its work record, updates affected contracts, and clears the active TODO
entry. Keep validation logs out of this file and TODO. Record substantive owner
decisions in the packet record and apply their current rule to the relevant
contract or this roadmap; do not maintain competing decision logs or handovers.
