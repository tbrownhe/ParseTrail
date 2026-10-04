# Ledger migration evidence audit

Run from the repository root with the client Python environment:

```powershell
client/.venv/Scripts/python.exe devtools/ledger_audit/audit.py --source C:/path/to/history.db --output scratch/ledger-audit-run
```

The output must be a new directory. It contains a consistent SQLite `snapshot.db`
and a private `audit.json`. Keep both out of Git; `scratch/` is already ignored.
The report includes internal IDs, date ranges, and exact balance differences for
local investigation. It omits account/category names, descriptions, and source
filenames. Console output includes aggregate counts and snapshot verification,
which should also be treated as private user data.

The tool uses only Python's standard library. It does not load the application,
settings, credentials, network clients, or migrations. It opens the source with
SQLite `mode=ro` and `query_only`, copies through the online backup API (including
committed WAL data), then audits the snapshot through another read-only connection.
Existing output is never overwritten. The snapshot has a 60-second timeout.
Source main/WAL hashes before/after are recorded as an observation: an unrelated
writer can change them during a run. Snapshot content must remain unchanged during
the audit. This is not the complete archive/backup/restore gate required by L2.

Checks include SQLite integrity/foreign keys; source membership ownership/counts;
exact statement balance equations; posting dates within declared periods; adjacent
statement endpoint differences; accounts with no statements or internal date gaps;
unlinked/manual-origin markers; exact monetary storage and currency consistency;
and potential opposite transfer legs. Unknown schema or SQL failures stop the run
without migrating anything. Failed-run output is retained locally for inspection;
retry into a new directory.

`--window-days` controls a 0–31-day candidate window (default 7). Candidate legs
have opposite nonzero amounts in the same currency on different accounts. The
search includes non-Transfer categories so label inconsistencies remain visible.
It records zero/multiple/reciprocal-unique candidate counts. These counts refer to
Transfer-labeled source rows, not unique payments. Candidate IDs are capped at 20
per row; the full candidate count and truncation flag remain available.

None of these candidates confirms ownership or an accounting relationship. A
matching pair can still be unrelated; an unmatched row can be a legitimate
transfer with missing/aggregated evidence. Manual-origin markers recognize fixed
labels as review hints, not an authoritative provenance field. A passing statement
equation is only as independent as its stored balances: some parsers derive a
closing balance from parsed transactions. Adjacent-boundary checks compare only
immediately ordered, day-adjacent statement ranges; they are not a full overlapping
statement reconciliation. No historical data or bookkeeping exception is repaired.

The L1 contract is in [client-ledger-contract.md](../../docs/client-ledger-contract.md).

The bounded [MOHELA replacement review](MOHELA_REPLACEMENT.md) preserves detailed
loan-export evidence in a disposable rebuild without inventing statement endpoints.
