# Client 2.0 rebuild and cutover plan

Planning baseline: October 4, 2026, after owner acceptance of the MOHELA replacement
review. The owner approved a required rebuild for the next major client version.
The application version stays unchanged during development. This document defines
the cutover target and implementation order, not completed migration or release
acceptance. Work stays on `feature/client-financial-insights`; server P0 stays closed.

## Release boundary

Client 2.0 uses the double-entry ledger as its only accounting model. Opening a
supported 1.x database offers a local rebuild into a separate 2.x profile; it never
upgrades that database in place. Source documents are replayed locally, without
uploading them to the server. A new user can create an empty 2.x profile directly.
An unknown, damaged or newer database format must fail before any writable schema
initialization. Database format identity and schema revision are separate from the
application's release version.

There will be no permanent legacy reporting engine, dual writes, or obligation to
migrate every intermediate development database. Retain only the bounded legacy
reader/rebuild path needed for the owner's inventoried source and recovery. Keep
the published 1.4.2 application and untouched source profile available for rollback.
Within released 2.x versions, resume ordinary versioned schema migrations with
backup and recovery checks. User decisions made in an activated 2.x profile are
durable data, not disposable development fixtures.

The first 2.0 release should support daily imports, review/correction, spending,
cash movement, account balances, budgets and exports from the new model. It need
not finish forecasting, new ML insights, securities cost basis, every loan format,
or reconstruction of missing servicer history. Unsupported evidence stays accessible
with explicit scope limits; it cannot silently disappear from a financial total.

## Starting point and remaining integration

The [ledger contract](client-ledger-contract.md), recovery bundle, fresh replay,
category preservation, exact posting kernel and staged Windows review workflows
are implemented. Accepted workflows cover ordinary expenses/refunds, income,
transfers/card payments, reviewed cash/card openings, source review/reconciliation,
expense/income corrections and supported loan payment/match corrections. The
MOHELA replacement preserves detailed evidence without posting it. These are
development workspaces; their sample decisions are not financial approvals.

The normal application still uses the legacy transaction model. Its import service,
dashboard, transaction review, budget queries, reports and account/category editors
must be connected to ledger services. The standalone review windows are reusable
components, not a finished everyday application. The current archive recovery tool
also excludes profile settings, plugins and models, so it is not yet the complete
cutover package.

## Preservation contract

Build a versioned, read-only preservation manifest before designing the activation
UI. Inventory the actual source schema, profile files and referenced external paths.
Every source item receives a destination, a retained-history disposition, a
rebuildable designation or an explicit unresolved reason. Unsupported user-authored
state is a blocker until its handling is agreed; a whole-database backup alone
does not establish that the new application can still use it.

| Data | Required treatment | Evidence for acceptance |
| --- | --- | --- |
| Original database and documents | Preserve a consistent database snapshot and complete archive, including failed/duplicate/pending files and relevant companion exports. Keep original inputs untouched. | Independent restore, file hashes, table/content inventories, source-membership checks. |
| Accounts | Preserve identities, names, numbers/aliases, institutions, descriptions, currencies, types and saved appreciation assumptions. Map closed/tracking status explicitly. | Every original account mapped once or blocked with a reason; closing an account creates no money movement. |
| Categories and budgets | Preserve custom definitions, hierarchy, active state, type, exact budget targets and currencies. Keep built-in semantic identities distinct from matching custom names. | Definition/mapping parity, exact budget comparison and usable budget editing in 2.0. |
| Verified categorization | Restore category-level verification on exact, unambiguous matches; retain original assertions for split/grouped or unmatched evidence. Preserve refunds and signed amounts. | Conservation by account/category/currency; every assertion restored or retained with its reason and source. No automatic ML overwrite or inferred transfer confirmation. |
| Other transaction edits and labels | Inventory unverified categories, edited descriptions/dates/amounts and any state actually present. Preserve legacy values and explain differences from fresh parser output. | No silent loss of manual work; each non-reproducible change has a reviewed disposition. |
| Manual values and entries | Preserve owner-confirmed asset values and closure intent. Inventory all remaining manual-only rows separately from source-derived transactions. | Values and provenance remain accessible; no invented purchase funding, expense or balancing transaction. |
| Genuine accounting decisions | Carry only explicitly authorized decisions whose source identity and interpretation still agree. Revalidate against the final rebuild. | Stale decisions return to review; no disposable UI exercise is promoted into the owner's books. |
| Settings and local resources | Preserve nonsecret preferences, account configuration, report locations, update preferences, and model/plugin inventories. Map database/archive/output paths to the new profile deliberately. | New writes cannot target the retained source archive/profile. Keep OS credentials in the existing credential store; no secrets in the financial manifest. |
| Plugins and ML artifacts | Retain compatible signed parser artifacts and trust/version provenance for offline replay. Preserve old model files for recovery; retrain locally when category/feature compatibility changes. | Installed replay works offline with verified parsers. An incompatible/missing model cannot block manual use or change verified categories. |
| Derived caches and reports | Recompute balances, charts, proposal caches and model predictions. Preserve existing exported files as historical artifacts. | No cache becomes an accounting fact; old/new differences are explained rather than forced to match. |

The first implementation inventory must confirm this list against actual data; do
not infer that all user state is covered because known tables were copied. Retain
private manifests, counts, identifiers and financial examples outside Git.

## Everyday behavior required at cutover

- Import supported PDFs/CSVs/XLSX into immutable evidence with account mapping,
  exact values, parser provenance and duplicate/multi-account membership handling.
  A duplicate import must not create another journal. Import retries and archive
  recovery must remain safe across cancellation and restart.
- Distinguish statement coverage from export activity spans. CSV/XLSX without
  independent endpoints cannot become reconciled statements through fabricated
  balances. Retain complete export snapshots. Until conservative changed-history
  comparison exists for a format, refuse automatic replacement/combination of
  ambiguous exports and present them for evidence review. Reimporting MOHELA must
  not silently erase a prior snapshot or compound its history.
- Offer the accepted review/correction workflows inside the application, with
  efficient batch acceptance for ordinary items. A retained verified category
  needs no new categorization; separate accounting confirmation can use the
  existing batch workflow. Ordinary acceptance needs no per-expense explanation.
- Manage accounts, categories and budget targets in the new model. Manual entries
  require explicit origin and a balanced interpretation; uncertain values remain
  observations. Reversal/replacement preserves posted history. Unsupported changes
  must be clearly unavailable rather than falling back to legacy writes.
- Show posted spending/income separately from cash movement. A card purchase adds
  spending once; repayment affects funding-account liquidity and liability, not a
  second expense. Loan principal is distinct from evidenced interest. Drill-down
  explains source evidence, postings, categories, dates and unresolved allocations.
- Show every tracked account, including closed or unsupported ones. Separate
  reported balance observations, ledger balances and valuation estimates, with
  their dates and provenance. An account without usable postings is unknown, not
  zero. A net-worth total must expose incomplete scope and cannot blend source
  balances into a ledger total without an explicit, labeled presentation rule.
- Drive budget actuals, charts and exported reports from the same ledger queries
  and scope rules. Budget targets survive the transition. Report metadata includes
  cutoff, account scope, coverage/freshness and unresolved items. Preserve useful
  basic balance/spending views; richer CF3 comparisons can follow in small chunks.
- Keep local category suggestions/training and recurring analysis separate from
  posted facts. Adapt existing tools to new read services or visibly defer them;
  every old menu action must have an explicit implemented/replaced/deferred
  disposition before activation. No stale legacy query may supply an unlabeled total.

## Activation blockers and permitted uncertainty

| Condition | Cutover policy |
| --- | --- |
| Missing/corrupt source, failed restore, unexplained lost user state, inconsistent mappings, unsupported source format needed for replay | Block activation until repaired or the owner explicitly reviews a concrete retained/excluded disposition. Never silently fall back to old financial rows. |
| Imbalanced journals, duplicate allocations, broken correction history, misleading totals, accidental writes to the source profile | Always block activation. A disclaimer cannot waive accounting/storage invariants. |
| Ambiguous category match | Block automatic restoration of that verified assertion. Retain its original category/history and candidates; activation requires resolving it or explicit acceptance of the visible pending item. Never call a partial restoration complete. |
| MOHELA unexplained differences, HSA boundary gaps, uncertain loan origination, missing historical coverage | May remain visible and unresolved. No invented income, interest, equity adjustment or verified coverage. MOHELA uncertainty was accepted on October 4. Other retained exceptions need their own disposition. |
| Unreviewed accounting/openings, unsupported investment or loan interpretations | Keep evidence and review queues. Affected account balances/period totals cannot be labeled complete or reconciled. Owner acceptance must identify the usable reporting scope and visible limitations. |
| Stale data | Allowed for historical reporting with explicit dates. Never present it as current disposable cash or proof that a recurring bill stopped. |

Passing cutover means preservation and functional correctness, with a reviewed
exception inventory. It does not mean every historical bank or servicer record has
been reconciled. No forecast or complete net-worth claim is a 2.0 launch gate.

## Small implementation chunks

These chunks organize the existing L/CF roadmap; they do not restart accepted work.
Complete each service before its UI integration. Keep commits focused and stop for
owner involvement at native acceptance or a concrete unresolved product decision.
Each row is a scope boundary, not a promise of a single commit.

| Order | Chunk and deliverable | Focused acceptance |
| --- | --- | --- |
| V2-1 | Preservation inventory and cutover manifest service, read-only. Classify source tables/fields, external files, parser availability and legacy UI actions. Reuse recovery/rebuild audits. | Synthetic missing-source/unknown-field/manual-state cases; private inventory from an authorized read-only snapshot; complete disposition totals. Stop for any uncovered user-data policy. |
| V2-2 | Explicit database format detection and 2.x schema lifecycle, before legacy ORM initialization. Retain a bounded read-only 1.x adapter. | New empty profile, supported legacy input, unknown/newer/corrupt files; no mutation on refusal; supported 2.x migration/backup failure recovery. |
| V2-3a | Single replay/import service for fresh reconstruction and ongoing evidence ingestion. First integrate ordinary statement sources and provenance. | Exact parser replay, duplicate/overlap/multi-account import, immutable source retention; no automatic posting or derived endpoint certification. |
| V2-3b | Bounded export ingestion policy using the accepted MOHELA reader and explicit review for uncertain overlap/revisions. Adapt other needed CSV/XLSX sources only after inventory. | Repeated identical file is idempotent; added/changed/missing/indistinguishable rows never silently overwrite decisions or imply complete coverage. |
| V2-3c | Main application import UI, archive recovery and cancellation integration. Reuse existing file-action contracts. | Cancel before/after commit, archive-write failure, restart/retry, unchanged original archive. Owner Windows import walkthrough. Keep any required C2b worker change separately reviewable. |
| V2-4a | Account/category/budget metadata services plus bounded manual-value/closure handling. | Preservation parity, built-in enforcement, exact budgets, unsupported manual cases retained without fabricated postings. |
| V2-4b | Integrate accepted ordinary/income/transfer/opening/source/loan review and correction services into the application, one workflow at a time. Include associated editors. | Owner Windows combined workflow, persistence, efficient ordinary batch review, reversal/correction and visible pending work. Do not ask to retest unchanged standalone behavior without reason. |
| V2-5a | Common ledger read services for spending, cash movement, balances and budget actuals; define remaining CF2 scope semantics. | Purchases/payments counted once; month-crossing clearing; loan interest/principal; refunds/splits/reversals; incomplete/unposted/unsupported accounts visible; exact totals with drill-down parity. |
| V2-5b | Replace dashboard/budget queries and report exports in small view-specific chunks. Inventory remaining menu actions and remove live legacy query paths. | UI/export/service agreement, explained old/new differences, scope/freshness warnings, owner Windows daily-use walkthrough. Decide any proposed feature deferral before removing it. |
| V2-6a | Verified cutover package and activation service. Add profile/resource preservation beyond today's database/archive bundle; stage and validate a separate profile. | Independent restore; source-change detection; interrupted build/activation and config-write failures; atomic profile switch/recovery; source database/archive unchanged. |
| V2-6b | Rebuild assistant: source selection, preflight, preparation, preservation/exception review, explicit activation and rollback instructions. | Owner Windows cancel/retry/failure/reopen/activation/rollback rehearsal on copies before a live switch. Live activation is a separate explicit approval. |
| V2-7 | Remove obsolete runtime compatibility paths after integration gates, freeze the 2.0 release candidate, and run installed-client/release acceptance. | Full relevant suite; packaged resources/signed parser replay; fresh and upgraded offline profiles; Windows x64 and targeted Intel Mac install/startup/rebuild/rollback checks. No public publication without release approval. |

V2-1 is next. It creates a reviewable inventory, not a schema rewrite, version bump,
live rebuild or new feature implementation. V2-2 through V2-7 are the planned order;
inventory findings can split or reorder bounded work without expanding the release
promise. Loan posting extensions needed for useful daily coverage receive their
own service/UI chunks under V2-4; do not require full loan-history reconstruction.

## Rebuild, activation and rollback sequence

1. Inspect the selected source read-only. Freeze a consistent database/archive and
   profile-resource inventory; bind parser artifacts and explicit owner decisions.
   Preserve an independently restorable package before activation work.
2. Build the candidate under a distinct database path and separate writable archive,
   settings and output locations. Current archive paths derive from the database
   stem, so a database-pointer change alone is insufficient. Retain verified local
   parser resources; development-only unsigned source replay is not the installed
   release's trust policy.
3. Compare preserved user state and new source evidence. Present exact accounting
   differences, exception dispositions and the proposed reporting scope. Bind real
   owner decisions to this input set; ignore earlier disposable walkthrough choices.
4. Before activation, close sessions and quiesce old writes. Recheck source database,
   archive and relevant configuration against the reviewed inventory. New imports or
   category edits invalidate the candidate; rebuild from a fresh snapshot and
   revalidate carried decisions. Do not activate a stale candidate.
5. After explicit owner approval, switch the complete profile reference atomically
   and verify reopening. Failure must leave a usable old or new profile with a clear
   recovery state, never a mixture. Do not overwrite or rename the legacy database
   into the new schema. Preserve the old application's independent configuration.
6. Rehearse returning to the retained 1.4.2 profile. Never give the 2.x database to
   the old application. If new 2.x imports/reviews exist, retain that profile too;
   rollback does not backport its decisions. Explain which post-cutover work would
   require re-entry before switching back. Returning later to 2.x reuses its retained
   profile only after checking for divergent 1.x edits.

## Release scope and gates

No version bump, live activation, installer build or publication is authorized by
this planning document alone. Use 2.0.0 when the integrated release candidate is
ready; keep app version, database format and signed manifest schema independent.
Retain existing installer targets and signed distribution contracts unless an actual
interface problem is found. If server work is necessary, stop, merge accepted client
work first and use a short-lived server branch. The server is not a development
dependency for rebuilding financial history.

Routine native feature acceptance remains Windows-only. Profile paths, packaging,
installation and rollback warrant a targeted Intel Mac release walkthrough; do not
repeat every accounting feature there. Apple Silicon native support remains deferred.
Experimental ARM CI feasibility is optional and cannot block this cutover.

Release evidence must include preservation/restore parity, accounting invariants,
read-service/UI/export agreement, a usable ongoing import/review cycle, explicit
exception dispositions, a stale-candidate refusal test, native activation/rollback
acceptance and traceable signed release artifacts. Public activation remains a
separate final approval after the exact artifacts are reviewable.

CF3 richer historical comparisons, CF4 confirmed recurring obligations, CF5 forecasts
and local AI insights follow the ledger cutover. Existing requested priorities remain
in [TODO](../TODO.md); making the new model usable does not authorize every proposed
feature. General parser declarative cleanup, automatic mutable-history merging,
investment performance/cost basis and speculative MOHELA history repair remain
separate scopes.
