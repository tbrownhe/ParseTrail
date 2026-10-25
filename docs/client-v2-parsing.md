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
The [source pipeline](../client/src/parsetrail/core/v2_source_pipeline.py) requires
one matching verified CSV/PDF definition before import; ambiguous or missing
routes and explicitly mismatched selection refuse before a source write.

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

Account for candidate rows in declared activity sections as parsed, explicitly
ignored with a reason, or unresolved. Preserve unexpected dated/amount rows,
continuations, non-activity detail and unclassified page text visibly. Recent
Citi retains source dispositions and unclassified located text without promoting
summary/disclosure/detail lines to financial movements. A source-check failure
refuses admission with bounded diagnostics; never fabricate a balancing row or
endpoint to make the source agree.

The evidence envelope excludes categories, verification flags, journals and
postings. Endpoint scopes are explicit: `account_total`, `cash_component` or
`principal_component`. Row roles are `activity`, `period_summary` or
`header_charge`; period summaries carry a derived `statement_period_end` date,
and header charges retain their non-activity period-end role and date provenance.
Neither becomes an invented activity date. Preserve generic
loan activity dates and unknown openings independently of printed closing
principal; principal-component scope does not establish the total obligation.

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
