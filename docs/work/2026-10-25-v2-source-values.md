# Review source closing values without manufacturing journal balances

Date: 2026-10-25. Roadmap IDs: V2-4/5, P2-4.
Authorization: approved roadmap and continued initial V2/P2 development.
Implementation: complete after settlement closeout (`506978a`); schema 19.
Automated verification: 760 V2 checks plus final affected GUI checks passed.
Independent review: accounting/provenance/persistence and functional GUI/report
review complete; no actionable findings remain.
Owner acceptance: pending consolidated V2-UX.
Release authorization: not authorized.

## Scope and controlling decisions

Admit explicit review of finite supported statement closing values as nonposting
dated account facts. Preserve the exact raw amount, source locations/provenance,
statement end date, parser/revision and authored source-review annotations.
Financial kind and tracking scope must match a code-owned family rule. A value
never supplies missing activity, creates cash/income/gains, fills an opening,
asserts settlement or zeros a closed account. Total/component values never sum
automatically into certified net worth.

Extend the existing AccountDatedValues history rather than a second value store.
Source/manual origins remain explicit; source review accepts no arbitrary amount
or date override. Add append-only withdrawal so a wrong manual/source point can
be retired to unknown instead of corrected to an invented zero. Withdrawn and
superseded points do not constrain opening dates or become current values; exact
historical retries cannot retire a fresh decision. Different current values at
one date require an explicit conflict/correction/withdrawal choice, not latest
import/ID ordering.

Use typed finite source proof and immutable withdrawal history, evolving the
pre-release schema and recreating disposable profiles. Current active source
values protect their exact source/section binding until withdrawal (including
empty sections); retired history retains its original account after a reviewed
reassignment. Manual values remain independent. Common reads and verified backup
validate original proofs and history without requiring old bindings to stay current.

Candidate discovery uses an explicit parser/family, kind, scope and sign whitelist.
Capital One auto-loan closing principal is positive owed and needs the finite
negative debit conversion; Wells Fargo loan principal is already debit signed
and must not be inverted again. HSA cash-component closings require matching
asset cash-component tracking; HSA/retirement total values require account-total
tracking. Banks/cards/Yamaha require their admitted exact conventions. Unknown
or assumed endpoints/dates stay unavailable. This packet does not admit activity-
export/MOHELA running principal as a statement endpoint or loan postings.

Printed/observed and finite source-derived values retain distinct labels.
StatementSourceReview origin/timing assertions remain separate authored facts;
do not silently mark a parsed value reported or complete. Full capture, source
arithmetic, live reconciliation and complete activity are independent qualifications,
not blanket blockers for recording a nonposting source value.

`category_service` (ledger) owns the store, new pure source-value module and
service tests. `positions_desktop` owns the account-value dialog and focused
interaction checks. The primary owns shared contracts, workspace/report/export
integration and cross-layer tests; `positions_integrity` reviews accounting,
provenance and persistence independently. Agree the narrow APIs before dependent
edits and keep one writer per file. Synthetic/disposable data only; no private,
1.x, daily-profile or release mutations.

## Result and review

Read-only design advice identified source-proof origin/withdrawal, exact binding
anchors, same-date conflicts, opposite loan sign conventions and component double
counting as the main risks. The store now uses schema 19, typed source proofs in
the existing value table, immutable withdrawals and explicit conflict acknowledgement.
No source amount/date override is accepted. Latest-date disagreements produce a
conflict and no selected point; equal current amounts are retained without summing.
Manual correction stays manual, while source review recomputes its proof.

Positions expose point status separately from the books and show extracted versus
normalized debit amounts, rule meaning and retained review-context qualifiers.
Source values have direct account/selected-position navigation. Conditional workbook
metadata retains values, withdrawals, source proofs and exact locations; no source
point appears as a journal/posting/allocation row. Source/manual zero and unknown
remain distinct, including a historical withdrawal retry after a fresh zero point.

Independent review found that the earlier account/file source-review key could
project an A-section qualification onto B after simultaneous or sequential account
assignment changes. Schema 19 now records the reviewed section identity/form and
keeps historical assertions separate from current exact-section applicability.
An actual stale unreviewed A form could also save B's qualification and permit an
opening, because both expected revision IDs were absent. The write APIs now check
the loaded section/basis under the write lock, and the desktop uses coherent loaded
review snapshots. Final affected verification passed. No parser/source
facts or accounting product policy changed to resolve these provenance failures.

Final review also resolved controlled missing-account/malformed source-review
metadata refusal, displayed the actual conflict point date at a later report cutoff,
and changed opening-boundary wording to describe reviewed values without falsely
calling source points manual. Original source proof, exact section anchors and zero
versus unknown remain preserved. Source-review changes are informational qualifiers
on retained nonposting facts; they do not rewrite the point or post adjustments.

## Verification

Use synthetic immutable sources for each admitted rule, exact sign/date/scope and
origin qualifiers. Check unknown/derived endpoints, no journals, read-only discovery,
review/correction/withdrawal/retry, stale forms/assertions, same-date conflicts,
whole/file/row binding changes, retired proof preservation, opening-point bounds,
positions display, export/backup/reopen and controlled malformed-proof refusal.
Focused plus relevant integration, independent review, functional GUI error/cancel
checks, offscreen inspection and repository hooks are required.

Windows 11 AMD64, Python 3.13.15, Qt offscreen; synthetic/disposable inputs only.
Use `PYTHONPATH=.;client/src;client`, `QT_QPA_PLATFORM=offscreen` and
`client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider ... -q`.

- Primary first three source-value/report/export/recovery cases: **3 passed in
  2.78s**. Expanded five cases including actual positions/conflict/selected-source
  navigation and workspace/import guard: **5 passed in 4.85s**. The source-value,
  prior anchor integration, report dialog and workbook suite passed **14 in 10.81s**.
  Module: `client/tests/test_v2_source_value_integration.py`.
- Final service source/anchors/binding/opening/reconciliation suite: **164 passed
  in 131.43s**, including **57** new source-value/family/proof/withdrawal/conflict/
  scoped-review cases. Earlier 40 anchors passed in 29.61s and 41 source-value
  cases passed in 35.94s before final provenance guards.
- Independent actual bounded-parser check covered all **21 statement families /
  22 sections**, preserving exact source amounts/dates/scopes/locations against the
  prior independent family baseline. Two MOHELA activity exports remain outside the
  endpoint domain. This is parser-fact/pure-rule evidence, not signed/frozen/private
  source or accounting acceptance.
- Independent actual scoped-review regression preserves A's old proof after
  withdrawal and reassignment, gives B no inherited qualification, refuses the
  unreviewed B opening with no journals, and preserves a fresh A point after an
  old withdrawal retry through backup/reopen. Both frozen old-form GUI repros warn,
  create no B qualification, block B opening and leave zero journal entries.
- Final independent source/integration/source-review/opening/reconciliation/common
  journal/export suite: **131 passed in 117.65s**; source-value GUI module
  **15 passed in 31.59s**. Independent actual empty Wells statement with printed
  zero remained known/nonposting, protected an empty section, became missing after
  withdrawal, and a fresh zero survived the old withdrawal retry and backup.
- Desktop final four-module GUI suite: **49 passed in 61.48s**, followed by **34
  passed in 47.38s** covering the final source/manual boundary wording. Independent
  GUI/report/export suite **40 passed in 58.10s**, then **8 final affected cases
  passed in 16.09s**. Source/history layouts were readable with explicitly loaded
  Segoe UI at 1080x790; this is Qt offscreen evidence, not owner native acceptance.
- Broad V2 suite: **760 passed, 1,107 deselected in 623.03s** using
  `client/tests -k v2 -q --tb=short`. It began before the final neutral boundary
  wording; the focused final source/manual checks above cover that display change.
  Final financial/provenance core was frozen for this run.
- Changed-file Ruff/format, `git diff --check`, documentation link checks and
  repository hooks passed (one test's mixed line endings were normalized). No private/live/1.x writes, production signing,
  installation, Intel/native or owner acceptance was performed.

## Remaining work

Supported loan/HSA accounting and source-use/component proofs, report integration,
then integrated UX/runtime/platform/release gates. Preserve the Wells Fargo parser-
change deferral and incomplete-history disclosure; no historical reconstruction gate.
