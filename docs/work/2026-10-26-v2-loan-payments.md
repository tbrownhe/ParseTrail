# Review evidenced loan principal and interest payments

Date: 2026-10-26. Roadmap IDs: V2-4/5, CF2.
Authorization: approved roadmap and continuing initial V2/P2 development.
Implementation: complete against HSA baseline `c0ea8a2`.
Automated verification: focused and broad V2 integration passed.
Independent review: complete; no outstanding accounting/provenance/persistence findings.
Owner acceptance: pending integrated V2-UX; an earlier synthetic review is available.
Release authorization: not authorized.

## Scope and controlling decisions

Admit a bounded reviewed payment event pairing an explicitly selected, observed
owned asset outflow with printed Capital One/MOHELA principal/interest components
or explicitly selected Wells principal/interest rows. Require exact gross equality
and complete printed component support. Do not infer grouping from dates, invent a
bank counterpart, estimate a payment schedule, fill unavailable principal/interest,
post origination, or change the Wells parser/unknown period start. Nonzero fees,
unsupported capitalization/disbursement and incomplete/mixed-sign breakdowns stay
pending. Existing source admission for all families remains separate from this
accounting admission. Yamaha account-total register support is a separately bounded
part of the remaining loan work, with no fabricated component breakdown.

Preserve original source facts and locations. Loan activity dates are observed
activity dates with no current parser posting candidate. An explicitly reviewed
assumed accounting date may use that activity date only under the existing global
default-off preference; never mutate imported evidence or call it reported. Bank
and loan legs retain their own effective dates, using existing transfer clearing.
No forced common date or invented statement endpoint. Unknown opening remains
unknown; principal-component positions do not establish the total obligation.

Capital example (minor units): printed gross -22000, principal -20000, interest
-2000 becomes liability debit +20000, interest expense +2000 and clearing -22000.
The actual bank source posts -22000/+22000 clearing at its own date. Consume the
raw loan row's -22000 once, separately from the +20000 derived financial principal
allocation. MOHELA -10000/-8000/-2000 similarly gives +8000 principal/+2000 interest.
Wells principal +2000 and interest +100 gives +2000 liability/+100 expense; an
interest-only row creates no zero principal posting or fabricated financial
observation. A typed component proof supports that imported expense/clearing leg.
Printed zero interest creates no expense posting/category. Interest is counted
once; gross payments are not a second expense.

The pre-release schema adds immutable loan events/actions, full raw source
uses, derived financial principal observations and separate derived allocations.
Keep `ledger.Observation` financial-only and retain existing raw allocation meaning.
Add a finite typed component-proof validation path, default empty for old callers;
never bypass imported evidence validation with a boolean or manual origin.
Every common report/read/backup must validate proofs and exact entry shapes.

Preview/snapshot captures account bindings/scopes, original/component facts,
normalization, effective dates/assumption, proposed entries, blockers and an
optimistic basis. Posting revalidates under one write lock; category creation,
proof/source uses, observations, entries and allocations commit atomically.
Whole withdrawal/replacement retains exact dated inverses and original context,
releases active raw/derived uses and creates fresh identities on fresh review.
Idempotent history retries cannot revive retired money. Ordinary single-entry
correction/posted-repeat repair must refuse loan-event legs. Later repeat exclusion
must not discard changed component vectors merely because gross totals match.

All work is on the active client branch with public synthetic/disposable inputs.
The primary owns scope, shared contracts/record and report/export/drill-down
integration. `positions_service` is the sole loan store/ledger/proof writer after
HSA closeout; `positions_desktop` owns the new loan dialog, workspace menu and
focused GUI tests. Independent integrity review covers money, provenance, persistence,
retirement, input versions and failure paths. No recursive delegation or live/
1.x profile mutation, production signing, publication or daily activation.

## Result and review

Read-only design investigation confirmed all four source shapes and the mismatch
between raw gross use and principal financial allocation. Existing financial-only
allocation validation cannot support Wells interest-only entries without an
explicit typed proof path. Supporting this with a fake financial source row or
manual-origin entry is excluded. The existing source adapters remain unchanged.

Schema 21 implements the five immutable table groups described above. The finite
typed `LoanComponentProof` path in `ledger.validate_entry` preserves ordinary
financial observation/allocation requirements, validates the exact component entry,
and supports interest-only evidence without a manual-origin exemption. Loan events
retain exact full raw source uses and separate canonical principal allocations.
Public snapshot/preview/post/history/whole-withdrawal/replacement APIs recheck
cached basis/event versions and original context under transactional locks.
Scope/binding locks include retained interest-only proof. Common journal reads,
pending/overlap guards, principal comparisons, positions, reconciliation versions
and verified backup validate both dimensions and exact retirement inverses.
Rule 6 normalizes principal comparisons; saved rule-5 HSA scopes remain exact/stale.

The Review menu opens an explicit bank/component selector with no automatic
matching or grouping. It displays raw amounts, normalized principal/interest,
original activity dates, assumed accounting dates, source previews and exact dated
entries. Global assumed-date permission defaults off; enabling it is explicit.
Reference/reason, confirmation and complete history support whole correction and
withdrawal. Failure/stale/cancel paths clear obsolete previews and preserve books.

Cash reports split only actual bank effects into principal/interest purposes,
while journal expense remains at the lender's reviewed date. Workbook raw Source
Allocations and Derived Allocations are separate. Loan event/source-use/component/
location/action sheets retain all-date history as metadata, including retired
events, without adding period money. Entry drill-down links whole events across
dates/corrections; an interest-only row still offers both bank/lender source
previews despite having no financial allocation. Formula-looking references remain
literal workbook strings. Missing openings/period starts do not become balances.

## Verification

Platform: Windows 11 AMD64, Python 3.13.15; Qt offscreen. Commands use
`PYTHONPATH=.;client/src;client`, `QT_QPA_PLATFORM=offscreen`,
`client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider ... -q --tb=short`.

- Final service `test_v2_loan_payments.py`: **42 passed in 34.84s**, after final
  finite manifest-rule/size and nested retirement validation. Covers exact
  variants, raw/derived uniqueness, interest-only/zero interest, default-off date
  permission, stale/retry/rollback/tamper, whole history, original binding/scope,
  unknown balances, backup and retained rule-5 HSA cash scope.
- Earlier adjoining ledger/profile/HSA/binding/reconciliation/overlap/transfer
  run: **189 passed, 2 failed in 174.67s**. Both failures were old rule-5 literal
  test assertions loaded before their authorized rule-6 updates. A later combined
  loan/HSA/overlap/wider pass had **104 passed in 114.50s**. The earlier invocation
  is not represented as fully green.
- GUI `test_v2_loan_payment_dialog.py` plus source-value integration and settlement
  dialogs: **35 passed in 38.29s**, including **19 new** actual-service cases.
  Source/preview/history layouts inspected with Segoe UI at 1240x800; long IDs/date
  role columns resize/scroll. No owner/native acceptance is inferred.
- Primary `test_v2_loan_integration.py`: **4 passed in 10.17s**. Exact bank opening
  100000/loan -970000 at December 31 produces bank 78000 and loan -950000 after
  January's payment; clearing is 22000 after bank date and zero after lender date.
  Expense 2000 occurs only at lender date. Tests cover workbook exact/literal
  values and locations, interest-only source preview with zero financial
  observations, whole correction/withdrawal audit money, and actual public
  synthetic Capital PDF through bounded extraction, posting and verified restore.
  After independent review's count-note clarification, the complete four tests
  **passed in 7.56s**, additionally asserting one actual cash record, two purpose
  counts, the explicit nonadditive notice and both source previews in the cash GUI.
- Independent actual bounded-source probes reproduced all four Capital/MOHELA/
  Wells shapes. Wells interest-only yielded expense/clearing with no derived
  observation; detailed MOHELA zero interest created no interest category. Unknown
  Capital opening and Wells period start remained unknown.
- Final independent seven-module pass over loan service/GUI/integration, ledger
  kernel, binding corrections, reconciliation history and common journal integrity:
  **171 passed in 217.66s** on frozen schema 21/rule 6. No actionable findings.
  Actual worker probes refused a changed principal/interest vector with equal
  gross/date/description as `source_overlap_component_conflict`; no pending state,
  raw consumption or money was changed. Ordinary interpretation withdrawal and
  posted-repeat repair refused both bank and interest-only loan legs, including
  events with zero derived observations. Whole histories/usage stayed unchanged
  and verified backup passed. Overdeep/oversized manifests/component evidence and
  unknown rule tags failed with controlled errors. No private/native owner or
  installed/Intel acceptance is claimed.
- Broad command `client/tests -k v2`: **872 passed, 1107 deselected in 839.38s**.
  This ran after financial/service/desktop freeze. The final purpose-count wording
  and added cash-GUI assertions are additionally covered by the four-test rerun
  above. Changed-file Ruff check/format, repository hooks, local-link and Git
  whitespace checks passed after line-ending normalization only.

Checks exercise exact synthetic Capital/MOHELA/Wells cases, including zero principal,
observed zero interest/fee versus unknown, separate accounts, effective dates and
default-off assumptions. Exercise duplicate raw use, derived IDs, partial/mixed
components, exact bank matching, wrong bindings/scopes, stale/retry/rollback,
whole correction/withdrawal, historical rebinding, tamper/finite decoding, account
history locks, common reports/positions/reconciliation, workbook/source drill-down
and verified backup/restore. GUI verification includes explicit selection, no
automatic posting, preview, cancel/failure/stale clearing and whole-event history.
Focused and relevant integration checks, independent review and hooks gate closeout.

## Remaining work

Yamaha account-total register activity and remaining initial
runtime/frozen/platform gates. Keep unsupported history visibly unresolved. Human
UX and release acceptance remain their separate roadmap gates.
