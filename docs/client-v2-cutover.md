# Client 2.0 fresh-profile cutover contract

This document owns the fresh-profile, runtime and release-boundary contract.
[ROADMAP.md](../ROADMAP.md) is the sole ordered plan and release-gate list;
[TODO.md](../TODO.md) identifies selected work. Dated implementation and
verification belong in [work records](work/README.md). Earlier planning and
native acceptance narratives remain in the [archived cutover plan](work/archive/2026-10-25-client-v2-cutover.md).

## Development review update — October 25, 2026

The owner approved autonomous design and first functional V2 UI implementation
within selected scope, completed with meaningful automated checks and agent
review. Follow [the current review policy](../AGENTS.md#v2-development-and-human-review).
Human UI/UX review is consolidated at V2-UX; new features and substantial UI
changes do not require individual owner acceptance. Keep historical owner
acceptance intact and identify specifically missing platform/release checks.

## Release boundary

Client 2.0 uses a double-entry ledger and one new authoritative 2.x SQLite
profile. It does not open a 1.x database for writable initialization, migrate it,
import its authored transaction/category decisions, or add aliases for old IDs.
The owner re-enters accounts, categories, budgets, manual values and review.
Original documents chosen for 2.0 become new evidence and require new review.
There is no requirement to re-import all historical documents before first use.

The existing 1.4.2 application, database, archive, exports and recovery material
remain independent and unchanged. They are the historical reference and fallback.
Work in either profile is not synchronized or backported. A return to 1.4.2
opens only its retained 1.x profile; it never reads a 2.x database.

Unknown, damaged, newer and earlier disposable pilot formats are refused before
writable schema initialization. Pre-release approved schema changes recreate
pilots; released 2.x evolution follows its migration contract. The
[single-store contract](client-v2-unified-store.md) defines lifecycle and storage.
Keep the application version unchanged during pilots. A version bump, production
signing, live-profile activation, installation/release, deployment or publication
requires its specifically selected release scope and acceptance.

Explicit `--v2` source launch can offer New/Open/Restore without mandatory profile
or cache CLI paths. Existing explicit paths and deliberate `--create-profile`
automation remain available. A chooser never activates the last profile by
default; cancellation writes nothing. Separate preferences/catalog configuration
is checked before creating/restoring, invalid selections preserve the current
workspace, and a failed staged refresh restores its prior selection. This does
not change ordinary 1.x startup or authorize daily-profile activation/release.

## Evidence and accounting rules

- Retain original source bytes/digest, exact parser definition/revision, engine
  and extractor versions, raw fields, exact money, typed dates and locations.
  Parser output and account matching are evidence, not authorized journal entries.
- Distinguish statement periods from export activity spans, and observed,
  derived, assumed and unknown values. Calculations never replace printed
  endpoints; missing history is not zero activity.
- Post only reviewed supported interpretations, with exact balanced entries and
  unique active evidence consumption. Expense/refund, income, transfer/card
  payment, loan components and openings have distinct rules. No balancing plugs.
- Retain immutable imports, append-only correction/review history and durable
  decisions across catalog updates. Exact-source retries reuse snapshots;
  reparse produces a comparison rather than overwriting reviewed history.
- Preserve revised/overlapping sources for explicit evidence review. Follow the
  [bounded occurrence-review contract](client-v2-source-overlap.md). Supported
  existing double postings have an explicit atomic repair workflow; neither
  candidate detection nor repair claims complete deduplication.
- Reports/exports share ledger scope rules and show pending/uncovered work.
  Internal transfers and card repayments do not create a second expense.
- Keep source capture, independent arithmetic, allocations, interpretations,
  reconciliation, calendar coverage and freshness visible as separate dimensions.
  Unverified capture is an evidence limit, not a blanket balance-check blocker.

The [ledger contract](client-ledger-contract.md) defines accounting meaning.
Unsupported interpretations remain visible and unposted; unexplained history
must not become invented income, spending, interest or equity.

## Parser and decoder direction

V2 uses a shipped finite engine with signed versioned JSON definitions and fixed,
client-owned bounded decoder workers. All current parser families, including
recent Citi, remain in first-release scope. CSV/PDF imports use the authenticated
pipeline; XLSX decoding remains an isolated synthetic-tested capability, not an
admitted workspace format. The [parser contract](client-v2-parsing.md) and
[family inventory](client-v2-parser-inventory.md) own these details.

Native worker limits, packaged pipes, source parity, full-page capture and
installed/offline trust are separate claims. Record only platforms actually
checked. Keep client work on the active client branch; a service interface needs
the documented reviewed design and separate-branch handoff. The owner's October
25 DEC-2 permits local signed-catalog installation for the first release and
defers its service to separate later work.

## Implementation chunks

The authoritative milestones and dependencies are in [ROADMAP.md](../ROADMAP.md#initial-20-milestones).
This heading preserves earlier links; it does not maintain a second work queue.
The [archived plan](work/archive/2026-10-25-client-v2-cutover.md#implementation-chunks)
retains the earlier implementation and owner-acceptance history.

## Cross-source occurrence safeguard — October 25, 2026

Current matching, review and posting rules are in the
[occurrence-review contract](client-v2-source-overlap.md). Its completed packet
and dated verification are in the [work record](work/2026-10-25-v2-source-overlap.md).
Other implemented workflow details belong in their component contracts and code;
records distinguish automated/agent verification from actual owner acceptance.

## Current stop/go decision

Development within selected V2/P2 scope may continue under the repository review
policy. The application is not release-ready. Use the roadmap's
[release checklist](../ROADMAP.md#release-checklist) for current unmet gates,
including the resolved scope dispositions, consolidated UX, supported-platform,
production-catalog and installed/offline acceptance. Historical pilot success
never authorizes daily-profile activation or public release.

Forecasting, new ML insights and complete historical loan reconstruction are
later work. The owner's October 25 legacy-action deferrals remain visible in the
[action inventory](client-v2-menu-inventory.md); they are important future
capabilities, not permanently retired features.

<a id="client-20-clean-profile-cutover-plan"></a>
Earlier heading links are retained for the historical snapshot linked above.
