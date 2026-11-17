# Prepared evidence through import confirmation

Date: 2026-11-16. Roadmap IDs: V2-3/UX.
Baseline: bb6bfd0, clean feature/client-financial-insights checkout.
Authorization: owner-approved prepared-import refactor following architecture review.
Implementation: complete; code committed and isolated test prepared.
Automated verification: core, integration and native checks passed.
Independent integrity: findings resolved and final adversarial reruns passed.
Design: existing interaction preserved and actual native screens inspected.
Owner acceptance: not performed for this change. Release authorization: not granted.

## Scope and controlling decisions

Normal forms already query retained immutable evidence. This change carries
core-owned prepared evidence through both interactive workspace import paths,
account-first and explicit CSV format selection. Unchanged inputs save the exact
reviewed evidence without further source parsing/PDF decoding after confirmation.
Retain source/catalog/definition/engine/extractor binding, complete candidate
recognition, physical profile and account basis, automatic-preference checks,
cancellation and atomic source/account assignment. Changed facts invalidate the
decision rather than silently accepting a replacement. No database write lock is
held across user review. Saved-source retries and ordinary form reads need no
source parser. Explicit reparse remains a comparison.

Keep source schema 27 and current persistence/read model unchanged. Extraction
revision history, projection expansion, compression, release and profile activation
are not selected. No user workflow redesign or extra confirmation is needed.

Memory decision: retain canonical evidence JSON bytes for accepted candidates
under a 32 MiB aggregate limit, with catalog-bounded candidate count; release each
unselected Python model immediately. Reconstruct only the selected frozen model.
No private temporary files or full collection of candidate object graphs. Refuse
the entire preparation before preview if the budget is exceeded; never prune the
candidate set. The UI receives bounded summaries/opaque operation IDs, not session
objects or full evidence. Clear session-owned source, serialized payloads and models
on success, skip, cancellation, failure, drift retry and closure. Public review
objects retained by UI/tests must not retain those private session resources.

Core-issued operation/session ownership, not a caller-supplied digest, authorizes
the prepared fast path. Reconstruct plans from the authentic bound review and
current store. Forged/trimmed recognition, altered hidden rows, expired sessions,
cross-operation/profile reuse and changed candidate/engine identity must refuse.
Existing guarded developer APIs can retain reparsing; their complete selected
payload must match, not just preview rows.

Evidence specialist owns recognition, source import, account import and workspace
core modules, new session helper and focused core tests. Root owns integrated/native
checks, small failure guidance, contracts and this record. Independent integrity
reviews design and final adversarial behavior. One writer per file; no recursive
delegation. Only public synthetic fixtures and new disposable profiles are allowed;
all owner test folders, private PDFs/archives, root environment and production
services/signing remain untouched.

## Result and review

Implemented `PreparedImportSession`, used by both interactive workspace paths.
Recognition parses each valid interpretation once, delivering canonical evidence
to its operation owner while discarding full candidate graphs. Decode reuse ends
before review. Detached public summaries carry an opaque operation ID; the private
session binds source/catalog/declaration/engine/extractor, complete recognition,
physical profile and review basis. Selection reconstructs one frozen evidence model;
commit saves that same complete payload with no source parsing or decoding.

Unchanged form choices, saved-source retries and ordinary saved-evidence reads also
execute no source parser. Account-first drift rebuilds review with a fresh operation;
explicit-format stale inputs refuse. Private catalogs/reviews/plans/selections are
detached from caller objects; comparisons repeat after freshness callbacks and
writes use only authorized private snapshots. One apply attempt consumes authority.
Session close clears resources even if public DTOs remain referenced. This is
owner-reference cleanup, not secure byte erasure or a Python execution sandbox.

Three integrity issues were reproduced and closed:

- Legacy caller-built evidence could alter a sixth row beyond the five-row preview
  and still pass candidate equality. The guarded path now compares the complete
  authoritative selected payload; prepared sessions never accept caller evidence.
- Initially shared frozen public objects could still be mutated in place, trimming
  recognition or redirecting a confirmed account choice. Detached private snapshots,
  private write values and post-callback comparisons now reject both exploits.
- Explicit-format source/catalog changes during writable-profile opening and
  cancellation during validation could escape the earlier final checks. A late
  freshness callback and inside-transaction cancellation/payload/profile checks
  now refuse before source insertion.

The 32 MiB aggregate canonical budget refuses the whole preparation before preview,
without partial recognition or imported state. Small GUI guidance explains how to
recover with a smaller supported export or a more specific signed format package.
No schema/persistence change, compression, private temporary evidence file,
persistent decoded-text cache or extraction revision history was introduced.

## Verification

Locked Python 3.13.15, Windows AMD64, native Qt windows plugin. Public synthetic
CSV/PDFs and locally signed fixture catalogs only, isolated HOME/USERPROFILE/
APPDATA/LOCALAPPDATA and null keyring. Commands use `PYTHONPATH=.;client/src;client`
and `client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider ... -q --tb=short`.

- Author combined prepared/account-import/workspace-account/workspace-recognition/
  automation/source-import selection: 95 passed in 255 seconds after alias fixes.
  Final stricter cancellation guard: 3 stage cases passed; final new test module
  has 34 cases, so the next complete discovery includes one additional case.
- Separate parser-pilot source pipeline/catalog admission/family checks: 58 passed.
- Root final cross-entrypoint/full-seven-row-evidence/PDF decode-operation/read
  selection: 10 passed. It forbids parser/decoder execution after review, checks
  both CSV choices, compares complete stored evidence and queries forms/retries.
  Added final cancellation-during-validation selection: 1 passed.
- Independent integrity: 8 direct authority/lifecycle groups, 9 workspace/actual
  bounded-PDF groups, 7 late freshness/cancellation pytest cases, and 7 public-alias
  repro scenarios passed. Both original alias exploits and hidden-row forgery now
  refuse. Automatic-preference drift regression was independently exercised.
- Changed Python lint/format and normal commit hooks pass; diff whitespace clean.
  Counts overlap and are not additive. No private-family parity claim is made.

Independent native artifacts: `scratch/prepared-import-runtime-20261116/`.
Baseline `bb6bfd0` ran from a separate read-only public source archive, without
switching the shared checkout. A full 23-declaration catalog and one-page public
Capital PDF were used. Matching baseline samples: 0.29861/0.29159 seconds from
final confirmation to ready, with 2 evidence builds, 2 loan parses and 1 decoder
child after confirmation. Latest prepared samples: 0.104890/0.104962 seconds,
with all three counters zero after confirmation. Preparation used one build,
one loan parser and one decoder child. These small samples are synthetic source
runtime timings, not predictions for real statement archives or flushed OS caches.

Latest PDF artifacts `final-d62df953/summary.json` and CSV artifacts
`final-a9444f78/csv-summary.json` retain exact counters/screens. Native CSV chose
the nonfirst declaration from two matches: each candidate parsed once before
review, then zero builds/parses during unchanged forms, confirmation and retry;
confirmation-to-ready was 0.098808 seconds. Complete source/evidence persisted
exactly, no journals were created, cancellation retained prior imports, and reopen
restored both saved documents. Preview and worker objects were invalidated and
their destruction callbacks ran on the GUI thread. Successful complete native
processes exited raw 0 with normal GC. One initial harness assertion chose an
arbitrary document summary and exited 1; using source hash fixed the harness.
Actual 1050x700 previews/completion/reopen screens remained readable with account,
institution, period, tracking scope and pending-review distinctions intact.
No owner usability, other-platform/scaling or installed/release claim follows.

Code commits: `fd79bbc` core/session authority and regressions; `72d956c`
integration/no-reparse/read tests and preparation-limit guidance. Current parsing
and unified-store contracts updated. Schema remains 27.

Fresh test: `scratch/v2-owner-fresh-20261116-070f3fa2/`, launcher
`Open-workflow-test.cmd`, pinned to `72d956c` (313 public runtime files), 23 fixture
declarations, ephemeral development signing key discarded, independent home/
catalog/preferences. No financial accounts/documents/budgets/journals preloaded;
only protected Loan interest is seeded. Pinned Windows startup smoke passed with
import enabled, empty documents, unchanged profile digest, six sidebar steps and
raw exit 0. App is closed; the launcher preserves this candidate across reopen.
Previous owner candidates were not read or modified; only two explicitly public
preparation helper source files were reused. Treat this folder as private after
the owner imports real statements.

## Remaining work

Owner test of the prepared candidate, large/private-history performance, additional
platform/scaling/installed acceptance and release remain separate. Extraction
revision adoption remains a separate future feature. No required implementation
or integrity finding remains open; existing populated candidates stay pinned.
