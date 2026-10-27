# Make archive-sized cash and coverage review responsive

Date: 2026-10-26. Roadmap IDs: V2-3/4/5/UX/7.
Branch/runtime: feature/client-financial-insights, source and pinned pilot.
Authorization: owner reported approximately ten-second Cash activity/Statement coverage actions on the real-statement pilot.
Implementation: measured optimization complete; integration and updated-runtime handoff active.
Automated verification: focused checks, 2,141-test client integration and final 17-test devtool integration passed.
Independent review: final store equivalence, corruption, concurrency and failure paths passed; runtime-bundle adapter under review.
Owner acceptance: performance/usability issue reported; follow-up pending.
Release authorization: not authorized.

## Scope and controlling decisions

The owner accepts embedded PDF source bytes but questioned large JSON evidence
snapshots, explicitly withholding a request to change that format. Preserve
`EvidenceSnapshots.content`, schema revision 22, exact money/dates/provenance and
the separation of extracted source facts from reviewed accounting. Measure why
the two reported actions are slow; do not assume SQL searches JSON or redesign
persistence merely from its visual size.

Use a verified, consistent disposable snapshot of the authorized owner pilot.
The active owner-reviewed profile, original statement archive and all V1 state
remain read-only. Keep private contents, paths, account identifiers and raw
reports out of Git/routine logs; local confidential profiling output stays in
ignored scratch. Report only function timings and aggregate state counts.

Primary owns shared contracts/roadmap/TODO, this record, measurement integration
and the eventual reviewable runtime handoff. The ledger specialist exclusively
owns `v2_profile_store.py` and focused added regressions; any GUI edits require
separate explicit ownership. Independent integrity review checks actual changes.
No recursive delegation. No production signing/release or daily-profile action.

Prefer avoiding redundant validated source loads within a consistent read
snapshot and precise indexed reads. Preserve corruption detection, full source/
definition/evidence/observation integrity, stale review guards, correction paths,
unknown values and transaction consistency. Do not bypass database format checks
or introduce stale process-global caches. Recheck results and byte preservation.

The owner's further comment that they are not an accountant and feel lost is
recorded as product feedback. Explain the purpose of source snapshots and the
ordinary import/assign/review/report progression plainly; larger interface
simplification remains its separate later pass rather than this performance fix.

During this packet the owner reiterated not to fix broad UI/UX now, clarified
that the proposed architecture change concerns the development-agent team and
workflow, and chose to complete an independent review of that. Agent definitions,
AGENTS.md and workflow skill instructions remain unchanged. This packet closes
only the measured performance fix and its verified runtime handoff.

## Result and review

The profile is 255,832,064 bytes: 219,458,039 original-source bytes and 28,625,066
JSON evidence bytes (largest snapshot 217,250 bytes). The JSON is a typed immutable
parser result with locations/provenance, separate from authored ledger choices;
its visual size does not explain the observed latency by itself.

On a verified disposable copy of the owner's 946-source profile, cProfile shows
cash review loading/verifying snapshots 2,844 times and coverage 5,676 times.
Overlap indexing repeatedly reloads each source through account-binding reads,
scans its observation inventory per source, and coverage rebuilds the same index
again. This is repeated archive-wide work, not a SQL JSON-search bottleneck.

The store now streams Sources with a LEFT JOIN to definitions/evidence plus one
ordered observation inventory. Every source, including unbound/empty ones, still
passes the same blob sizes/hashes, evidence and exact observation checks. The
LEFT JOIN refuses missing snapshots rather than silently omitting their sources.
Binding decisions are prefetched once, verified evidence is reused inside the
operation, and reconciliation reuses its verified overlap index. There is no
persistent cache, skipped integrity gate, schema change or JSON-format change.

Primary actual dialog construction on the same copy, without profiler:

| Action | Original pinned runtime | Optimized source |
| --- | --- | --- |
| Cash activity review | 12.4419s | 1.2598s |
| Statement coverage | 24.4460s | 1.2951s |

Dialog show/paint processing added approximately 0.01s. These are observed warm
Windows/offscreen timings, not cold-start or installed-platform benchmarks.
Old-code wall measurements explicitly used the retained pinned runtime to avoid
a working-tree edit race. The ambiguous first unprofiled probe was excluded from
the before/after comparison. All probes preserved the copy's file hash.

Actual Windows Qt with display suppressed also constructed the optimized cash
and coverage dialogs in 1.3632s/1.3190s, with approximately 0.03s/0.01s show
processing and unchanged copy bytes. No private screenshot or source details
were emitted. This is agent native verification, not owner performance acceptance.

Independent service equivalence checks matched complete normalized outputs and
basis tokens exactly, with cash 12.2125s → 0.9285s and coverage 24.3239s → 1.0103s.
The private copy has no authored financial accounts; bound/correction scenarios
are covered synthetically. The owner's actual profile was opened read-only only
to create the consistent copy and remained byte-identical during that operation.

The public runtime pinner also supports a separate existing workspace. It checks
that profile's pre-release schema read-only and copies only public runtime files
into a new versioned bundle. Its launcher uses the existing profile, preferences
and catalog without replacing the old pinned runtime. Default preparation stays
compatible. This prepares a concrete optimized handoff while preserving current
owner review state; versioned-bundle generation follows the clean code commit.

The first exact updated-launcher probe found a locked existing workspace startup
log, preventing Python invocation while the batch returned zero. Updated bundles
now keep their own startup logs and initialize a failing command status before
redirection, so a locked log cannot yield false startup success. A native Windows
sharing-mode regression proves both launching beside a held-open workspace log
and nonzero refusal when the bundle's own log is locked. No owner window was
closed or altered by the agent.

## Verification

Windows AMD64/Python 3.13.15/PySide6 6.11.2; `PYTHONPATH=.;client/src;client`,
Qt offscreen. Tests use `client/.venv/Scripts/python.exe -m pytest
-p no:cacheprovider ... -q --tb=short`:

- New performance/read regressions: **20 passed in 3.45s**.
- New plus store/overlap/reconciliation/cash-review modules: **59 passed in 30.42s**.
- Independent new/binding-correction/overlap/reconciliation: **75 passed in 53.45s**.
- Runtime pinner/pilot/demo integration: **16 passed in 46.64s**; final separated-
  workspace/schema-refusal cases **2 passed, 6 deselected in 5.20s**.
- Independent separated-workspace/schema cases: **2 passed in 5.08s**;
  read-only tooling review found no issue for the required fresh bundle directory.
- Actual Windows launcher sharing/redirection regression: **1 passed in 1.22s**;
  final full devtool integration after that fix: **17 passed in 50.59s**.
- Full `client/tests`: **2141 passed, 4 skipped in 994.67s**, including the new
  regressions. Process-only PowerShell execution policy and the existing scratch
  NSIS compiler enabled native packaging fixture checks; no installer was run.

Coverage includes bulk/single equality, unbound and zero-observation sources,
verification of unrelated sources exactly once, 15 source/evidence/definition/
inventory/missing-snapshot corruption cases across cash/coverage/overlap, WAL
concurrent commits, next-read freshness, same-connection later writes, transaction
cleanup, preserved review basis, runtime schema refusal and no profile copy/write.
Changed-file Ruff/format passed. Parser declarations/engine/worker behavior are
unchanged by this packet, so no additional parser-pilot rerun was required.

Confidential function profiles and before/after/equality reports remain under
ignored `scratch/v2-review-performance-85820e2`; no source contents/identifiers
are printed or committed.

## Remaining work

Complete profiling, implement/review the measured optimization, prepare a concrete
updated-runtime handoff that preserves the owner's pilot state, and record actual
tests/performance. Owner account review, further UI/UX simplification and the
supported-platform/release gates remain separate.
