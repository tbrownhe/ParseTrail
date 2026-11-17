# Fidelity retirement statement value review

Date: 2026-11-17. Roadmap IDs: V2-3/4/5/UX. Components: client core/desktop.
Authorization: owner reported Fidelity 401(k) summary rows blocked in cash Review
and confirmed the PDFs contain only summary totals. Implement the recommended
summary-focused review using existing source closing-value accounting.
Implementation: complete.
Automated verification: focused core/integration, native UI and affected regressions
passed; three unchanged report assertion failures reproduced on baseline separately.
Design verification: initial journey and actual integrated native screenshots reviewed;
all scoped design findings closed.
Independent review: financial/provenance, streaming validation and physical-profile
checks passed; no unresolved actionable findings.
Owner acceptance: pending for this change. Owner reports prior CAPONE/card workflows
are streamlined; that feedback is separate from this retirement workflow.
Release authorization: not requested.

## Scope and controlling decisions

Route Fidelity 401(k) statements into a dedicated summary Review showing the printed
period, beginning value, contribution/market/other component totals and ending value.
Record the exact evidenced closing through the existing source-value service. The
source components remain period summaries, with no invented individual dates,
payroll/bank counterparts, journal entries, transfers, categories or budget effects.
Market-value changes do not become spendable income. Capture and balance-check
qualifications remain distinct and supporting evidence discoverable.

Pending/completed review must distinguish statement-value work from activity posting.
Only an active exact source-backed value for the current bound section establishes
completion; an equal manual/other-source point or withdrawn/corrected-away value does
not. Date/amount conflicts remain visible. Keep original evidence unchanged, schema
27 and existing source-value correction/withdrawal/retry safeguards.

Initial scope is the finite Fidelity 401(k) summary family. No parser/declaration
change, per-contribution matching, securities/cost-basis accounting, unattended
value approval, other summary-family expansion or service changes are included.

Primary owns integration, user context, current contracts/planning and this record.
Ledger specialist owns the core read model, store integration and focused tests.
UI/UX establishes and rechecks the interaction design; desktop owns the integrated
view/routing/status and native tests. Independent integrity review covers source
proofs, completion, conflicts, history, exact values and no unintended money effects.
One writer per file; specialists do not commit or recursively delegate.

Only public source fixtures and newly disposable profiles may be used. Existing
owner test profiles, originals, archives, screenshots and logs remain untouched.
No private PDF is needed; the owner supplied the summary-only context.

## Result and review

Baseline: f3e7259. Investigation confirmed the parser already preserves observed
amounts/locations as `period_summary` at `statement_period_end`; cash Review routing
causes the misleading dead end. The existing Fidelity source-value rule records an
observed ending value/date without journals. Public parser checks (5 cases) and the
existing Fidelity source-value case passed during investigation.

Core adds an immutable statement-summary snapshot with exact source section/account,
money/date evidence, closing candidate/version/basis, physical profile identity,
history, conflicts and derived completion. Documents expose separate pending/reviewed
statement-value counts while activity-allocation counts keep their meaning. An active
exact source proof under the current binding and assessment is required; equal manual
or other-source values, withdrawn/corrected points and conflicts do not complete a
statement. Later-date values do not conflict with an earlier statement.

The existing source-value write has an optional physical-profile guard, checked before
historical retry and commit. Selected reads also capture/recheck physical identity.
No schema, declaration, parser, journal or budget policy changed. Saved-evidence reads
do not parse/decode PDFs. Original statement bytes and prior history remain unchanged.

GUI routes the finite Fidelity family to the embedded value bridge, with one explicit
record action, neutral completed history and a distinct nonposting completion event.
Source evidence, missing-account, conflict, stale, failed and withdrawn states have
recovery. Initial reference/reason are populated under details; blank edits show shared
required/valid cues and a visible explanation even while details are collapsed.
Successful initial completion can advance to the next pending document; unrelated
refresh/correction/report-return does not advance.

Value/history recovery retains the source date and relevant existing value ID. View
account value preserves the selected account and statement-end date in Reports, shows
the source value/date/origin visibly beside the separate journal position, and leaves
spending dates and budget month unchanged. Generic report defaults remain unchanged.

Independent review closed one retention concern: a naive snapshot-wide cache could
retain originals for all historical source points. The final inventory streams verified
sources with a fail-closed deferred source-proof protocol; every registered proof must
validate before return. Metadata/history/binding checks remain immediate. A selected
summary retains only its selected original; other proof sources load transiently.
Read epoch changes, unvalidated proofs, invalid sources, nesting and exceptions fail
closed and clear the context. Ordinary anchor reads retain immediate validation.

Design review closed two findings: misleading View spending routing and missing
required-field feedback. Primary screenshot inspection also found that the report's
default hidden value column concealed the handoff result; contextual visibility/order
now makes the recorded value directly visible without history/details/horizontal scroll.

## Verification

Root integration/regression (Windows locked source Python; isolated APPDATA/
LOCALAPPDATA, test HOME/USERPROFILE and null keyring):

```text
client/.venv/Scripts/python.exe -B -m pytest -q -o cache_dir=scratch/retirement-root-test/cache client/tests/test_v2_statement_summary_integration.py client/tests/test_v2_loan_automation.py client/tests/test_v2_loan_automation_integration.py
```

22 passed in 54.44 seconds, raw exit 0. New retirement integration uses a real public
synthetic PDF, then forbids parser/PDF worker calls while reviewing/recording, reading
Reports and withdrawing. Exact source/definition/evidence remain unchanged; source
value is known at its period end, absent before then, with zero journal, category,
budget or transfer effect and unknown journal opening. Value withdrawal returns the
summary to pending. Existing loan automation/refusal/history tests still pass.

After final streaming changes, the new root integration case passed again: 1 passed
in 4.03 seconds, raw exit 0. Changed root test passed Ruff check/format. Counts overlap;
do not add reruns as independent test totals.

Core specialist: 16 unique new cases passed across the focused suite and targeted
rechecks (15-case suite 31.63 seconds; read-time physical-profile replacement case
6.51 seconds). Final source-value/account-position regressions: 67 passed in 272.51
seconds. Document/accountless inventory and deferred-error checks: 28 passed in 176.32
seconds. All raw exits 0. Earlier synthetic shape setup was corrected because an
invalid activity/period-end pairing is refused by the evidence schema itself.

Independent integrity: 13 financial/provenance cases, 9 streaming/deferred-validation
cases and 1 read-identity case passed with raw exits 0. Covers exact/other-source/
manual values, conflicts, withdrawal/correction/retry, source-assessment changes,
zero closing, stale/failed writes, physical clones, parse-free reads, retained source
bytes and no journal/allocation/transfer/loan/budget effects. Protocol checks cover
unvalidated proofs preventing return, invalid other-source proofs, DML epoch changes,
nested refusal, cache release and ordinary immediate validation. Evidence under
`scratch/retirement-summary-integrity-20261117/`: `review.py`, `protocol.py`, successful
`run-*/summary.json`, `protocol-0ea13ffa/summary.json` and `identity-2f8168f1/summary.json`.
Intermediate negative-harness expectations were corrected when an earlier fail-closed
inventory error preceded the intended pending-proof check; no production check was
removed to accommodate the harness.

Desktop: 9 native Windows cases passed in 97.04 seconds, raw exit 0, plus targeted
final visible-value and required-field cases (1 passed in 4.88 seconds; 1 passed in
3.80 seconds). Actual 1050x700, 1100x650 and 1280x800 screens cover pending/recorded/
withdrawn values, original evidence, missing binding, historical conflict with later
points, failed reload, stale confirmation, confirmed-write close refusal, next-document
navigation, visible report value/date/account and unchanged budget/spending context.
Explicit destruction checks verify GUI-thread deletion and native invalidation;
normal GC remains enabled. Early harness API mistakes (missing date bounds and treating
synchronous anchors as job-based) were corrected before the complete successful run.

Existing anchors/source-value-dialog/core-journey/document-browser regressions:
45 passed in 103.29 seconds, raw exit 0. Additional report-position/dialog selection:
6 passed and 3 failed in 95.71 seconds. All three failures reproduced unchanged against
an isolated public Git archive of baseline f3e7259 (7.89 seconds, raw exit 1): old title
wording, a clearing amount formerly expected in the title instead of its detail field,
and a one-category count predating seeded zero-value Loan interest. Baseline source,
GUI and test bytes were checked against Git; no shared branch switch or assertion
weakening occurred. The first baseline archive lacked public devtools and failed
collection; the complete archive rerun established the baseline comparison. Evidence:
`scratch/retirement-summary-ui-20261117/baseline-report-regression.log`.

Actual native screenshots under `scratch/retirement-summary-ui-20261117/final/`,
`visible-value/` and `required-details/` were inspected by primary and independent
UI/UX. The final visible report is `visible-value/.../09f99452/07-statement-account-value-report.png`;
the missing-field cue is `required-details/.../c045b9e9/08-required-review-field-0.png`.
No significant scoped design finding remains. Screenshot/code and Qt software-event
checks do not establish independent live interaction, uncoached discovery, owner,
installed, other-platform, hardware-input or accessibility acceptance.

All changed Python files passed Ruff check/format and normal commit hooks. The first
core commit hook normalized mixed line endings; restaging and normal hooks passed.
Code commits: `eba3607` (core) and `173c408` (desktop).

## Fresh disposable owner test

Prepared `scratch/v2-owner-fresh-20261117-8ccd4d8d/Open-workflow-test.cmd` from code
revision `173c40872ed7579cb1360d6e4e3e618a2416aff4`: 316 pinned runtime files, unchanged
schema 27 and 23 public development declarations. No imported sources, financial
accounts, budgets, journals, transfers, loan events or tangible-asset values are
preloaded; only protected Loan interest is initialized. Preferences/catalog/app-home
are local to this new folder; the test signing key was discarded. Earlier populated
owner workspaces remain untouched. START-HERE explains the retirement summary journey
and the previous loan automation behavior.

```text
client/.venv/Scripts/python.exe -B -X utf8 scratch/v2-owner-fresh-20261117-8ccd4d8d/prepare_fresh.py
client/.venv/Scripts/python.exe -B -X utf8 scratch/v2-owner-fresh-20261117-8ccd4d8d/runtime/devtools/owner_fresh/fresh_launch.py --open scratch/v2-owner-fresh-20261117-8ccd4d8d --smoke
```

Both raw exits 0. Windows-plugin startup confirmed an empty Documents view, enabled
Import, six navigation entries and unchanged profile bytes; Qt exit 0. Startup smoke
hides its window, separately from the visible native UI checks. App left closed.
After owner import this new folder is private; preparation does not authorize later
inspection of its financial data.

## Remaining work

No scoped implementation or agent-review finding remains. The three baseline report
assertions above remain unchanged outside this packet. Owner use of this exact
candidate, wider native/platform/scaling/accessibility/installed validation and
release authorization remain separate. No production publication or daily-profile
activation is authorized.
