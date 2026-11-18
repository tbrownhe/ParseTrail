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
  amounts. Parser output and account binding alone do not authorize postings.
  The separately enabled standing loan-payment policy below is an explicit
  authorization for its bounded future-import case.
- The 1.x application, database and archive remain independent and untouched.
  The [cutover contract](client-v2-cutover.md) defines the fresh-profile boundary;
  the [ledger contract](client-ledger-contract.md) defines financial meaning.

## Profile format and lifecycle

The current pre-release profile schema is revision 27; check `SCHEMA_VERSION`
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

Financial accounts retain nullable managed `product_type` metadata independently
of asset/liability kind, institution and tracking scope. Products constrain class
and allowed scopes: a loan can represent the whole liability or only principal;
HSA/investment products can represent a whole account or a cash component. Unknown
existing product metadata remains unknown. New interactive creation requires a
supported product; it supplies the class and allowed scope instead of asking the
user to coordinate conflicting choices. Product names do not alter money signs,
source amounts, posting rules or historical entries.

Interactive PDF/CSV import reviews compatible existing accounts or provisional
new accounts for every complete source-account group before retaining the source.
Create a new account remains available even when headers fit existing accounts.
Only reliable source identity can supply automatic PDF matching under existing
preferences; generic CSV compatibility never selects account identity. Signed
format/product associations narrow the choices independently of source provenance.
An account-column distinction is asked early only when interpretations imply
different groups. Remaining material date/amount differences stay explicit in the
preview. A selected bank/product does not manufacture a parser match.

The final import plan binds source/catalog/declaration identity, complete group
mappings, new-account drafts and the current account/profile basis. One atomic
write creates referenced drafts, retains original/evidence and applies source,
whole-file or mixed-row assignments according to their actual group scope. It
creates no journals or openings. Cancel/failure rolls back all new state; exact
retry retains saved evidence and assignments. Interactive imports retain the
complete signed recognition result and canonical candidate evidence in a private
short-lived preparation session. Source/catalog are reread after review and just
before writing; detected drift or changed account state rebuilds account-first
review and requires another explicit confirmation. Explicit-format selection
refuses stale inputs. No source parsing/decoding follows either confirmation.
PDF signed routing and complete candidate proof are established during preparation
and bound to the exact source/catalog; a public summary cannot replace that proof.
Manual/headless source-only import and later guarded assignment remain separate
supported boundaries; the combined UI does not change immutable evidence policy.

Prepared sessions bind an opaque operation identifier, exact source/suffix,
catalog/declaration/engine/extractor context, physical profile and account basis.
Detached public review/selection/plan objects are compared with private authorized
snapshots, including after freshness callbacks; writes use the private choices.
Only canonical evidence reconstructed and checked against its complete retained
payload is saved. A session is consumed by one apply attempt and clears its
source/catalog/review/plan/evidence resources on every exit. Unselected Python
evidence graphs are discarded during recognition; retained JSON across candidates
has a 32 MiB aggregate bound. Overflow refuses the whole operation before preview.
No partial candidate set, new temporary evidence file or persistent cache is used.
Developer commit DTOs lacking session authority require independent recognition
and complete payload equality. Schema and ordinary saved-evidence reads remain
unchanged; this does not implement multiple extraction revisions per source.

Import previews default to Always. The global Only when attention is needed mode
skips display only for one recognized interpretation whose complete account groups
uniquely match existing accounts, without recovery notices or material monetary
warnings. It retains unreviewed evidence and creates no financial entries. The final
write rechecks live preferences, source, catalog and account state; changed inputs
return to review. Confirmed partial-identifier associations remain partial, require
the abbreviated-matching preference and cannot override a conflicting current match.
Unknown, new or ambiguous assignments require confirmation. Pre-import originals
are bounded, digest-checked, read-only in-memory views, separate from saved evidence.

Warnings have two classes. Estimated dates and generic unverified full-page capture
are Informational. Unverified statement monetary balances, actual balance mismatch,
unknown amounts and unexplained amount-bearing content Require review. Missing
verification is not presented as failed arithmetic; checks respect principal/cash/
account-total scope and exports do not manufacture missing statement checks. Full
codes and source locations remain discoverable. Posting-date permission is separate.
A uniquely confirmed account can skip account setup even when monetary content
requires the transaction preview. No source-defect repair override is introduced.

New PDF-import accounts retain an immutable source-linked institution/product lock,
created after account binding inside the atomic import. Values chosen during import
remain distinct from parser-established facts. Names remain editable. Read validation,
updates and backup enforce the same lock. An authenticated PDF section binding can
establish this origin even when the section has balances but no activity rows;
unrelated accounts and nonexistent sections cannot. Tangible assets cannot bind statement cash
activity or enter cash transfer candidates merely because their ledger class is asset.

`Institutions(id,name)` is a managed identity registry independent of installed
document formats. Fresh profiles seed canonical institution names/IDs; explicit
registration can retain additional managed identities from verified catalog
contexts. Account writes accept only a registered non-null institution ID, or
NULL for an unidentified institution. The registry and its references are checked
on open and retained in backup/restore; identifiers and registered names cannot
be overwritten. Institution selection does not establish parser support.
Different IDs cannot share a casefolded, whitespace-normalized display name;
unknown/required UI labels are reserved and cannot become matching identities.
Catalog admission and profile preflight enforce these distinctions before names
reach a selector. Catalog-aware account add/update retain registry entries and
account changes atomically, including failure and caller-owned rollback.

Unknown institution is an absence, not a shared placeholder bank. Explicit
source/file/row assignment, reviewed posting and correction remain available.
Unknown institutions never authorize automatic account-number matching or
cross-document batch seeding. Manual association with a known account does not
rewrite unidentified source provenance. The account ID remains the journal's
identity; institution metadata does not calculate spending or move postings.
The shared source-account-context policy distinguishes signed format association
from source identification. Generic CSV bank/class labels never become verified
source identity through uniqueness or user format choice. Only reviewed
institution-identifying CSV families (currently MOHELA component exports with
their admitted declaration/evidence shape) and exact verified PDF context can
supply that inference. Preview, account creation, matching and batch proposals
use the same policy; generic context can still populate managed-name choices.

Catalog activation and profile registry retention have separate outcomes.
Predictable registry identity conflicts refuse before activation. If retention
later fails, report that formats were installed and institution names could not
be retained; do not claim activation failed or silently roll the catalog back.
Account creation/batch apply recheck and explicitly register current catalog
identities within their own writes. Merely populating a selector never writes.

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

Ordinary cash/card/register review reads one committed snapshot on a worker-owned
connection. All retained sources and observation inventories are still verified;
the selected evidence model and small verified period/guard facts are reused only
within that transaction. Cache validity includes the transaction and connection
change count. It does not create a process-wide source cache or waive corrupt
unselected-source refusal. Closing or superseding a read discards its presentation
result; confirmed writes remain owned until their real outcome is delivered.

An ordinary category batch belongs to one explicitly selected document and kind.
Its immutable preview records each row, purpose/category, independent accounting
date, exact journal entry, explicit shared reason, current review basis and
profile identity. Previewing does not post entries or create categories. Final
posting rebuilds and compares every entry inside one immediate transaction,
rechecks source/account/overlap/active-use guards and commits all rows together.
An exact committed retry returns the existing keys; stale, altered, corrected or
withdrawn previews refuse without partial posting. Ordinary corrections and
whole-event loan/transfer/settlement corrections retain their existing workflows.

The ordinary review UI accepts Ctrl/Shift multi-selection for a common purpose,
category and note. Staging prevalidates every selected row before changing any
in-memory staged choice, enforcing the existing 2,000-row union limit. A refused
proposal preserves earlier stages and their captured shared reason. Each card
row retains its own accounting date; an unstaged date override must first be
staged individually. Missing or noncanonical individual dates cannot silently
fall back to a source candidate. Bulk correction/withdrawal is not offered.
Selection changes retain independent row proposals and the common proposal;
retained edits participate in the document/profile/close discard guard. Account
or category refresh preserves those proposals while obtaining a fresh review
basis. Header assignment status and the review snapshot must agree.

Saved ordinary-review notes are read-only interpretation context, distinct from
the editable reason for a new correction or withdrawal. Selecting a saved row
does not itself create a draft. New reasons belong to the selected row and active
entry key; a replaced entry cannot inherit an older draft. Same-entry refresh and
canceled confirmation retain authored changes, while a successful write refreshes
the saved context and clears the editable reason. Existing basis/transaction
guards, inverse/replacement history and immutable source evidence are unchanged.

Append-only pending-transfer revisions retain the headless no-money designation
boundary. Transfer/card-repayment
designation is an authored interpretation, with no journal, allocation, clearing
or inferred counterpart. It survives restart, preserves its source/account context
and reason, and may wait for another statement. Current state is derived against
verified source facts, active uses and revisions; changed context becomes stale.
Corrections and withdrawal require an explicitly entered reason and revision check.
Reclassification to an ordinary category atomically withdraws the current designation
and posts the independently validated category entry.

Current ordinary review stages category postings, posted unresolved transfer sides
and zero-amount nonposting reviews in one immutable batch. A transfer financial
posting uses its qualified source accounting date and the existing date permission.
The captured exact effects, zero-review revisions and source uses commit together
or all roll back. Exact retries cannot overwrite a later correction. Legacy
no-money designations remain separate from the current financial Type selection.

An ordinary review set may therefore contain different posting/nonposting effects.
Its immutable preview and final write validate the exact selections and pending
revisions together in one transaction. Confirmation separates both effects. Initial
shared reasons default to `Initial Review`; edits persist with the review set.
Saved decisions have separate blank correction/withdrawal fields. The default alone
does not count as an unsaved draft or authorize a correction.
When the complete selected proposals and captured reason already match the staged
set, Stage is disabled; new or changed choices re-enable it. Zero rows can retain
purpose/category/reason and correction/withdrawal history without zero journals,
allocations or budget movement. Their review state clears ordinary pending counts.

Background profile jobs retain worker connections until completion, coalesce
superseded reads and serialize their confirmed writes per resolved profile.
Services remain authoritative for transaction ownership and stale validation.
Independent restore jobs validate the selected backup without first opening the
damaged current profile. Backup/restore/export/recovered-original publication
keeps its existing verification and destination-preservation rules; closing waits
for a confirmed publication's actual outcome instead of claiming cancellation.
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
unsaved form edits. Unknown institution setup uses a searchable managed-name
selector and deliberate Institution not identified choice, rather than free-text
codes. The UI offers built-in, retained and current verified-catalog identities;
it has no institution editor in this slice. Exact signed identification remains
read-only context.
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

Ordinary-review match proposals require current explicit transfer designations
on both legs. The designation mode is captured in planning/confirmation identity
and revalidated at write time. Both-leg designation makes a row eligible, never
confirms ownership or a match. The separate manual transfer workflow retains its
explicit source selection without this prerequisite. Retiring a confirmed event
does not revive old designations as current decisions.

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
remain available. The finite Fidelity 401(k), Vanguard and Fidelity HSA summary
families have a dedicated statement
value Review rather than cash categorization. Its printed beginning value, component
totals and ending value remain statement-period facts. Explicit confirmation records
the exact source closing through the existing dated-value service, without creating
journals, contribution counterparts, categories, transfers or budget effects.
Scope metadata survives correction, withdrawal and history.

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
`JournalDerivedAllocations`. A complete printed Capital/MOHELA payment or selected
Wells component rows from one source/loan account may post its lender side without
a bank leg: principal reduces debt, printed interest is expense and gross offsets
transfer clearing. If a bank outflow is selected it must match the complete gross.
Nonzero fees, incomplete/mixed components, disbursements and capitalization stay
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

Supported loan documents open a source-focused component view rather than ordinary
cash categorization. It displays source total, principal and interest, component
proof and prerequisites, and hands the selected source/row to whole-payment review
without selecting a counterpart. A fresh focused review selects the sole eligible
payment; ambiguous/multiple components retain manual selection. Saved events
remain whole-event history/correction actions with neutral inspection buttons;
blue actions indicate pending review. Completed document review says Review complete.
Observed activity dates, separately
assumed accounting dates, principal-only scope and unknown openings stay explicit.

The global **Automatically post supported loan payments** preference defaults off.
Enabling it explicitly authorizes lender-only posting for eligible future imports;
it never sweeps existing evidence, changes an existing posting or revives a withdrawn
event. The initial admitted shape is one audited Capital loan-history engine v2
payment bound to a compatible loan-principal account that existed before import.
Complete printed principal/interest/gross arithmetic, no material import warning,
permitted accounting date and no overlap, prior use or payment history are required.
The existing narrow missing-opening informational exception remains applicable;
unknown opening and unverified reconciliation remain unchanged. Origination,
unsupported/multiple/incomplete rows and defects remain in manual Review.

Standing authorization and assumed-date permission are separate choices. Import
start captures consent/profile context, and posting revalidates current consent,
profile identity, cancellation and source/account/history state transactionally.
Automatic outcomes identify posted principal and interest, the unresolved paying
account and retained automatic authorization reason/reference. A subsequent posting
failure leaves the successfully imported evidence saved and reports manual review.
Exact source retries never post again. Automatic posting uses the same lender
entries, raw/derived evidence and whole-event correction/history as manual posting;
it never selects a paying-account transaction or claims a human inspected the source.

## Separate transfer resolution and loan funding

The profile retains immutable `UnresolvedTransferLegs`/actions and explicit
`TransferResolutionLinks`/actions. Review posts an evidenced generic source side or
lender-only loan event; Transfers is the profile-wide relationship workflow.
Two posted sides link without journals. A deliberately selected unposted counterpart
creates only its missing side against clearing, retaining existing lender principal
and interest. Automatic proposals require explicit transfer/loan designation; raw
sources are separately labelled manual alternatives with ownership confirmation.
Every amount/date/source/basis is rebuilt at commit. Exact missing-leg retries,
withdrawn-link refusal and wider-window replay retain their original identities.

Each unresolved side stays individually visible even when aggregate clearing is
zero. Reports count sides using their actual posting dates and current matching
state; this does not infer historical match dates. Multi-date component bundles
retain all qualified dates, require all dates inside a matching window and count
once if any actual leg satisfies the report's complete period bounds. Link withdrawal
retains the posted sides; posted-side withdrawal requires unlinking first and retains
exact inverses. Whole lender-payment correction remains with its owning loan history.

`LoanOriginationEvents`/actions/source uses admit the finite Capital Amount Financed
shape separately from repayment. The positive observed principal, absent interest,
source activity date and locations remain intact. Financing posts the exact principal
increase against transfer clearing using the explicitly permitted assumed accounting
date. Destination may remain unknown, or a selected eligible financial account may
constrain later receipt matching without receiving an invented posting. Transfers
shows this borrowing as outgoing funding, retaining its source proof and qualification.
Either sign of liability movement is eligible for separate resolution, including
card-to-card transfers and liability-to-asset funding; legacy settlement rules remain
separate. Fees are never inferred from unmatched amounts.

Selecting a tangible asset requires explicit confirmation that this financing funded
the asset and a separately authored allocation date. Only the exact financed portion
is allocated to the asset against clearing. Full acquisition cost remains unknown;
estimated value never supplies a downpayment, bank movement or balancing entry.
The separate finite full-acquisition API still admits an exact independently authored
cost and evidenced bank downpayment, with each own date, when that complete shape is
available. Physical profile identity and exact proof bind previews before retry.
Withdrawal preserves inverses/source history; matched funding must first be unlinked.
Other origination source shapes, including unestablished Wells formats, remain unsupported.

The managed `tangible_asset` product describes vehicles, precious metals, property,
jewelry or equipment through an authored nickname. Creation requires no valuation.
Classification is fixed by valuation/funding history. `TangibleAssetValues` records
separately authored dated estimates and optional signed annual value change in integer
basis points (-10000 through +100000). Negative rates decline and positive rates
appreciate. Decimal projection uses 365.2425 days per year and cent rounding; it posts
no journals or budget expense. A missing rate leaves a later estimate unknown;
explicit zero permits a flat estimate. Entered values remain available on their own
dates. Origination-created estimates default to the source activity date, separately
editable; standalone estimates default to today. Values do not establish acquisition
cost or previously unknown book openings. Fresh schema27 profiles include the protected
Loan interest category through explicit initialization, without writes on read.

The sidebar order is Documents, Accounts, Review, Transfers, Budget, Reports. Loan
posting never forces matching. Explicit Transfers handoff closes the payment modal,
focuses its row and preserves return context. Saved match inspection names both sides,
dates, note and evidence; confirmation identifies exact existing and new effects.
Current report/workbook views retain monetary qualifications and full-profile decision
history separately from the selected journal period. No owner/release acceptance is
established by the development implementation.

Successful initial review posting may advance to the next incomplete statement only
after fresh saved summaries show the current document complete. Posted unmatched sides
belong to Transfers. Generic refreshes, failures, cancellations, corrections and
report/Transfers source-return contexts do not advance. A completion notice and route
back preserve context; drafts and outstanding operations prevent navigation.

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

Supported statement-value completion is distinct from activity allocation. Documents
track pending and reviewed statement-value sections separately; zero pending activity
does not mean a summary value has been reviewed. Completion requires an active exact
source-backed closing under the current account/section binding. Equal manual or
other-source values do not complete that source; withdrawal, relevant correction or
conflict reopens/qualifies its review. The embedded Review shows the recorded value
and neutral history access. Unknown openings, absent individual transaction dates,
unverified capture and source-check qualifications remain explicit. The separate
Accounts value-management workflow retains correction, conflict and withdrawal
history; a generic refresh never silently records or restores a value. Summary
history/conflict handoffs retain the statement-end as-of date and focused existing
value, even when later points exist. View account value opens Reports at that
account/date and shows the latest reviewed dated value beside the separate journal
position; spending dates and budget month are preserved. Required reference/reason
fields are initially populated, with explicit missing-field cues if edited blank.

The separate **Automatically record supported statement values** global preference
defaults off. It explicitly authorizes nonposting closing-value recording after
eligible future imports from the finite Fidelity 401(k), Vanguard and Fidelity HSA
account-total summary families. The HSA cash-activity family remains separate. One
bound compatible section, exact supported closing/date, no material import warning,
conflict or prior value history for that source are required. Account creation may
qualify after its import assignment is explicitly confirmed. Agreeing manual or
other-source points do not replace the new source proof and are never summed.

Import start captures consent and physical profile context. The existing source-value
transaction rechecks current consent, cancellation, current source/section/history
and exact candidate/basis/profile before recording and commit, including before any
historical retry branch. Automatic history states automatic authorization. Saved
source retries, withdrawn/corrected history and ordinary refreshes never trigger
recording or revival. Enabling the setting leaves the current Review draft unchanged.
Import and subsequent automation have distinct outcomes: a refusal or rolled-back
recording retains the imported evidence and explains its manual-review requirement;
cancelled batches keep completed imports and stop remaining files. This creates no
journal, transfer, opening, income, spending or budget effect and does not use the
assumed-posting-date opt-in. Loan automation remains a separate choice.

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
