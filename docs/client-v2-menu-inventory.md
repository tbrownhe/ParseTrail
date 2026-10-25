# 1.x desktop action inventory for the 2.0 cutover

This inventory comes from `client/src/parsetrail/gui/main_window.py`. It records
the current 1.x menu actions and adjacent dashboard tabs. A 2.0 implementation
listed here is limited to the fresh-profile workspace; it does not imply the
legacy window has been replaced. **Pending** means the owner has not approved a
2.0 implementation or a release deferral. No pending action is silently dropped.

| 1.x action | Current 2.0 state | Remaining release decision or work |
| --- | --- | --- |
| File → Preferences | Global abbreviated-account matching toggle is available. | Inventory other 1.x preferences against the final 2.0 profile and catalog settings. Pending. |
| File → Open Database | Profile → Open 2.0 profile accepts only a verified `.db`. | Native profile switching accepted; no old-profile activation. |
| File → Database Location and Privacy | Profile → Data locations and privacy shows copyable profile, signed-catalog cache and global-preference paths, plus storage and encryption limits. | Native presentation acceptance pending. |
| File → Back Up Database | Profile → Back up current profile creates a verified new 2.0 snapshot. | Native backup accepted. |
| File → Test Database Backup | Restore validates a copy before switching. | Decide whether a separate read-only restore test is still useful. Pending. |
| File → Restore Database | Profile → Restore backup as new profile creates a new `.db`, then switches. | Native restore accepted; no overwrite or migration. |
| File → Export Account Configuration | Accounts live in the fresh 2.0 profile and its backup. | Separate account-config export pending decision. |
| File → Sign Out of Server | The pilot uses a local signed catalog. | Server-account behavior and any 2.0 action are pending; no server change in this branch. |
| Plugins → Plugin Manager | Signed catalog install is available. | Full catalog management/update UI pending. |
| Plugins → Troubleshoot Parsing | Saved evidence preview is available. | Parser diagnostics workflow pending. |
| Accounts → Edit Accounts | Fresh financial-account creation and identity editing are available. | Closures, manual values and wider account review remain pending. |
| Accounts → Appreciation Calculator | No 2.0 counterpart. | Pending decision; investment values are not invented from activity. |
| Statements → Import All | Multi-file and shallow folder batch import are available and accepted on native Windows. | Archive recovery and daily-workflow acceptance with real data remain pending. |
| Statements → Pick File for Import | Selected CSV/PDF import through the verified catalog is available. | Supported-family rollout and native acceptance remain release work. |
| Statements → Completeness Grid | Read-only statement coverage now shows explicitly bound periods, calendar overlap/gap hints, printed balances and evidence limits; the owner accepted the native interaction. | Reconciliation and missing-statement conclusions remain pending. |
| Statements → Correct Discrepancies | Evidence preview and explicit journal correction exist for narrow cash activity. | General source/balance discrepancy review pending. |
| Statements → Send for Plugin Development | No 2.0 action. | Server submission is pending decision; preserve local source files and evidence. |
| Categories → Category Manager | Fresh category names/kinds and effective-month budgets are available. | Additional editing and hierarchy behavior, if needed, pending. |
| Transactions → Review Transactions | Explicit bound asset expense/income review and same-kind corrections are available for activity exports and supported account-total bank statements. | HSA cash components, cards, liability, transfer, loan, manual and other interpretations pending. |
| Transactions → Identify Recurring | No 2.0 counterpart. | Pending decision; forecasting is outside the initial 2.0 gate. |
| Transactions → Insert Manually | No 2.0 counterpart. | Explicit manual journal/value workflow pending. |
| Train Model → Train Model for Testing | No 2.0 counterpart. | Pending decision; category review remains explicit. |
| Train Model → Train Model for Deployment | No 2.0 counterpart. | Pending decision; no trained-model compatibility layer is planned. |
| Reports → Export Three Months | Reviewed journal workbook export uses an explicit date range. | Time presets, if desired, pending; no claim of complete transaction coverage. |
| Reports → Export One Year | Same explicit-range export. | Time preset pending. |
| Reports → Export All Time | Same explicit-range export. | An all-time selection/preset is pending. |
| Help → About | No 2.0 counterpart in the pilot shell. | Release metadata presentation pending. |
| Help → Getting Started | Synthetic demo and cutover documentation exist. | Final onboarding pending. |
| Help → Check for Updates | No 2.0 counterpart in the pilot shell. | Client/catalog update workflow pending; no server change here. |
| Balance History dashboard tab | Account movement shows reviewed changes with unknown opening positions visible. | Reconciled balances and balance history pending. |
| Category Spending dashboard tab | Reviewed Spending report shows category totals and incomplete scope. | Chart/drill-down decision pending. |
| Budgets dashboard tab | Monthly budgets table compares effective targets with reviewed spending. | Chart/variance behavior beyond the current table pending. |

The 1.x Reports menu writes an `.xlsx` workbook with transaction rows and two
category pivots. The first 2.0 export instead records active reviewed journal
non-opening entries, posting lines, source allocations, correction links and scope in one
workbook. It omits superseded entries and reversals from active rows while
retaining correction links. The 2.0 workbook cannot certify unique source
coverage, account balances or cash flow. The owner chose reviewed transaction
rows for this first export and accepted its native Windows behavior. Some
internal keys remain visible for now; pivot and preset choices remain open.

## Proposed cutover scope for owner review

The first 2.0 release should be usable as a fresh daily profile, without
recreating the 1.x menu structure. The proposed launch work is:

- A verified offline starter catalog covering every current parser, with a
  selected-file import path and clear pending status for unsupported accounting.
- Explicit account binding, category and budget editing, ordinary bank/card
  review, transfers, loan interpretation, manual opening/value decisions, and
  corrections. Unknown source facts must stay visible and unposted.
- Statement-period overlap and reconciliation review before any balance claim;
  Spending, Income, budgets, account movement and transaction-row export must
  keep their incomplete-source scope visible.
- A clean profile lifecycle with verified backup/restore, visible storage and
  privacy information, and a minimal About/Getting Started path for the final
  build. Native Windows and targeted Intel Mac acceptance remain release gates.

The proposed deliberate omissions are the 1.x trained-model actions,
recurring-transaction detector, appreciation calculator, separate account
configuration export, standalone backup-test button, export date-preset
buttons, pivot sheets and dashboard charts. The verified profile backup already
contains account configuration; the explicit date range and tabular reports
cover the immediate reporting use. Server sign-out and source submission do
not belong in the local-only client cutover; server publication has its own
later gate. None of these omissions has owner approval yet.

Two choices still affect implementation order: whether users need arbitrary manual journal
entries in addition to reviewed openings and values, and whether a local
catalog-install action is sufficient until the separate server publication.
