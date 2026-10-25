# Initial-release readiness audit

Date: 2026-10-25. Roadmap IDs: P2-3/4/5, V2-3/6/7.
Branch/runtime: `feature/client-financial-insights`, Windows source runtime.
Authorization: owner-approved roadmap and continued development instruction.
Implementation: complete read-only investigation; no runtime changes.
Automated verification: 256 synthetic checks passed.
Independent review: acceptance specialist investigation reported to primary.
Owner acceptance: not performed; consolidated V2-UX remains open.
Release authorization: not authorized.

## Scope and controlling decisions

Identify actual remaining development versus historical completed slices and
external gates. Only repository code, synthetic declarations/fixtures and
temporary test outputs were used. No private fixture replay, root `.env`, live
profile, production key or external service mutation. Primary owns this record.

## Result and review

All 23 current declarations cover the 22 required families (two MOHELA export
definitions). `devtools/parser_engine_pilot/test_catalog_admission.py` admits
them together in a test-signed snapshot. Fixed workers are client-package code
and dispatch before runtime bootstrap in `client/src/parsetrail/main.py`.
Both native build scripts already call `scripts.frozen_worker_smoke`.
Historical pilot README comments about missing frozen table/XLSX workers do not
describe current code. Do not repeat these package moves or infer source parity
from catalog admission. Existing archived execution/Windows frozen probes are
historical evidence, not acceptance of the current candidate.

This record completes the bounded source-fact readiness/disposition inventory
against existing evidence, retaining summary/non-activity distinctions, unknown
HealthEquity descriptions, omitted synthetic origination/openings and unavailable
loan openings. Capture remains a separate, often unverified dimension.

### Family source-fact dispositions

Primary reviewed the dated family evidence in the
[archived inventory](archive/2026-10-25-client-v2-parser-inventory.md#shipped-parser-and-fixture-matrix)
and [recent Citi extraction record](archive/2026-10-25-client-v2-parsing.md#small-implementation-chunks).
The table below inventories already-recorded evidence; no private source was
replayed for this audit and no historical result is promoted to exact-candidate
native/installed acceptance. All 23 current declarations admit in the current
synthetic snapshot check. Every PDF family retains unverified full-page capture;
located dispositions and dated-start coverage do not certify every page item.

| Reference family | Existing dated source-fact evidence | Initial-release evidence disposition / remaining limit |
| --- | --- | --- |
| MOHELA CSV | Two account-history files (78 rows); one detailed export (299 rows). | Separate definitions preserve detailed or explicitly unknown identities and components; no statement endpoints invented. Loan interpretation is separate. |
| Capital One Auto | 26 source comparisons. | Intentional difference: omit legacy synthetic origination and reconstructed opening. Printed facts retained; opening can remain unknown. |
| Chase card | Five source comparisons and independent printed equations. | Printed activity date retained; posting proxy remains assumed, subject to review/date opt-in. |
| Citi 2015 | 135 sources, 1,740 rows and printed balances; separate monetary inventory of 133 sources. | 1,944 monetary lines remain explicitly unclassified. Owner-approved transaction review requires the independent equation and all supported-dollar-token lines located, visible and unposted. Bounded inventory is not a complete monetary classification claim. |
| Citi June 2025 | Eight sources, 323 rows and printed balances; 1,311 raw table rows disposed. | Monetary tails classified separately; no extra activity from table/text copies. |
| Citi November 2025 | Ten sources, 486 resolved dated starts, 2,940 dispositions; independent balance equations. | Dated-start/channel and dollar-line coverage are bounded claims. They do not establish full-page capture. |
| Fidelity 401(k) | 94 sources compared; printed values and old dated rows match complete V2 rows. | Intentional difference: period summaries are non-activity. Investment valuation/posting is separate. |
| Fidelity HSA | 59 sources compared; identities/endpoints and complete V2 rows match. | Period summaries are non-activity; account-value scope is separate from cash movements. |
| Happen savings | Two source comparisons. | Printed balances and activity retained. |
| HealthEquity HSA | 60 compared; 53 direct matches and seven blank-description differences. | Preserve unknown printed descriptions rather than invented Interest; cash component excludes investment sections. |
| LendingClub older table | Seven sources, 18 rows, running/summary values. | 28 monetary tails have located dispositions. |
| LendingClub newer lines | Five source comparisons; routes separate seven older-layout files. | Derived date substitution remains explicit. |
| OCCU bank | 113 sources; checking/savings rows and running balances. | 78 sources use bounded first-page annotation dates; personal credit-line sections remain outside captured scope. |
| OCCU card | 32 sources and accepted rows/printed balances. | Header interest remains a separate located charge; treatment requires its own supported interpretation. |
| Synchrony/Amazon | Ten separately authorized sources, 97 accepted rows. | Four pre-period activity dates retain source dates and separate assumed posting candidates; they are not automatically posted. |
| Transamerica | 12 sources, 49 printed-value components. | Opaque plan identity and non-activity value summaries retained. |
| US Bank REI | 97 source comparisons. | Printed posting dates retained; unknown transaction dates remain unknown. |
| Vanguard | Ten sources compared; complete rows match old dated rows. | Intentional difference: printed period summaries are non-activity, not cash movements. |
| Wells business | 29 sources, 225 activity rows and printed endpoints. | Optional printed row balances remain source facts; other balances are not filled. |
| Wells personal | 148 sources, 6,618 rows and printed balances. | Located after-stop dispositions do not establish full-page capture. |
| Wells personal loan | 45 sources and printed principal allocations. | No fabricated 31-day period start or synthetic origination. Owner's legacy-parser-change deferral remains in force. |
| Yamaha | 37 source comparisons and independent balance equations. | Both printed dates and source signs retained; loan interpretation is separate. |

These dispositions satisfy the source-fact inventory step, while supported-family
exact-candidate native/packaged admission, installed trust and accounting-workflow
checks remain open. Optional personal-credit-line capture and unmatched extra CSV
formats were not silently admitted. Unknown source facts do not become runtime
errors merely to force legacy-result equality.

`V2Workspace.import_file/import_files` leaves selected originals untouched;
`V2ProfileStore.import_source` embeds exact source, declaration and evidence in
SQLite atomically, and `snapshot_to` retains them. There is no managed V2
SUCCESS/FAIL archive move to recover. The appropriate next recovery packet is
embedded-source recovery/export and lifecycle failure checks, rather than copying
legacy file-move semantics.

Remaining autonomous accounting work includes durable reconciliation history,
opening/transfer/binding and duplicate-posting correction safeguards, refunds and
negative income adjustments, fees/partial settlements, supported loan/HSA/value
interpretations, closures, cash-flow classification and drill-down. Consolidated
human UX review does not block these workflows. DEC-1/2/3 were subsequently resolved
in the [positions packet](2026-10-25-v2-account-positions.md).

## Verification

Python 3.13.15, Windows 11 AMD64. Acceptance specialist inspected isolation first;
client conftest provides a disposable home/profile and null keyring.

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider devtools/parser_engine_pilot client/tests/test_v2_catalog_import.py client/tests/test_v2_data_catalog.py client/tests/test_v2_catalog_release.py client/tests/test_v2_worker_entry.py -q
```

256 passed in 18.30 seconds, exit 0. Includes Windows Job Object memory refusal,
timeout/cancellation and bounded synthetic decodes. This is neither Intel nor
installed/offline release acceptance, and does not establish private-source parity.

Independent acceptance review verified every family row/count against existing
records and current code. It identified the omitted Citi 2015 monetary-inventory
limit and stale decision wording; both were corrected. All 21 PDF definitions
reach installed-package source checks, but that parameterized test expects source
refusal: it does not prove a successful end-to-end import for every family.

## Remaining work

Continue bounded development packets. DEC-2/3 were subsequently resolved in the
positions packet; deferred capabilities remain important future work. External gates remain V2-UX,
targeted Intel native/packaged pipes, exact-candidate packaging and installed
offline/OS behavior, R2's physically absent build-toolchain environment when
available, and specifically authorized production signing/release/publication.
