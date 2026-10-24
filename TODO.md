# ParseTrail engineering TODO

Unfinished work only. `[ ]` is pending, `[~]` is in progress, and `[USER]` needs
owner GUI/platform testing or a product decision. Remove an item only after its
acceptance checks pass; preserve lasting behavior and evidence in the
[component guides and acceptance record](docs/engineering-acceptance.md).

Work Windows x64 and Intel macOS first. Apple Silicon native support remains
deferred; a bounded experimental GitHub CI/build feasibility check is welcome
without making it a Windows/Intel release gate. The [client review](docs/client-development-review.md)
contains findings and detailed acceptance criteria for the chunk IDs below.

The owner has approved the client roadmap below on September 26, 2026, following
P1.5, P1.6, and P2.2 acceptance. Unselected proposals remain suggestions, not
blanket implementation approval. Windows and Intel installed offline/P2.2 walkthroughs are
accepted. The owner also accepted the existing feature set after the Windows
private-copy retests and closed this development effort; see the
[closeout record](docs/engineering-acceptance.md#client-development-closeout-september-21-2026).
Client 1.4.2 is published for Windows x64 and Intel macOS; the
[production acceptance record](docs/engineering-acceptance.md#client-142-production-release-september-26-2026)
preserves release, recovery, and verification evidence.

The completed Mac results are in the [Intel return note](docs/intel-mac-return-note.md).
The [signed Windows candidate record](docs/engineering-acceptance.md#signed-windows-candidate-september-19-2026)
identifies the preserved installer used for Windows native acceptance.

## Active client roadmap — local spending and cash planning

Start from `main`, checkpoint `stable-1.4.2` (`effced9`), on the long-running
`feature/client-financial-insights` branch. Keep changes in small, tested,
reviewable commits on this branch. Stop when a product decision is ambiguous or
owner native GUI/platform acceptance is needed; prepare isolated profiles,
candidate code/artifacts, and concrete walkthroughs before that handoff.

This branch contains client features and their supporting tests/documentation.
Server P0 stays closed. If a client feature requires a server interface change,
stop at that boundary, merge the accepted client work first, and use a separate
short-lived server branch. The owner's locally hosted server is not part of
routine client development or automated tests.

### Agreed product behavior

- All financial analysis and ML stay local. Prioritize understanding spending,
  cash flow, and upcoming obligations ahead of categorization automation.
- Fixed built-in categories coexist with user-defined categories. Built-ins have
  stable semantic identities and fixed account types; workflows enforce the relevant
  built-in when the evidence establishes the expense type. Start with Loan interest.
  Preserve definitions and reviewed history created in 2.x; matching names do not imply
  matching accounting semantics. Add further built-ins as their workflows are scoped.
- Present spending separately from account cash movement. A card purchase counts
  as spending once; its repayment transfers money to the card account and still
  reduces available checking cash on its payment date. Exclude internal transfers
  from consolidated income/spending; show savings/investment contributions
  separately. Show loan obligations, separating principal/interest when supported
  by the data. Preserve unresolved classifications instead of guessing.
- Compare the latest fully covered comparable periods across selected accounts;
  default to month versus preceding month, with year-over-year when available.
  Explain category/merchant contributions and retain transaction drill-down and
  uncategorized amounts in reconciled totals.
- Start recurring detection with fixed and variable monthly bills. Display
  evidence-backed suggestions immediately; allow confirmation, correction, and
  dismissal. Only confirmed schedules feed the first cash-balance forecast.
- Reuse Statements > Completeness Grid's per-account intervals. Distinguish
  historical coverage from freshness: the owner's history is generally complete
  through August 2026 but imports happen in batches with a one-to-two-month lag.
  Never interpret unimported periods as zero spending or a stopped/missed bill.
- Forecast per funding account, showing its lowest projected balance and date,
  as well as recorded versus estimated values. Start upcoming obligations with
  a visible 30-day horizon. An available-to-spend scenario must disclose its
  horizon, reserved obligations, chosen cash buffer, and stale/missing inputs;
  stale records cannot support an unqualified current disposable-cash figure.
- Before offering available-to-spend estimates, capture confirmed card autopay
  account, due date, and payment basis (statement balance/minimum/fixed amount).
  A payment is not necessarily the card's current total balance. Later allow
  dated checking/card balance observations without rewriting transaction history;
  these refresh the forecast starting point but do not fill missing spending.
- The next major client targets 2.0 with a fresh local profile. The owner will
  re-enter accounts, categories, budgets, manual values and verification; there
  is no 1.x database updater or compatibility layer. Keep the 1.x profile
  independent and unchanged by development. Keep the version unchanged during
  development; resume versioned migrations only within released 2.x. Preserve
  exact money and evidence imported into 2.x, and keep derived insights reproducible.
- On September 27, the owner approved a genuine double-entry ledger as the
  authoritative financial model before new cash-flow totals. Preserve imported
  evidence separately from journal entries and postings. Categories are migration
  evidence, not proof of a transfer; distinguish interpretation review, balanced
  posting, statement reconciliation, and coverage/freshness. Keep predictions and
  ML suggestions separate from posted facts. The owner authorized testing against
  a disposable snapshot of the live database; private paths/data/reports stay out
  of Git. See the [ledger contract](docs/client-ledger-contract.md).
- The October 13 clean-start decision supersedes the earlier archive-rebuild
  acceptance requirement. Existing verified categories and other 1.x authored
  state need not be imported into 2.x. Keep the old database/archive available
  in 1.4.2; selected original documents can be imported and reviewed afresh
  in 2.x. See the [current cutover plan](docs/client-v2-cutover.md).

### 2.0 cutover plan

The owner chose a clean new 2.0 profile on October 13. The
[2.0 cutover plan](docs/client-v2-cutover.md) defines launch behavior,
blocking failures and the independent 1.x fallback.
The existing L/CF items below provide implementation history and remaining service
work; V2 organizes their integration into the everyday application.
The owner also included [engine simplification and declarative parsers](docs/client-v2-parsing.md)
in 2.0. Target a built-in engine plus signed versioned JSON definitions, with rare
explicit client-built extraction handlers instead of downloaded Python bytecode.

- [x] **V2-1 — Fresh-profile boundary:** the completed
  [1.x preservation inventory](docs/client-v2-preservation-inventory.md) remains
  read-only development evidence. The 2.x contract uses a clean profile with no 1.x
  database migration, aliases or automatic authored-state carry-forward. Keep
  the old application/profile independent; no live writes or schema changes.
- [x] **P2-1 — Parser/engine review:** all 22 shipped parser families are in
  [the parser inventory](docs/client-v2-parser-inventory.md). Read-only archive replay
  and installed-catalog checks passed; historical parser revisions were bound
  source by source, including an ambiguous Citi layout split. Four representative
  PDF operation costs and the remaining 18 family costs are reviewed. The owner
  requires every current family in the first 2.0 release. Per-family fixture
  parity and native acceptance remain P2-3/P2-4 work.
  An October 24 read-only replay through a locally test-signed catalog parsed
  all 956 PDFs (20 represented PDF families, 20,095 evidence rows) and one
  MOHELA CSV (29 rows) in the successful archive without routing/extraction
  failure; Synchrony has a separate ten-source fixture. This is execution
  coverage, not full-page capture, legacy parity or accounting acceptance.
  The same 957 distinct sources also imported through the verified-catalog
  service into one disposable 2.0 profile, with zero failures; the complete
  profile reopened read-only with 957 saved sources before removal. Ledger
  posting and production-signed trust remain separate gates.
  Inventory all current parsers, archive layouts,
  repeated extraction/normalization/checks, source provenance, developer tools and
  release coupling. Produce a family/fixture matrix and explicit custom-operation needs.
- [x] **P2-2 — Declaration/evidence design and prototype:** strict, finite
  table/card/HSA/Wells/Citi pilot definitions and a shared immutable V2 source
  evidence envelope cover exact values, nullable/provenanced endpoints, source
  locations and multiple accounts. The table declaration refuses unknown schema,
  capabilities and executable fields. This is a pilot contract, not final signed
  catalog admission or a released storage schema.
- [~] **P2-3 — Parser and decoder pilots:** a bounded synthetic table prototype is
  in [the parser engine pilot](devtools/parser_engine_pilot/README.md). The first
  read-only detailed CSV comparison matched the accepted reader; a separate
  PDF line pilot retained page/line locations on Chase and cross-page HSA
  fixtures, and a finite Chase statement pilot matched the authorized archive
  while retaining uninterpreted dated detail lines. A finite HealthEquity cash
  pilot now matches the authorized archive's printed cash fields and running
  balances across continuation pages, with descriptionless and non-dated lines
  explicitly unresolved. A read-only XLSX adapter passes synthetic workbook
  checks with ZIP/sheet limits. Its new resource-limited worker matches the
  synthetic evidence and refuses formulas. The shared table engine, XLSX
  adapter and worker now live in the client package; a windowed Windows x64
  probe passed its synthetic worker pipe and parent boundary. No referenced
  archive fixture or Intel Mac native limit check exists. A read-only Wells
  Fargo business table pass supports a finite page-local geometry pilot; its
  raw cells and dated candidate count match all referenced archive sources but
  do not establish capture. A bounded worker now reproduces the in-process
  cells/regions on 21
  archive PDFs (1,029 rows), but Intel Mac native limits and runtime integration
  remain open. The shared PDF line and continuation operations, anchored table
  engine, Wells table engine and their workers now live in the client package.
  A windowed Windows x64 probe passed both table worker pipes and parent
  resource boundaries on synthetic evidence.
  A finite Wells business statement operation now joins declared description
  continuations and exact printed summary fields. All 29 business PDFs in the
  authorized closed-copy profile matched the accepted reader on account,
  period, balances and all 225 rows. Temporary V2 storage reopened those rows
  and 1,073 table terminator/after-stop dispositions without source changes.
  Full-page capture, after-stop review and native acceptance remain open.
  Citi multi-channel recovery has conflicting date/amount-only matches. A
  read-only page-level follow-up classified the eight referenced sources'
  candidate shapes. A finite channel resolver reproduces all 421 accepted
  date/amount row occurrences and printed balance equations, while refusing
  unexplained overlaps. The simple text matcher also leaves 71 dated source
  lines for explicit disposition, including foreign multiline activity.
  Shared continuation and exact channel-occurrence matching now have finite
  pilot operations. The refactored Citi audit passed on nine recent-layout
  archive files with 428 resolved occurrences and unchanged source hashes.
  A dated-start ledger now accounts for all 67 extra starts in the nine-file
  sample as 66 table copies and one fee. Including the first recent-layout
  statement, ten archive PDFs have 486 dated starts linked one to one to 486
  resolved rows, 72 table copies, one fee, zero unresolved starts and ten
  passing printed balance equations. It records three first-character losses
  in table descriptions. Full-page capture and runtime integration remain open.
  A separate simple-text PDF worker now has byte/page/line/output, deadline and
  OS memory limits. Windows native memory and timeout tests pass; its text
  exactly matches nine recent-layout Citi archive PDFs without source changes.
  The three PDF text layouts, first-page date annotation decoder and shared
  worker limit runner now live in the installed client package. The app has an
  early frozen worker entry before profile and GUI bootstrap. A windowed
  Windows x64 probe ran both worker pipes, a positive annotation decode and
  native timeout. All fixed decoder workers now live in the client package;
  windowed Windows x64 probes passed text, annotation, XLSX, anchored table,
  Wells table and Citi table pipes. The build scripts gate those worker pipes.
  Intel Mac limits and ordinary runtime integration remain open.
  Wells and Citi word/table finding and XLSX XML decoding now run in bounded
  workers. The Citi worker matched 543 raw table/interest rows across ten
  recent-layout archive PDFs without changing source hashes. The shared
  continuation operation forms 471 table transactions and retains 36
  supplemental detail lines separately, with accepted-row order parity.
  Bounded evidence now also reproduces layout classification, statement
  dates, account suffix and printed balances on those ten sources.
  A standalone recent-Citi evidence path now runs without the old reader; the
  comparison audit still matches all ten statements and source hashes.
  A monetary-line ledger accounts for 183 first-page and 98 later-page
  dollar-sign lines outside dated transactions; zero remain unresolved.
  Five garbled first-page summary lines and ten garbled later-page cardholder
  subtotals are retained as extraction artifacts, never as transaction or
  balance evidence.
  A deterministic partial-date operation now refuses invalid, distant and
  ambiguous `MM/DD` years while retaining ten-statement Citi parity. The
  [upstream boundary review](docs/client-v2-upstream-boundary-review.md) orders
  typed evidence, Citi's exit from 1.x parser methods and bounded admission
  ahead of the approved 2.0 storage implementation.
  A strict shared source-evidence model now represents statement and activity
  export payloads, typed locations, raw values and unknown/derived provenance.
  A synthetic CSV and ten recent Citi statements round-trip through it. The
  Citi path now uses a finite pilot definition without importing 1.x parser
  methods; 486 rows and 803 located dispositions are retained, including 36
  supplemental details. The bounded source pipeline and fresh 2.0
  SQLite source store now save exact source, definition and strict evidence in
  one transaction; ten Citi PDFs reopened in a temporary profile with unchanged
  source hashes. Full capture and native admission remain open.
  The finite Chase line pilot now maps into the shared V2 evidence envelope;
  the exact checked-in definition passed the bounded path on five archive PDFs
  (139 rows, 99 dated auxiliary dispositions) with unchanged hashes. Capture,
  signed routing and Intel Mac worker acceptance remain open.
  The finite Happen savings line operation now matches both referenced archive
  statements on printed endpoints and all eight rows, including running
  balances. Bounded strict evidence reopened in a temporary profile with 11
  located dispositions and unchanged source hashes. Full-page capture remains
  open for this family too.
  The shared savings engine's older LendingClub operation now matches all five
  referenced archive statements, including 24 inherited-date/running-balance
  rows and the independently printed summary equation. Their strict evidence
  reopened from a temporary profile with 20 located dispositions and unchanged
  source hashes; full-page capture and native admission remain open.
  Strict HealthEquity cash evidence now labels its printed balances as a cash
  component, never whole-account value. A bounded read-only pass covered all
  60 referenced PDFs (236 cash rows, 489 unclassified cash-window lines) with
  unchanged hashes. Of those lines, 260 contain decimal values; classify them
  before this family enters normal import admission.
  Fidelity HSA now has a finite account-value summary operation. All 59
  referenced PDFs matched account, period, printed balances and 133 summary
  components against the accepted reader; each printed equation passed.
  Temporary V2 storage reopened them with 133 explicitly tagged period-summary
  rows and 472 dispositions, and the source hashes remained unchanged.
  Full-page capture and accounting review remain open.
  Yamaha now has a finite two-date card operation. All 37 referenced PDFs
  matched masked account, derived period, printed balances and 74 rows against
  the accepted reader; every printed balance equation passed. Temporary V2
  storage reopened the 37 sources with 74 rows and 74 header dispositions,
  and source hashes remained unchanged. Complete capture remains open.
  Capital One auto now has a bounded history operation. All 26 referenced PDFs
  matched account, printed activity range and closing principal; 26 printed
  rows retain 51 principal or interest components. Temporary V2 storage
  reopened all 26 sources, 26 rows and 104 dispositions with unchanged hashes.
  The unprinted opening principal stays unknown; full-page capture and
  accounting review remain open.
  US Bank REI now has a bounded dual-text card operation. All 97 referenced
  PDFs matched the accepted reader on account, period, printed balances and
  2,137 rows; all printed equations passed. Nine interest-period headers have
  explicit dispositions. Temporary V2 storage reopened 97 sources, 2,137
  rows and 150 dispositions with unchanged hashes. Complete capture, signed
  routing and native acceptance remain open.
  Vanguard now has a finite account-value summary operation. All ten
  referenced PDFs matched identifier, period, printed balances and 45 summary
  components against the accepted reader; all ten printed equations passed.
  Temporary V2 storage reopened ten sources, 45 period-summary rows and 65
  dispositions with unchanged hashes. Full-page capture and accounting review
  remain open.
  Fidelity 401(k) now has a finite plan-label summary operation. All 107
  referenced PDFs matched plan label, period, printed balances and 194 summary
  components against the accepted reader; all 107 printed equations passed.
  Temporary V2 storage reopened 107 sources, 194 period-summary rows and 55
  blank-line dispositions with unchanged hashes. Later fund-section capture,
  accounting review and native acceptance remain open.
  OCCU NICE card now has a finite default-layout operation. All 32 archived
  PDFs matched the accepted reader on account, period, balances and 219 rows:
  187 dated activity observations and 32 separately tagged header charges.
  Every printed equation passed. Temporary V2 storage reopened all sources,
  219 observations and 96 located dispositions with unchanged hashes. The
  rewards `PreviousBalance` is separately labeled as points evidence. Full
  page capture, signed routing and native acceptance remain open.
  OCCU bank now has a bounded two-account operation. All 113 archived PDFs
  matched the accepted reader on 226 savings/checking accounts, 6,427 rows,
  printed running balances and closing equations. The 78 statements without
  text dates use a bounded first-page annotation decoder with exact ordinals;
  six dated ATM inquiries are nonfinancial dispositions. Temporary V2 storage
  reopened all 113 sources, 6,427 observations and 295 dispositions without
  changing source bytes. Other account sections, complete page capture,
  signed routing and native acceptance remain open.
  Older Citi now has a finite default-layout continuation operation. All 135
  routed archived PDFs matched the accepted reader on account, period, printed
  balances and all 1,740 dated rows; every printed equation passed. Five
  zero-activity statements keep zero rows only with matching printed balances.
  Temporary V2 storage reopened all 135 sources, 1,740 rows and 547 located
  dispositions with unchanged hashes under the first declaration. The revised
  declaration retains every uncovered line with a supported dollar token as a located source
  disposition. A read-only replay of the 133 successful-archive PDFs kept 1,675
  activity rows, located all 4,552 lines with supported dollar tokens,
  classified 532 clearly labeled annual/period fee and interest totals, and left 1,944 explicitly
  unclassified. These are source labels, not transaction postings. Owner-approved
  older-Citi review policy: proceed to transaction review when the independent
  printed balance equation passes and every supported dollar-token line is
  located; show each unresolved non-activity line with source text and location,
  and leave it unposted. `capture_verified` stays false; other page text,
  full-page capture, and separate accounting review remain open. The read-only
  preview shows a nonzero unclassified dollar-line count and the individual
  lines; the owner confirmed the native Windows preview on October 24, 2026.
  Middle Citi now uses a generic declaration-driven header-anchor table worker.
  All eight routed archive PDFs matched the accepted reader on account,
  period, printed balances and 323 rows. The 1,311 raw table rows divide into
  382 admitted source rows and 929 located dispositions, including a repeated
  header across a foreign-transaction page break. Temporary V2 storage
  reopened all eight sources with unchanged source hashes. The 21 dollar-bearing
  table tails now match declared fee-total, interest-total and APR-disclosure
  shapes; unmatched dollar-bearing tails refuse extraction. They remain source
  summaries/disclosures and do not add activity rows. Complete page capture,
  production-signed routing and native acceptance remain open.
  Older LendingClub savings now reuses the header-anchor worker with seven
  header words locating five data columns. All seven routed archived PDFs
  matched 18 accepted rows, printed running balances and six-value summary
  equations. Temporary V2 storage reopened seven sources, 18 observations
  and 225 located table dispositions with unchanged source hashes. The 28 money-bearing
  tail rows now require four declared table/text shapes per statement and are
  classified as prior balance, printed summary, interest summary or savings-rate
  disclosure, with 28 matching text lines retained separately (253 total
  dispositions). An unfamiliar dollar-bearing tail refuses extraction. Full-page capture
  and native acceptance remain open.
  Wells personal bank now has a finite six-column anchored-table operation.
  All 148 routed archive PDFs matched the accepted reader on period, account,
  printed endpoints and 6,618 transactions. The pilot checked 1,512 printed
  running balances and every closing equation; 5,473 table terminator or
  after-stop rows remain located dispositions. A temporary V2 profile reopened
  all 148 sources with unchanged hashes. Full-page capture, signed routing
  and native acceptance remain open.
  Transamerica retirement now has a bounded account-value summary operation.
  All 12 routed archived PDFs matched 49 accepted summary components and
  printed endpoints; every equation passed. The six-digit plan prefix is
  retained as opaque identity and `Gain/Loss` stays a period summary, not
  cash activity. Temporary V2 storage reopened 12 sources, 49 observations
  and 92 located dispositions with unchanged hashes. Full-page capture,
  account-identity review, signed routing and native acceptance remain open.
  Wells personal loan now preserves printed principal and interest allocations
  separately, with an unknown period start. All 45 routed archive PDFs matched
  account, printed statement end and closing principal; 41 matched the old
  opening, while four expose its synthetic zero opening and origination row.
  The 84 printed allocation rows differ intentionally from 86 legacy
  transformed rows. Each principal balance equation passed. Temporary V2
  storage reopened all 45 sources and 45 identity-copy dispositions with
  unchanged hashes. Ledger treatment, full-page capture and native acceptance
  remain open.
  Detailed MOHELA now round-trips 299 rows and ten loan identities through the
  strict source pipeline and temporary 2.0 profile, retaining 208 unknown
  principal balances. The older MOHELA account-history CSV now retains all 78
  rows from two authorized files with an unknown account identity and no
  invented balance; all 78 printed component equations pass. Loan allocation
  remains a review decision. HealthEquity now classifies all 489 non-dated cash-window
  lines and round-trips 60 PDFs, 236 cash rows and 489 dispositions through the
  bounded pipeline and temporary profile. Cash scope and full-page capture
  remain explicit limits. Ten authorized Synchrony PDFs outside the imported
  archive now match account, period, printed balances and all 97 accepted rows
  through the bounded 2.0 path. Another 891 located table rows are retained as
  dispositions; all ten printed balance equations pass, and temporary storage
  reopens all ten snapshots with unchanged source hashes. Four source activity
  dates precede their printed periods, so no posting date is invented. Full-page
  capture, routing, ledger treatment and native GUI acceptance remain open.
  A second-channel Synchrony scan now links 97 dated text copies to the table
  rows and locates 20 dated summary lines; unmatched dated lines fail. All 118
  undated monetary table rows now have finite summary/disclosure dispositions;
  unfamiliar monetary table lines fail. A shared finite prefix rule in the
  declaration now classifies another 258 money-bearing text lines as payment,
  reward, balance, activity-summary, interest/fee, APR or payoff disclosures;
  unknown monetary text fails. All ten revised Synchrony snapshots reopened
  with 97 rows and 1,169 located dispositions, and source hashes stayed
  unchanged. Other nonmonetary page regions remain a capture review item.
  Intel Mac native checks remain open; XLSX has synthetic parity only.
  Continue decoder worker limits before choosing final schema and operations.
  Define strict schemas and a bounded engine; exercise MOHELA CSV, simple and
  continuation/layout PDFs, plus synthetic
  XLSX. Compare against corrected archive evidence, retain unknown balances and
  source locations, and prove validation/cancellation. Inform V2-2 before schema freeze.
- [ ] **P2-4–5 — Conversion and catalog client:** convert parser families in small
  archive-tested batches; add signed data-catalog loading, caching and publication
  tooling with offline/compatibility checks. No Python/SQL/eval in definitions;
  explicit client-built exceptions require engine support, not downloaded handlers.
  A local 2.0 catalog verifier/cache now authenticates exact Ed25519-signed
  snapshots, checks embedded definition hashes and a caller-supplied strict
  admission rule, and atomically selects a verified offline release. Synthetic
  tamper, rollback, cancellation and reopen tests pass. A local artifact builder
  now validates and signs the 23 declarations using an encrypted key outside the
  repository, then verifies and writes the pair to a new directory. The release
  command now requires the encrypted key to match a public key in the shipped
  plugin trust store; catalog IDs keep a separate signing domain. Installed
  offline acceptance and server publication remain open. The isolated 2.0
  workspace can now install a locally selected signed release pair. Exact
  signature/definition validation, same-release retry and rollback refusal run
  before updating the active catalog; tampered input leaves the current release
  available. The window exposes this as Install signed catalog, and keeps
  source import disabled until verification succeeds. The owner accepted the
  native Windows install interaction on October 24, 2026; a production-signed
  starter pair and installed offline acceptance remain open.
  One strict local admission callback now validates all 23 checked-in pilot
  definitions (22 current parser families, including both MOHELA export formats)
  inside a test-signed snapshot. An explicitly selected verified definition can
  reach the pending-source import service; mismatched parser output is refused
  before a profile write. CSV imports select a unique verified matching definition,
  including both MOHELA formats; zero or multiple matches leave no source write.
  All 21 PDF declarations now require bounded recognition rules. Automatic PDF
  imports decode text in the worker and require one verified route before parsing;
  zero, multiple or explicitly mismatched selections leave no source write. A
  read-only scan routed all 956 successful archive PDFs uniquely across 20
  families, plus three sampled Synchrony PDFs for the remaining family. This
  checks recognition. One read-only archived source from each of the 21 PDF
  families also passed the installed source-to-evidence pipeline; full archive
  extraction parity and installed-client admission remain open. The catalog
  revision field accepts the existing Citi `pilot-2`
  revision without requiring a numeric alias.
  The bounded source pipeline now validates supplied declarations before PDF
  dispatch and selects all 21 PDF pilots by parser identity rather than exact
  checked-in hashes. A valid changed Happen revision reaches its finite operation.
  Recent Citi now passes its supplied routing, table-continuation and occurrence
  rules into the handler and binds output to the supplied revision/hash. A
  revision-only change preserved all 486 observations across ten read-only
  archive PDFs, with unchanged source hashes. A changed routing body refused an
  authorized source, and one revised statement reopened from a temporary
  pending 2.0 profile after local test-signature verification. Financial rule
  changes still need separate source parity review; this is pilot dispatch,
  not automatic document recognition or a released engine.
  A separate read-only developer dialog now shows saved observations, source
  locations, dispositions and coverage limits from a disposable 2.0 profile.
  Its expanded synthetic example has five observations, two source accounts,
  one unknown balance and one classified blank line. Offscreen tests pass and
  the owner accepted the native Windows preview layout on October 17, 2026.
  All finite parser operations and bounded adapters now live in the client
  package. The verified-catalog import service uses that installed source
  pipeline by default; a synthetic signed CSV import saves and reopens its
  evidence without an injected parser. The existing frozen runtime smoke now
  exercises one synthetic V2 parse and pulls the pipeline into packaging. A
  windowed Windows x64 probe passed that runtime smoke and all six worker
  pipes after the package move.
  The runtime smoke now covers synthetic signed-catalog activation, offline
  reopen, catalog import and fresh-profile reopen. A rebuilt windowed Windows
  x64 probe passed this and all six worker pipes; it is not an installed release
  or owner GUI acceptance.
  Daily-workflow desktop import and native Intel Mac acceptance remain open.
- [ ] **P2-S — Declaration catalog server:** after accepted client work is merged,
  use a short-lived server branch for the reviewed snapshot API/storage/publication
  contract. A table may hold JSON definitions; clients consume immutable signed
  releases. Keep 1.4 artifacts available for rollback. No server deployment yet.
- [ ] **V2-2 — Format boundary:** create a clean 2.x profile and refuse 1.x,
  unknown, corrupt and newer databases before writes. Migrate only between
  released 2.x schema revisions. The isolated fresh-profile slice now reopens
  stored, hash-checked evidence without reparsing and refuses synthetic legacy,
  unknown and newer profile shapes before ledger writes; production integration
  and a released snapshot schema remain open.
- [ ] **V2-3a–c — Import integration:** common replay/ongoing ingestion, bounded export
  evidence policy, then main-window import/cancellation/archive recovery and Windows
  acceptance. Keep each service/UI chunk separately testable. The global
  abbreviated-account matching setting defaults off; the 2.0 review now uses
  exact signed-catalog institution/class context, suggests a unique suffix
  match, and offers a reversible inline toggle. The owner accepted that toggle
  on native Windows. Consolidate the
  temporary V2 source store with the user-database service before activation.
  The first isolated import service now skips parsing on exact-source retry,
  retains revised bytes as a second pending snapshot, and leaves no source or
  observation write after parser failure or post-parse cancellation. It can
  compare a new parse against saved evidence without replacing the snapshot.
  The verified-catalog import path now passes cancellation through the bounded
  worker and CSV row loop. A running worker is killed on cancellation; a
  cancelled import leaves no source write. Installed-client
  trust and archive recovery remain open. The separate 2.0 desktop shell now
  opens an explicit fresh profile and verified catalog cache, lists saved
  sources, imports CSV/PDF in a cancellable thread, previews evidence, creates
  financial accounts and opens accountless-export review. It does not post
  entries or initialize 1.x settings. Offscreen interaction tests pass; the
  owner accepted this shell on native Windows. It is a pilot, not the final
  profile picker or daily ledger workflow.
  The fresh profile now stores user-authored financial accounts and explicit
  accountless-export bindings alongside immutable source evidence. A whole-file
  assertion covers a single-account export; individual row assignments cover
  mixed files. The two modes are mutually exclusive and neither posts a ledger
  entry. The owner approved one authoritative account table for the clean 2.0
  database; the provisional financial-only `LedgerAccounts` table has been
  replaced by `Accounts` in pre-release schema revision 7. Earlier disposable
  pilot profiles are refused and recreated, with no migration layer. The
  [unified store direction](docs/client-v2-unified-store.md) leaves reviewed
  journal persistence and category/budget authoring as V2-4 work. An isolated
  accountless-export review dialog now
  presents a six-row disposable MOHELA-shaped demo and saves either explicit
  file or selected-row decisions. Offscreen interaction tests pass; the owner
  accepted its native Windows interaction on October 23, 2026. A separate 2.0
  workspace service now opens only marked fresh profiles, loads an authenticated
  catalog, reads a chosen CSV/PDF without moving it, and saves pending evidence.
  Missing catalog, unsupported/oversized files, cancellation and 1.x profile
  refusal leave no source import. The owner accepted the native Windows shell
  on October 23, 2026. A further slice stores reversible, explicit bindings
  for source-identified statement and export accounts, and offers separate
  review for printed identities and accountless rows. Offscreen tests pass;
  the owner accepted the native review dialog on October 24, 2026. Signed parser
  context and the 2.0 global preference now support unique automatic matches;
  the owner confirmed the on direction and requested a persistent off toggle,
  then accepted the correction. Explicitly bound statement sources now show a
  read-only possible-period-overlap warning when another saved statement is
  bound to the same ledger account and their known date ranges intersect. The
  warning names the other source and makes no duplicate or posting decision;
  the owner confirmed its native Windows presentation on October 24, 2026.
  Ledger integration remains open.
- [ ] **V2-4a–b — Daily review:** create/edit accounts, categories and budgets; connect
  accepted ledger workflows to the application in small increments. A first
  same-database service slice now creates an explicit expense category and posts
  one reviewed cash outflow only when its financial account is explicitly bound,
  its source date role is `posting_date`, and exact source/ledger signs agree.
  Journal and source allocations are immutable; the same decision is idempotent,
  while conflicting reinterpretation and liability rows are refused. A
  correction service now reverses and replaces a reviewed cash expense in one
  transaction, preserves its source allocation history, and refuses changes to
  account assignments after posting. The workspace opens a fresh category
  dialog for adding expense/income
  categories and renaming their display names; an existing journal keeps its
  account ID and payload after a rename. Offscreen acceptance passes, and the
  owner confirmed the native Windows dialog on October 24, 2026. A new
  cash-expense review dialog shows all source rows and permits explicit posting
  or append-only recategorization only for bound asset outflows from activity
  exports with a source posting date. Its offscreen interaction test passes;
  native Windows acceptance remains open. Manual values, closures and
  unsupported accounting remain explicit. Owner Windows integration gate.
- [ ] **V2-5a–b — Report cutover:** shared ledger spending/cash/balance/budget queries,
  then dashboard and export integration. Inventory every legacy menu action; approve
  concrete deferrals rather than silently removing functionality. Owner Windows gate.
- [ ] **V2-6a–b — Profile selection:** backup/restore the new profile and make
  1.x/2.x profile selection explicit. No old-database activation or rebuild
  assistant. Owner Windows reopen/fallback rehearsal is required.
- [ ] **V2-7 — Release:** remove obsolete runtime paths after integration, set the major
  version when ready, then packaged Windows/targeted Intel acceptance and a separately
  approved publication. Include the P2 declaration-catalog release gate; installer
  contracts and Apple Silicon support remain unchanged.

Unexplained imported history can remain visible with an explicit disposition;
invalid journals and misleading totals block release. Forecasting,
new ML insights and complete historical loan reconstruction are not 2.0 launch gates.

### Existing ledger and insight implementation sequence

Each service/calculation chunk precedes its GUI chunk. Windows x64 owner GUI
acceptance is sufficient for routine client features; do not require a separate
Intel walkthrough for every feature. Retain supported-platform automated checks
and request targeted native cross-platform testing when dependencies, packaging,
OS integration, or evidence of platform-specific behavior warrants it. Record
only platforms actually tested; this does not claim Intel acceptance by inference.

L2 recovery preparation and L3 isolated kernel passed automated acceptance on
September 27; see the [verification record](docs/engineering-acceptance.md#ledger-recovery-and-isolated-kernel--september-27-2026)
and [kernel guide](docs/client-ledger-kernel.md). L4R fresh-source/category and
asset-value preservation passed owner Windows acceptance on September 27; see the
[accepted rebuild record](docs/engineering-acceptance.md#historical-parser-compatibility-and-complete-annotation-preservation--september-27-2026).
The active application still uses
the legacy model. The owner approved corrected HSA evidence for the first disposable
shadow migration, retaining printed-balance gaps as explicit exceptions.

- [~] **L1 — Accounting contract and migration audit:** the
  [contract](docs/client-ledger-contract.md) and [read-only auditor](devtools/ledger_audit/README.md)
  are prepared and exercised on a consistent authorized snapshot. The owner
  confirmed legacy manual closures are bookkeeping instructions: preserve them as
  evidence and map their intent to account-status metadata, not cash postings.
  The HSA parser now reads continuation pages and validates printed cash balances;
  all authorized source fixtures reparse successfully. A private history-correction
  preview is approved for shadow conversion. Remaining differences between consecutive
  printed balances stay unresolved through migration; do not invent balancing adjustments.
  Private findings/review notes stay in ignored storage. Complete account/sign/
  evidence mappings after review; unknown residual balances remain explicit.
  LendingClub savings now validates its independent printed summary; Capital One
  Auto validates printed principal/interest/payment components but still has a
  reconstructed opening balance because the source supplies only the closing
  principal. Preserve reported/derived/assumed balance provenance in the ledger
  design, and use separate prior-statement evidence for cross-statement checks.
  Do not label a derived-endpoint equation as independent reconciliation. See the
  [parser verification record](docs/engineering-acceptance.md#lendingclub-and-capital-one-balance-evidence--september-27-2026).
  Wells Fargo personal-loan parser changes are deferred at the owner's request;
  preserve legacy synthetic-loan uncertainty in migration. A private account-mapping
  and source-exception review is prepared. The approved first shadow run uses the
  source-corrected HSA observations with remaining gaps unreconciled; live history
  is untouched. Opening anchors, synthetic-loan treatment and investment/valuation
  semantics still need explicit review before posting those interpretations.
  The [loan-readiness audit and read-only view](devtools/ledger_audit/LOANS.md) now
  inventory fresh loan source periods, exact balance equations, distinct movements
  and parser/component limits. Synthetic origination, capitalized interest and asset
  funding remain explicit review hints; no loan observation is admitted or posted.
  The owner accepted all three read-only tabs, evidence hints and reopening on October 3;
  no financial decisions were changed. The next bounded scope uses Capital One Auto's
  payment/interest contract. Keep Wells Fargo origination uncertainty deferred.
- [~] **L4 — Fresh-ledger posting and reconciliation:** the
  [shadow converter](devtools/ledger_audit/SHADOW.md) established kernel/replay checks;
  the approved breaking transition now uses freshly parsed evidence from L4R.
  Wire that evidence into journal/reconciliation workflows without a permanent legacy
  compatibility layer. Complete balance/timing provenance, reviewed opening positions,
  confirmed transfers and remaining evidence allocation before report cutover.
  No automatic balancing adjustments or duplicate purchase/asset recognition.
  The [cash/card proposal service](devtools/ledger_audit/PROPOSALS.md) now maps fresh
  checking/savings/card observations into kernel evidence and generates immutable,
  unposted ordinary expense/refund proposals from retained verified categories.
  Source membership, signs, dates and category verification are preserved; accounting
  review remains false. Exact balance, allocation uniqueness and deterministic replay
  pass on synthetic fixtures and the accepted private rebuild. Unknown interpretations,
  zero rows and accounts outside this scope remain explicit. Balance endpoints remain
  unverified; no opening positions or reconciliation certification are inferred.
  Ordinary proposal review/posting controls are implemented in a separate disposable
  workspace: filtered batch selection, explicit accept/post or reject decisions,
  cancel-safe confirmation and atomic persistent history. The owner accepted the
  [Windows review walkthrough](devtools/ledger_audit/PROPOSALS.md#windows-review-walkthrough)
  on October 2. Ordinary acceptance now uses a standard audit reason unless an
  optional note is supplied; rejection/corrections still require explanations.
  The active application and original proposals remain unchanged; rejection means
  the accounting interpretation needs work, not that the source movement disappears.
  The [transfer/card-payment service and review](devtools/ledger_audit/TRANSFERS.md)
  now suggest exact opposite movements on distinct owned cash/card accounts, exposing
  missing/multiple candidates, expense conflicts and existing allocations. Confirmation
  posts atomically: one same-day entry or two source-dated entries through clearing.
  No expense/income, balancing adjustment or automatic transfer confirmation is inferred.
  The owner accepted the Windows transfer workflow and persistence on October 2.
  Earlier ordinary-review test decisions are UI exercises, not accounting decisions
  to carry into rebuilt books. The [opening-readiness audit](devtools/ledger_audit/OPENINGS.md)
  now records earliest source balances, conditional cutoffs, provenance blockers and
  interval-aware continuity checks without posting journals. Equal balances across
  missing periods do not establish coverage. Chase posting dates are transaction-date
  proxies and must remain explicitly estimated, not silently certified as bank dates.
  Explicit source balance/date review and atomic opening confirmation are now
  implemented in a fresh disposable workspace. Source assertions are append-only;
  nonzero openings use opening equity, and zero openings record no journal.
  Estimated dates remain visible in ordinary/transfer details; later source-review
  changes mark affected opening decisions stale. Raw evidence and gaps are preserved.
  The owner accepted the Windows opening workflow and persistence on October 2.
  These disposable sample decisions are workflow tests, not financial attestations.
  The [reviewed-source reconciliation service](devtools/ledger_audit/RECONCILIATION.md)
  now checks saved provenance and current openings against exact balances and evidence.
  Versioned, read-only reports keep interpretation review, date uncertainty, unresolved
  movements and coverage independent; no GUI test decisions become financial approvals.
  The statement-reconciliation review UI now exposes source/ledger differences,
  selected-statement evidence, coverage and movements outside the ledger. Any eligible
  statement can receive explicit source review; known estimates remain locked. Saved
  display snapshots survive reopen and become visibly stale after source/ledger changes.
  Owner feedback confirmed source-review persistence; the table now shows current
  recorded/not-recorded status and a dedicated filter independently of stale checks.
  The owner accepted the Windows reconciliation workflow, persisted source review and
  status/filter visibility on October 3. Sample decisions remain disposable UI tests.
  Broader split/correction workflows, remaining interpretations and report cutover remain open.
- [~] **L5b — Ledger interpretation editing:** persist review decisions, confirmed
  transfers/splits, opening anchors, source corrections and reversal/replacement
  workflows; require a separate Windows native walkthrough before report cutover.
  The [expense/refund correction service](devtools/ledger_audit/EXPENSE_CORRECTIONS.md)
  now previews exact category splits and atomically reverses/replaces posted ordinary
  entries, preserving the whole original financial movement and verified category history.
  The correction editor now lists active/superseded entries, previews exact category
  splits with a required reason, and supports cancellation before application.
  The owner accepted the Windows correction workflow and persistence on October 3;
  sample decisions remain disposable tests. The next bounded chunk explicitly classifies
  wholly unallocated cash/card evidence as an expense/refund with exact category splits,
  preserving rejected proposal history. Its [service](devtools/ledger_audit/EXPENSE_INTERPRETATIONS.md)
  and Unposted movements tab passed owner Windows rejection/recategorization/persistence
  acceptance on October 3. The next bounded chunk adds explicit positive checking/savings
  income receipts and category corrections, preserving the deposited amount without
  inferring gross pay/deductions. Its [service and UI](devtools/ledger_audit/INCOME.md)
  passed owner Windows workflow and persistence acceptance on October 3.
  The read-only loan-readiness checkpoint under L1 passed owner acceptance. The
  [Capital One loan-payment service and review](devtools/ledger_audit/LOAN_PAYMENTS.md)
  now preview and atomically post an explicitly selected bank payment, loan payment
  and separately evidenced interest component. Only the interest adds expense; both
  payment dates survive through clearing when needed. Pending expense conflicts,
  missing/ambiguous components and allocated movements block posting. No loan opening,
  financing, synthetic origination or reconciliation is inferred.
  The owner accepted the Windows workflow on October 3 and requested fixed categories.
  Interest now enforces the shared Loan interest built-in; ordinary expense workflows
  retain built-in/custom category choices and splits. The
  [loan bank-match correction workflow](devtools/ledger_audit/LOAN_PAYMENTS.md#correcting-a-bank-match)
  now previews and atomically reverses/replaces an entire payment/interest bundle,
  preserving loan components, fixed interest classification and both source dates.
  The previous bank movement returns to review; current and superseded matches remain
  visible. The owner accepted the Windows correction workflow on October 3 and
  requested sorting on every column. Shared ledger review tables now support
  ascending/descending sorting with exact numeric money/count ordering.
  The owner accepted sorting on October 3. Ordinary Wells Fargo Personal Loan
  payments now reuse the same payment/interest and bank-match correction workflow
  after archive replay and printed-component checks. Review exposes printed
  principal balances and the assumed 31-day period; synthetic origination and
  separate extra-principal rows remain unposted. The owner accepted the Windows
  Wells Fargo workflow on October 3.
  [Declarative accounting contracts](docs/statement-accounting-contracts.md) now
  capture validated parser metadata in new imported statement rows and dispatch
  both loan formats through one retained total-payment/separate-interest contract.
  Balance/period/date provenance and excluded components are explicit. Unknown
  declarations remain review-only; previews bind the retained declaration, and old
  decisions retain their original meaning. Migration leaves old statements undeclared.
  **Next: V2-1 preservation inventory and P2-1 engine/parser review.**
  Extend evidence representations only in bounded chunks needed for that scope.
  **MOHELA: one-time detailed-export replacement passed owner Windows review
  on October 4.** The owner selected MOHELA alone; StudentAid/ECSI are not required
  inputs. The [replacement tool](devtools/ledger_audit/MOHELA_REPLACEMENT.md) creates
  a disposable unposted rebuild, retaining the accepted original and source bytes.
  Old aggregate movements are superseded only when detailed components match
  exactly. Verified categories survive as historical group annotations; bank
  evidence remains unchanged. Separate loan identities, principal/interest/fees,
  zero rows and unknown reported balances are retained without fake endpoints or
  balancing entries. The read-only review covers balances/differences, retained
  categories, possible bank matches and source activity. The owner accepted leaving
  the differences unexplained for now; suspected capitalized interest is not a
  supported dated accounting entry. Loan posting and live-profile cutover remain
  separate work.
  The owner reports missing prior-servicer transfer activity and incremental balance
  changes without corresponding records. The new history remains an unverified
  source claim, not proof of the actual obligation. General recurring export
  replacement remains a separate design proposal:
  - Distinguish immutable statements with asserted periods/endpoints from mutable
    activity exports. File hashes prove retained bytes, not source completeness.
    First/last transaction dates and adjacent requested export ranges do not certify
    coverage; backdated, revised or omitted activity can escape incremental imports.
  - Propose retaining every export snapshot, import/retrieval-time provenance and
    any explicit requested/as-of range separately from transaction dates. Compare
    repeated full-history exports where available; a rolling overlap alone provides
    no guarantee against arbitrarily late changes. Even full-history exports remain
    source claims, not proof of completeness.
  - Design stable-ID or conservative occurrence-aware matching across snapshots,
    with added/changed/missing/ambiguous evidence review. Do not silently delete
    previously observed rows, double-count duplicates, or overwrite verified
    categories and posted interpretations when source history changes.
  - Keep reported balances, reconstructed activity and unexplained differences
    separate. Missing transfer history must not become invented income, interest,
    spending or a balancing entry. Consider separately reviewed prior-servicer
    evidence and opening positions; incomplete debt history must remain visible.
  These are design requirements/proposals, not approval for a broad import rewrite.
  Review the remaining loan formats before adding declarations; principal-only
  payments, disbursements and capitalized interest need distinct, tested accounting
  semantics rather than a guessed mapping to total-payment-plus-interest. Per-row
  semantic tags and mixed representations within multi-account statements remain
  extensions in the P2 evidence design where needed. Broader declarative extraction
  and parser simplification are now included in 2.0 under P2. Other loan/source
  component corrections need separate bounded chunks before claiming full loan
  reconciliation. Cutover may retain explicit unresolved scope under the V2 plan.
  Negative income adjustments, transfer/clearing, loan, asset, opening and source
  corrections remain separate scopes.
- [ ] **CF2 — Ledger-backed cash-flow contract:** under V2-5a, define account scope, income,
  purchases, refunds, internal transfers, card payments, and loan treatment.
  Synthetic transfers/card payments cannot double-count consolidated spending;
  unresolved matches stay visible. Establish reviewed transfer interpretations
  before forecasts rely on them.
- [ ] **CF3a — Spending comparison service:** exact totals, comparable periods,
  merchant/category drivers, uncategorized rows, and source transaction evidence.
- [ ] **CF3b — Spending overview UI:** account/date filters, coverage/freshness,
  reconciled totals, and drill-down; owner Windows workflow acceptance, with
  targeted Intel checks under the testing policy above.
- [ ] **CF4a — Upcoming-obligation detector:** fixed/variable monthly patterns,
  expected dates/amount ranges, supporting history, and abstention on insufficient
  evidence. Backtest using earlier data only; cover refunds, irregular purchases,
  sparse history, calendar variation, and missing statement periods.
- [ ] **CF4b — Obligations UI and feedback:** persisted confirm/correct/dismiss
  decisions; distinguish estimates from recorded transactions. Native acceptance.
- [ ] **CF5 — Cash-planning design and implementation:** separately scoped chunks
  for confirmed income/bills/card autopay, dated balance observations, exact
  account-level projections, and scenario UI. Backtest forecasts, reserve each
  obligation once, expose assumptions/uncertainty and lowest-balance dates, and
  gate available-to-spend on input freshness and the selected horizon/buffer.

F2 import history supports later coverage/recovery explanations; old added/reused
counts that were never stored remain unknown. C2b precedes larger import flows.
F3 rules remain behind the first insights; split deterministic read-only preview
from atomic application/provenance. F4 should split verified bundle creation from
disposable restore. F1 offline onboarding and C3 dependency cleanup remain lower
priority proposals. New/unscoped features still require a design discussion.

## P1.5 — Client release reliability

- [~] **R2 — Intel macOS packaging:** `[USER]` Accept operation on a machine
  where build tools are physically absent when that environment is available.
  The signed candidate's installation, synthetic runtime/offline probes,
  and owner offline first start/restart with system-only `PATH` passed; see the
  [installed candidate record](docs/engineering-acceptance.md#intel-installed-candidate-verification-september-19-2026).

Acceptance: one clean tag produces traceable target-specific artifacts; a dry
run does not change public directories, and publish-existing uses exactly the
reviewed bytes. Intel clients start without Homebrew/build tools at runtime.

## Client correctness and cleanup proposals

Implement after the release/offline chunks. Each item is a focused change with
the review's acceptance checks, not a broad refactor.

- [ ] **C2b — Responsive imports:** move import work to a worker with account and
  warning decisions on the UI thread. Cancellation must preserve commit/archive
  recovery invariants and accurately report committed work.
- [ ] **C3 — Packaging/docs cleanup:** measure the installed/frozen dependency
  graph, separate release/server-devtool dependencies into appropriate extras,
  and include client scripts/migrations in hosted lint. Keep devtools functional
  and pass native frozen/offline checks before removing a dependency.
- [ ] **W1 — Website theme script order:** remove the duplicate asynchronous
  `main.js` loader from the download page and review matching pages. It can run
  before jQuery, producing a console error even though the normal theme and both
  installer downloads work. Verify with delayed dependency loads and a public
  browser check. This pre-existing issue was recorded during 1.4.2 publication;
  its fix requires a separately tested website release, not new client installers.

## Client feature proposals

These remain follow-on proposals unless selected in the active roadmap. F1
addresses empty-profile offline use; C2 should precede larger import/analytics
features. Scope and acceptance must be settled before implementing each proposal.

- [ ] **F1 — Signed offline parser starter pack:** choose bundled baseline catalog
  or local signed-catalog import, verify before activation, preserve a newer
  installed release, reject tampered/incompatible bundles, and make no-model
  guidance actionable. Accept with a clean offline synthetic statement import.
- [ ] **F2 — Import history/reconciliation:** persist per-account added/reused
  transaction counts, source/archive states, failures, and pending recovery.
  Accept with overlapping/multi-account fixtures and safe retries after restart.
- [ ] **F3 — Categorization rules with preview:** add ordered local
  merchant/account rules, read-only preview, and atomic bulk application.
  Preserve manual verification unless the user explicitly selects those rows;
  prove deterministic precedence with synthetic merchants.
- [ ] **F4 — Complete local backup GUI:** expose the verified
  [recovery service](devtools/recovery/README.md) through an optional database/archive
  workflow and restore into a new profile. Preserve plain database backup and
  request Windows native acceptance. The L2 command-line bundle/isolated restore
  checks are complete; profile activation and GUI integration remain proposals.

## Deferred platform and product work

### Apple Silicon (arm64)

Native acceptance is blocked on access to suitable test hardware; experimental
CI feasibility can proceed separately and is not a Windows/Intel release gate.

- [ ] **ARM-CI — Bounded feasibility check:** inspect native GitHub ARM runners,
  exact interpreter/dependency availability, and the existing Intel-only build,
  target, and binary-audit assumptions. Start with source tests, then propose
  separate experimental build artifacts if practical. Do not publish installers
  or claim support from hosted tests; retain native acceptance below.
- [ ] `[USER]` Establish an Apple Silicon development/native acceptance machine.
- [ ] Add the separate arm64 build, architecture-specific CI and installer
  publication after the target contract is in place. Prove Intel/arm64 artifacts
  at the same version coexist and each client selects a compatible installer.
- [ ] `[USER]` Complete native installation, Keychain, no-build-toolchain/offline
  startup, updater selection, and fresh-user walkthroughs before claiming support.
  Record any translation-mode behavior separately.

### P3.1 — Local data-at-rest protection

- [ ] Extend the device-loss threat model into an encryption/recovery design for
  SQLite, managed archives, backups, logs, and OS swap/crash dumps.
- [ ] Prototype platform-backed database/archive encryption with recovery and
  export paths before choosing SQLCipher or an equivalent.
- [ ] `[USER]` Choose the usability/recovery tradeoff and rehearse backup restore
  and lost-key behavior before enabling encryption by default.

### P3.2 — Linux support

- [ ] Add a Linux package, desktop entry, safe file-launch integration,
  sandbox-aware data locations, and CI smoke test.
- [ ] Test on a Debian-family and an immutable/packaged desktop before advertising
  support.

### P3.3 — Dashboard purpose

- [ ] Decide whether to retain a small account/download/admin surface, add
  privacy-safe operational features, or retire the dashboard if it has no clear job.

### P3.4 — Paid platform distribution trust

Defer until adoption or distribution friction justifies recurring vendor costs.

- [ ] Add Windows Authenticode signing and RFC 3161 timestamping for the executable
  and installer.
- [ ] Add macOS Developer ID signing, hardened runtime, and notarization.

## Separate server follow-up

Outside the active client scope.

- [ ] Migrate production bind-mount ownership and run the backend as a non-root
  user. Rehearse file/key/resource permissions and rollback on staging before a
  separately authorized production change.
