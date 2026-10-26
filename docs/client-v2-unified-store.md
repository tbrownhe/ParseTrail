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

The current pre-release profile schema is revision 15; check `SCHEMA_VERSION`
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

Financial display/identity edits retain the account ID and ledger class.
Account assignments with journal history cannot be changed. Any saved occurrence
review also fixes the affected rows' account bindings, even after returning its
pair to pending; history must not silently reactivate under a changed account.

`CategoryBudgetRates` stores at most one target per category and effective month.
The latest rate at or before the report month applies until another rate is
saved. An empty target clears later months without changing earlier targets;
zero is a valid target. These planning values do not post money or infer
categories. Category display-name edits retain historical account references.

## Journal and review history

Supported reviewed cash/card/transfer workflows atomically validate and save
balanced journal entries and signed source allocations. Cash-category and
card-category/date corrections save inverse reversals, replacements and their
links together; original entries and allocations remain history, and only active
allocations consume evidence. Source-backed opening corrections append revisions
and exact retirement inverses, including zero decisions without replacements.
Whole-transfer withdrawal/replacement preserves every original leg and creates
fresh replacement identities. Unsupported interpretations and unknown posting dates remain
pending.

`StatementSourceReviews` is one append-only assertion history for bound statement
sections. Opening/closing origin, inclusive-period timing, posting-date certainty,
source reference and note are separate assertions. Known assumed card dates
cannot be asserted reported. A stale form cannot overwrite another revision.

An opening decision requires matching observed account-total openings across all
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

## Common reads and recovery

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
