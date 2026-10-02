# Fresh cash/card journal proposals

This opt-in service follows the [accepted evidence rebuild](REBUILD.md). It copies
an inactive, checksum-verified rebuild into a new private directory and adapts
checking, savings and credit-card observations to the isolated ledger kernel.
The normal application and live database continue using their existing model.

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/propose.py `
  --rebuild <accepted-private-rebuild-directory> --output <new-private-directory>
```

Keep all artifacts in ignored storage. The output must not exist. The input
`plan.json`, `fresh.db` and retained `legacy.db` must match `report.json` checksums;
database sidecars are refused. The copied database must belong to that rebuild
plan. Input checksums are checked again at completion. No archive reparse, profile
activation, server request or normal-client database migration occurs.

## Interpretation contract

Rule `cash-card-proposals-1` uses a small explicit list of checked parser/account
sign contracts. Source status, account ownership, posting dates and the statement
equation must agree. Unknown parser contracts and source exceptions remain pending.
Every canonical nonzero eligible movement becomes one kernel observation, including
uninterpreted payments and income. Overlapping statements refer to the same
observation; duplicate statement memberships are rejected. Zero rows stay in source
evidence with an explicit decision and create no zero postings.

Only restored, verified **Expense** categories suggest a two-posting journal:

| Source movement | Financial-account posting | Expense posting |
| --- | --- | --- |
| Checking purchase of $30 | Credit cash $30 | Debit expense $30 |
| Card purchase of $30 | Credit liability $30 | Debit expense $30 |
| Card refund of $5 | Debit liability $5 | Credit expense $5 |
| Checking refund of $5 | Debit cash $5 | Credit expense $5 |

These are proposed interpretations. A historical expense label can describe a
capital purchase or another event needing different accounting. Category-level
verification stays intact, while every proposal has accounting review set to false.
No journal is posted and no observation is consumed. Card payments, transfers and
income receive no automatic counterpart; they await interpretation. Loan, HSA,
retirement and tangible-asset activity remain outside this adapter. Retained manual
asset values and all category/source tables are preserved in the copied database.

Raw signs are preserved: credit-card charges are negative liability credits; the
adapter does not invert an amount merely because the account is a liability.
The source posting date remains the journal date. Each proposed financial posting
allocates exactly one complete observation and balances against its expense
counterpart in integer minor units. Kernel validation rejects inconsistent signs,
ownership, dates, amounts, currencies and duplicate consumption.

The fresh parser output does not yet carry independently verified endpoint
provenance. Kernel statement endpoints therefore remain conservatively `assumed`,
and their original provenance text is retained in the proposal plan. A successful
statement equation is not independent reconciliation. No opening anchor or balancing
adjustment is generated.

## Artifacts and retries

- `candidates.db`: copied rebuild evidence plus kernel accounts/observations/statement
  evidence and append-only `JournalProposalPlans` / `JournalProposals`. Posted journal,
  allocation, review and reconciliation tables remain empty.
- `proposals.json`: deterministic proposal plan, per-transaction decisions, source
  exception details, statement provenance and counts.
- `report.json`: completion record with artifact checksums, counts, unchanged-source
  and idempotent-replay checks. `ready_for_cutover` remains false.

Kernel evidence loads in one transaction and proposal registration in a second.
Registration failure rolls back every proposal in that batch; evidence may already
be present. Identical service retries are idempotent; conflicting identities are
rejected, including attempts to rename a proposal for the same observation. Neither
phase posts entries. Failed output without a completion report is incomplete and
must not be activated. The command refuses existing output; use a fresh directory
for a new run. Separate clean runs must reproduce plan and database bytes.

## Ordinary proposal review and posting

Create a separate writable copy for the owner review:

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/review_proposals.py `
  --candidates <verified-proposal-directory> --folder <new-private-review-directory>
```

Add `--prepare-only` to create/verify the workspace without opening a window.
Resume saved decisions by omitting `--candidates`:

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/review_proposals.py `
  --folder <existing-private-review-directory>
```

`review.db` contains a copy of all proposal evidence plus append-only decisions.
`review.json` binds that workspace to the original verified proposal plan and source
database hash. The review database is deliberately mutable through its decision
service; the original `candidates.db` and completion checksums stay unchanged.
Only a prepared workspace can be opened. Integrity, foreign keys, workspace identity
and immutable proposal-plan contents are checked on reopen.

The window shows pending, posted and rejected proposals with source statement
filenames, retained category verification, financial-account effects and both
postings. Dates run newest first. Text filtering searches all displayed columns;
Ctrl/Shift selects multiple rows, and Ctrl+A selects the currently visible rows.
Changing filters clears selection. A nonempty reason and pending selection enable
the actions. The confirmation shows the selected count, proposed expense effect,
reason and expandable row details; Cancel is the default.

**Accept and post** validates the journal against current kernel evidence usage,
posts a reviewed entry, consumes its exact observation and records the decision in
one transaction. **Reject** records the reason without posting or consuming anything.
The entire selected batch commits or rolls back. Exact service retries are idempotent;
conflicting/stale decisions and already-consumed evidence fail without partial writes.
Historical category assertions and proposal payloads are never rewritten.

Decisions are final in this bounded workflow. Posted corrections will use the later
reversal/replacement workflow; rejected movements await a new interpretation. Neither
action confirms transfers, opening anchors or statement reconciliation. These are
disposable acceptance artifacts, not the active application database.

## Windows review walkthrough

Use a fresh prepared owner copy; there is no need to review the entire history now.

1. Filter for a familiar ordinary purchase. Select it and check the source account,
   category, amount and cash/card effect in the details pane.
2. Enter a reason, click **Accept and post selected**, then **Cancel**. It must remain
   pending. Repeat and confirm; find it under **Posted** with the saved reason.
3. Select a different pending row and reject it with a test reason. It must appear
   under **Rejected** while its source evidence and category remain visible.
4. Optionally select two pending rows with Ctrl/Shift and inspect the batch count and
   amounts in the confirmation. Cancel to leave them unchanged.
5. Close with X and reopen the same folder without `--candidates`. Verify that the
   posted/rejected decisions and reasons remain. Report any confusing terminology,
   selection behavior or financial effect.

For automated accept/reject/filter/reopen checks on a **new test copy**, pass
`--candidates`, a new `--folder`, and `--smoke`. This records synthetic test reasons
and one posting only in that disposable workspace, and saves a private screenshot.
It is not owner acceptance. Never use the smoke copy as the untouched owner copy.

Owner Windows acceptance is pending. Confirmed transfers/splits, opening positions,
source corrections, reversal/replacement workflows and ledger-backed reports follow
separately after this checkpoint.
