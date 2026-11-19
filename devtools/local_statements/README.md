# Local statement batch checks

## V2 recognition and import-warning audit

`audit_v2_imports.py` checks authorized PDF/CSV originals through the same V2
format recognition, unique PDF routing, strict parser and source-warning policy
as interactive import. It opens no profile, assigns no accounts, posts nothing,
and neither moves originals nor saves source bytes or extracted text. It checks
the file digest again after recognition to refuse a changed original.

For current development declarations:

```powershell
uv run --project client --frozen --python 3.13.15 python `
  devtools/local_statements/audit_v2_imports.py C:\path\to\statements `
  --development-definitions devtools/parser_engine_pilot `
  --pattern 'CITIAA*.pdf' --pattern 'CITISIMP*.pdf'
```

Development mode admits the explicit declaration directory, including its public
account-context/product manifests, using an ephemeral in-memory test key. It is
labelled **development_definitions_not_installed_catalog**; it does not establish
installed-catalog trust or reproduce an older pinned application's engine.

To audit an explicitly selected signed release instead, replace
`--development-definitions ...` with `--catalog-release C:\path\to\release`, where
the directory contains `catalog.json` and `catalog.sig`. The shipped public trust
keys are used by default. A development release can supply `--trust-keys
C:\path\to\public-keys.json`, a JSON mapping of `data-ed25519-...` key IDs to
32-byte public keys in hexadecimal. No key, catalog or preference is installed.

The default console output contains only aggregate counts and warning-code counts.
Add `--report C:\private\v2-import-audit.json` to create a **new** local JSON report;
existing files are never overwritten. This report retains per-file hashes,
format/revision/definition hash, engine/extractor, typed period/provenance,
row/group counts, warning severity, occurrence counts and bounded source locations.
It excludes transaction values/descriptions, account identities and raw date text.
Hashes and periods are still private diagnostic metadata: keep the report out of
Git and routine logs. The default per-file labels are ordinal/digest labels; add
`--show-filenames` only when relative filenames may be stored in that report.
This option never adds filenames to console output.

Selection is shallow by default; use `--recursive` deliberately. Repeat `--pattern`
for basename globs, or omit it for `*.pdf` and `*.csv`. Glob matching ignores case.
Nonrecursive literal filenames are addressed directly without listing siblings,
including missing files, which receive an explicit failure. Literal filenames
otherwise follow the operating system's filename casing. Pattern paths containing
separators or Windows drive/stream colons are refused. Glob scans skip symlinks, junctions and unsupported suffixes;
explicit linked files refuse before reading. An unreadable scanned subtree refuses
the audit instead of claiming complete selection. File count is capped at 10,000
(`--max-files` may lower it), scanned entries at 100,000, source bytes at the runtime
16 MiB limit, and retained report metadata at 64 MiB. PDF extraction retains the
runtime worker's bounds. Ctrl+C requests cancellation through recognition/workers
and reports only metadata for completed files.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Every selected file has one valid format and no source warning requiring review. |
| 1 | At least one source requires attention, is unmatched/ambiguous, failed, or exceeded the metadata budget. |
| 2 | Setup, catalog/trust, selection or report-writing failure. |
| 130 | Cancelled; a requested report contains completed metadata when cancellation reaches the audit loop. |

An audit is not an import or a claim of complete capture, valid account assignment,
reconciliation or posting eligibility. In particular, multiple valid CSV candidates
are retained as **ambiguous**, not classified as a failed import: interactive account
intent may narrow them. The audit does not inspect profile state, saved evidence,
matching preferences or account choices. Warning counts aggregate occurrences across
the retained candidates. No undocumented source-warning bypass is introduced.

Run the public synthetic checks with:

```powershell
uv run --project client --frozen --python 3.13.15 pytest -q `
  devtools/local_statements/test_audit_v2_imports.py
```

## Retained 1.x source plugins

This headless development adapter checks a directory of authorized local
statements against plugins compiled from the current source checkout:

```powershell
uv run --project client --frozen python `
  devtools/local_statements/batch_plugin_tester.py `
  C:\path\to\statements
```

It reads each statement into memory, compiles plugins into an OS temporary
directory, and never moves statements or creates plaintext statement copies.
Output uses a short content digest by default; pass `--show-filenames` only when
the local filenames are safe to display. Validation warnings fail unless
`--accept-warnings` is explicitly supplied.

Add `--diagnose-routing` to print only public plugin identifiers surviving the
suffix, PDF metadata, header, and body stages. Extracted text and PDF metadata
values are never logged.
