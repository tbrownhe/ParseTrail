# Bounded parallel import preparation

Date: 2026-11-18. Baseline: `1c0aabc`. Scope: V2-3/UX/P2-4.
Implementation, native verification and independent integrity review completed;
owner/platform/release acceptance separate.

## Intent and design

The owner requests up to four import workers to improve a roughly 900-statement
batch. Parallelize source recognition/decoding and evidence preparation; keep
account decisions, profile validation, automatic policies and writes in file order.
Reuse the mechanism in the read-only directory audit with a selectable worker count.
Default to available CPUs capped at four, retaining a one-worker comparison mode.

A bounded ordered preparation queue owns at most four slots INCLUDING the current
consumer until it releases its slot. Each task owns its source/catalog, private
prepared authority and synchronous decoder children; coordinator threads never
touch GUI objects or share database connections. Existing process/time/memory
limits remain active. Do not enqueue all 900 sources, keep unbounded results or
decode all files before showing the first decision. Raw decoded pages are released
at each operation boundary. Serialized original/evidence retention remains bounded
by the slot count and existing per-source limits; overall Python/process memory
also includes decoder and model overhead and must not be represented as only the
serialized byte budget.

Prepared account choices are built only at ordered consumption against current
profile/accounts/preferences. Thus first-file account creation is available to
later prefetched statements. Existing source/catalog/profile checks remain before
confirmation and commit; stale speculative results or failures must be refreshed
or refused without admitting old proof. Already saved sources and repeated paths
reuse saved evidence, not speculative duplicate writes. One file failure stays a
per-file outcome in order. Cancellation stops future submissions, cancels/joins
all active producers/decoder children and disposes unused authorities/errors;
confirmed imports remain saved. No schema, parser or financial-rule change.

The existing unified compact progress/review/report journey remains in place.
Its current filename and completed count refer to ordered consumption, even when
later sources are prepared in the background. No additional account prompts or
out-of-order completion cues are introduced. Verify this actual native flow.

## Ownership and allowed data

Evidence owns the shared ordered queue, workspace/prepared integration and new
headless concurrency tests. Primary owns audit integration/tests, lasting contracts,
planning, this record and the user conversation. Desktop owns new native tests and
a reproducible public synthetic import benchmark. Integrity independently reviews
queue authority, cancellation, stale proof, privacy and persistence. One writer
per file; no recursive delegation, branch switching or independent commits.

Use only public synthetic statements and isolated disposable profiles/catalogs,
locked client Python, isolated app data and null keyring. No owner originals,
archives, populated trials, screenshots/logs or private catalog inspection in
this task. Only the previously identified public fresh-test helper code may be
reused to prepare another empty candidate. No root .env, live mutations, service
or signing/publication/daily-profile activation. Benchmarking is synthetic; do
not extrapolate it as measured performance of the owner's archive.

## Verification criteria

- Prove actual overlapping work, 1..4 validation, slot/backlog bounds and ordering
  with deterministic barriers; no unbounded future/result retention or worker leaks.
- Compare exact evidence, source identities/bindings, row/date/amount facts and
  journal counts between one/two/four workers with real bounded public PDF decoding.
- Check new/remembered accounts, automatic imports, duplicate paths/saved sources,
  failure and skip order, stale success/failure, source/catalog/profile/preferences
  drift, cancellation at wait/review/write and cleanup of exception chains.
- Independent cancellation of four actual decoder children must reap them before
  batch completion; native GUI lifetime/shutdown checks retain normal GC/raw exits.
- Audit retains source drift, bounded private metadata, safe paths/trust, cancellation
  and deterministic summaries/exit semantics with the shared queue.
- Measure comparable synthetic wall time for one/two/four workers, record workload,
  actual platform/caps and limits. No guaranteed fourfold speedup claim.
- Relevant focused/integration regressions, changed-file lint/hooks and native
  mixed-account/progress/cancel journeys. Owner and other-platform gates separate.

## Result and verification

The shared `OrderedPreparation` queue uses coordinator threads and the existing
bounded decoder subprocesses. Default workers are available CPUs capped at four;
the core batch API accepts `preparation_workers=1..4`, and the audit CLI accepts
`--workers 1..4`. The slot window includes the consumer until disposal, then refills.
Threads join before unused successful authorities or detached exception outcomes
are discarded. Producer tracebacks, causes and contexts cannot retain source frames.

Workspace uses an immutable initial saved-source-hash inventory to avoid decoding
already saved files. Each producer prepares only source/catalog data. A private
single-use context handoff preserves the ordinary import_file wrapper and its
post-import automation. The consumer rechecks saved/duplicate sources, exact current
bytes and catalog before taking authority, builds current account choices and uses
the existing confirmation/commit guards. Changed speculative successes and failures
are refreshed. Source-only and explicit-format batches use the same queue. Small
per-file result DTOs are built and full evidence results released before refilling.
No profile-format, parser, accounting or preference-storage change.

Audit preparations also use their own decode-operation caches and produce sanitized
metadata. Source drift, trust, private-report fields, limits and ordered failure/
cancellation semantics are retained. Serial and concurrent reports are identical
for the same catalog and inputs. No private archive was inspected or benchmarked.

### Checks and independent findings

- Core/new and existing workspace/recognition/account/prepared-integration/loan and
  statement-value automation suite: 88 passed, 60.69s, raw0. Two additional stale
  successful-preparation cases plus existing format-cancel boundary: 18 passed,
  7.40s, raw0. Final stronger full-evidence parity core module: 17 passed, 6.41s.
  Tests cover reverse completion, fresh account choices, 900 items/four-slot cap,
  saved retries without decode, failure/error-buffer disposal, source/catalog drift,
  cancellation and exact one/two/four-worker source-only evidence parity.
- Root complementary standalone prepared authority, format recognition, loan/value
  automation integration and audit suite: 76 passed, one skipped, 15.68s, raw0.
  The skip is the unchanged Windows real-symlink privilege limit; rejection/bounded
  path and source-drift tests still run. Audit-only focused: 16 passed/one skipped,
  0.73s, including four-way overlap/reverse completion, ordered parity, cancellation
  joining all four preparations, completed metadata prefix and invalid worker count.
- Native combined final run: 17 passed, 22.27s, raw0 (six new cases, seven unified
  progress cases and four first-use OCCU dialog cases). Workspaces 1050x700 and
  1100x650, compact progress approximately 600x215, account review 1050x700.
  Four preparations overlap while current file1 is shown, GUI heartbeat remains
  responsive, first review creates two accounts and later statements reuse them.
  Cancel/close before and after confirmed writes keeps exactly zero/one saved source
  and joins lookahead before GUI-thread invalidation. Normal GC retained; no scoped
  usability finding. Only subsequent production change released a full pure-data
  result before refill; targeted headless checks cover that lifetime adjustment.
- Actual rendered screens inspected beneath
  `scratch/parallel-import-native-20261118/final-native`; Windows11, locked Python
  3.13.15, Qt6.11.2 Windows plugin, SegoeUI9, DPI96, DPR1. Qt software-test input,
  not human/OS-input acceptance. No other-platform or installed candidate claim.

Independent integrity checks exercised four actual decoder processes with a public
12-page/370KB PDF. All four were alive and communicating before cancellation;
all were reaped, no preparation threads remained (0.34s). Retaining a delivered
error did not retain a producer buffer or its cause/context. Actual bounded public
PDF cases verified changed prefetched bytes, a formerly missing file created during
earlier review, and a signed-catalog swap after all four preparations: new inputs
were reviewed/retained, account IDs remained two and no journals were invented.
Cancel after a confirmed import kept exactly one source/two accounts and stopped
the remaining five; a middle review-callback failure yielded imported/failed/imported
with two saved sources, no journals and a redacted error. Unused authorities and
threads closed. A baseline format-callback cancellation regression was corrected
to check cancellation before interpreting None as Skip. No material scope expansion.

### Public synthetic benchmark

Reproducible helper: `devtools/local_statements/benchmark_v2_imports.py`. Workload:
eight generated three-page OCCU PDFs with 100 checking activity rows each and a
balance-only savings section, identical source bytes/catalog definition across runs.
One explicit account review, two accounts, 800 observations and zero journal entries.
Full saved evidence and account bindings match across one/two/four workers.

| Workers | Preparation only | Full import | Peak prepared slots/active decoder calls |
| --- | ---: | ---: | ---: |
| 1 | 2.1129s | 3.2952s | 1 / 1 |
| 2 | 1.0407s | 2.1109s | 2 / 2 |
| 4 | 0.5877s | 2.2002s | 4 / 4 |

Four workers gave approximately 3.60x preparation and 1.50x end-to-end speedup in
this single ordered trial. Two workers happened to be slightly faster overall;
there is no statistical or fourfold whole-import performance claim. Serial profile
validation/decisions/writes limit total speedup. Peak retained source/canonical
evidence was 123332/246664/493328 bytes; these measurements exclude transient decoded
pages, Python model overhead and process RSS. Existing decoder memory caps remain
512MiB per process by default; four active decoders bound that component to four
caps, in addition to application/preparation overhead. No system-wide RAM/RSS claim.
The large-item queue test proves bounded scheduling, not 900-original throughput.
Report: `scratch/parallel-import-native-20261118/benchmark-eight-100/benchmark.json`.

Independent final review reports no actionable findings; its focused suite passed
33 tests with the same one Windows symlink skip. All seven changed/new Python files
pass Ruff check/format and git diff whitespace checks pass. No owner data was used.
Fresh pinned test preparation and commit closeout are recorded below. Owner acceptance,
other supported platforms, signing/publication and daily-profile activation remain
separate.

## Commits and fresh test

- `79535ae`: shared bounded ordered preparation queue, all batch import paths and
  headless concurrency/freshness/parity tests.
- `e46b997`: shared audit preparation, public benchmark, native lifetime/progress
  tests and affected contracts/status. Normal pre-commit hooks passed for both.
- Fresh empty candidate:
  `scratch/v2-owner-fresh-20261118-parallel-53b02ca7/Open-workflow-test.cmd`.
  Pinned to `e46b997`, unchanged schema 28, 322 public runtime files and 23
  development definitions; no sources, journals or account-consolidation records.
  Only protected Loan interest exists. Ephemeral catalog signing key discarded.
  Native Windows hidden startup smoke passed: ready, empty Documents, Import
  enabled, expected sidebar, unchanged profile bytes and raw Qt exit0. START-HERE
  explains automatic worker selection, ordered questions/progress/cancellation,
  default-off existing preferences, audit controls and measured benchmark limits.
  Existing trials are untouched; all owner-added sources/profile/logs/screenshots
  in this new candidate remain private after handoff. No owner acceptance claimed.

## Report destination follow-up

The owner attempted the full shallow PDF audit with four workers and a literal
example `C:\path\to\new-audit.json` output. Its parent does not exist; the previous
tool deferred opening that destination until after scanning and redacted the error
as generic audit_file_failed. Report destination existence/parent checks now occur
before catalog or source reads, and report_exists/report_parent_unavailable/
report_write_failed have static actionable guidance. Exclusive creation still
prevents overwriting; operating-system path/exception text stays redacted.

Public synthetic audit suite: 19 passed, one existing Windows symlink skip, 0.86s.
Tests prove missing/non-directory destinations refuse before catalog/source access
and a late permissions error reports safe guidance. Ruff check/format and whitespace
checks pass. No parser, financial, schema or desktop behavior change.

For this follow-up only, the owner-supplied SUCCESS directory/shallow *.pdf command
is rerun read-only with four workers and development definitions, writing metadata
to a new ignored scratch report. This is separate from the prior synthetic-only
implementation/benchmark. No original/source copies or extracted-text dumps are
saved, no financial profile is opened, and the private report is excluded from Git.
The rerun completed and its JSON report was parsed/validated: 945 selected/completed,
943 recognized, 275 require review, two failures, zero remaining/ambiguous/cancelled
and no metadata truncation. This matches the owner's original aggregate summary;
exit1 reflects remaining source review/failures, not setup failure. The two failed
records retain redacted audit_file_failed rather than private exception text.
Report: `scratch/import-audit-20261118-f1f03ecf.json`, confirmed Git-ignored, with
945 per-file metadata records and explicit filenames. No report contents, original
financial data or private exception paths are committed. Per-file interpretation
and remaining parser refinements are separate from this destination fix.
