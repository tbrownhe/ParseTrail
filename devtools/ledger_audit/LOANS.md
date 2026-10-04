# Loan evidence readiness

This read-only L1 checkpoint inventories loan accounts from the accepted fresh rebuild.
It does not add loan accounts to the cash/card candidate adapter, admit observations,
post journals, revise annotations, alter parsers or change the active profile. Its report
is a source review aid before designing loan payment, interest and financing workflows.

Create a private report and open the view from the repository root:

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/loans.py --rebuild <verified-rebuild-folder> --folder <new-report-folder> --review
```

Omit `--review` for report creation only. Reopen with `--folder <report-folder> --review`
and no `--rebuild`. `--review --smoke` exercises selection/filter clearing/close and saves
private screenshots. Output creation refuses overwrites. Input plan, fresh database and
retained legacy database hashes are checked before and after generation; database
sidecars prevent use of an active input. The view verifies the report checksum and
rebuild identity and does not open either database.

## Source contracts under review

| Parser | Representation and limits |
| --- | --- |
| Capital One Auto | Printed closing principal; opening reconstructed from principal activity. Payment totals and interest components are separate rows. A zero equation difference is not independent opening verification. |
| Wells Fargo Personal Loan | Ordinary statements read prior/ending principal. Payments combine same-date principal and interest and retain a separate interest component. The parser assumes a 31-day period. Its no-activity branch creates a synthetic origination at statement end and resets opening to zero; that date is not an observed disbursement. The owner's parser-change deferral remains in force. |
| Yamaha Finance | Printed previous/new register balances, purchases, payments and charges. The balance's principal/interest composition needs review. The parser reads the remaining date token after removing the first date when populating transaction date; distinct transaction/posting date provenance needs a targeted archive check before certification. |
| MOHELA CSV | Total and interest columns become separate rows; balances start at assumed zero and are reconstructed. First/last transaction dates are an activity range, not independently established coverage. Disbursements and capitalized interest need their own interpretation. |

These are parser behavior descriptions, not independently reviewed assertions about
every statement. The report retains the recorded parser manifest and raw source
provenance. Unknown parser contracts stay unknown. No label establishes a payment match,
an expense, a bank receipt, an asset value, or an opening balance.

## Report and review

**Loan accounts** shows source periods, distinct movements, parsers and posting blockers.
Overlapping statement memberships never multiply the account movement inventory.

**Source balances** shows opening/closing values and the exact equation
`closing − opening − sum(parsed movements)`. Its details separate balance provenance,
period assumptions and component representation. Agreement remains distinct from
independent reconciliation. Differences, out-of-period movements, missing/failed sources,
unknown parser contracts and unsupported account/currency mappings remain visible.
This checkpoint does not establish continuity between statements or complete coverage.

**Loan movements** retains source dates, amounts, descriptions and statement membership.
Search hints distinguish possible payments, interest components, capitalized interest,
financing/disbursement, purchases/asset funding and other rows. Hints are unreviewed and
never create postings. In particular, “Interest Charge on Purchases” is an interest hint,
not a purchase hint. Synthetic Wells Fargo origination remains explicitly estimated.

Future loan posting must use payment components consistently: matching a full bank
payment to a loan-register payment must not recognize the separately represented
interest a second time. Principal reduction is not spending, and disbursement is not
income. The evidence review precedes those posting rules and their own owner acceptance.

For Windows acceptance, select a familiar account, inspect a source balance's basis,
then filter movements for interest and synthetic origination. Verify the descriptions
and limitations are understandable and that clearing/changing filters clears old details.
Close/reopen the report. There are no financial approval or posting controls in this view.
All private reports, identifiers, amounts and screenshots remain in ignored storage.

The owner accepted all three tabs, the evidence hints and reopening on Windows on
October 3, 2026. No financial decisions were changed in this read-only view. The next
bounded workflow is [Capital One payment and interest confirmation](LOAN_PAYMENTS.md).
