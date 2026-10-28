# Responsive accountless review and visible document associations

Date: 2026-10-27. Baseline: 331fc60, clean feature/client-financial-insights.
Scope: owner reports sluggish row selection in Review > Assign rows without an
account and unclear document association after assigning all Mohela rows.
Implementation: complete in development; verified public runtime prepared.
Automated verification: 138 integrated tests passed; hooks/lint/format pass.
Native/design verification: Windows accountless interaction and integrated views inspected.
Independent review: financial guard parity, stale writes, corruption, WAL and associations passed; no material blocker.
Owner feedback: built-in PDF/CSV readers confirmed working; batch workflow good
for now. No new reader/batch features selected. Owner acceptance of this fix pending.
Release authorization: not selected.

## Findings and decisions

`V2AccountBindingReview._update_controls` opens SQLite and creates a full binding
correction snapshot on each selection/combo update. That revalidates source and
financial history on the GUI hot path. Replace it with a consistent verified
read snapshot on reload and pure cached selection guard queries. Mutation APIs
must still recheck actual current financial/correction history before writing.
Do not duplicate financial policy in widgets or turn one slow selection into
N expensive snapshot reads per reload.

Current document summaries already derive bound account names from confirmed
row assignments. Missing printed identity remains distinct from missing authored
assignment. All rows assigned to one account establish a discoverable derived
document association without creating a whole-file assertion. Preserve mixed,
partial, empty and unknown cases, and distinguish account assignment from pending
activity allocation/reconciliation. Saved sources remain in Documents by default;
an asynchronous clarification asks whether the reported issue is unknown-looking
association or a desire to hide assigned documents.

ui_ux preimplementation review recommends explicit whole-file/individual-row
association wording, Review row account assignments once rows are confirmed,
and search across every associated account name rather than only the first two
visible in a title. Existing row assignments do not require conversion to a
stronger whole-file assertion. No schema, source-account number, financial posting
or automatic accountless batch inference is selected.

## Ownership and permitted data

Desktop owns accountless review GUI and its tests. Ledger owns authoritative
store read snapshot/document summary additions and focused new tests. Primary
owns workspace/document labels/search, integration/docs/planning/commits and
public runtime handoff. Integrity independently reviews financial guard/cache
and evidence boundaries; ui_ux inspects actual integrated screens. No recursive
delegation, overlapping writers or independent commits.

Use public synthetic/disposable data and archive-sized synthetic benchmarks only.
No private owner archive/profile/original reads, mutations or app activation.
Updated public runtime may read the owner's schema marker only and must preserve
the same saved profile/catalog/preferences/home and earlier runtime bundles.

## Criteria and results

- Row selection and account-combo changes perform zero DB opens/source reads.
  Reload verifies sources once per operation, with aggregate guards and bounded
  cancellation where used. Record actual click/reload timings and dataset size.
- Current service mutation checks still refuse posted/overlap/opening/value/
  correction-history changes after stale UI snapshots. Errors clear cached UI
  and prevent accidental writes; selection is retained where useful after save.
- Reopening Documents/Review shows exact saved association basis/completeness,
  including all-row one-account, partial and multi-account cases, without
  invented identities or file assertions. Search finds every associated account.
- Focused meaningful tests, integrated workspace regressions, independent guard
  parity/stale probes and actual native Qt inspection use isolated synthetic data.

The owner's clarification identifies stale/unassigned-looking presentation: after
restart the fully row-assigned Mohela source left batch candidates. A public
baseline 331fc60 pinned-runtime reproduction shows the normal one-window return
already commits/refetches correctly: batch candidates 1→0, correct saved account
name and zero unassigned activity rows. Its action still reads Assign rows without
an account and its list emphasizes unallocated activity, which is a different
stage. Evidence: `scratch/accountless-refresh-baseline-f01d19e4/result.json`.

The implemented store read model `accountless_binding_review_snapshot` validates
one committed snapshot and returns immutable row/file guard facts with pure
`ordinary_blockers_for_rows`. The GUI no longer opens or parses the profile on
row selection, combo change or repaint. Save/correction methods are unchanged
and remain authoritative. Successful reload preserves selected/current rows;
failed reload clears models/accounts/guards and disables actions.

Document summaries now expose associated account IDs, source/file/rows/mixed
basis, completeness and exact assigned-row counts. Source identities, file
assertions, journals and batch eligibility policy are unchanged. Documents and
Review explicitly say All rows assigned individually, qualified partial or
multi-account associations, or whole-file assertion. The row action changes to
Review row account assignments after saved rows exist. Search includes all
associated names, including the third account omitted from a compact title.

Profile/WAL file metadata checks on window/batch activation detect changes made
while that view was inactive and queue background refresh only when changed.
Revision is captured before reads and rechecked after completion. Existing batch
choice/draft retention applies to refreshed plans; successful Apply remains visible.
This metadata never authorizes writes. Tests show already-open document/batch
views update after an external save without restart, and unchanged activation
does not reread the database.

Verification so far, using locked Python, isolated homes/null keyring and public
synthetic/disposable profiles:

- Before: 100 sources × 100 rows, 26.4 MB database; ten programmatic selections
  took **3.830s** (maximum 0.4113s), **10 store opens / 1,030 source verifications**.
  After: 100 actual native Windows mouse clicks plus combo changes took **0.178s**,
  median **1.7ms**, maximum **10.2ms**, **zero opens/verifications**, unchanged
  profile bytes. Construction improved 0.3834s→0.1668s with one selected-source
  verification in this no-financial-history benchmark. Evidence:
  `scratch/binding-click-performance-20261027/`. Substantially populated financial
  history remains a separate performance limit.
- Desktop focused suite: 9 passed; related accountless/inline suite: 25 passed.
  Ledger focused snapshot/summary/GUI suite: 47 passed in 41.90s. Initial root
  browser/workspace/batch regression suite: 34 passed in 31.19s; new actual
  review-return/external-change/search integration: 3 passed in 5.29s.
- Independent reviewer matched cached/authoritative journal, overlap, transfer,
  correction and zero/nonzero source-opening protections, stale mutation refusal,
  corruption clearing, WAL-consistent snapshots and read-only unchanged hashes.
  One file-vs-row opening nuance was found and fixed: row guards inspect raw
  row assignments; file guards inspect the separate file assertion. Dedicated
  tests now cover it. Existing GUI/correction suite: 40 passed; independent
  snapshot/summary/browser/workspace suite: 28 passed. Evidence:
  `scratch/ux-audit-accountless-performance-20261027/`.

Final integrated snapshot/summary/accountless GUI/workspace/browser/batch/inline/
binding/correction suite: **138 passed in 138.67s**. Ruff check/format and diff
whitespace checks pass. No assignment-write API, schema, batch policy or migration
changed. Cache facts describe a read; authoritative services still refuse unsafe
or stale mutation.

Native ui_ux checked 1024x768 Documents and 1080x620 row review with public three-row
Mohela evidence: partial→all-row one-account→multiple accounts; all names searchable;
exact selected association and separate unallocated activity; existing batch refresh
after real Qt activation; empty state; injected read failure and Reload recovery.
Fifty actual native row clicks with DB open forbidden had median 1.63ms/max 6.61ms.
No file assertions/journals were created. Evidence:
`scratch/accountless-association-ux-cdfc8991/`. Dirty choices in another batch group
were not exercised in this native fixture; existing reload-choice preservation
regressions passed. DPI/screen-reader/owner-visible acceptance remains untested.

Prepared a new public runtime without replacing prior bundles or touching owner
accounting data:
`scratch/archive-demo-f92c025/runtime-updates/20261027-accountless-review-refresh/Open-updated-demo.cmd`.
It copies 283 public code/resource files, reads only the same demo's schema marker
(22), and keeps its existing profile/catalog/preferences/home. The owner launcher
was not executed. A separate disposable pinned-module journey performed 100
selections with DB opens forbidden, assigned two Mohela rows, refreshed already-open
document/batch views without restart, verified exact unchanged source evidence,
two row assignments, zero file assertions/source bindings/journals and visible
account association. Evidence: `scratch/accountless-pinned-check-801c2c0f/result.json`.

No private data was inspected, no owner review decisions were changed and no new
release/platform acceptance is attested. Native Windows/agent verification is
separate from owner acceptance and Intel/installed-release gates.
