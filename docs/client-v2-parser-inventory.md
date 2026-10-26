# P2-1 parser and engine review

This is a dated technical family map from the October 25, 2026 checkout review.
The parser IDs, source versions and family labels below identify the independent
1.x reference implementations; they are not V2 catalog IDs or a guarantee that
installed artifacts equal this checkout. The owner requires every current parser
family, including recent Citi, in the first V2 release. The
[parser contract](client-v2-parsing.md) owns enduring engine/evidence rules;
[ROADMAP.md](../ROADMAP.md) owns priorities, selected scope and release gates.

The [archived inventory](work/archive/2026-10-25-client-v2-parser-inventory.md)
contains the original fixture counts, comparisons, operation-cost estimates and
chronology. Those are dated observations, not new execution instructions. Use
[packet records](work/README.md) for subsequent verification. No private fixtures
were replayed to consolidate this document.

## Shipped parser and fixture matrix

The snapshot contains 22 source parser families: 21 PDF and one CSV. V2 may use
different admitted definition/operation identities. The matrix preserves useful
evidence distinctions and observed limits without duplicating validation logs.

| 1.x parser ID | Dated source version | Reference family/layout | V2 evidence distinction or observed limit |
| --- | --- | --- | --- |
| `csv_mohela_202411` | 0.2.1 | Life-of-loan account-history CSV | Activity-export rows preserve loan components and duplicate occurrences; unavailable principal stays unknown, with no invented statement endpoints. |
| `pdf_capitaloneauto_202402` | 0.2.2 | Auto loan PDF with payment components | Printed closing principal and source-native components are retained; unprinted opening and synthetic legacy origination remain unknown/unposted. |
| `pdf_chasecc_202602` | 0.1.0 | Section/line credit-card PDF | Activity dates and assumed posting candidates remain separate; printed balance equations do not establish page capture. |
| `pdf_citicc_201505` | 0.3.1 | Older Citi line credit-card PDF | Finite line/continuation evidence retains source occurrences and dispositions; complete page capture remains unverified. |
| `pdf_citicc_202506` | 0.3.1 | Citi table credit-card PDF | Anchored-table evidence retains wrapped/foreign-transaction detail and monetary-tail dispositions separately from activity. |
| `pdf_citicc_202511` | 0.4.0 | Citi table plus text/fee recovery PDF | Table/text/fee copies use finite occurrence reconciliation with exact locations; unclassified page text remains visible and capture unverified. |
| `pdf_fidelity401k_201810` | 0.2.1 | Retirement PDF, wrapped account labels | Printed value components are period_summary rows with derived statement-period-end dates; investment posting remains unresolved. |
| `pdf_fidelityhsa_202001` | 0.2.0 | HSA line PDF | Account-value summaries are non-activity components; source facts do not decide HSA accounting or investment values. |
| `pdf_happenbank_202606` | 0.1.0 | Savings line PDF | Located savings activity and independently printed balances remain distinct from capture/coverage claims. |
| `pdf_hehsa_201810` | 0.2.1 | HealthEquity cash and continuation PDF | Cash-component scope excludes investment sections; blank printed descriptions stay unknown rather than being relabeled Interest. |
| `pdf_lendingclublus_202506` | 0.2.0 | Older savings table PDF | Anchored bank rows, printed running balances and located monetary tails remain separate evidence. |
| `pdf_lendingclubsavings_202601` | 0.1.1 | Savings line PDF | Signed routing distinguishes the line layout from the older table layout; date substitution retains derived provenance. |
| `pdf_occubank_201409` | 0.2.0 | Multi-account bank PDF | Checking/savings sections retain printed or first-page-annotation date locations; personal credit-line sections remain outside the captured scope. |
| `pdf_occucc_201904` | 0.2.0 | Credit-card line PDF | Dated activity and printed header_charge interest retain distinct roles and locations; account identity is last_four. |
| `pdf_synchrony-amzncc_202501` | 0.3.0 | Store-card table PDF | Anchored card rows retain shared continuations; pre-period activity dates and separate assumed posting candidates require the ordinary date gate. |
| `pdf_transamerica_202104` | 0.2.0 | Retirement line PDF | Opaque plan identity and period-summary value changes remain evidence; they do not establish cash movements or accounting interpretation. |
| `pdf_usbankreicc_201405` | 0.2.0 | Credit-card line PDF | Bounded extraction retains printed posting dates and unknown transaction dates where absent; capture remains unverified. |
| `pdf_vanguard_202210` | 0.2.0 | Retirement line PDF | Period-summary value changes keep derived period-end dates; they do not become cash activity or approved valuation postings. |
| `pdf_wfbankbus_202110` | 0.2.0 | Business bank dynamic table PDF | Located table activity, optional printed row balances and after-stop dispositions remain separate; missing balances are not filled as source facts. |
| `pdf_wfbankper_202105` | 0.2.0 | Personal bank table PDF | Anchored table rows retain printed debit/credit and running-balance provenance; retained activity is not a claim of complete page capture. |
| `pdf_wfloanper_202306` | 0.2.1 | Personal-loan line PDF | Printed principal/interest allocations and closing principal are retained; period start stays unknown and legacy synthetic origination is omitted. |
| `pdf_yamahafin_202306` | 0.2.0 | Auto-loan line PDF | The finite two-date operation preserves transaction/Post dates and declared sign syntax. Bounded reviewed account-total register activity/repayments are implemented separately; no principal/interest split is inferred. Source admission is not owner accounting acceptance. |

Source-fact comparison, routing execution, full-page capture, accounting review,
ledger allocation, reconciliation and period coverage are separate claims.
A dated parity result is scoped to its tested sources. No row in this matrix
requires replaying every historical source or joining legacy database IDs before
using a fresh V2 profile. Original 1.x data remains available through the
independent fallback application.

The owner's deferral of Wells Fargo personal-loan parser changes remains a scope
boundary. Existing finite evidence does not authorize additional legacy-parser
changes, historical loan reconstruction or principal/interest postings.

The [October 25 source-fact disposition audit](work/2026-10-25-v2-readiness-audit.md#family-source-fact-dispositions)
maps every family to already-recorded comparison evidence and intentional
differences. It completes that inventory step without new private-source replay
or full-page/installed acceptance. In particular, the older Citi monetary
inventory retains 1,944 explicitly unclassified lines across 133 sources;
supported-dollar-token lines remain located, visible and unposted under the
owner-approved bounded review policy. Do not turn admitted definitions or expected
source-refusal tests into claims of successful packaged import for every family.

The [synthetic admission packet](work/2026-10-25-v2-family-source-admission.md)
successfully exercises all 23 current declarations (21 PDF and two CSV) through
real bounded workers, a test-signed full catalog and disposable-profile import.
This closes the synthetic success-path gap while exact-candidate frozen/installed
admission, private-source parity and full-page capture remain separate claims.

## Shared engine and repeated behavior

Current V2 extraction uses the client-owned finite operations selected through
[v2_source_pipeline.py](../client/src/parsetrail/core/v2_source_pipeline.py) and
[v2_catalog_admission.py](../client/src/parsetrail/core/v2_catalog_admission.py):

| Shared boundary | Current responsibility |
| --- | --- |
| Bounded decode and routing | Fixed PDF text/layout, annotation and table workers expose capped evidence to unique signed-definition routing; declarations cannot launch modules. |
| Exact normalization | Finite money, partial-date and source-sign rules retain raw strings, source locations and observed/derived/assumed/unknown provenance. |
| Section/table extraction | Declared line windows and anchored geometry retain rows, continuations, printed endpoints and explicit non-activity dispositions. |
| Occurrence/channel handling | Shared continuation and occurrence operations preserve distinct occurrences and table/text/fee locations without counting source copies as additional money. |
| Strict output | source_evidence.py distinguishes statement/export payloads, endpoint scopes, activity/period_summary/header_charge roles and diagnostics; it contains no accounting decisions. |

Named built-in handlers are shipped client code selected from a fixed registry;
a definition cannot download an executable exception. Prefer shared finite
operations and record genuinely new operation scope in its packet. Changes to
engine capabilities require a client release; supported definition changes use
the signed catalog and fixture review.

Historical findings about 1.x balance filling, loan synthetic rows and CSV
adaptation remain in the
[archived shared-behavior review](work/archive/2026-10-25-client-v2-parser-inventory.md#shared-engine-and-repeated-behavior).
They are not current V2 behavior. Unknown endpoints and descriptions must stay
unknown; summary rows, header charges and component breakdowns retain their
explicit roles instead of being promoted to ordinary activity.

## Representative PDF operation cost review

The earlier representative cost estimates and their subsequent pilot results are
preserved in the
[archived review](work/archive/2026-10-25-client-v2-parser-inventory.md#representative-pdf-operation-cost-review).
Current work uses the source/evidence contract and roadmap rather than those
historical estimates. This heading preserves existing links.

## Remaining family operation costs

The original family-cost table is preserved in the
[archive](work/archive/2026-10-25-client-v2-parser-inventory.md#remaining-family-operation-costs).
Its candidate operations and conversion gates describe the earlier design stage;
they do not select new work or establish current runtime admission. Current
family limits are summarized above and tracked under P2 in the roadmap.

## Archive layouts and developer/release coupling

The retained 1.x managed archive may contain drop-zone, SUCCESS, FAIL and DUPLICATE
files plus unreferenced companion exports. It remains independent/read-only in
V2 development. A selected original document can be imported afresh; there is no
full-SUCCESS replay or legacy-ID reconstruction gate. Preserve private source
paths, bytes and comparison reports outside Git and routine output.

The original inventory found no referenced XLSX parity fixture. A synthetic
XLSX adapter now uses the fixed bounded worker with ZIP/XML, input/output,
page/sheet/row, deadline, cancellation and OS memory limits as applicable. That
isolated decoder is not admitted to the workspace's CSV/PDF imports. Synthetic
parity does not establish archived-workbook, Intel or installed acceptance.

Legacy batch/replay tools compare specifically authorized read-only inputs and
can bind historical artifacts; they do not authorize broader source discovery,
profile writes or old-data carry-forward. The 1.4 bytecode catalog retains its
own trust contract. V2 uses signed data snapshots and atomic offline activation.
Engine and extraction-library versions belong in saved evidence; installed
source/worker checks and publication remain separately recorded gates.

## Conversion and release gates after P2-1

The sole current conversion/catalog/release plan is
[ROADMAP.md](../ROADMAP.md#initial-20-milestones), especially P2-3/P2-4 family and
worker evidence, P2-5 offline catalog acceptance and separately scoped P2-S.
[DEC-2](../ROADMAP.md#dec-2) retains the unresolved local-catalog versus service
publication dependency. The
[archived gate list](work/archive/2026-10-25-client-v2-parser-inventory.md#conversion-and-release-gates-after-p2-1)
preserves the old sequence; this heading is a redirect, not a second queue.
