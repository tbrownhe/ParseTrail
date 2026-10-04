# One-time MOHELA evidence replacement

This client-only tool replaces an aggregate MOHELA source in a new disposable,
unposted rebuild. It uses the detailed MOHELA CSV with loan identifiers,
principal, interest, fees, total and unpaid principal. StudentAid and ECSI are
not dependencies. The active profile and accepted rebuild are never edited.

Run from the repository root with the client environment:

```powershell
client/.venv/Scripts/python.exe devtools/ledger_audit/mohela_replacement.py --accepted scratch/accepted-rebuild --csv C:/private/detailed-export.csv --old-export C:/private/original-export.csv --folder scratch/mohela-review --prepare-only
client/.venv/Scripts/python.exe devtools/ledger_audit/mohela_replacement.py --folder scratch/mohela-review
```

The output directory must not exist. Inputs must be unchanged, inactive accepted
rebuild artifacts with no posted journal entries. Their checksums and plan identity
are verified before writing. Original plan/database copies and optional original
CSV bytes are kept under `original/`; the detailed CSV is retained as
`new-export.csv`. Failed preparation leaves diagnostic artifacts without a verified
report; retry in a new directory. Keep everything in ignored private storage.

The accepted input must contain exactly one aggregate MOHELA source on one USD
account. Every old movement must match the new same-date/type component group
exactly. Ambiguous mappings, changed totals, shared source movements and ambiguous
verified categories stop preparation. This deliberately bounded replacement is not
a general incremental CSV importer or a repeated snapshot reconciliation service.

## Evidence and categories

The detailed reader validates each row's component equation using integer minor
units. Loan identities, source signs, raw fields, zero rows and duplicate occurrences
are retained. `Unavailable` remains unknown. Transaction dates establish the observed
activity span, not statement coverage or an as-of date. Capture time identifies when
the tool read the file, not when the servicer generated it.

The replacement removes old derived MOHELA rows and their invented statement
endpoints from active rebuild evidence. Their original records remain in immutable
superseded-source storage. The new export and rows have separate immutable evidence
tables; they are not silently promoted to reconciled statements or journal entries.

Verified categories are retained on exact groups of replacement components, including
legacy categories outside the expense-preservation subset. Original category, verified
flag and source row are preserved. These annotations do not approve loan accounting
or convert gross payments/disbursements into expenses. The old aggregate and new
components must not be counted twice. Existing bank evidence and cash/card proposals
remain unchanged.

## Windows acceptance

The window has four sortable, filterable tabs:

1. **Loan balances:** supplied principal observations, net listed principal through
   the observation date, and unexplained differences. Missing and conflicting
   observations stay unknown. Even a zero difference is not reconciliation.
2. **Retained categories:** original verified choices and the component groups to
   which they were carried. Select a row for provenance and interpretation limits.
3. **Bank match candidates:** possible exact-amount checking/savings counterparts
   within seven days of a daily payment total. No match is confirmed. A date can
   contain multiple withdrawals; absent candidates can reflect stale bank imports.
4. **Export activity:** all supplied loan rows and components, including zeros and
   unknown balances. Select a row to inspect the original fields.

Check sorting/filtering, selected details and closing/reopening. There are no state
change controls. `--smoke` exercises selection and reopening offscreen, captures
private screenshots and confirms the database hash stays unchanged. The ordinary
rebuild preview redirects users to this specialized review to avoid mislabeling
retained export annotations as pending categories.

The legacy MOHELA plugin version 0.2.1 rejects detailed exports in ordinary statement
import, whose interface would require invented numeric endpoints. The new reader is
available only through this replacement tool. Older aggregate replay remains
compatible. No plugin publication, live migration or report cutover is included.

After native acceptance, separately design reviewed loan openings and payment
posting from this evidence. Missing history must stay visible; it does not authorize
invented income, interest, spending or balancing entries. Future full-history export
comparisons must preserve previous snapshots and review added/changed/missing rows
and associated interpretations before replacing them.
