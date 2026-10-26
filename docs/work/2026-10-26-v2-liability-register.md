# Review account-total loan-register activity

Date: 2026-10-26. Roadmap IDs: V2-4/5, CF2.
Authorization: continuing approved initial V2/P2 development.
Implementation: complete against review-tooling baseline `65a413e`.
Automated verification: focused and broad V2 boundary checks passed.
Independent review: complete; no actionable financial/provenance/persistence findings.
Owner acceptance: pending final integrated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Admit the finite `pdf_yamahafin_202306` source only for account-total liability
register review. Preserve source transaction and posting dates independently,
including dates derived from printed month/day and statement-year context.
Reuse exact ordinary liability/category posting, purpose/class correction,
withdrawal/repost and reviewed occurrence safeguards through an explicit register
API/UI policy. A register financial movement is the whole liability effect; it is
not principal, and no principal/interest breakdown or loan-interest category is
invented. Keep this source outside the printed principal-component loan workflow.

Use neutral `liability payment` terminology consistently for owned account-total
liability receipts, including cards and the Yamaha register. Friendly UI can say
card and loan-register repayments. This is an accounting-shape label, not a new
financial-account subtype or a claim that the whole payment is principal. Keep
existing printed-component `LoanEvents` separate. Preserve whole transfer/partial
settlement corrections, source dates, exact fees and unresolved clearing.

Synthetic example (minor units): source opening -100000, purchase -1000 on
February 7 (transaction February 5), payment +2000 on February 10 (transaction
February 9), closing -99000. Explicit reviewed purchase expense is 1000. A
selected observed bank outflow -2000 pairs with the liability receipt and creates
no second expense; clearing retains its amount between the two posting dates.
Unknown principal/interest stays unknown. Source endpoints, capture and reviewed
books remain distinct; reconciliation needs its ordinary scope/timing/source-use
requirements. No date assumption is needed for observed posting dates.

Evolve the pre-release format if stored payment-kind semantics change; recreate
disposable pilots rather than add aliases/migration. Preserve separate card APIs
and source gates while sharing mechanics; a register API must not silently admit
principal-component loans or arbitrary liability sources. Register category
correction retains the source posting date and purpose/class. Positive row purpose
is explicitly reviewed, never automatically inferred from sign or description.

Ownership: `positions_service` exclusively owns the store, shared pure transfer/
settlement payment-kind policy, narrow legacy shared-transfer callsite and financial
tests. `positions_desktop` owns register review, shared liability dialog adaptation,
transfer/settlement wording and workspace entry, with interaction tests.
Primary owns report/export integration, shared contracts/record and integration.
Independent integrity review covers source admission, exact liability signs,
full allocation, repayment no-double-expense, correction/history and failure paths.
No recursive delegation. Public synthetic/
disposable data only; no parser changes, private/live/1.x profile mutation,
production signing, installation or release actions.

## Result and review

Read-only investigation found the existing observed component-free liability
category machinery fits Yamaha; finite source admission and truthful UI/domain
labels were missing. Adding the parser only to the card family would mislabel the
loan as a card. Neutral payment terminology and an explicit register wrapper avoid
new unsupported principal/interest semantics or invented account subtype metadata.

Schema 22 admits the neutral stored payment kind; the profile table layout and
reconciliation rule 6 are unchanged. Older disposable profiles are refused before
writes. `v2_liability_register.py` owns the finite policy and typed review row,
including both dates/provenance and actual financial ID/kind/scope. Public
post/correct APIs reuse private ordinary liability mechanics while retaining
separate card/register source gates and a required register purpose. Source
posting dates are fixed; they may be observed or derived from printed context,
with no assumed-date requirement. The new namespace participates in initial/
corrected history validation, ordinary withdrawal/repost and posted-repeat repair.

Pure transfer, whole pair and settlement domain kinds are neutral liability
payments. Cash classification uses `liability_payment` for card and whole-register
repayments; printed-component loan events keep their separate principal/interest
cash purposes. The full register effect never becomes a principal estimate.
Workspace/transfer/settlement/cash wording includes the newly supported scope.
The shared card dialog has an explicit register adapter and a thin source-specific
wrapper. The selected-source Review action is enabled only for Yamaha and guarded
during imports. Read-only source dates, both-date provenance, explicit purposes,
plain text/IDs and source previews remain visible. Cancel/stale/read failure
clears stale posting controls; ordinary correction/withdrawal retains history.

No automatic interest category or component event is created by a purchase or
repayment. Users may still explicitly select an authored expense category,
including built-in Loan interest, under the ordinary category contract; this does
not rewrite source evidence or invent a printed component. Two isolated legacy
shared-kind consumers needed narrow marker/display updates; no legacy data/runtime
activation or broader refactor occurred. Independent review found only friendly
entrypoint wording omissions, corrected by the assigned GUI owners.

## Verification

Platform: Windows 11 AMD64, Python 3.13.15; Qt offscreen. Commands use
`PYTHONPATH=.;client/src;client`, `QT_QPA_PLATFORM=offscreen` and
`client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider ... -q --tb=short`.

- Service register/loan/transfer-correction pass: **94 passed in 102.86s**, including
  **18 new** register checks. Actual public synthetic PDF passes bounded parsing,
  exact source opening/charge/repayment/closing, no automatic interest/components,
  fixed date correction, explicit positive purpose, full repair/history, rollback,
  persisted amount/date corruption refusal, old-schema refusal and verified backup.
- Earlier adjoining seven-module pass: **121 passed, 2 failed in 135.52s**. Both
  failures were a legacy GUI's old card-kind display/search mapping after the
  shared neutral-domain change. The narrow mapping/search fixes passed the full
  `test_ledger_transfers.py`: **19 passed in 10.72s**. No money change was required;
  the earlier invocation is not represented as fully green.
- Final register/card/category-purpose/transfer-correction/settlement GUI pass:
  **56 passed in 71.34s**, including **12 new** actual-service cases. Source and
  preview layouts inspected with Segoe UI at 1200x650 (minimum 432x390); actual
  financial context, both dates, fixed posting date and unknown components readable.
- Primary register/cash/settlement-cash integration: **21 passed in 26.55s**,
  including **2 new** actual-source cases. Verify expense 1000 versus cash -2000,
  liability -101000 then -99000, clearing 2000 then zero, nonposting whole-liability
  source value, no derived principal or automatic interest category, exact raw
  workbook allocations, generic withdrawal/fresh whole pair and verified restore.
  Whole-pair export keeps its existing raw-allocation contract; optional advanced
  settlement metadata does not add retired history to active money.
- Independent eight-module review: **141 passed in 194.99s**, covering new service,
  GUI/integration, existing card/transfer/settlement/pure transfer and common journal
  integrity. No actionable financial/provenance/persistence findings. Additional
  actual two-PDF correction/repeat-repair/withdraw/fresh-purpose/historical-retry/
  reviewed-binding-correction probes preserved old account history and exact
  February 7 posting dates, with one active raw allocation and verified backup.
  Capture warning remained separate from successful register reconciliation.
- Broad command `client/tests -k v2`: **904 passed, 1107 deselected in 859.50s**.
  Financial/service/GUI code was frozen; later changes only clarified entrypoint
  wording. Ruff and repository hooks passed after line-ending normalization only;
  local-link and Git whitespace checks passed.

All data/profiles were synthetic/disposable. No parser behavior changed; no
private-source parity, owner/native/Intel/installed acceptance or release is claimed.

## Remaining work

Final default V2 startup/offline diagnostics, frozen candidate and available
platform verification. Retain external/native owner and signing/release gates.
