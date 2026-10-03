# Transfer and card-payment workflow

This client-only checkpoint extends the [ordinary proposal review](PROPOSALS.md).
Use a **fresh disposable copy** of the verified, unposted candidates. Earlier GUI
test decisions are workflow tests, not approved financial interpretations to migrate.
The live profile and accepted rebuild/candidate artifacts remain unchanged.

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/review_proposals.py `
  --transfers --candidates <verified-proposal-directory> --folder <new-private-review-directory>
```

Use `--prepare-only` to create the copy and save a private `transfer-preview.json`
without opening the window. Resume by passing `--transfers --folder <existing-directory>`
and omitting `--candidates`. The normal application still uses its legacy database.

## Candidate rules

The service searches eligible cash/card observations from the checksum-bound proposal
plan. It considers exact opposite nonzero amounts, matching currency, different owned
accounts, and a configurable posting-date gap of 0–31 days (default seven). It suggests
checking/savings transfers and cash-account outflows paired with card-liability
reductions. No source date or amount is changed. Overlapping statement memberships
refer to the same canonical movement and do not multiply candidates.

Equal amounts are suggestions, never confirmation. Legacy labels, category verification,
merchant text and apparent uniqueness cannot automatically authorize a transfer.
Candidates distinguish single possible matches, multiple possible matches, pending
expense interpretations, allocated observations, confirmed pairs and dismissed pairs.
Candidates blocked by pending expense interpretations still count as alternatives;
their potential relevance is not silently removed to make another pair look unique.

The source-movement view separately exposes zero/one/multiple possible counterparts
and complete/partial allocations. “No candidate” is not evidence of missing activity:
ordinary purchases and external income often have no owned-account counterpart.
Loans, investments, cash advances, card-to-card transfers, fee differences and partial
settlements need later interpretation. This workflow never invents a fee split,
counterpart, income/expense entry or balancing adjustment for them.

## Confirmation and accounting

Confirmation validates the pair again against current evidence and allocation state.
An observation with any existing active allocation cannot enter this whole-movement
workflow. A conflicting pending ordinary expense/refund proposal must first be
explicitly rejected with a reason in the **Expense/refund interpretations** tab.
Its verified category remains retained as historical evidence. Confirming the transfer
does not delete or overwrite that assertion.

- Same-day confirmation creates one balanced reviewed entry. A card payment credits
  cash and debits the card liability; a savings transfer credits the outgoing cash
  account and debits the receiving cash account.
- Different-date confirmation creates two balanced entries sharing an economic-event
  identity and a dedicated asset clearing account. Each financial posting retains
  its observed date. Clearing holds the amount in transit between those dates and
  returns to zero after both entries. If the receiving institution posts first,
  clearing can temporarily have a credit balance; dates are not rearranged.
- Neither form creates an expense or income posting. Account cash movement remains
  visible without treating card repayment as another purchase.

The decision, any clearing account, all journal entries, allocations and event links
commit in one transaction. Invalid/stale evidence or failure midway rolls back all of
them. Exact retries create no duplicate entries. Conflicting pair selections in a
batch cannot allocate a movement twice. Decisions and their journal links are append
only. This workflow does not yet offer reversal/replacement of confirmed transfers.

Confirmation uses a standard audit reason with an optional note. Dismissing a pair
requires an explanation and consumes no evidence; other possible pairings remain
available. A dismissal is about that specific pairing, not either source movement.
Saved confirmed/dismissed decisions stay visible when the search window is narrowed.
Opening positions and independent statement reconciliation remain unfinished.

## Windows workflow acceptance

This is a **UI exercise on disposable data**, not a request to review the entire
financial history or approve the selected pair for the final rebuilt books.

1. In **Transfer candidates**, filter for `Card payment` or an account name. Select a
   sample and check that both accounts, source dates, amounts and source statements
   are understandable. **Show Details** in confirmation exposes the same evidence.
2. Click **Confirm and post pair**, then Cancel. The candidate must remain unchanged.
   Repeat and confirm. Find it using the **Confirmed** filter; confirmation should
   not require typing a note.
3. Choose another candidate, enter a test explanation and **Dismiss this pair**.
   It should appear under **Dismissed**, with its source movements preserved.
4. Inspect **Multiple possible matches** and **Expense conflict** rows. Conflicting
   expense interpretations must disable confirmation. Changing text/status filters
   must clear the prior selection; transfer actions must disable on other tabs.
5. In **All source movements**, filter for a tested movement and inspect its remaining
   allocation. Inspect a different-date pair for the explanation of transfer clearing.
6. Close with X and reopen the same folder without `--candidates`. Confirm that test
   decisions and notes persisted. Report confusing wording or selection behavior.

For automation, `--transfers --smoke` requires `--candidates` and a new test folder.
It exercises cancel, a different-date confirmation, dismissal, filtering, close and
reopen, saving a private screenshot. Its archive-sized fixture needs at least one
unique different-date pair and another available candidate. This smoke does not
establish native owner acceptance; synthetic tests cover edge cases independently.

The owner confirmed Windows workflow and persistence on October 2, 2026. This accepts
the controls, not the sample financial interpretations. The next service checkpoint
is [opening-position readiness](OPENINGS.md). Keep all snapshots, reports and screenshots
in ignored private storage. No server operation or new dependency is required.
