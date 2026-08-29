# Local statement batch parser

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
