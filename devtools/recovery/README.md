# Ledger recovery preparation

Use the client environment from the repository root. This command-line tool is
the L2 migration recovery gate, not a new GUI backup workflow.

```powershell
client/.venv/Scripts/python.exe devtools/recovery/backup.py create --source C:/path/history.db --archive C:/path/managed-statements --output scratch/private-recovery
client/.venv/Scripts/python.exe devtools/recovery/backup.py restore --bundle scratch/private-recovery/recovery.zip --output scratch/independent-restore
```

Both output directories must be new. The archive argument is the managed import
root containing SUCCESS, FAIL, DUPLICATE and any pending statement folders. The
tool copies PDF/CSV/XLSX files and opaque ZIP/text export companions recursively;
unknown file types and filesystem links stop creation for review. Nested ZIPs
are not unpacked. Profile settings, authentication, signing keys, plugins and
models are not collected. Select the statement tree, not an application profile.

Creation opens the database read-only, uses SQLite's online backup API (including
committed WAL), checks integrity/foreign keys, and fingerprints the full schema
and record contents. Every snapshot statement must resolve to a SUCCESS file
matching its recorded MD5 or SHA-256; shared multi-account references are retained.
Private `source-review.json` reports missing/mismatched statement IDs. Missing
sources block a complete bundle rather than being silently omitted.

The ZIP contains `database.db`, `archive/...`, and a manifest with SHA-256 hashes,
sizes, table counts, schema revisions and the database content fingerprint. Before
publishing `recovery.zip`, creation restores its partial ZIP into `restore-test`
and validates copied bytes, relational integrity, all record values and statement
references using only the bundle. Verification reports and the snapshot remain
beside it. No financial semantics or parser corrections are applied.

Restore writes into a new isolated data directory, refuses overwrites, and rejects
traversal, absolute/Windows-special paths, links, case collisions, unexpected or
missing members, mismatched sizes/hashes, and excessive size/file counts. Default
limits are 20 GiB uncompressed and 100,000 data files. It neither launches the
client nor migrates or activates the restored database. The original paths are
not stored in the manifest and are not read during restore. A successful restore
has `restore-verification.json`; failures leave an incomplete directory for local
inspection, never replace source files, and require a new destination on retry.

All artifacts are plaintext private financial data. Keep them out of Git. Hashes
detect corruption; they are not signatures or encryption. A development-workspace
copy proves recovery mechanics but does not replace an independently stored backup.
The GUI F4 product workflow and native profile activation remain separate work.
