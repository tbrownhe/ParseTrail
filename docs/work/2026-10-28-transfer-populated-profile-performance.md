# Transfer performance on the populated review profile

Date: 2026-10-28. Baseline: d34f661, clean feature/client-financial-insights.
Scope: owner reports current demo still takes about ten seconds for transfer
opening, date-gap changes, posting and refresh. Prior synthetic performance case
did not represent the remaining bottleneck. Implementation, independent review,
integrated/native checks and public runtime handoff complete.
Owner acceptance: previous improvement not sufficient on the current demo.
Release authorization: none.

## Investigation and boundaries

Measure the identified current demo read-only using aggregate call counts/timings,
not financial values, names, raw contents, identifiers or private paths in output.
Do not post, migrate or mutate that profile, original archive or settings. Its
ordinary financial data remains local. Public synthetic/disposable profiles must
represent both archive volume and substantial posted/cancelled/replaced history;
mutating benchmarks and all automated tests use those profiles only.

Investigate window entry/shell, source validation, candidate computation, history,
GUI publication, confirmed mutation and post-refresh separately. Preserve complete
matching, source/evidence/inventory verification, financial proofs, corrections,
stale detection, clearing, preference and atomic/cancellation boundaries. Prefer
indexed and operation-scoped computation; no silent cap or persistent trust cache.
If a substantial GUI interaction changes, design-review it before implementation.

Ledger owns store/history algorithms and new focused performance tests. Desktop
initially owns scratch-only GUI/runtime profiling; tracked GUI edits require a
disjoint assignment. Integrity independently reviews financial/verification parity.
Primary owns the read-only actual-demo profiler, integration/UI as needed,
contracts/planning, commits and public runtime handoff. No recursive delegation or
overlapping writers. Public runtime update preserves all saved owner state and
earlier immutable runtimes; no owner launcher activation by tools.

## Results

### Diagnosis and implementation

The current 258,920,448-byte profile has 946 saved sources, 19,169 source rows,
631 transfer events and 994 journal entries. Matching combinatorics were not the
main cost. A profiled baseline snapshot spent 18.71s across four history reads;
5,050 account-binding calls consumed 15.26s. It repeatedly scanned whole binding,
journal and allocation collections while validating each historical event.

The store now builds source rows/scopes/current bindings, event journals and
allocation indexes once per validation pass. Active allocation multiplicity is
preserved. Complete validated history can be reused within the initial unwritten
epoch of the owning transaction. Any local DML disables reuse for the rest of
that operation, even after a savepoint rollback; final post-write validation is
fresh. Success, failure and cancellation clear all operation state. Global
original/declaration/evidence/inventory verification remains mandatory. No public
API, schema, accounting policy, matching cap or GUI interaction changed.

### Read-only current-demo comparison

Using the demo's saved preferences, baseline pinned d34f661 and current code
produced identical complete snapshot fingerprints at each tested gap. Only the
fingerprint, aggregate counts and timings were written; source facts and profile
bytes were never serialized into diagnostic output or Git. No owner posting or
profile/settings mutation was performed.

| Maximum gap | Baseline including open | Updated including open | Candidates |
| --- | --- | --- | --- |
| 7 days | 19.692s | 2.259s | 189 |
| 3 days | 20.257s | 2.320s | 147 |
| 14 days | 20.050s | 2.221s | 209 |

Evidence is local ignored aggregate JSON under
`scratch/transfer-real-profile-20261028/`. These are warm development-machine
measurements, not cold installed-app or universal performance guarantees.

### Public representative and independent checks

A separately authored public fixture matches 946 sources / 19,169 rows / 631
posted events / 994 journal entries / 39 accounts (31.3MB, unique amounts and
same-day/different-day transfers). Baseline snapshot including open was 14.829s;
updated was 1.169s. Entire serialized snapshots, including basis, candidates,
events and reviews, were exactly equal; original fixture bytes were unchanged.
Its smaller source payloads explain why this does not replace the actual-demo
read-only timings above.

Native Windows workspace entry on that fixture constructs the transfer dialog in
2.6-4.5ms, completes its worker in 1.28-1.41s, publishes all 189 candidates and 631
events in 20.7-21.1ms, and becomes ready in 1.47-1.60s. Screenshots and timings:
`scratch/transfer-history-runtime-20261028/workspace-entry-*`. Primary inspected
the actual populated Qt screenshot. There is no justified widget rewrite for
this bottleneck. An artificial republish without the real route's table clearing
is excluded from performance claims. Closing an unchanged dialog still queues
an asynchronous 2.7s workspace inventory refresh; skipping that refresh is a
separate possible optimization, not the reported transfer computation bottleneck.

Independent integrity review found no actionable issue in final code. Its public
61-event fixture includes active, cancelled and replaced events, current and
invalidated dismissals, and a corrected binding on a cancelled event. Baseline
and current snapshots, positions and reviewed journal are exactly equal. Mutation
probes cover cancellation after insert with exact rollback, successful post and
idempotent retry, active-binding tampering, savepoint rollback and later journal
corruption on the same store. All nine new history regressions independently
passed in 11.87s. Evidence:
`scratch/ux-audit-populated-transfers-20261028/`.

Integrated transfer/history/batch/async/corrections, overlap matching/index,
binding corrections and read-performance regressions: **168 passed in 204.20s**
with the locked client environment, isolated test homes/null keyring and offscreen
Qt. Focused settlement/cash integration checks also passed (45 tests). Changed
Python lint/format and Git diff checks passed.

Prepared a new immutable public runtime:
`scratch/archive-demo-f92c025/runtime-updates/20261028-transfer-history-performance/Open-updated-demo.cmd`.
It copies 284 public code/resource files, checks schema marker 22 read-only, and
opens the same existing profile/catalog/preferences/home. Earlier runtimes and
saved owner review state are preserved; the owner launcher was not executed.
The separate pinned-module disposable-profile walkthrough used the real final
confirmation button: one isolated pair posted and two competing suggestions
remained pending. Register repayment navigation, category creation with retained
edits/no journal and completed-repayment history also passed. Evidence:
`scratch/transfer-pinned-check-e166a99e/result.json`. Final source/commit byte
verification is recorded beside the launcher after committing.

Representative public-only posting comparisons use fresh disposable copies and
the same confirmed action in baseline/current processes. A frozen SQLite clock
on those test connections alone makes authored timestamps comparable; production
clock behavior is unchanged. Complete before/after snapshot equality excludes
only the physical profile identity; event IDs and every SQLite table's row digest
are also exactly equal. Originals, observations and the pristine fixture remain
unchanged.

| Public action | Baseline post | Updated post | Baseline reload | Updated reload | Total before / after |
| --- | --- | --- | --- | --- | --- |
| One isolated pair | 12.492s | 1.411s | 16.719s | 1.254s | 29.211s / 2.665s |
| All 189 isolated pairs | 21.519s | 1.501s | 20.840s | 1.208s | 42.360s / 2.709s |

The single post leaves 632 events / 188 candidates; the batch leaves 820 events /
zero candidates. These are disposable public posting measurements, not writes to
or posting-time claims for the owner's private profile. Evidence:
`scratch/transfer-history-post-20261028/service-comparison.json`.

Native Qt selected-pair confirmation and automatic reload complete in 2.828s:
6.44ms click dispatch, 1.572s write worker, 1.166s reload worker and 20.2ms table
publication. The test supplies the explicit confirmation answer; it is agent
verification, not owner acceptance. The resulting full snapshot, every table's
fingerprint and entire DB binary hash equal the corresponding headless current
result. Saved status is truthful; pristine fixture remains unchanged. Evidence:
`scratch/transfer-history-post-20261028/native-single-result.json` and screenshot.

Memory peak was not measured. Native Windows evidence does not establish owner,
Intel/macOS, installed-release, scaling or screen-reader acceptance. No release,
signing, publication or daily-profile activation was authorized or performed.
