# Import review follow-up and batch safety

Date: 2026-11-18. Roadmap scope: V2-3/4/UX. Baseline: `32e365c`.
Implementation: clear fixes complete; larger recovery/progress choices remain for
discussion. Automated/native verification and independent review passed as below.
Owner acceptance: owner reports previous OCCU batch fix works; this pass is not yet
owner accepted. Publication/release/daily-profile activation: not requested.

## Scope and decisions

The owner requests clear fixes followed by discussion of unresolved design choices:
CITIAA/CITISIMP remaining monetary source roles, accidental Skip during repeated
batch confirmations, recovery from serious extraction warnings, remaining Fidelity
HSA tails, stale reused batch preview/progress presentation, valid empty HealthEquity
cash statements, replacement USBREI card identities on one ledger account, Vanguard
additional summary columns and Wells business checking defaults/post-table content.

Keep exact original bytes, parser evidence, observed/derived dates, signs, values
and locations immutable. Resolve proven source roles rather than suppressing unknown
money/date warnings. Any optional period/YTD/chart/inclusive value columns remain
distinct from the primary closing. Valid empty-account evidence must be finite and
retain capture/coverage qualifications. No invented transactions or balancing money.

Clear UI fixes prevent accidental Skip and stale source display. Agree a concise
batch journey before implementing significant interaction changes. Unmodified letter
shortcuts must not steal input from account editors. Editable extracted values and
a larger recovery/progress redesign are discussion items, not automatic permission
to mutate evidence or implement new accounting policy.

Ownership: primary integrates UI, shared warning projection, Wells account-context
defaults, account-identity model investigation, contracts/planning and this record.
Evidence specialists own disjoint Citi/Wells and summary/HSA parsers/tests; UI/UX
reviews the batch journey. Independent integrity reviews material evidence/context
changes. No specialist commits or recursively delegates; no concurrent shared-file
writers. Keep the existing checkout branch.

Allowed data: public invented sources/disposable profiles and the task-named local
PDF families in the previously authorized SUCCESS folder, read-only and in memory
for focused diagnosis/parity. No private source/text/evidence copies, profiles,
screenshots or routine logs from originals. All populated owner test workspaces,
including the newly handed-off `v2-owner-fresh-20261118-c542c241`, are off limits.
No root .env, production service, private signing keys, publication or live mutation.

## Verification criteria

Check positive and boundary-negative parser examples, exact original financial
facts, warning classifications and retained qualifications. Test account defaults
only with authenticated compatible source context. Verify many source identities
can bind one compatible account without inventing identity continuity or mixing
independent obligations. Exercise native repeated batch choices, editor keyboard
input, skip/cancel behavior, current-source previews and GUI-thread cleanup/shutdown.
Use the locked client environment with isolated APPDATA/LOCALAPPDATA and null keyring.

## Result

1. Citi AA's named example retains 57 activity rows with zero unresolved monetary
   lines. The Simplicity example retains its three activity rows; ten unknown lines
   reduce to one unlabelled amount at page 1, line 40. That genuine source-role
   ambiguity remains reviewable. Exact finite legal/repayment and matching benefit-
   savings structures become context, not new activity. Unsupported optional sidebar
   amounts retain their unknown lines instead of refusing the whole import.
2. Shared primary Next/Import and retained Back slots prevent Skip moving into a
   previous Import position; Skip stays beside Cancel. Alt+N/I/B/S/O work from
   editors while ordinary typing and Enter retain their input behavior.
3. Guidance now explains comparing the original, retaining source warnings and no
   transaction posting. Evidence cells remain read-only. Repair choices below remain
   separate from the current import confirmation.
4. Fidelity's combined contact heading/explanatory note is a finite context role.
   Unexplained monetary/date suffixes still require review.
5. A neutral pending state immediately hides prior rows/accounts/warnings/preferences
   during Import/Skip/next-file reading and restores the current request afterward.
   This removes stale source presentation. It does not implement the proposed compact
   progress handoff across all batch phases.
6. Valid empty HealthEquity cash tables can skip preview under the audited proof and
   exterior-audit policy. A full rate/fee frame is required for detached totals;
   current nonzero fees and unknown monetary/date content remain reviewable. Source
   capture stays unverified. No financial movement is invented.
7. Owner acceptance of the prior OCCU first-use batch fix is recorded in this pass;
   no new OCCU production change was necessary.
8. Five public synthetic replacement identities successfully bind one financial
   account after explicit choices, retain separate source facts and do not mutate its
   stored full number or post journals. An unseen replacement number is not inferred
   merely because another card at the institution already exists.
9. Vanguard's labelled current-period/YTD columns remain separate located evidence.
   Primary values, period-summary roles and source closing are unchanged; the shared
   Fidelity plan-label engine and complete synthetic envelopes remain pinned.
10. Wells' 42 activity rows and all 30 footer occurrences remain retained; verified
    totals, explanations and finite fee tables no longer require review. Its located
    printed product heading supplies checking/savings defaults and the ordinary
    nickname suggestion. The route supports both products, so filename/parser ID
    alone never supplies the product. Missing/conflicting proof stays undecided.

Independent review found and closed empty-HSA unframed-total and named-date holes,
a header-normalization false review, and optional Citi amount conversion refusal.
Independent UX review found repeated Enter could reach Cancel immediately after
Import; pending now focuses a neutral accessible page. Repeated Enter is inert;
Tab followed by Enter still deliberately cancels.

## Verification

- Evidence specialists replayed the exact task-named originals read-only in memory.
  The nine summary/HSA examples preserve account/endpoints/period/row values, dates,
  roles, raw amounts, locations and provenance; engine-bound row IDs and dispositions
  intentionally differ. Citi/Wells original hashes remain unchanged. No originals,
  private extracted evidence or owner-profile copies were persisted.
- Summary/HSA initial affected run: 186 passed and two baseline assertions failed.
  Those failures also reproduce using all four baseline parser modules: they assumed
  the seeded Loan interest category did not exist. The test now snapshots the exact
  Accounts table before a failed write and requires it unchanged afterward; both
  corrected atomic cases pass. Latest summary/HSA boundary checks: 82 passed.
- Citi/Wells/client integration: 168 passed; signed admission checks and cancellation/
  truncation checks passed separately. A pytest cache permission warning was observed
  in one specialist run; no data or assertion failure followed. Later Citi converter/
  warning checks: 121 passed.
- Root Wells defaults: nine passed, including native 1050x700 account creation with
  suggested nickname/read-only identified product. Five replacement-card identities:
  one focused multi-source persistence/matching test passed.
- Desktop native combined regression: 26 passed; five focused checks passed after a
  styled-width correction. Root's six final native queue tests pass after the pending
  focus fix, including repeated clicks/Enter, Alt/editor input, restored current
  content, cancel retaining a committed import, GUI-thread destruction/invalidation
  and normal process exit. Normal GC remained enabled.
- Independent integrity: 304 focused checks passed, followed by 196 stable boundary
  checks after final fixes, raw exits 0. Direct counterexamples verify unknown money/
  dates remain reviewable and conflicting Wells product hints stay undecided.
- Independent UI/UX inspected actual Windows screenshots at 1050x700 and 1100x650,
  then reproduced and rechecked the keyboard finding with native software events,
  raw exit 0. No significant finding remains within the small-fix scope. Public
  screenshots: `scratch/import-review-ui-followup-final-sized`,
  `scratch/import-review-keyboard-final` and `scratch/wells-defaults-ui-20261118`.

Final integrated native journey/defaults/queue run: 19 passed in 36.12 seconds, raw
exit 0, including the full import/review/report/correction/recovery subprocess
journeys. Changed-file Ruff check/format and code commit hooks pass. Windows source
runtime uses locked Python 3.13.15 / Qt 6.11.2, Segoe UI 9pt at 100% scaling. These
checks do not establish human comprehension, owner acceptance, other platforms/
scaling, installed behavior or release authorization.

## Options for discussion

For serious source problems, keep extraction immutable. Current safe choices are to
repair an account choice with Back, compare the original and retain a qualified
source, or skip a wrongly extracted file and retry a supported export/updated format.
Editable preview cells cannot repair omitted source content. A future source-issue
workflow could show the exact offending text/page and support an explicit reparse
comparison. Authored amount corrections are a separate audited interpretation with
original/replacement, reason, confirmation and dependent posting/history effects;
they should not silently overwrite parser evidence.

For batch progress, recommend one compact progress surface between decisions, opening
the larger account/review dialog only when user input is required, and one final
per-file results report. Cancellation must continue to preserve confirmed imports.
This requires deliberate modal/lifetime/signal-order integration; the neutral pending
state is the completed immediate fix, not a claim that this larger redesign is done.

For replacement card numbers, one financial account is appropriate when the statements
represent the same continuing obligation. The printed identities remain distinct.
Independent simultaneous debts/accounts, or a real transfer to another institution,
should retain separate financial accounts and evidenced transfer treatment. Number
changes alone do not establish a money movement or accounting continuity; source
overlap and repeated-transaction review remain separate.

## Commits and disposable test

Code commits: `58035ef` parser/source roles and warning guards; `c693fab` printed
Wells defaults and replacement identity verification; `f9a1202` stable batch actions
and pending state. Contracts/planning/this record form a separate closeout commit.

Prepared `scratch/v2-owner-fresh-20261118-8c4007b4`, pinned to `f9a1202`, schema 27,
23 development-catalog definitions and 319 hash-pinned public runtime files. It
contains no financial accounts, sources, budgets, journal entries or transfer events;
the built-in Loan interest category is present. Test signing authority was ephemeral
and discarded. Only public helper code was reused; populated candidate data was not
read or copied.

The first pin attempt refused a helper CRLF/LF mismatch before creating a runnable
manifest. That unhanded candidate was verified empty and regenerated with normalized
helper bytes; final preparation and native startup passed. Startup reports ready,
empty documents, import enabled, unchanged profile hash and raw Qt/process exit 0.
`Open-workflow-test.cmd` and concise `START-HERE.txt` are ready for owner testing.
No populated owner workspace was rebuilt or modified. After owner import, this new
candidate is private and outside further inspection without appropriate scope.
