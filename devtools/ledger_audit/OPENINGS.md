# Opening-position readiness and review

This read-only service follows the accepted transfer workflow. It inspects the
immutable [fresh rebuild](REBUILD.md) and [cash/card candidate plan](PROPOSALS.md),
not the disposable GUI test decisions or the live profile.

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/openings.py `
  --rebuild <verified-rebuild-directory> --candidates <verified-candidate-directory> `
  --output <new-private-output-directory>
```

The output must not exist. The command verifies plan/database/retained-source
checksums, rejects database sidecars, verifies the candidate-to-rebuild binding,
checks deterministic replay and rechecks all input hashes before publishing its
completion report. It never opens a database for writing or changes accepted files.
Private filenames, dates, balances, account names and source hashes stay in ignored
`readiness.json` and `report.json` artifacts.

## Opening candidates

For each scoped checking/savings/card account, the audit gathers **all** statements
with the earliest source period start. It retains their filenames, parser manifest,
source balances, original provenance and kernel eligibility. It never skips a failed
earliest statement to use a more convenient later opening. Conflicting earliest
balances yield no proposed amount. Missing statements, earlier unmatched movements,
incomplete source replay and unavailable kernel statements remain explicit blockers.

An agreed earliest opening amount retains its exact sign. A conditional cutoff is
shown immediately before the earliest inclusive statement period, according to the
kernel convention. This is a proposal requiring source timing verification, not an
assertion of when the real account opened. A nonzero liability opening is neither
income nor spending; eventual posting must use opening equity. A zero opening needs
no zero-valued journal but still needs provenance and timing review.

Every candidate remains unreviewed and unposted. The service deliberately keeps
`ready_for_opening_posting` and `ready_for_cutover` false. It does not upgrade
`assumed` endpoints just because a parser succeeded or adjacent amounts agree.
No opening-entry controls are exposed by this audit.

## Continuity and limitations

An interval sweep compares each next statement against the furthest covered prior
endpoint. Nested periods cannot manufacture false gaps. Multiple statements ending
at the same frontier all participate, so conflicting closing balances cannot be
resolved by arbitrary row order. Results distinguish adjacent agreements, adjacent
balance differences, coverage gaps, overlapping periods and conflicting prior
closings. Agreement is an exact comparison of parser output, not independent
statement reconciliation.

A gap records its inclusive missing dates and uncovered-day count. Equal balances
on either side still leave a coverage gap. A changed balance across a gap is not an
invented transaction or an equity adjustment. Overlapping boundaries are not treated
as consecutive closing/opening amounts.

Known date limitations are retained explicitly. The current Chase parser exposes
only source transaction dates and uses statement-bounded posting-date proxies. Those
are not established bank posting dates, even though earlier transfer handling
preserved the normalized dates exactly. Other parser dates have not been independently
certified by this audit. The source-review controls below carry these distinctions
into opening review without rewriting raw evidence.

The reference archive's unused-file inventory was also inspected during development;
no missing card-period source was identified there. This does not establish that
those statements never existed or cannot be obtained from their institutions.

## Source provenance and opening confirmation

Create a new disposable workflow copy from the accepted **unposted** candidates and
the matching readiness report. Earlier ordinary/transfer GUI test decisions are not
accounting approvals and must not be carried into this copy.

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/review_proposals.py `
  --openings --readiness <verified-readiness-directory> `
  --candidates <verified-candidate-directory> --folder <new-private-review-directory>
```

Use `--prepare-only` to create it without opening the window, or `--smoke` for an
offscreen cancellation/posting/reopen exercise in a separate new test copy. Reopen
with only `--openings --folder <prepared-review-directory>`.

The service verifies artifact binding and independently checks each proposed amount,
cutoff and earliest-source set against the raw statements. The review stores separate,
append-only source assertions: opening/closing balance origin, inclusive-period timing,
posting-date provenance, source reference and review note. A source reference is
required; a blank optional note receives a standard audit reason. All tied earliest
sources need review. Structural readiness blockers cannot be dismissed by attestation.
The GUI reviews earliest sources; the service retains date provenance for every
eligible statement. Ordinary and transfer details also expose conservative date labels,
including in older review copies. A movement with any estimated source remains estimated.

Only a reported opening with confirmed period timing can authorize confirmation.
Nonzero positions post a balanced, reviewed opening-equity journal without consuming
transaction evidence or creating income/expense. Zero positions record a decision
without a journal. Posting and decision history commit atomically; exact retries are
idempotent. Earlier postings or another opening require separate correction, not an
offset. Unsaved form changes disable confirmation; changed source assertions during
confirmation require a refresh. Revising source review after posting marks the opening
stale without rewriting it; reversal/replacement controls remain future work.

Known Chase date proxies cannot be relabeled as reported bank dates. Opening review
does not remove coverage gaps or certify transaction dates. Raw `LedgerStatements`
remain unchanged and the existing reconciliation entry point still uses their original
unverified provenance. A separate reviewed statement view is available, but integrating
it with independent, date-aware reconciliation is the next bounded chunk. There is no
active-profile or report cutover here.

## Windows workflow walkthrough

This accepts **UI behavior only**, not the financial assertions entered in the test copy.

1. Select a nonzero opening. Choose **Printed on statement** for its opening origin,
   check period timing, and enter **Workflow test** as the source reference. Leave
   closing provenance and transaction dates unchanged for this exercise. Cancel
   **Record source review**, then repeat and save. Confirm that the opening button
   enables only after saving. An optional note is not required.
2. Cancel **Confirm opening position**, then repeat and confirm. The account should
   show **Opening posted**. Select a zero opening and repeat; it should show
   **Zero opening confirmed**. No zero-valued journal is created.
3. Inspect an earliest Chase source: its posting-date control should remain
   **Estimated posting dates** and disabled. Closing the window and reopening with
   the command above must retain the saved source review and opening statuses.

The owner accepted this Windows workflow and persistence on October 2, 2026. This
accepts UI behavior only; sample financial assertions remain confined to the disposable
copy. The automated exercise used a different copy, and the owner copy began with no
source assertions, opening decisions or posted journals.
