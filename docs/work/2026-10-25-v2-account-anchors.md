# Review account openings, dated values and closure metadata

Date: 2026-10-25. Roadmap IDs: V2-4/5, DEC-1.
Authorization: approved roadmap, resolved DEC-1 and continued development.
Implementation: complete.
Automated verification: broad V2 integration and final focused controller/label checks passed.
Independent review: financial/persistence and GUI/report review complete; anti-plug finding resolved.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Complete explicit opening withdrawal so an invalid source assignment can be
corrected after its active money is retired. Preserve each prior decision and an
exact original-date inverse, including the distinction between a withdrawn/
unknown opening and a reviewed zero opening. Withdrawal must work when the
current source basis is unavailable, without requiring a replacement source or
inventing zero. Re-establish an opening only through a fresh explicit review.
Support corrections, stale forms, idempotent retry, rollback and retained history.

Implement DEC-1 source-independent reviewed openings and separate reviewed dated
values. Owner use cases are missing new-loan opening information and missing
final statements on recently closed loans. No arbitrary manual journals. A manual
opening uses exact typed amount/date, explicit financial kind/tracking scope,
reference and reason, and opening equity rather than income/expense. It must not
skip earlier known account activity or become a later unexplained balancing plug.
Natural liability display means positive owed; preserve exact stored debit signs.

Dated values are nonposting observations with explicit manual origin, date,
scope, reference, reason and correction history. They do not fill spending
history, establish a settlement, replace an opening or silently override journal
positions. A final manual zero value leaves residual books visible. Account
closure/stopping-tracking metadata retains its date/reason/history and never
zeros postings or hides an unexplained residual. Show books and dated values as
distinct qualified facts in account review/positions.

Introduce reviewed account tracking scope so account-total, principal-component
and cash-component values cannot silently be mixed. Establish scope before it
authorizes interpretations; existing reviewed history cannot be reinterpreted by
an ordinary metadata edit. Source-value adapters and loan/HSA/investment posting
remain later packets. Do not infer source sign normalization from positive raw
balances. No source-evidence or legacy-parser changes in this packet.

Ledger owns the store/schema/common-read implementation and focused service
tests. Desktop owns opening/account-value/lifecycle adapters and focused GUI
tests. Primary owns shared docs, workspace account/scope/menu wiring and report
integration; agree exact snapshot/model APIs before dependent edits. Independent
integrity review is required. Earlier disposable schema
revisions are recreated without migration; private/1.x inputs remain untouched.
No recursive delegation, daily-profile activation or release action.

Manual openings are independent reviewed facts; adding a source must not turn
their origin into printed evidence or certify missing history. Current source
bindings/reviews only block correction when an active source-backed opening
depends on them; withdrawn history and independent manual openings do not create
a false source-anchor lock. Keep all closed accounts and residual/unknown books
visible. Values never silently supply a missing opening. Source/manual opening
switches require explicit current-version review and fresh identities.

Manual anti-plug bounds distinguish intervals/activity from point facts. A cutoff
must be before actual known activity/active non-opening journal dates and known
observed/derived statement starts. When no statement start is known, its known
end is a point; current non-superseded dated values and corrected lifecycle phase
dates are points too. A cutoff may equal the first point but cannot follow it.
This avoids forcing an invented prior-day value. Superseded wrong dates and
creation timestamps do not establish current account history; assumed posting
guesses do not become observed source activity. New earlier history makes a
manual opening stale under the same rules. Keep actual earliest activity separate
from earliest known history in the UI. No Wells period start is invented.

## Preparation evidence

The evidence specialist reviewed public synthetic source shapes and ten actual
bounded decodes, with 78 existing source/kernel checks passing in 13.55 seconds
on Windows AMD64/Python 3.13.15. Capital One/MOHELA gross payments and principal
allocations differ in amount/sign from principal-only ledger movement. Wells
retains separate principal/interest rows and unknown period start; its parser
deferral remains. Yamaha has account-total liability signs but no component
breakdown. HealthEquity is cash-component evidence; Fidelity HSA and retirement
summaries are noncash account-value evidence. These findings justify explicit
scope and provenance boundaries; they do not admit new accounting operations.

## Result and review

Schema 17 extends authoritative account tracking scope and the existing immutable
opening decision/revision chain with source/manual origin, active/withdrawn state,
reference and persisted full-context versions. Withdrawal retires exact nonzero
opening money at its original date; zero withdrawal has no journal. Fresh review
has a new identity and retains all history. Exact historical withdrawal retries
return the stored receipt and do not touch a newly established opening.

`AccountDatedValues` retains nonposting manual amount/date/scope/reference/reason
and correction links; `AccountLifecycleDecisions` retains closure/reopen phases
and corrections. Values and lifecycle changes create no journal or allocation.
All relevant authored inputs enter reconciliation versions and common read/backup
validation. Account scope is explicit and kind-compatible, with one shared
history-lock policy for API and UI; existing source operations remain gated to
their admitted account-total scope. Manual/source switching is explicitly
reviewed, not a parser output or automatic source correction.

Desktop adds `V2AccountAnchors(profile, account_id=None, parent=None)` with
Opening, Dated values and Tracking closure tabs. The source opening adapter
retains source assertion review and adds withdrawal/current state/history.
Primary wires account creation/edit scope, Accounts-menu navigation and selected
position review. Positions append scope/origin/value/lifecycle columns while
preserving existing monetary columns. Manual zero values remain separate from
residual books; closed metadata exposes recorded residuals and opening-based
unknowns with an explicit as-of date. Non-account-total labels identify the
component scope and still distinguish duplicate account identities.

Independent review found an empty statement's known interval was absent from the
manual anti-plug guard: after withdrawing its opening, a later manual opening
could act as a balancing adjustment. The bounded history rules above are now
implemented by one shared creation/staleness predicate and independently checked.
This is an engineering
application of the existing no-later-plug contract, not a new owner decision.

## Verification

Test nonzero/zero/stale/unavailable opening withdrawal, fresh re-establishment,
old-date inverses, manual loan owed/asset signs, no earlier-activity bypass,
source/manual switching with explicit correction, version conflicts/idempotence,
failed writes, immutable value/lifecycle corrections, final zero without fake
settlement, closed residual visibility, tracking scope locks, common report/
reconciliation versions, backup/reopen and malformed stored history. Verify
functional GUI states and meaningful synthetic end-to-end examples, then focused
and V2 integration, Ruff/hooks and independent financial/persistence review.

Preliminary Windows 11 AMD64/Python 3.13.15/Qt offscreen checks: 33 new service
cases passed in 24.07 seconds; an opening/positions/common-integrity/retirement
run passed 85 in 68.30 seconds; profile/binding/reconciliation/source repair/
transfer checks passed 125 in 94.25 seconds. Desktop opening/anchors checks passed
31 in 29.52 seconds. Primary window/position integration passed three in 2.18
seconds. Independent GUI/report review passed 59 checks across two runs (43 in
31.03 seconds, 16 in 12.59 seconds), with readable temporary Segoe UI rendering
at 1080-by-740 and 1180-by-780. These precede final anti-plug tightening.

Independent service review passed an initial 99 checks in 80.06 seconds and
additional WAL/version and lifecycle-phase/date-correction probes. Valid-scope
overwrites of mutable account metadata were independently refused by common
reads/reconciliation/backup when source journal or transfer review history
assumed account-total scope. No partial backup was published. Final affected and
V2 integration, Ruff/hooks and review resolution remain before closeout.

Final financial verification: 142 service checks passed in 130.66 seconds before
the last lifecycle-input clarity branch. Invalid new phase dates now refuse with
`account_lifecycle_date_order` before insertion; saved-history corruption retains
its integrity refusal. Seven focused lifecycle cases passed afterward (5.44
seconds); the independent rerun passed seven in 5.39 seconds. Independent final
opening/positions/reconciliation/common-integrity checks passed 111 in 107.16
seconds. Empty known intervals, inclusive endpoint/value/lifecycle points,
corrected wrong dates, later history arrival and actual card transaction dates
versus assumed posting guesses were independently exercised without findings.

Final GUI/source opening checks passed 35 in 26.68 seconds, plus five affected
cases after clearing stale boundary tooltips (4.16 seconds). Independent GUI
refinement recheck passed five in 6.36 seconds. Date-order input guidance remains
separate from damaged saved history; the UI displays service-provided boundaries
without inventing its own policy.

The broad final V2 run passed 574 checks, 1,107 deselected in 395.60 seconds.
Afterward, display-only tracking-scope identity was made consistent across source,
accountless and correction binding choices/history, plus the workspace edit
choice. Same-name/same-number total/component accounts retain correct stable IDs.
Six new regressions plus existing binding/adapters passed 45 in 33.66 seconds;
workspace/controller checks passed 13 in 8.30 seconds. Independent final label/
controller review passed all ten focused cases in 7.21 seconds. No financial or
service semantics changed after the broad run. This distinguishes the broad run
from subsequent focused verification rather than claiming one later green run.

Changed-file Ruff check/format, whitespace, local links and repository hooks
passed after normalizing line endings in the store and new service test.
Human/native/Intel/installed acceptance and release actions were not performed.

## Remaining work

Refund/negative-income, fees/partial settlement and admitted loan/HSA/source-value
workflows, then integrated UX/runtime/platform/release gates.
