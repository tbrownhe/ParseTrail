# V2-1 preservation inventory: first pass

Started October 4, 2026 on `feature/client-financial-insights`. This is a code/schema
inventory and a read-only private-inventory tool, not an accepted cutover manifest.
No live profile was opened for this repository document. The [cutover contract](client-v2-cutover.md)
controls activation; the old database and archive remain authoritative until a
reviewed rebuild is explicitly activated.

## Source database field disposition

The current ORM and Alembic head contain nine business/reference tables plus
`alembic_version`. The inventory command enumerates actual tables and fields and
marks any unexpected or missing field unresolved. The known `0003` legacy revision
predates `Statements.AccountingContract`; the command records that absence without
blocking source-reference checks. The same absence on the `0004` head remains an
issue. These are proposed dispositions
for fields currently known in code; every value remains in the retained original.

| Source fields | Proposed 2.x treatment | Required check |
| --- | --- | --- |
| `Currencies.CurrencyCode, MinorUnit`; `AccountTypes.AccountTypeID, AccountType, AssetType` | Retain reference definitions and map account kinds explicitly. | No unknown currency scale or account kind is silently converted. |
| `Accounts.AccountID, AccountName, AccountTypeID, CurrencyCode, Company, Description, AppreciationRate` | Preserve identity, labels, institution, currency, type, description and saved appreciation assumption. Preserve legacy IDs as provenance even if 2.x keys differ. | One source account to one mapped account or a blocking reason; appreciation remains an assumption, not a cash posting. |
| `AccountNumbers.AccountNumberID, AccountID, AccountNumber` | Preserve exact aliases and source account association. | No fuzzy number/institution mapping. |
| `Categories.CategoryID, Name, Type, Active, ParentID, BudgetMinor, BudgetCurrencyCode` | Preserve every definition, hierarchy, active state and exact target/currency. Add built-in semantic identity separately; matching names are insufficient. | Count and value parity, parent mapping, usable editing, no custom/built-in conflation. |
| `Plugins.PluginID, PluginName, Version, Suffix, Company, StatementType` | Retain parser provenance and 1.x artifacts for rollback; bind each replay to an available verified 2.x definition/engine or an explicit exception. | A historical parser reference without replay support blocks automatic reconstruction. |
| `Statements.StatementID, PluginID, AccountID, ImportedAt, StartDate, EndDate, StartBalanceMinor, EndBalanceMinor, CurrencyCode, TransactionCount, Filename, ContentHashAlgorithm, ContentHash, AccountingContract` | Retain every legacy assertion and file reference. Reparse original bytes into separate immutable evidence; do not certify legacy endpoints as observed merely because they are numeric. | Referenced `SUCCESS` bytes/hash, membership, source dates/account and accounting-contract provenance; distinguish statement coverage from export activity. |
| `Transactions.TransactionID, AccountID, TransactionDate, PostingDate, AmountMinor, BalanceMinor, CurrencyCode, Description, Fingerprint, FingerprintVersion` | Retain original row and any edits as an annotation. Match to fresh source evidence using exact identity and occurrence rules; preserve unmatched/changed values for review. | No amount, date, description, refund sign or fingerprint history silently lost. Legacy row balances are not independent printed evidence by default. |
| `Transactions.CategoryID, Verified, ConfidenceScore` | Carry a verified expense category only on an unambiguous match; retain every other assertion, including unverified categories and predictions, with status and source. | Conservation by account/category/currency; category verification never implies transfer confirmation or statement reconciliation. Confidence is suggestion provenance, not a posting. |
| `StatementTransactions.StatementID, TransactionID, StatementRow` | Retain exact source membership and row order; rebuild relationships from evidence without duplicating overlapping transactions. | Every old membership explained; duplicates and multi-account files remain distinct. |
| `alembic_version.version_num` | Retain old format identity in the source package; 2.x gets its own format and migration history. | Unknown/newer format refused before writable initialization. |

The current `ledger_rebuild.match_categories()` handles verified **expense**
assertions and stores pending reasons for failed or ambiguous matches. It does
not yet make the other transaction fields, verified non-expense rows, unverified
categories, `ConfidenceScore`, or all manual rows usable in the everyday 2.x app.
The inventory reports counts for those classes rather than declaring them
rebuildable. `ledger_rebuild.retain_reviewed_asset_values()` supports only
owner-reviewed positive manual tangible-asset values. The owner-confirmed
closure marker is status intent, not a money movement. All other unlinked rows
need a separate disposition before activation.

## Files and local settings

| Source | Current path/behavior | Proposed disposition |
| --- | --- | --- |
| SQLite database and `-wal`/`-shm`/journal companions | `settings.db_path`; database may be active | Preserve a consistent independently restorable snapshot and original files; recheck for intervening edits before activation. The initial tool only reports file markers and relational integrity. |
| Managed archive | `db_path.parent / db_path.stem`, with root drop zone and `SUCCESS`, `FAIL`, `DUPLICATE` | Retain **all** regular files and relative names, including unreferenced, failed, duplicate, pending PDF/CSV/XLSX/ZIP/TXT exports. References in `Statements.Filename` resolve in `SUCCESS`; verify original hash algorithm. Unknown extensions and links need review. A new 2.x archive needs a separate writable path. |
| `config.json` and `backup/` | Platform profile directory under AppData/Application Support | Retain original config and backups. Map known nonsecret preferences and all external paths deliberately; unknown keys require review. Do not copy access tokens into the financial manifest. |
| `accounts.json` | Profile export of account metadata | Preserve as a user-created historical artifact; database account definitions remain the primary mapping source. |
| `plugins/` | Signed release pointer, manifest/signature and bytecode release directories | Retain entire verified 1.x catalog for rollback and inspect available parser IDs/revisions. 2.x must use its own signed definitions and engine versions. |
| `models/`, configured `model_path` | Local classifier bundles | Retain old files for recovery; retrain or mark incompatible for 2.x. A model cannot overwrite a verified category or block manual use. |
| `report_dir` and exported files | Configurable external directory | Preserve historical exports in place; map new output deliberately and regenerate future reports from ledger queries. |
| `logs/`, `log_file`, `downloads/`, `server_public_key.pem` | Profile or configured paths | Retain private history and trust/update resources as appropriate; logs are not financial facts. Inspect any paths outside the profile. |
| OS credential store | Profile-specific service name | Leave credentials in the existing store; inventory only the service identity, never secret values. |

The current recovery bundle includes only database plus managed archive. It
does not package config, models, plugins, account export, reports or external
paths. `AppSettings` currently creates its profile directory and may write
`config.json` at import, so the V2-1 tool uses only the Python standard library
and does not import runtime settings.

## Legacy application action inventory

These are the actions registered in `gui/main_window.py`. Each needs an
implemented/replaced/deferred decision before V2-5/V2-7; this table records
the likely owner of that decision without approving a deferral.

| Menu/actions | 2.x disposition to verify |
| --- | --- |
| File: Preferences; Open Database; Database Location and Privacy | Profile selection and mapped settings under V2-2/V2-6; prevent 1.x writable opening. |
| File: Back Up Database; Test Database Backup; Restore Database; Export Account Configuration; Sign Out of Server | 2.x aware backup/restore and account export; server sign-out remains a separate account action. |
| Plugins: Plugin Manager; Troubleshoot Parsing | Signed definition catalog and source diagnostics under P2-4/P2-5. |
| Accounts: Edit Accounts; Appreciation Calculator | Ledger account metadata and explicit valuation assumptions under V2-4; calculator decision remains open. |
| Statements: Import All; Pick File for Import; Completeness Grid; Correct Discrepancies; Send for Plugin Development | Evidence import/recovery, true coverage and review under V2-3/V2-4; contribution remains explicit. |
| Categories: Category Manager | Preserve/edit custom and built-in definitions and exact budgets under V2-4. |
| Transactions: Review Transactions; Identify Recurring; Insert Manually | Ledger review and bounded manual origin under V2-4; recurring analysis must use labeled ledger scope or receive an explicit deferral. |
| Train Model: Train Model for Testing; Train Model for Deployment | Local model lifecycle against 2.x categories and evidence, separately from posted facts. |
| Reports: Export Three Months; Export One Year; Export All Time | Common ledger queries, scope/coverage metadata and export parity under V2-5. |
| Help: About; Getting Started; Check for Updates | Update/help content and parser catalog contract under V2-7/P2-5. |
| Main window tabs/controls: latest balances, balance history, budgets, charts | Reconnect to shared ledger read services under V2-5; inspect every control before removal. |

## Read-only private inventory command

`devtools/v2_inventory/inventory.py` accepts explicit paths and writes a new
JSON report **outside the repository**. It records actual table/field policies,
ordered table content fingerprints, row and preservation-class counts, legacy
parser references, archive file hashes/reference status, profile file hashes,
known setting keys/path availability, bounded hashes of configured external
resources such as historical reports, and unresolved items. Legacy credential
key files are recorded by presence only. The configured database path is bound
to the selected closed source copy by byte identity when they differ. It
does not write to the source, import application settings, parse statements,
copy a profile or assert activation readiness.

```powershell
client/.venv/Scripts/python.exe devtools/v2_inventory/inventory.py `
  --source C:\private\source.db --archive C:\private\source `
  --profile C:\private\ParseTrail --output C:\private\v2-inventory.json
```

The report is private: file names, configured paths, IDs and hashes may be
sensitive. Missing profile input is recorded as an issue. The command refuses
SQLite WAL/SHM/journal sidecars and opens a closed copy with SQLite's read-only
immutable flag, so it never creates SQLite sidecars in the source directory.
Use a consistent, closed snapshot; the before/after file markers are **not**
an atomic snapshot or a no-change proof while another process is writing.
V2-6 must freeze a consistent source/package, verify restore and
recheck database, WAL, archive and configuration before activation. Do not
put private report content in Git or attach it to a public issue.

An authorized closed-copy run found no structural inventory exceptions: known
legacy schema, source references, profile files/settings and configured report
resources were all accounted for, and the configured database matched the copy
byte-for-byte. This is structural coverage, not approval of accounting meaning
or a cutover-ready manifest. The exact private report stays outside Git.

## Remaining V2-1 decisions and evidence

1. Run the private command on an authorized, consistent copy of the owner's
   source/profile and inspect every unknown table, field, setting and file.
   Record only aggregate, nonprivate findings in the repository.
2. Compare every category definition and verified assertion against the fresh
   replay preservation report; add exact parity for unverified categories,
   edited values, manual-only rows and profile resources. Resolve uncovered
   user-data policy with the owner before declaring V2-1 complete.
3. Bind installed parser availability and signed catalog provenance to every
   referenced source. The [P2-1 review](client-v2-parser-inventory.md) identifies
   current source parsers; local installation may differ.
4. Extend the manifest into a restorable cutover package, then test missing
   sources, unknown fields, manual state, interrupted build and stale source
   detection on isolated profiles. Native activation remains a later owner gate.
