# 1.x desktop action inventory for the 2.0 cutover

This compatibility inventory maps `client/src/parsetrail/gui/main_window.py`
actions and adjacent dashboard tabs to the fresh V2 workspace. Ordinary startup
still uses the independent 1.x window. The inventory does not select work:
[ROADMAP.md](../ROADMAP.md) owns scope and approved initial-release deferrals, and
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
| File → Test Database Backup | Restore validates a copy before switching. | Separate read-only backup-test action is deferred under [DEC-3](../ROADMAP.md#dec-3). |
| File → Restore Database | Restore creates a new verified `.db`, then switches; native restore was accepted. | [V2-6](../ROADMAP.md#v2-6); no overwrite or legacy migration. |
| File → Export Account Configuration | Profile backup already retains account configuration. | Separate configuration export is deferred under [DEC-3](../ROADMAP.md#dec-3). |
| File → Sign Out of Server | The pilot uses a local verified catalog and has no server sign-out action. | Deferred client/server actions under [DEC-2](../ROADMAP.md#dec-2)/[DEC-3](../ROADMAP.md#dec-3); separately scoped [P2-S](../ROADMAP.md#p2-s). |
| Plugins → Plugin Manager | Signed catalog installation is available. | Offline starter/update behavior [P2-5](../ROADMAP.md#p2-5), service boundary [DEC-2](../ROADMAP.md#dec-2). |
| Plugins → Troubleshoot Parsing | Immutable saved-evidence preview is available. | Diagnostics/authoring scope [P2-4](../ROADMAP.md#p2-4); integrated [V2-UX](../ROADMAP.md#v2-ux). |
| Accounts → Edit Accounts | Financial accounts have explicit tracking scope; reviewed openings, dated values and closure/reopen history are available. Residual books remain visible. | Integrated account review [V2-4](../ROADMAP.md#v2-4), manual breadth [DEC-1](../ROADMAP.md#dec-1). |
| Accounts → Appreciation Calculator | No V2 counterpart; activity does not establish investment values. | Deferred initial-release capability under [DEC-3](../ROADMAP.md#dec-3). |
| Statements → Import All | Multi-file and shallow-folder CSV/PDF batch import are available; native batch presentation was accepted. | Archive recovery [V2-3](../ROADMAP.md#v2-3), consolidated daily-workflow [V2-UX](../ROADMAP.md#v2-ux). |
| Statements → Pick File for Import | Selected CSV/PDF import uses a verified catalog; narrow shell/import flows have recorded native acceptance. | Family/installed checks [P2-3](../ROADMAP.md#p2-3)/[P2-4](../ROADMAP.md#p2-4), final imports [V2-3](../ROADMAP.md#v2-3). |
| Statements → Completeness Grid | Statement coverage shows bound periods, overlap/gap hints, printed endpoints, journal movement, live checks and saved reconciliation history/current-input status. Bound source provenance and source-backed openings have explicit review. | Integrated [V2-UX](../ROADMAP.md#v2-ux) and [V2-5](../ROADMAP.md#v2-5); retain independent capture/reconciliation limits and historical native evidence. |
| Statements → Correct Discrepancies | Evidence preview and append-only category/card-date corrections exist for supported rows. | Wider source/balance discrepancies and correction paths [V2-4](../ROADMAP.md#v2-4). |
| Statements → Send for Plugin Development | No V2 action; ordinary imports remain local. | Submission is deferred under [DEC-3](../ROADMAP.md#dec-3); any service work stays separately scoped [P2-S](../ROADMAP.md#p2-s). |
| Categories → Category Manager | Fresh category names/kinds and effective-month budgets are available. | Additional editing/hierarchy scope, if needed, [V2-4](../ROADMAP.md#v2-4)/[DEC-3](../ROADMAP.md#dec-3). |
| Transactions → Review Transactions | Bound asset cash expense/income, negative card expense and whole transfer/card-payment review are available. Whole events can be withdrawn/replaced; suggestions can be dismissed/reopened. Category/card-date corrections and history remain append-only. Ordinary interpretations support withdrawal/posted-repeat repair; source assignments support explicit history-preserving correction after withdrawal. Repeated-row review guards detected unresolved or supporting repeats. | Fees, partial settlements and HSA/loan/source-value interpretations [V2-3](../ROADMAP.md#v2-3)/[V2-4](../ROADMAP.md#v2-4); consolidated [V2-UX](../ROADMAP.md#v2-ux). |
| Transactions → Identify Recurring | No V2 counterpart; forecasting remains outside the initial release gate. | Deferred initial-release capability; later CF4 scope under [DEC-3](../ROADMAP.md#dec-3). |
| Transactions → Insert Manually | Reviewed manual openings and nonposting dated values implement DEC-1 for missing new-loan openings or final statements on closed loans. Arbitrary manual journals remain excluded. | Integrated review under [V2-4](../ROADMAP.md#v2-4); arbitrary manual journals excluded. |
| Train Model → Train Model for Testing | No V2 counterpart; category review remains explicit. | Deferred initial-release capability under [DEC-3](../ROADMAP.md#dec-3). |
| Train Model → Train Model for Deployment | No V2 counterpart or automatic trained-model compatibility layer. | Deferred initial-release capability under [DEC-3](../ROADMAP.md#dec-3). |
| Reports → Export Three Months | Reviewed journal workbook export accepts an explicit date range; native export was accepted. | Date presets and pivot presentation are deferred under [DEC-3](../ROADMAP.md#dec-3); reports [V2-5](../ROADMAP.md#v2-5). |
| Reports → Export One Year | The same explicit-range reviewed journal export is available. | Date preset deferred under [DEC-3](../ROADMAP.md#dec-3). |
| Reports → Export All Time | The same explicit-range reviewed journal export is available. | All-time selection/preset deferred under [DEC-3](../ROADMAP.md#dec-3). |
| Help → About | Help > About this workspace shows current build identity and explicit development-pilot status. | Final release identity [V2-7](../ROADMAP.md#v2-7); no version bump or 2.0 release claim. |
| Help → Getting Started | Local daily-workflow guidance covers import, review, qualified reports and recovery. | Final integrated onboarding [V2-7](../ROADMAP.md#v2-7), [V2-UX](../ROADMAP.md#v2-ux). |
| Help → Check for Updates | No V2 counterpart in the pilot shell. | Client/catalog update scope [P2-5](../ROADMAP.md#p2-5)/[DEC-2](../ROADMAP.md#dec-2); service work stays separate. |
| Balance History dashboard tab | Account positions/history uses an inclusive as-of date, scope/origin, opening validity, separate manual values, closure residuals, pending scope and separate live/historical/current saved reconciliation cutoffs. | Remaining [V2-5](../ROADMAP.md#v2-5) report integration; no current bank-balance claim. |
| Category Spending dashboard tab | Reviewed Spending reports exact category totals with incomplete scope. | Charts deferred; truthful drill-down scope [V2-5](../ROADMAP.md#v2-5)/[DEC-3](../ROADMAP.md#dec-3), later CF3 comparisons. |
| Budgets dashboard tab | Monthly targets are compared with reviewed spending in a table. | Charts deferred; further variance scope [V2-5](../ROADMAP.md#v2-5)/[DEC-3](../ROADMAP.md#dec-3). |

The V2 workbook contains active reviewed non-opening entries, exact posting and
source-allocation lines, correction links and scope for its selected date range.
The Retirements sheet records original/inverse links without a dummy replacement.
Transfer Reviews retains whole-event withdrawal/replacement links.
Active rows omit superseded entries and reversals while preserving correction
links. It does not certify unique source coverage, reconciled balances or cash
flow. Presets, category pivots and hiding internal keys remain separate
presentation choices rather than missing export implementation.

## Approved initial-release deferrals

The workspace Reports menu also provides cash movement by reviewed purpose for
an explicit selection of asset accounts. It separates admitted cash categories,
owned transfers and card payments, preserving dates and unclassified/pending
limits. This is table reporting with common entry/source inspection; charts and
forecasts remain outside this action. Repeated-source review now supports the
bounded nearby-date/role-difference policy in the
[occurrence contract](client-v2-source-overlap.md).

The [roadmap](../ROADMAP.md) is the single launch and later-work plan. This
inventory records the owner's October 25 decisions. The table above follows these explicit dispositions:

- [DEC-1](../ROADMAP.md#dec-1) resolved October 25: reviewed openings and dated
  values only; arbitrary manual journals excluded.
- [DEC-2](../ROADMAP.md#dec-2) resolved: local signed-catalog installation suffices
  for the first release; the catalog service follows separately.
- [DEC-3](../ROADMAP.md#dec-3) resolved: both trained-model actions, recurring
  detector, appreciation calculator, separate configuration export, standalone
  backup-test action, export presets/pivots, dashboard charts, server sign-out
  and source submission are deferred from the first release.

The owner emphasized that these are important product capabilities to add later,
preferably in a future context run. They are **deferred, not retired**. The first
release retains the existing table reports, explicit-range export, verified
backup/restore and local catalog installation. This decision does not authorize
service deployment, production signing, release or live-profile activation.
Unknown accounting evidence stays visible and unposted.
