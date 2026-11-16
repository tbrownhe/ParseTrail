# Client 2.0 parsing engine and declarative catalog

This is the current parser/evidence contract for the fresh V2 workspace.
The owner included engine simplification and a finite declarative catalog in
2.0, including every current parser family and the recent Citi PDF layout.
The [roadmap](../ROADMAP.md) owns P2 priorities, remaining gates and scope
selection; the [work records](work/README.md) own dated verification.
The [archived design and pilot history](work/archive/2026-10-25-client-v2-parsing.md)
retains the earlier proposal, comparisons and acceptance chronology.

The [fresh-profile cutover contract](client-v2-cutover.md) supersedes automatic
1.x database replay and category carry-forward. Archive comparisons are
read-only parser evidence. Ordinary financial documents and analysis stay local.

## Target and distribution

The client ships a finite engine and accepts versioned parser definitions as
signed data. Normal V2 parsing does not load the 1.x downloaded `.pyc` catalog.
Routine layout changes can use admitted definition revisions; new operations or
client-built extraction handlers require a client release.

The [catalog verifier/cache](../client/src/parsetrail/core/v2_data_catalog.py)
verifies exact snapshot bytes, embedded definition hashes, release sequence,
engine/schema compatibility and strict declaration admission before activation.
It switches the complete offline release through an atomic pointer write;
unsupported declarations, tampering, mixed releases and silent downgrade are
refused. Explicit rollback and key rotation retain their separate trust rules.
A failed or cancelled activation preserves the last good catalog.

The [admission registry](../client/src/parsetrail/core/v2_catalog_admission.py)
selects fixed finite operations. Definitions carry their supplied revision and
hash through parsing rather than requiring a new hard-coded hash allowlist for
each admitted revision. A financial-rule change still requires fixture review.
The [source pipeline](../client/src/parsetrail/core/v2_source_pipeline.py) admits
only verified definitions. PDF requires one matching signed route; ambiguous or
missing routes and explicitly mismatched selection refuse before a source write.
CSV recognition fully parses installed CSV definitions, retains at most five
typed preview rows per valid candidate, and discards full candidate outputs.
Recognition also retains every distinct source-account group, including empty PDF
sections and unidentified CSV rows; more than 100 groups refuses explicitly.
CSV headers must match the declared ordered fields exactly, subject only to the
declaration's admitted explicit header normalization. Renamed, reordered or extra
columns are not fuzzy-matched. Header matching alone never authorizes admission;
complete file parsing and validation remain required. Interactive import first
asks which compatible account each group belongs to, always offering creation.
Institution/product choices narrow valid formats through signed associations.
The final Review import is read-only: users never assign amount, balance, date or
account columns. Exactly one compatible declaration is required. Conflicting
source-account group structures refuse before assignment; other unresolved overlaps
block final import until account metadata or the supported catalog/export resolves
them. The client does not guess or offer a parser-choice bypass. No valid candidate
has no forced-import override. Noninteractive import still requires a unique
valid CSV match unless an explicit validated selection is supplied.

Recognition opens no profile connection and writes no evidence. A selection binds
source SHA-256, catalog snapshot SHA-256, parser ID, revision and definition digest.
After the GUI decision, the workspace rereads source/catalog, reparses the selected
signed definition and independently rebuilds the complete valid candidate set to
enforce unique account-compatible routing. It then rereads source/catalog again
before atomic persistence; a trimmed preview cannot bypass routing checks.
Detected drift rebuilds the preview and requires another explicit confirmation.
Preview summaries are never treated as authoritative stored evidence. Exact
source retries reuse already verified saved evidence without another choice.
Batch Skip, cancellation and per-file refusal preserve completed imports and
original files. The interactive plan atomically retains evidence, creates only
referenced account drafts and assigns complete source groups; ledger posting
remains a separate explicit review. Headless source-only import remains available.

Institution identity comes only from reliable signed parser context or separately
authored account metadata. Generic column compatibility does not identify a bank.
Institution names/IDs are managed separately from the set of supported formats;
neither choosing an institution nor accepting a candidate establishes complete
capture, period coverage, reconciliation or accounting correctness.

The shared `verified_source_account_context` policy leaves generic CSV institution
and account class unidentified even if a signed format carries a bank label or
the user selected that format. It preserves exact verified PDF context and the
reviewed MOHELA CSV families only when their semantic declaration and located
observed-component shape qualify. Merely renaming a generic parser does not
qualify. Those same rules govern preview, account creation, automatic matching
and cross-document proposals, so later account setup cannot upgrade a format
choice into institution proof.

Catalog entries may contain bounded signed `account_profiles` associations with
managed institution (or wildcard), product and tracking scope. One format can
support several products and a product can have several formats. These associations
are compatibility, not source identification. Identifying `account_context` may
add a product only when established; reviewed single-product family defaults are
finite client policy. Generic CSV compatibility never upgrades those provenance
fields. Existing asset-cash/component/card/loan scope safeguards still govern the
supported interpretations; metadata cannot manufacture a new accounting path.
The catalog builder accepts `account-profiles.json` alongside declarations; signed
catalog admission validates products, scopes and managed institution identities.

The saved source snapshot keeps its chosen definition. Exact retries do not
replace that interpretation, and comparison reparsing remains read-only. The CSV
preview discloses before Import that changing the retained format afterward is
not yet supported. Post-import format correction remains an incomplete recovery
capability; this does not restrict existing reviewed category/date corrections.

The [workspace](../client/src/parsetrail/core/v2_workspace.py) currently accepts
CSV and PDF sources. The bounded XLSX decoder has synthetic evidence only and
is not admitted to workspace imports. Catalog format support for a suffix or a
successful decoder test does not itself authorize runtime support.

The [catalog artifact builder](../client/scripts/v2_catalog_release.py) produces
and verifies a deterministic signed snapshot in a new directory. Its encrypted
private key remains outside the repository; the selected public key must be in
the shipped trust store. The builder does not publish or activate artifacts.
Test-signing with an ephemeral fixture key does not establish production trust.

Production starter-catalog packaging and installed/offline acceptance remain
[P2-5](../ROADMAP.md#p2-5) work. Server storage, transport and publication belong
to separately scoped [P2-S](../ROADMAP.md#p2-s) work after the client handoff.
[DEC-2](../ROADMAP.md#dec-2), resolved October 25, permits local signed-catalog
installation for the first release and defers the service to separate later work.
No server table design, publishing UI or deployment is authorized here. Preserve the independent
1.4 bytecode catalog and installer trust contract for fallback.

## Initial code findings

The [parser inventory](client-v2-parser-inventory.md) maps source families,
fixture coverage and finite-operation needs. Earlier findings about 1.x readers,
computed endpoints and candidate extraction are preserved in the
[archived review](work/archive/2026-10-25-client-v2-parsing.md#initial-code-findings).
Use current code and reviewed work records when assessing runtime behavior;
old pilot language does not establish a missing feature or a new admission gate.

## Definition and engine boundary

| Definition group | Contents |
| --- | --- |
| Identity | Stable parser ID, revision, institution/document label, suffix, schema version and required capabilities. |
| Recognition | Required headers, bounded text/metadata predicates, layout variants and explicit ambiguity refusal. |
| Extraction | Page/section/table selectors, account groups, column maps/named captures, bounded continuation and section boundaries. |
| Normalization | Exact money formats and signs, date formats/year resolution, bounded inherited dates and text normalization. |
| Evidence | Statement/export/observation kind, original fields and locations, value provenance and component roles. |
| Validation | Required/unique fields, component equations, independent checks where available, allowed absences and diagnostics. |
| Help | Download instructions and known source limitations. |

Declarations use strict schemas and a finite set of named operations. They cannot
execute Python, SQL, shell, `eval`, arbitrary module references, filesystem/network
actions or general expressions. Bound document size, nesting, row iteration,
normalization, pattern work and extraction output; regex length alone does not
bound matching time. Malformed, truncated, ambiguous and cancelled inputs must
have bounded refusal paths.

Prefer shared finite operations for common layout behavior. A remaining exception
uses a small named handler shipped with the client and selected from a fixed
registry; declarations cannot load downloaded code. Keep the exception visible in
the family inventory and assess complexity across engine, definitions, tests and
authoring/release tooling. Do not disguise a general programming language as JSON.

PDF library decoding, text/metadata extraction, annotations and word/table finding
run behind [fixed decoder workers](../client/src/parsetrail/core/v2_worker_limits.py).
The boundary enforces source/output, page/row, wall-clock and OS memory limits,
terminates cancelled or overdue work, and refuses when required resource controls
are unavailable. XLSX ZIP/XML decoding uses the same boundary in its isolated
pilot. Worker dispatch happens before profile/GUI bootstrap through fixed
arguments; a declaration cannot choose a worker module or launch command.

Native Windows and Intel macOS decoder, termination and packaged-pipe evidence
remain distinct. Record the platform actually exercised. A Windows/offscreen
result cannot establish Intel or installed/offline acceptance. Remaining native
checks live in the roadmap rather than being inferred from a synthetic decode.

## Evidence and validation

Emit immutable observations, not journals. Retain exact source signs, values,
components, occurrence IDs and locations: PDF page/line/region, CSV row/column or
XLSX sheet/cell. Retain original source bytes and digest, exact definition bytes,
revision/digest, engine/extractor versions, normalization settings, output schema
and diagnostics in the V2 evidence/profile boundary.

Observed, derived, assumed and unknown values remain distinguishable. Calculated
balances never overwrite printed endpoints; unknown is not zero. Multi-account
and multi-loan identity survives without counting both summaries and components
as separate activity. Source rows with equal values remain separate occurrences
unless a reviewed interpretation establishes a supporting relationship; parsing
or account matching never authorizes postings.

For dates, `derived` means deterministic resolution from printed source facts,
such as a Post month/day within the statement period. `assumed` identifies a
posting-date guess where only an activity/transaction date is printed. Preserve
the printed date separately. A global assumed-date preference defaults off and
can permit a reviewed entry to use the guess; toggling it never changes source
evidence. A later accounting-date correction reverses and replaces the journal.

Keep field validity, internal arithmetic, independent printed-source checks,
full-page capture, family parity, accounting review, reconciliation and period
coverage separate. A balanced equation or successful archive replay proves only
its named check. Activity spans, requested export ranges and capture times cannot
certify coverage. The owner-approved incomplete-capture presentation keeps
`capture_verified` false where complete capture is unverified; it does not add a
blanket balance-reconciliation blocker.

The import convenience decision uses two warning classes. Estimated dates and
generic unverified capture are Informational; unverified monetary statement balances,
actual mismatch, unknown monetary fields and unexplained amount-bearing content
Require review. Check equations use the declared account/component scope, including
principal separately from gross loan payments. Unavailable endpoints are described
as unverified rather than failed arithmetic, and activity exports do not invent
statement balance checks. Warnings consider all rows, preserve bounded locations
and occurrence counts, and leave original complete dispositions unchanged. Requiring
preview does not create a source-repair override or modify posting-date permission.

Account for candidate rows in declared activity sections as parsed, explicitly
ignored with a reason, or unresolved. Preserve unexpected dated/amount rows,
continuations, non-activity detail and unclassified page text visibly. Recent
Citi retains source dispositions and unclassified located text without promoting
summary/disclosure/detail lines to financial movements. A source-check failure
refuses admission with bounded diagnostics; never fabricate a balancing row or
endpoint to make the source agree.

The legacy Citi line engine separately recognizes finite anchored account/payment
summary, credit-term, bounded repayment-example, interest-detail and APR-table
shapes as informational source dispositions. It preserves values and locations
and creates no additional activity.
Extra monetary tokens (including truncated dollar amounts) on otherwise recognized
closing/total lines remain unresolved. Unlabelled coupon/disclosure amounts do not
become benign merely through proximity or an equal amount. Engine identity records
the policy revision; declarations and retained snapshots remain unchanged. Exact
source retry still reuses its original evidence. No complete-capture or missing
transfer claim follows from reclassifying known non-activity text.

The evidence envelope excludes categories, verification flags, journals and
postings. Endpoint scopes are explicit: `account_total`, `cash_component` or
`principal_component`. Row roles are `activity`, `period_summary` or
`header_charge`; period summaries carry a derived `statement_period_end` date,
and header charges retain their non-activity period-end role and date provenance.
Neither becomes an invented activity date. Preserve generic
loan activity dates and unknown openings independently of printed closing
principal; principal-component scope does not establish the total obligation.

Yamaha's account-total register retains its transaction and posting columns
separately, including year derivation from printed statement context. The register
review workflow uses that posting fact without adding a guess or principal/interest
breakdown. A whole liability repayment is distinct from the principal-component
loan workflow. See the [register packet](work/2026-10-26-v2-liability-register.md).

Bounded reviewed loan payments retain the complete raw row/component/location
proof separately from canonical derived principal observations. Capital/MOHELA
gross amounts are not principal allocations; Wells interest-only rows create no
financial principal observation. The accounting layer may explicitly review an
assumed activity-based date under the global default-off preference without
changing an original activity date or adding a parser posting guess. Unsupported
components and unknown endpoints remain unresolved. See the
[loan-payment packet](work/2026-10-26-v2-loan-payments.md).

The reviewed HealthEquity cash workflow admits only its finite cash activity
family bound to an asset with cash-component tracking. Printed posting dates and
unknown descriptions remain unchanged. The accounting layer may supply a generic
entry label, explicitly separate from source text; it cannot relabel blank text
as interest. Summary-only HSA/retirement values remain separate nonposting facts.
See the [HSA cash packet](work/2026-10-25-v2-hsa-cash.md).

Catalog updates do not overwrite saved evidence or authored decisions. Exact-source
retry reuses its saved snapshot without parsing; reparse produces a comparison.
Changed output needs explicit review before replacing affected interpretations.
Hashes alone do not guarantee replay parity across engine/library versions;
restoring retained evidence remains distinct from reproducing the original parse.

## Small implementation chunks

The sole ordered P2/V2 plan is [ROADMAP.md](../ROADMAP.md). P2-1/P2-2 cover the
inventory and contract foundation; P2-3/P2-4 track family evidence, decoder limits
and diagnostics; P2-5/P2-S track offline catalog and separate service work.
Their completed pilots, commands and acceptance limits belong in
[work records](work/README.md) and the
[archived implementation history](work/archive/2026-10-25-client-v2-parsing.md#small-implementation-chunks).
This section retains its existing link anchor without maintaining another queue.
