# One 2.0 user database for source evidence and ledger work

This is the current single-store contract approved by the owner on October 24,
2026. The [roadmap](../ROADMAP.md) owns sequencing and remaining scope;
[TODO](../TODO.md) identifies selected work. Implementation and verification
evidence belong in [packet records](work/README.md).

## Target boundary

- One fresh 2.0 SQLite profile owns immutable source bytes, declarations and
  evidence; user-authored accounts, categories and budgets; reviewed journal
  entries, corrections and review decisions; and common report reads.
- One authoritative `Accounts` table covers financial, category and internal
  ledger accounts. A financial account has an explicit asset/liability kind and
  institution metadata; a category has an income/expense kind. Source-account
  bindings refer to the account ID. Account identity and display fields are not
  copied into a second ledger account table.
- Pure double-entry checks remain in `ledger.py`; `v2_profile_store.py` owns
  profile journal tables and transactions. The isolated legacy ledger/rebuild
  stores are historical development evidence, not another runtime database or
  an attachable migration target.
- Immutable source rows remain separate from authored interpretations. A review
  supplies the financial account and any permitted accounting-date decision.
  Journal allocations point to admitted source rows and preserve their signed
  amounts. Parser output and account binding do not authorize postings.
- The 1.x application, database and archive remain independent and untouched.
  The [cutover contract](client-v2-cutover.md) defines the fresh-profile boundary;
  the [ledger contract](client-ledger-contract.md) defines financial meaning.

## Profile format and lifecycle

The current pre-release profile schema is revision 22; check `SCHEMA_VERSION`
in `v2_profile_store.py` when opening a packet. Format markers, exact table and
foreign-key shapes, append-only triggers and SQLite integrity are checked before
writable use. Older disposable pilots, 1.x, unknown, damaged and newer shapes
are refused. Earlier pilot profiles are recreated without migration or aliases.
Ordinary migrations apply only between released 2.x revisions.

Imports atomically retain source bytes and digest, exact declaration, immutable
strict evidence, and source observation identities. An identical source retry
returns saved evidence; a reparse is a comparison, not an overwrite. Revised
bytes remain a separate pending source. Failure/cancellation must preserve
completed imports and leave no partial new source.

`EvidenceSnapshots.content` preserves the complete typed parser result as JSON,
including source locations and provenance. `SourceObservations` is its relational
projection for observation identity, date, amount and allocation checks; authored
accounts and journals remain separate. The snapshot is evidence of extraction,
not an approved transaction list. Archive-wide reads stream and validate retained
sources and observation inventories once per operation, reuse that verified
evidence within the existing read snapshot and retain all corruption checks.
No process-wide evidence cache or duplicate authoritative store is introduced.

The document-summary read verifies every retained source within one consistent
snapshot and reports recognizable saved identities, explicit account assignments,
typed dates/provenance and conservative pending counts. Empty statement sections
still need account confirmation even when they contain no activity rows. Source
period overlaps remain separate from reviewed occurrence decisions. The positions
read reuses the reconciliation inventory for pending counts within its transaction;
unavailable reconciliation must not omit pending sources.

## Authored accounts and decisions

Explicit printed-account bindings, whole-file assertions for accountless exports,
and row assignments for mixed exports remain separate from imported facts.
Whole-file and row-assignment modes cannot coexist for one source. Abbreviated
automatic matching requires the global default-off choice and admitted signed
parser context; a match never posts a journal entry.
An abbreviated number can select only one full-number suffix match within the
same institution and asset/liability class. With the choice off, show the unique
candidate as a suggestion and offer the inline enable control. Ambiguous matches
always require explicit review. An observed full number may match exactly without
enabling abbreviated matching; an opaque identity is not a suffix number.

Confirmed individual rows also establish a derived document/account relationship
for discovery. Document summaries expose saved account IDs/names, source/file/row
or mixed basis, exact assigned-row count and completeness, including empty source
sections. This does not create a whole-file assertion, infer a printed identifier
or establish statement coverage/posting. Partial and multi-account exports remain
qualified and searchable through every associated account name.

Accountless review reads one committed, verified snapshot of evidence, accounts,
bindings and relevant history guards. Selection and combo changes query cached
immutable guard facts without reopening SQLite; save/correction services recheck
current authoritative history. Failed reload clears the cached presentation.
Document/batch windows check profile/WAL metadata on activation and queue changed
reads off the GUI thread. Metadata is a freshness hint, never a write authority;
write-time validation and stale-plan refusal remain mandatory.
The account-confirmation UI distinguishes read-time matching suggestions from
saved explicit associations. A suggestion does not reduce its unassigned count
or authorize posting; Use this account records the explicit source association.
Inline account creation stores only an authored financial account and then
selects it for a separate assignment decision. Document-backed defaults use the
exact verified declaration context and selected section's balance scope; unknown
class/scope stays an explicit choice. Masked/opaque identifiers are retained as
document context and editable display labels, not invented full account numbers.
Creation never bypasses existing assignment/correction locks or changes evidence.

Document-backed account creation shows the parser-known institution and printed
account as read-only context, plus the selected section's locations, qualified
dates, printed endpoint values and represented scope. Missing product labels
stay unknown. Default names use the final up to four contiguous visible digits;
source identity/form/full number and existing names are unchanged. New account
can inspect its selected original in a memory-only PDF/CSV reader without losing
unsaved form edits. Unknown institution setup remains an explicit editable choice.
**Assign document accounts** groups saved unassigned sections by
verified institution, class, tracking scope and exact printed identity/form.
Current explicit associations can seed another document with that exact context,
including opaque masked identifiers; no hidden digits are reconstructed. Unique
full-number matches and explicitly enabled abbreviated matching remain distinct
proposal reasons. Conflicts, accountless exports and protected history require
manual review instead of selecting a first candidate.

New accounts and choices are staged in memory. A final summary and Apply confirm
selected accounts and bindings in one transaction; Cancel before Apply saves
nothing. Closing with user-edited choices or staged accounts requires explicit
discard confirmation, defaulting to Keep working; automatic proposals alone are
not user edits. New account uses the currently selected target's retained context,
without extra profile scans. Apply rechecks the same profile, current source/account/history state,
verified catalog and preferences under the write lock. Stale plans and failed or
cancelled transactions leave no partial accounts/bindings; exact retries report
already-applied sections. The operation never posts journals or alters sources.
Planning and applying use worker-owned connections and one verified source pass
per operation. Original access uses retained bytes as described in the
[privacy contract](privacy-and-data-flow.md#v2-retained-original-preview).

Financial display/identity edits retain the account ID and ledger class. Tracking
scope explicitly distinguishes account total, principal component and cash
component, with compatible asset/liability kinds. Reviewed history locks scope
against ordinary edits; source operations retain their own admitted scope gates.
Ordinary account assignments with journal or review history cannot be changed;
the explicit correction workflow below retains/invalidate history safely.

`CategoryBudgetRates` stores at most one target per category and effective month.
The latest rate at or before the report month applies until another rate is
saved. An empty target clears later months without changing earlier targets;
zero is a valid target. These planning values do not post money or infer
categories. Category display-name edits retain historical account references.

Code-owned built-in categories have protected semantic IDs and fixed name/kind,
starting with `builtin:loan-interest`. Discovery and reports never materialize
them. Explicit authoring or an atomic reviewed posting may create a selected
known built-in; custom same-name categories remain separate identities. Reserved
namespace and persisted built-in metadata checks apply to common reads/backups.

## Journal and review history

Supported reviewed cash/card/register/transfer workflows atomically validate and save
balanced journal entries and signed source allocations. Cash-category and
card-category/date corrections save inverse reversals, replacements and their
links together; original entries and allocations remain history, and only active
allocations consume evidence. Source-backed opening corrections append revisions
and exact retirement inverses, including zero decisions without replacements.
Whole-transfer withdrawal/replacement preserves every original leg and creates
fresh replacement identities. Unsupported interpretations and unknown posting dates remain
pending.

Transfer review reads and confirmed mutations may reuse verified immutable
evidence within their owning SQLite transaction. Every original/declaration/
evidence/inventory is validated at operation start; parsed evidence is released
unconditionally afterward. Mutable assignments, journal/history, lifecycle and
consumption remain authoritative. No process-global source trust cache is created.
History validation builds per-pass source/binding, event/journal and allocation
indexes instead of scanning the same records for each event. Its complete result
may be reused only inside the owning transaction before any local write. After
the first write, including one rolled back to a savepoint, subsequent history
checks validate afresh; all operation state is cleared on success or failure.
Nearby-source Boolean guards iterate lazily in the existing date/row order and
skip contiguous same-source runs; candidate policy, full enumeration and review
requirements do not change.

`plan_unique_transfers` captures the reviewed basis, profile identity, preferences,
date gap and complete current candidate graph. Degree one at both legs is required,
counting date-disabled competitors; source overlap and prior explicit suggestion
decisions retain their existing eligibility rules. One explicit manifest confirmation
posts all captured isolated pairs under one write lock after fresh graph/basis
validation. Stale, failed or cooperatively cancelled batches roll back every new
journal/allocation/event/clearing row. Exact retries report already-posted events;
withdrawal or changed context cannot silently restore a prior batch. Both source
dates and dated clearing remain exact; repayments create no second spending.

Full-window transfer planning additionally groups the complete selected-horizon
graph into connected components. Non-estimated both-leg-unique pairs are Ready;
date-only conflict proposals are tentative and initially unchecked. Each bounded
component maximizes total `maximum_gap + 1 - pair_gap`, with unmatched score zero
and no cardinality tie-break. Only edges present in every optimum are proposed;
equal alternatives stay unresolved. Estimated-date competitors remain in the
graph but their conflict component is not date-ranked. Components exceeding 64
legs or 512 edges retain all candidates for explicit manual review. Source
descriptions are displayed, not invented into shared transfer-reference facts.

Selected planning batches freeze the whole graph/rule, scope, basis, profile,
preferences and exact compatible pair set. Selection is restricted to Ready,
forced date proposals or explicitly permitted isolated estimated-date pairs;
other alternatives retain individual review. A single manifest confirmation grants
posting of that set after fresh validation under the write lock. Rule, scope and
selection identity remain in immutable reasons; no planning action posts money.
This preparation adds no unattended-posting or saved-rule policy. Unknown purpose
and missing evidence remain unknown even when the ranking has a unique optimum.
Exact retries fully verify history and reconstruct the original horizon while
releasing only the selected active entries for comparison. Changed competitors,
withdrawal or replacement cannot recreate the old selection. Non-graph metadata
may permit an otherwise identical verified no-write retry.

The transfer GUI loads/updates through retained worker-owned connections, clears
stale actions while requests run and captures confirmation context before modal
questions. Ordinary confirmed writes finish to a known saved outcome on Close;
batch Close requests cancellation before commit and reports a committed result
truthfully. Forced teardown drains workers. No assumed-date setting is silently
enabled by individual or batch review.

Unresolved Plan candidates also have direct manual group review. Its alternatives
come from the retained complete component, with source descriptions and date
qualifications; final confirmation uses the existing individual-pair service,
not an extension of automated selection eligibility. Correction controls label
their required reason and show the next unmet prerequisite rather than presenting
unexplained disabled actions. Active manual and planner events share withdrawal
and replacement services, including full retained inverse history.

Cached transfer actions bind to the profile and preferences of their loaded
snapshot. They freeze reviewed context before a modal, recheck it afterward and
pass the captured profile to the writer. An identical cloned profile can share
event IDs and financial basis, so those values alone do not authorize a cached
action in another profile. Stale scope reloads without posting to either profile.

TransferEvents also retains finite reviewed settlement manifests: one complete
asset outflow, up to 32 distinct owned receipts, and at most 64 explicit fee parts
assigned to their source legs. Every raw financial amount is allocated once;
each advanced leg posts at its own reviewed source date, with fee expenses and
transfer clearing. Sending fees reduce sent principal; receiving fees add to a
net receipt's reviewed gross settlement. Residual clearing stays unresolved.
Zero receipts require an explicitly confirmed, distinct existing owned destination
and reference. The service captures its identity/kind/scope under the write lock;
the expectation is authored metadata only. No destination observation, allocation,
receipt date or positive financial posting is created. Expected ownership cannot
coexist with actual receipts in one manifest. Later receipt evidence uses whole
replacement. Retained history protects destination kind/scope even after retirement.
Legacy whole-pair APIs retain their shape; generic history exposes the full
manifest without pretending it is one pair. Whole replacement/withdrawal retains
every dated inverse and source-use history. Earlier pilot formats are recreated.

Code-owned clearing identity/class/role/purpose/scope and sole active allocation
for each transfer source leg are checked in common reads/backups. Reserved
`internal:` IDs cannot be authored as custom financial/category accounts. JSON
history decoding has finite bounds and controlled malformed-depth refusal.
The [settlement packet](work/2026-10-25-v2-settlements.md) and
[HSA/missing-receipt packet](work/2026-10-25-v2-hsa-cash.md) record development checks.

Account-total cash/card/register category movements admit explicit expense, expense refund,
income and income adjustment purposes with compatible exact source signs and
category classes. Initial review requires a purpose/category choice. Category/date
corrections retain purpose/class; a change of purpose uses withdrawal/fresh review.
Net spending, income and budgets may be negative; refunds/adjustments never change
the imported amount or date and never imply an owned transfer or card payment.

Register payment navigation is a presentation hint from a supported printed
payment description or explicit user choice, not a stored financial purpose.
Missing assignment/wrong scope/posted-state qualifications remain visible.
Already allocated rows outside this category workflow show Reviewed elsewhere
with history navigation and disabled categorization. Creating categories from
review refreshes basis/category data while preserving draft purpose/date/reason;
only a newly created compatible category is selected, without posting anything.

The finite `hsa_cash_line_pilot` activity family additionally admits these explicit
purposes and owned movements only for an asset with cash-component tracking.
Unknown source descriptions remain unknown; a separate code-owned accounting label
can identify a reviewed entry without claiming printed merchant/interest text.
Printed openings and reconciliation admit that same exact component rule. Other
HSA/retirement summary rows remain nonposting; existing account-total opening rules
remain available. Scope metadata survives correction, withdrawal and history.

The finite `pdf_yamahafin_202306` register has its own explicit review API and
`review:register` namespace, restricted to component-free account-total liability
rows. Shared ordinary category correction/withdrawal/repost/repeat-repair validates
that source shape; card APIs retain their separate finite family gate. Register
purpose is required. Corrections retain purpose/class and the source posting date;
they cannot override that date. Original transaction dates and posting dates,
including derivation from printed month/day/year context, remain separately
visible. These printed/derived posting dates require no assumed-date opt-in.

Schema 22 uses neutral `liability payment` event-kind semantics for owned
account-total liability receipts, including card and loan-register repayments.
The whole liability effect is allocated once and creates no second expense.
Principal/interest is unknown when the register does not print components; no
principal observation, component loan event or interest category is automatically
created. Explicit authored category choice retains the ordinary category policy.
Source opening/closing values remain account-total and separate from capture/
completeness. See the [register packet](work/2026-10-26-v2-liability-register.md).

Schema 21 retains bounded reviewed loan payments in `LoanEvents`,
`LoanEventActions`, `LoanSourceUses`, `DerivedFinancialObservations` and
`JournalDerivedAllocations`. An explicitly selected observed asset outflow must
exactly equal one printed Capital/MOHELA principal/interest payment or selected
Wells component rows from one source/loan account. Nonzero fees, incomplete/mixed
components, disbursements, capitalization and missing bank counterparts stay
pending. These are principal-component liability interpretations; Yamaha's
account-total register is a separate shape.

Raw loan source use consumes the complete signed raw row exactly once. A separate
canonical derived financial observation allocates only the normalized nonzero
principal effect. Ordinary raw `JournalAllocations` retain their original meaning.
Typed finite component proof supports evidenced interest expense, including an
interest-only expense/clearing entry with no financial observation or zero posting.
The pure ledger retains financial-only observations and normal allocation rules;
manual origin is never a component-proof bypass. All common reads/backups validate
exact manifests, retained raw evidence, component locations, original bindings,
entry shapes/digests and both source-use dimensions.

Original activity dates and absent parser posting guesses remain unchanged. Loan
accounting separately records an explicitly reviewed assumed activity-date cutoff,
gated by the global default-off preference for new postings. Subsequent preference
changes do not invalidate historical review. Actual bank and assumed loan dates
remain separate, with clearing between them. Whole withdrawal/replacement retains
all original dated inverses and captured context, releases active raw/derived uses
atomically, and preserves retry receipts without reviving retired money. Binding
and scope history include interest-only proof even without a loan financial line.
Ordinary single-entry correction/repeat repair refuses loan-event legs.
See the [loan-payment packet](work/2026-10-26-v2-loan-payments.md).

`StatementSourceReviews` is one append-only assertion history for bound statement
sections. Opening/closing origin, inclusive-period timing, posting-date certainty,
source reference and note are separate assertions. Known assumed card dates
cannot be asserted reported. Every assertion retains its original section identity
and form. Current applicability requires the exact account/source/section; an A
assertion cannot qualify B after reassignment. Historical scoped assertions remain
available independently. Forms load a coherent section/review/basis snapshot and
the write lock rechecks that original context, including an unreviewed initial form.
A stale form cannot overwrite another revision or qualify a newly assigned section.

An opening decision requires matching observed account-total openings (or the
finite HSA cash-component case above) across all
tied earliest sources and their latest reported-origin/timing reviews. Nonzero
openings post through internal opening equity at the prior-day cutoff; zero
saves a decision without a journal. A changed relevant earliest-source assertion
makes the decision stale without rewriting its entry. Later unrelated reviews
do not change that opening basis.

`OpeningDecisionRevisions` retains corrected source-backed decisions and prior
versions; reads select the latest. Corrections validate the selected decision
version and current reviewed earliest-source basis atomically. Changed amount/date
reverses the old opening at its own cutoff and posts the new evidenced amount at
its cutoff; zero has no replacement entry. Basis-only changes can retain the
journal. Persisted digests, exact balanced opening shapes and links are checked.

`JournalRetirements` links an immutable original to its exact dated inverse
without requiring a replacement. Shared inactive reads release retired evidence
consumption; raw sums retain cancellation math. Inverse payload/index allocations
must be empty. History enters overlap/reconciliation versions and workbook
Retirements links. Pending/stale source facts remain recoverable. This foundation
does not expose arbitrary manual-entry or journal-cancellation workflows.

`TransferEvents`, `TransferEventActions` and `TransferPairReviews` retain exact
confirmed pairs, entry manifests, whole-event withdrawal/replacement and scoped
suggestion dismissal/reopen history. Account-context changes do not silently
apply an old suggestion decision. Composite reads and optimistic write versions
preserve review context. All-leg retirement is atomic; new assumed-date postings
require opt-in even though existing events can be withdrawn after it is disabled.
Persisted types/checksums, exact source/entry/index shapes and cancellation links
are validated in common reads and backup. Workbook Transfer Reviews links retain
whole-event actions separately from active rows.

`SourceOverlapReviews` saves append-only distinct/repeat/pending decisions.
Supporting repeats are references, never additional money. New cash/card/transfer
postings check the full detected occurrence index inside their write transaction.
The [bounded occurrence-review contract](client-v2-source-overlap.md) defines
matching, multiplicity, binding locks, posted conflicts and display limits.
Existing retained-row corrections remain available. Repeat review does not
replace source-row allocation or certify reconciliation or coverage.

`SourceInterpretationActions` and `PostedRepeatRepairs` retain supported ordinary
withdrawals and atomic existing-repeat repairs. Exact dated inverses release
active consumption while preserving original allocations; fresh reposts have
new identities. Repaired repeats require validated history and zero active
allocation before later repeat review. Workbook Source Reviews and Repeat
Repairs preserve action history separately from active money.

`BindingCorrections` retains typed, digested prior/new section/file/row mappings
and exact affected review context. Explicit correction requires zero active
source consumption and no active source-backed opening or dated-value anchor. Historical journals stay
under their original accounts. Connected repeat relationships receive pending
revisions; affected transfer suggestion reviews become inapplicable even after
an account changes away and back. Ordinary binding APIs retain journal, repeat,
transfer-review, correction-history, opening and exact source-value section locks. Switching file/row modes
requires an explicit clear first. Common reads/backup validate history and latest
mapping consistency; all file/row bindings and corrections version reconciliation.
Active source-backed openings/values must be explicitly withdrawn before their
anchored assignment changes, including empty sections without transaction rows.

## Common reads and recovery

Schema-17 opening decisions/revisions retain source/manual origin, active or
withdrawn state, reference, scope and full-context versions including creation
time. Withdrawal has no replacement amount/date and makes the opening unknown;
a reviewed zero is an active zero decision. Exact old-date inverses retire money;
fresh establishment never revives old entries. Historical exact retries return
their saved receipt without changing a newer opening. Only current active
source-backed openings lock dependent source assignments. Manual openings use
typed owner reference/date/amount and opening equity, with no manufactured source
facts or arbitrary journal entry. Known account-history bounds prevent later
manual balancing plugs; newly arrived earlier facts make the manual anchor stale.

`AccountDatedValues` is immutable nonposting manual/source observation and correction
history; `DatedValueWithdrawals` appends retirement receipts without inventing zero.
Source proofs retain immutable parser facts, locations, definition/evidence hashes,
finite scope/sign rules and captured authored source-review context. Source review
accepts no arbitrary amount/date override. Manual correction remains manual.
Current differing points at the latest date are an explicit conflict with no chosen
value. Retaining a new conflicting point requires an explicit acknowledgement;
agreeing amounts are never summed. Superseded/withdrawn points leave current value
and opening-point bounds, while exact old retries cannot retire a fresh point.
Source proofs preserve their original account/review after retirement/reassignment.

`AccountLifecycleDecisions` is closure/reopen phase and correction history. These
histories enter common validation, reconciliation input versions and backup. Dated values
never fill an opening or overwrite journal positions. Positions show their scope,
origin and date separately. Applicable as-of closure metadata retains every
account and its recorded residual; missing/stale/withdrawn openings remain unknown
even if a manual final value is zero. Closing tracking posts no settlement.
Parser-observed/derived values and authored source-review qualifications remain
separate; later review changes are flagged without rewriting captured facts.
Capture, arithmetic and complete activity are independent qualifications for a
nonposting point. Values, proofs, exact locations and withdrawals export as metadata
separate from active journal money. See the [source-value packet](work/2026-10-25-v2-source-values.md).

Every journal payload must contain exact integer, nonzero, balanced posting
lines within supported integer bounds. Common reads additionally validate
ordinary initial/historical source and SQL allocation shapes, active bindings,
unique consumption and exact correction inverses. Current assumed-date settings
do not invalidate previously reviewed card dates. Malformed stored journals are
refused by reports, positions, reconciliation, consumption and backup.

Reports use common ledger reads with explicit scope, correction handling and
pending evidence. Reconciliation is a versioned read over one committed SQLite
snapshot; capture, arithmetic, allocations, interpretation, coverage and
freshness remain independent dimensions. A journal sum is not automatically a
current account balance. Inclusive as-of account positions/history use one read
snapshot and distinguish recorded postings from an opening-based journal position;
missing/stale/future/conflicting openings remain unknown. Per-account pending rows
cover all dates; unbound rows and transfer clearing are separately visible. Source
dates and live reconciliation cutoffs do not establish complete bank balances.

Reviewed-entry drill-down filters that common query by selected account and
explicit period, using one read snapshot for current amounts and related audit
records. Historical records provide provenance and never add to active totals.
Immutable saved source previews remain separate from interpretations. Shared
profile read failures clear every displayed report and disable inspection/export;
budget month and inclusive position date remain independently scoped controls.

Cash-movement reports use explicit financial asset IDs with no default selection,
and retain common journal rows, financial labels and validated transfer metadata
inside one read snapshot. Known categories/transfers/card payments classify actual
selected effects; other reviewed shapes remain unclassified. Counterpart dates
outside the selected period provide context only. Dated clearing effects, source
allocation limits and noncash card purchases remain distinct from cash receipts
and expenses. This adds no profile tables or postings.

`ReconciliationDecisions` is append-only saved successful-check history. Explicit
confirmation revalidates the expected live input version inside one write
transaction and retains the exact check, cutoff, rule, reason and immutable
journal payload digests. Failed or unreviewed checks and stale forms cannot save.
Identical account/source/rule/version saves reuse the original decision without
changing its reason. Saving history does not alter its own input version.
History reads retain old checks and report current/stale status conservatively
against profile-wide input versions. Positions distinguish latest saved cutoff,
currently valid saved cutoff and a newly computed live cutoff. Snapshot backup
validates this retained history independently of current reconciliation availability
before publishing a new copy. A saved snapshot digest detects accidental changes;
it does not authenticate a profile against hostile modification. Earlier disposable
pilot schemas must be recreated, without a migration or 1.x alias.

Reconciliation rule 6 retains balance/tracking scope explicitly, compares loan
principal using normalized printed components, and qualifies HSA success as
cash-component only. Rule 5 retains its exact captured scopes and becomes stale;
older saved rules 3/4 retain their original account-total defaults. Current-rule
missing/mismatched scope is refused. Unknown loan openings/period starts stay
unknown. Capture, unclassified source text and portfolio completeness stay separate.
Cash reports disclose active expected receipts even when only the expected
destination is selected: no observed destination activity means zero movement,
alongside a missing-receipt warning. Workbook event metadata retains expectations
separately from actual source legs and journal money.

Loan cash-purpose classification splits only the actual selected bank outflow into
principal and evidenced interest. It adds no expense posting; journal interest is
recognized on the lender's reviewed date. Workbook and entry drill-down distinguish
raw use, derived principal allocations and source component/location proof.
All-date loan history provides context only and never adds to period money.

SQLite profile snapshots contain embedded sources, authored data, journals and
all review history. They are verified before publication at a new path; restore
validates a new profile before switching. Failure leaves the current profile in
place. The separate signed catalog cache and global preferences are outside the
database snapshot. The profile and its backups are unencrypted local files.

Selected source originals can be recovered from the verified embedded bytes to
a new file, including without a catalog or the old selected import path. Recovery
does not reparse, post, move the original or change the profile. Publication is
atomic and refuses existing/racing destinations; failures remove the temporary
copy. Recovered documents are ordinary unencrypted local financial files.

## Historical design

<a id="collision-to-remove"></a>
<a id="implementation-order"></a>

The old table-name collision, implementation sequence and schema-revision
chronology are preserved in the
[archived contract](work/archive/2026-10-25-client-v2-unified-store.md).
