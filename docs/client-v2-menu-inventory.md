# 1.x desktop action inventory for the 2.0 cutover

This compatibility inventory maps `client/src/parsetrail/gui/main_window.py`
actions and adjacent dashboard tabs to the fresh V2 workspace. Ordinary startup
now uses V2; the retained published 1.x application remains independent. The inventory does not select work:
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
| Accounts → Edit Accounts | Financial accounts have explicit tracking scope; reviewed openings, manual/source closing points, value correction/withdrawal/conflicts and closure/reopen history are available. Values remain nonposting and residual books stay visible. Source proofs retain finite scope/sign and original section qualifications. | Integrated account review [V2-4](../ROADMAP.md#v2-4), manual breadth [DEC-1](../ROADMAP.md#dec-1). |
| Accounts → Appreciation Calculator | No V2 counterpart; activity does not establish investment values. | Deferred initial-release capability under [DEC-3](../ROADMAP.md#dec-3). |
| Statements → Import All | Multi-file and shallow-folder CSV/PDF batch import are available; native batch presentation was accepted. | Archive recovery [V2-3](../ROADMAP.md#v2-3), consolidated daily-workflow [V2-UX](../ROADMAP.md#v2-ux). |
| Statements → Pick File for Import | Selected CSV/PDF import uses a verified catalog; narrow shell/import flows have recorded native acceptance. | Family/installed checks [P2-3](../ROADMAP.md#p2-3)/[P2-4](../ROADMAP.md#p2-4), final imports [V2-3](../ROADMAP.md#v2-3). |
| Statements → Completeness Grid | Statement coverage shows bound periods, overlap/gap hints, printed endpoints, journal movement, live checks and saved reconciliation history/current-input status. Bound source provenance and source-backed openings have explicit review. | Integrated [V2-UX](../ROADMAP.md#v2-ux) and [V2-5](../ROADMAP.md#v2-5); retain independent capture/reconciliation limits and historical native evidence. |
| Statements → Correct Discrepancies | Evidence preview and append-only category/card-date corrections exist for supported rows. | Wider source/balance discrepancies and correction paths [V2-4](../ROADMAP.md#v2-4). |
| Statements → Send for Plugin Development | No V2 action; ordinary imports remain local. | Submission is deferred under [DEC-3](../ROADMAP.md#dec-3); any service work stays separately scoped [P2-S](../ROADMAP.md#p2-s). |
| Categories → Category Manager | Fresh custom categories, explicitly added fixed built-ins and effective-month budgets are available. Built-in Loan interest and custom matching names retain distinct IDs/labels. | Additional editing/hierarchy scope, if needed, [V2-4](../ROADMAP.md#v2-4)/[DEC-3](../ROADMAP.md#dec-3). |
| Transactions → Review Transactions | Admitted cash/card, HSA cash-component and account-total loan-register rows require explicit purpose/category review. Printed loan principal/interest uses a separate evidenced payment workflow. Whole owned transfers/liability repayments support explicit fees, partial/multiple receipts and authored ownership with no receipt yet. Corrections/withdrawal preserve full dated history and unresolved clearing; ordinary interpretations support posted-repeat repair. Scoped source assignment/occurrence review protects immutable inputs and prevents duplicate consumption. | Consolidated [V2-UX](../ROADMAP.md#v2-ux) and platform/release gates; unsupported shapes remain pending under [V2-4](../ROADMAP.md#v2-4). |
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
| Balance History dashboard tab | Account positions/history uses an inclusive as-of date, scope/origin, opening validity, separate manual/source values with withdrawal/conflict history, closure residuals, pending scope and separate live/historical/current saved reconciliation cutoffs. Total/component and unknown states stay distinct. | Consolidated [V2-UX](../ROADMAP.md#v2-ux) and platform/release acceptance; no certified current-bank-balance claim. |
| Category Spending dashboard tab | Reviewed Spending reports exact category totals with incomplete scope. | Charts deferred; truthful drill-down scope [V2-5](../ROADMAP.md#v2-5)/[DEC-3](../ROADMAP.md#dec-3), later CF3 comparisons. |
| Budgets dashboard tab | Monthly budgets are compared with reviewed spending in a table. | Charts deferred; further variance scope [V2-5](../ROADMAP.md#v2-5)/[DEC-3](../ROADMAP.md#dec-3). |

The V2 workbook contains active reviewed non-opening entries, exact posting and
source-allocation lines, correction links and scope for its selected date range.
The Retirements sheet records original/inverse links without a dummy replacement.
Transfer Reviews retains whole-event withdrawal/replacement links.
Active rows omit superseded entries and reversals while preserving correction
links. It does not certify unique source coverage, reconciled balances or cash
flow. Presets, category pivots and hiding internal keys remain separate
presentation choices rather than missing export implementation.

## Approved initial-release deferrals

The current workspace order is Documents / Accounts / Review / Transfers / Budget /
Reports. Review can post evidenced transfer and lender-payment sides with unresolved
counterparts; Transfers resolves relationships separately, without another principal
or interest posting. Origination has a distinct finite vehicle acquisition route.
Accounts exposes vehicle dated values/optional nonposting annual decline estimates.
These [owner-requested refinements](work/2026-11-16-origination-transfer-resolution.md)
retain the remaining initial-release deferrals and owner/platform/release gates.

The guided workspace now embeds ordinary document activity review, qualified
account positions/history and existing report tabs across Documents / Accounts /
Review / Transfers / Budget / Reports. Related document actions retain transfer, component-payment,
fee and evidence-check workflows. Ordinary review supports search/status filters,
exact sorting, next-pending navigation and explicitly staged atomic category
batches; correction/withdrawal remains separate. Reviewed-elsewhere activity
routes to its owning event instead of appearing pending for another posting.
Signed statement-format setup is explained before import; trust checks are
unchanged. Background reads, backup/restore/export and source recovery retain
their scoped progress/outcome ownership. These presentation changes do not
reactivate any deferred capabilities listed below.

Documents uses a sortable table with Account(s), Institution, Period, Type and
Review columns, plus Find and compact account/institution/type/review/date filters.
Typed dates and pending counts sort without comparing formatted text; unknown periods
remain last. Source identity preserves selection across sorting and reload. Filtering
cannot silently discard a staged Review, and report/next-review handoffs explicitly
reveal their target if filters hide it. Pending actions use the next-action cue;
completed value/history actions remain neutral.

Import uses Choose accounts → Review import for PDF/CSV. Compatible
existing accounts and Create a new account are offered together; all source
groups are represented. Managed products supply class/scope defaults, while
unknown source provenance stays unknown. Draft creation waits for Import and
assign, which atomically retains evidence/accounts/assignments without posting.
Back preserves applicable choices. Exact declared CSV headers and account metadata
route formats automatically; unresolved overlaps block import without column choices. Catalog/source/account drift requires a refreshed confirmation.

Review keeps a recognizable document/account/period selector, a next-attention
action and separate assignment versus activity guidance. An explicit document-date
spending action uses its known inclusive source dates as the report interval
(exclusive end is the following day). Reports still include **all profile
accounts**, not just that document; ordinary Reports navigation retains the chosen
dates/tab. Unknown document dates require deliberate report-date selection.
Entry inspection offers a guarded return to the exact source row and a return to
the retained report. Transfers, settlements and loans retain owning-event review;
saved loan navigation opens history rather than an unconfirmed replacement draft.
Corrections retain explicit confirmation, old/new category context and immutable
evidence. Navigation itself posts nothing. Read-only row tables use arrows for
rows and Tab to leave the table for the next control. Unsupported imports explain
recovery with their diagnostic details available.

Cash review provides Manage categories beside its category choice. Category setup
retains the row, purpose, reason and staged choices and refreshes the available
categories on return; the Accounts-page category manager also refreshes retained
review. Account/category setup itself posts no spending. Saved-operation feedback
remains visible after completion and clears on a later explicit row change. Import
completion restores local format-management and other recovery actions after
failure or cancellation.

Ordinary pending review uses one flow for one or many rows: numbered transaction
choices → Stage selected → Review staged → exact posting confirmation. The table
shows Not staged, Staged · not saved, or reviewed choices independently of saved
eligibility/blocker status. Selected proposals can be removed without losing other
staged work; hidden stages are counted. Later edits are marked Changes not staged
and do not change captured proposals until restaging. Required missing/invalid choices are pale red;
valid unsaved choices are pale green; unchanged saved, retained source values and
optional empty fields are neutral. Inline state/prerequisite text and keyboard
focus supplement color. Green does not certify evidence, coverage or posting
eligibility. Account creation, document/row/batch assignment and category budgets
use the same distinction; saved budget cues compare the freshly read stored rate.
Available save/stage/confirm actions use pale blue with stable label padding;
disabled actions remain neutral. Ctrl/Shift selects multiple ordinary rows and
shows their count. Shared purpose/category/note choices stage the whole selection
or refuse it without changing prior stages. Exact confirmation remains separate.
Reviewed ordinary rows separate the read-only **Saved review note** from an empty
**Reason for correction**. Unsaved cues reflect authored edits; correction and
withdrawal cannot inherit authorization from a stored note. Cancel retains the
draft; successful save updates the active note and clears the new reason.
Reviewed entries require individual correction; multi-selection cannot post,
correct or withdraw the current anchor as a single entry. Hidden staged rows are
counted, and successful staging captures the note shared by the staged batch.
Possible-repeat blockers show a direct comparison action instead of a purpose
instruction. It opens a related unresolved row/group comparison in the existing
profile-wide repeat review, retaining capped-list limitations. Return refreshes
eligibility and preserves selection/stages; supporting evidence cannot post again.
There are no color-legend controls in workflow screens. Help > Getting started
explains the convention. Report filters apply automatically, so valid dates stay
neutral rather than appearing as unsaved financial choices.

Institution is a managed name selector with an explicit unidentified choice;
internal institution codes are not editable UI fields. Reliable signed parser
identification is read-only; matching generic CSV headers do not identify a bank.
The registry is separate from supported formats, persists in schema-23 profiles,
and unknown institutions allow explicit account review without automatic matches.

CSV import uses a shared per-file preview for single selections and batch queues.
Exact declared headers and compatible account details must resolve one fully
validated format. Review import shows activity and assignments without manual column
mapping. Conflicting group structures refuse before assignment; unresolved compatible
formats block import. Import stores original/evidence and confirmed accounts/assignments
without posting. Skip leaves that file untouched; Cancel remaining preserves completed imports. No match
has no force-import override. Source/catalog changes require a fresh preview.
PDF keeps unique signed routing; XLSX is not included in this workspace flow.

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
