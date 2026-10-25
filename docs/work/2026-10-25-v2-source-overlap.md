# Cross-source occurrence safeguard

Date: October 25, 2026. Roadmap IDs: V2-3/4.
Branch/runtime: `feature/client-financial-insights`, explicit fresh V2 workspace.
Authorization: owner selected bounded duplicate/overlap safeguards; no general
import rewrite or private/live-profile actions.
Implementation: complete; committed at `d9dab3e`.
Automated verification: passed, as recorded below; not rerun for documentation consolidation.
Independent review: completed, no remaining actionable findings within reviewed scope.
Owner acceptance: consolidated V2-UX pending; no native acceptance of this packet recorded.
Release authorization: not authorized.

## Scope and controlling decisions

Provide read-only candidates and existing-allocation checks, then explicit
repeat/distinct/pending review with a guard against new duplicate allocations.
Preserve original occurrences, exact values, immutable evidence and correction
history. The [occurrence contract](../client-v2-source-overlap.md) defines matching,
unknowns, account-binding locks and report limits.

Primary owned contracts/records/integration; the ledger specialist owned the
single store, pure descriptors and service tests; desktop owned the new dialog,
workspace entry and interaction tests. Integrity independently reviewed the
actual changes. Writes used synthetic/disposable V2 profiles only.

## Result and review

Added schema 11 `SourceOverlapReviews`, full-index posting guards, capped
pending-first inventory, explicit retained occurrences and side-by-side evidence.
Supporting references do not consume money. Same-source occurrence multiplicity,
conflicting interpretations, stale selections, failure rollback and retained-row
corrections were reviewed. Binding adapters explain saved-review locks.

Affected files: `core/v2_profile_store.py`, `core/v2_source_overlap.py`,
`gui/v2_source_overlap_review.py`, workspace and source/account-binding dialogs,
three synthetic test modules, and `devtools/parser_engine_pilot/review_source_overlap.py`.
`core/` and `gui/` are under `client/src/parsetrail/`.

## Verification

The following evidence is transferred from the original acceptance entry.
It records the original checks, not new execution during this documentation packet.

### Original verification record: V2 cross-source occurrence safeguard — October 25, 2026

Implemented the selected bounded V2-3/V2-4 packet on
`feature/client-financial-insights`: read-only cross-source candidates, explicit
distinct/repeat/pending history, and transaction-owned cash/card/transfer guards.
The [occurrence-review contract](../client-v2-source-overlap.md) records the exact
matcher, multiplicity rules, account-binding locks and remaining limits.
Pre-release schema 11 refuses earlier disposable profiles without migration.

Final Windows source/offscreen integration command from the repository root:

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider client/tests -k v2 -q
```

Result: **167 passed, 1,107 deselected in 56.66 seconds**. This includes 21 new
service checks, five repeated-row dialog checks and two account-binding adapter
checks. Focused service verification separately passed all 21 tests using
`client/tests/test_v2_source_overlap.py -q`. Cases include original evidence
preservation, same-source multiplicity, distinct/repeat contradictions, stale
forms, corrected retained rows, card dates, different-date transfer clearing,
injected write rollback, independent snapshot/reopen, display truncation and
full posting guards, schema refusal and SQLite NULL constraint enforcement.

Independent integrity review inspected the integrated diff and ran focused
synthetic checks. It found and resolved occurrence collapse, misleading
same-movement labels across separate retained groups, unreachable pending work
beyond the display cap, and binding-control presentation issues. Final review
found no remaining actionable defects within the inspected scope. The primary
also hardened the repeat constraint against NULL retained IDs. Two rendered
offscreen views were inspected for wording, layout and readable controls; the
render used a registered Windows Segoe UI font because the offscreen host lacked
a default font. No product font setting changed.

Ruff `check` and `format --check` passed for all ten changed Python files;
`git diff --check` passed. Manual changed-file checks passed for file size,
UTF-8 BOM, final newline, mixed line endings, whitespace and merge markers.
During initial verification the pre-commit runner was unavailable in the client
environment and the offline `uvx` fallback could not access its existing cache.
At the owner's subsequently authorized commit, the installed Git hook ran
successfully: large-file, case-conflict, merge-conflict, final-newline,
whitespace, line-ending, BOM, Ruff check and Ruff format hooks passed. TOML,
YAML and Biome hooks had no applicable changed files.

Writes used synthetic/disposable V2 profiles only. No private statement replay,
1.x/live-profile writes, parser changes, server operations, signing, packaging,
publication was performed. This is automated and agent verification;
owner native acceptance, Intel checks and release authorization are unperformed.
Consolidated UI/UX review remains pending. Shifted dates/different date roles,
repairing existing double postings, and correcting bindings fixed by review
history remain unfinished; account positions are a later separate packet.


## Remaining work

[ROADMAP V2-3/4](../../ROADMAP.md#v2-3) retains shifted-date/different-date-role
matching, existing double-posting correction and repair of account bindings fixed
by review history. V2-5 account positions remains a candidate, not a selected
follow-on. V2-UX and platform/release gates retain their separate acceptance.
The contract includes a disposable multiplicity scenario for later UX review.
