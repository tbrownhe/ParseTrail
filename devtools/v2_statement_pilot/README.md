# Local V2 archive pilot

Prepare a new independent, empty profile with the 23 current required declarations:

```powershell
client/.venv/Scripts/python.exe devtools/v2_statement_pilot/prepare_pilot.py --prepare-at scratch/NEW-PILOT
```

This creates `Open-statement-pilot.cmd`, `PILOT-GUIDE.txt`, separate preferences,
application home and catalog, and a hash-pinned copy of the public current runtime.
The local engineering catalog is signed by a fresh in-memory fixture key; only its
public key remains. It is not a production catalog or a release artifact.

Import the explicitly selected archive using the **copied** helper:

```powershell
client/.venv/Scripts/python.exe scratch/NEW-PILOT/runtime/devtools/v2_statement_pilot/prepare_pilot.py --import-archive LOCAL-ARCHIVE --pilot scratch/NEW-PILOT
```

The archive can be recursive. Only CSV/PDF files are selected, with at most
100,000 files / 20,000 directories; other formats and links are counted without
being followed. Pilot/archive overlap is refused. Sources retain existing byte,
decoder, deadline and memory bounds. Imports run in bounded single-file service
calls, grouped in at most 2,000-file chunks. Aggregate progress contains no source
names, statement text or account identities. Per-file confidential results stay
under `imports/` in the ignored pilot directory. The originals are read only and
checked for byte changes around each attempted import. This is not a hostile
filesystem authenticity guarantee.

Imports preserve evidence only: no accounts, bindings, openings or journals are
authored. A rerun reuses already imported source digests through the normal
idempotent service. Interrupted runs retain completed evidence and flushed local
receipts. The archive-import command refuses a profile after financial accounts,
bindings or journals have been authored; manual import in the app remains the
ordinary workflow once review begins.

The imported profile **contains confidential original statement bytes**. Keep the
entire pilot and its backups private and out of Git. Do not use a daily/1.x profile.
No legacy database, root `.env`, production key, service or original archive is
modified or loaded. A database backup does not include the separate catalog or
preferences. Import success alone establishes neither complete capture nor
accepted accounting.

`--verify PILOT` returns non-sensitive profile/catalog counts. `--smoke-ui PILOT`
opens the same pinned workspace with display suppressed, exits and checks unchanged
profile bytes. Actual visible owner review, Intel/installed checks and release
authorization remain separate.
