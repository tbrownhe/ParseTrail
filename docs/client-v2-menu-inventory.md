# 1.x desktop action inventory for the 2.0 cutover

This compatibility inventory maps `client/src/parsetrail/gui/main_window.py`
actions and adjacent dashboard tabs to the fresh V2 workspace. Ordinary startup
still uses the independent 1.x window. The inventory does not select work or
approve release omissions: [ROADMAP.md](../ROADMAP.md) owns those decisions and
[TODO.md](../TODO.md) identifies the current packet.

Current behavior below includes the completed bounded source-overlap safeguard.
Historical native acceptance remains recorded in the
[work-record index](work/README.md); implementation/agent verification is not
owner native acceptance. The [archived inventory](work/archive/2026-10-25-client-v2-menu-inventory.md)
retains the earlier snapshot and proposal wording.

| 1.x action | Current 2.0 behavior | Remaining scope / roadmap |
| --- | --- | --- |
| File → Preferences | Global abbreviated-account matching and assumed-posting-date toggles are available, both default off; their recorded native acceptance remains valid. | Inventory other preferences under [DEC-3](../ROADMAP.md#dec-3); integrated [V2-UX](../ROADMAP.md#v2-ux). |
| File → Open Database | Profile → Open 2.0 profile accepts only a verified `.db`; native switching was accepted. | Final profile lifecycle [V2-6](../ROADMAP.md#v2-6); no 1.x activation/migration. |
| File → Database Location and Privacy | Copyable profile, signed-catalog cache and preference paths explain storage/encryption limits; native presentation was accepted. | Integrated [V2-UX](../ROADMAP.md#v2-ux). |
| File → Back Up Database | A verified new profile snapshot includes source evidence and authored/reviewed data; native backup was accepted. | Final lifecycle/restore checks [V2-6](../ROADMAP.md#v2-6). |
| File → Test Database Backup | Restore validates a copy before switching. | Separate read-only backup-test action remains an unapproved omission under [DEC-3](../ROADMAP.md#dec-3). |
| File → Restore Database | Restore creates a new verified `.db`, then switches; native restore was accepted. | [V2-6](../ROADMAP.md#v2-6); no overwrite or legacy migration. |
| File → Export Account Configuration | Profile backup already retains account configuration. | Separate configuration export remains undecided [DEC-3](../ROADMAP.md#dec-3). |
| File → Sign Out of Server | The pilot uses a local verified catalog and has no server sign-out action. | Client/server disposition [DEC-2](../ROADMAP.md#dec-2)/[DEC-3](../ROADMAP.md#dec-3); separately scoped [P2-S](../ROADMAP.md#p2-s). |
| Plugins → Plugin Manager | Signed catalog installation is available. | Offline starter/update behavior [P2-5](../ROADMAP.md#p2-5), service boundary [DEC-2](../ROADMAP.md#dec-2). |
| Plugins → Troubleshoot Parsing | Immutable saved-evidence preview is available. | Diagnostics/authoring scope [P2-4](../ROADMAP.md#p2-4); integrated [V2-UX](../ROADMAP.md#v2-ux). |
| Accounts → Edit Accounts | Fresh financial-account creation and identity editing are available. | Closures, manual values and wider account review [V2-4](../ROADMAP.md#v2-4), manual breadth [DEC-1](../ROADMAP.md#dec-1). |
| Accounts → Appreciation Calculator | No V2 counterpart; activity does not establish investment values. | Omission remains undecided [DEC-3](../ROADMAP.md#dec-3). |
| Statements → Import All | Multi-file and shallow-folder CSV/PDF batch import are available; native batch presentation was accepted. | Archive recovery [V2-3](../ROADMAP.md#v2-3), consolidated daily-workflow [V2-UX](../ROADMAP.md#v2-ux). |
| Statements → Pick File for Import | Selected CSV/PDF import uses a verified catalog; narrow shell/import flows have recorded native acceptance. | Family/installed checks [P2-3](../ROADMAP.md#p2-3)/[P2-4](../ROADMAP.md#p2-4), final imports [V2-3](../ROADMAP.md#v2-3). |
| Statements → Completeness Grid | Statement coverage shows bound periods, overlap/gap hints, printed endpoints, journal movement and a versioned reconciliation check. Bound source provenance and source-backed openings have explicit review; their native flows were accepted. | Coverage conclusions and balance/report integration [V2-5](../ROADMAP.md#v2-5); retain independent capture/reconciliation limits. |
| Statements → Correct Discrepancies | Evidence preview and append-only category/card-date corrections exist for supported rows. | Wider source/balance discrepancies and correction paths [V2-4](../ROADMAP.md#v2-4). |
| Statements → Send for Plugin Development | No V2 action; ordinary imports remain local. | Submission disposition remains undecided [DEC-3](../ROADMAP.md#dec-3); any service work stays separately scoped [P2-S](../ROADMAP.md#p2-s). |
| Categories → Category Manager | Fresh category names/kinds and effective-month budgets are available. | Additional editing/hierarchy scope, if needed, [V2-4](../ROADMAP.md#v2-4)/[DEC-3](../ROADMAP.md#dec-3). |
| Transactions → Review Transactions | Bound asset cash expense/income, negative card expense and whole-movement transfer/card-payment review are available. Category/card-date corrections are append-only; native card/transfer review was accepted. Repeated-row review now guards detected unresolved or supporting repeats. | Broader overlap, repair of double postings/review-locked bindings, fees, partial settlements, transfer corrections, HSA/loan/manual interpretations [V2-3](../ROADMAP.md#v2-3)/[V2-4](../ROADMAP.md#v2-4); consolidated [V2-UX](../ROADMAP.md#v2-ux). |
| Transactions → Identify Recurring | No V2 counterpart; forecasting remains outside the initial release gate. | Later CF4 scope and unapproved omission [DEC-3](../ROADMAP.md#dec-3). |
| Transactions → Insert Manually | Reviewed source openings exist; arbitrary manual journals/values do not. | Manual breadth [DEC-1](../ROADMAP.md#dec-1), implementation [V2-4](../ROADMAP.md#v2-4). |
| Train Model → Train Model for Testing | No V2 counterpart; category review remains explicit. | Omission undecided [DEC-3](../ROADMAP.md#dec-3). |
| Train Model → Train Model for Deployment | No V2 counterpart or automatic trained-model compatibility layer. | Omission undecided [DEC-3](../ROADMAP.md#dec-3). |
| Reports → Export Three Months | Reviewed journal workbook export accepts an explicit date range; native export was accepted. | Date presets and pivot presentation remain undecided [DEC-3](../ROADMAP.md#dec-3); reports [V2-5](../ROADMAP.md#v2-5). |
| Reports → Export One Year | The same explicit-range reviewed journal export is available. | Date preset [DEC-3](../ROADMAP.md#dec-3). |
| Reports → Export All Time | The same explicit-range reviewed journal export is available. | All-time selection/preset [DEC-3](../ROADMAP.md#dec-3). |
| Help → About | No V2 counterpart in the pilot shell. | Final build metadata [V2-7](../ROADMAP.md#v2-7). |
| Help → Getting Started | Disposable demos and technical documentation exist. | Final onboarding [V2-7](../ROADMAP.md#v2-7), integrated [V2-UX](../ROADMAP.md#v2-ux). |
| Help → Check for Updates | No V2 counterpart in the pilot shell. | Client/catalog update scope [P2-5](../ROADMAP.md#p2-5)/[DEC-2](../ROADMAP.md#dec-2); service work stays separate. |
| Balance History dashboard tab | Account movement shows reviewed changes and confirmed source-backed openings separately. | Account positions/balance history [V2-5](../ROADMAP.md#v2-5); no current bank-balance claim. |
| Category Spending dashboard tab | Reviewed Spending reports exact category totals with incomplete scope. | Chart/drill-down scope [V2-5](../ROADMAP.md#v2-5)/[DEC-3](../ROADMAP.md#dec-3), later CF3 comparisons. |
| Budgets dashboard tab | Monthly targets are compared with reviewed spending in a table. | Further chart/variance scope [V2-5](../ROADMAP.md#v2-5)/[DEC-3](../ROADMAP.md#dec-3). |

The V2 workbook contains active reviewed non-opening entries, exact posting and
source-allocation lines, correction links and scope for its selected date range.
Active rows omit superseded entries and reversals while preserving correction
links. It does not certify unique source coverage, reconciled balances or cash
flow. Presets, category pivots and hiding internal keys remain separate
presentation choices rather than missing export implementation.

## Proposed cutover scope for owner review

The [roadmap](../ROADMAP.md) is the single launch and later-work plan. This
inventory preserves the decisions needed to reconcile the old menu with it:

- [DEC-1](../ROADMAP.md#dec-1): whether arbitrary manual journals are needed in
  addition to reviewed openings and values.
- [DEC-2](../ROADMAP.md#dec-2): whether local signed-catalog installation suffices
  until separate server publication, and the resulting client/service boundary.
- [DEC-3](../ROADMAP.md#dec-3): deliberate omissions or replacements for remaining
  1.x actions. Proposed omissions include the trained-model actions, recurring
  detector, appreciation calculator, separate configuration export, standalone
  backup-test action, export presets/pivots and dashboard charts. Server sign-out
  and source submission also need an explicit disposition.

These omissions remain **unapproved**. A profile backup retaining configuration
or a table covering immediate reporting needs supplies rationale for a decision,
not implicit owner agreement. Selecting an implementation packet does not decide
all pending actions or authorize server deployment, signing, release or live
profile activation. Unknown accounting evidence stays visible and unposted.
