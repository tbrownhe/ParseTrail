# One 2.0 user database for source evidence and ledger work

Status: **approved by the owner on October 24, 2026**. This replaces the
temporary assumption that the isolated ledger prototype database can be attached
to the 2.0 source profile as-is. It does not change the 1.x application or data.

## Collision to remove

The pre-release 2.0 source profile calls its financial-account table
`LedgerAccounts` and stores name, asset/liability kind, institution and full
account number. The isolated ledger prototype also calls a different table
`LedgerAccounts`; it stores a serialized account model and a source ID. Its
rebuild and review helpers create additional tables on demand. The two database
formats cannot be combined by opening both stores on one file.

## Target boundary

- One fresh 2.0 SQLite profile owns immutable source bytes, declarations and
  evidence; user-authored accounts, categories and budgets; reviewed journal
  entries, corrections and review decisions; and common report reads.
- One authoritative `Accounts` table covers financial, category and internal
  ledger accounts. A financial account has an explicit asset/liability kind and
  institution metadata; a category has an income/expense kind. Source-account
  bindings refer to the account ID. Account identity and display fields are not
  copied into a second ledger account table.
- Keep the pure double-entry checks in `ledger.py`, but have the 2.0 user-database
  service own its journal tables and transactions. The isolated ledger store and
  rebuild schema remain development evidence until the 2.0 workflows replace
  them; they are not a second runtime database or a migration target.
- Immutable source rows remain separate from authored interpretations. A review
  decision supplies the financial account and any posting date that the source
  did not establish. Journal allocations point to admitted source rows and are
  checked against their signed amount. No category, transfer or posting is
  inferred merely from a parser row or account binding.
- This is a pre-release schema replacement. Disposable pilot profiles are
  recreated; no 1.x or pilot-profile migration/alias layer is added. Reopen
  checks must refuse an older shape before a write.

## Implementation order

1. Replace the provisional account table with the single account shape and
   retain the existing explicit binding and abbreviated-match behavior.
2. Add reviewed journal storage and account/observation adapters in the same
   user-database service. Exercise one synthetic import-to-expense review and
   correction without opening a second database.
3. Add fresh category and budget authoring, then connect the daily review UI.
   Keep unsupported interpretation and unknown posting dates pending.
4. Use the same journal reads for spending, cash, balances and exports; only
   then remove obsolete 1.x runtime financial paths and freeze the released
   2.0 schema.

A bounded proof toward the first two steps is in pre-release schema revision 7:
a single `Accounts` table replaces the conflicting pilot account table, and
one reviewed asset outflow can create an immutable, balanced expense journal
entry with a source-row allocation in the same database transaction. It requires
an explicit account binding and source posting-date role. A liability row, an
activity-date-only row, an unknown interpretation or a missing category remains
pending. A reviewed expense can be corrected to a different expense category:
the service saves an inverse reversal, a replacement entry and a correction
record atomically. The old entry and source allocation remain as history, while
only the active allocation counts toward evidence use. Account assignments with
journal history cannot be changed. A narrow desktop review now posts and
recategorizes eligible asset outflows from activity exports; general journal
workflow remains open. Earlier disposable pilot profiles are refused, not
migrated.
