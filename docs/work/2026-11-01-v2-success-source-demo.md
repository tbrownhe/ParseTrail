# Current V2 demo from the selected statement sources

Date: 2026-11-01. Roadmap: V2-3/6/UX/7. Branch: feature/client-financial-insights.
Authorization: owner requested a demo using the explicitly named SUCCESS source directory.
Implementation: separate local artifact prepared; no application changes selected.
Automated verification: 9 synthetic tool checks, all 946 imports, baseline restore/recovery and populated launcher passed.
Design verification: reuses the current guided-review implementation; populated Windows inventory startup passed with display suppressed.
Independent review: completed-profile evidence, all 946 original hashes, 290 runtime files, 23 catalog declarations and launcher/isolation passed.
Owner acceptance: not performed.
Release authorization: not authorized.

## Scope and controlling decisions

Use the current working-tree implementation verified in the
[guided-review packet](2026-11-01-v2-guided-review-optimization.md). Create a new,
independent profile/runtime/catalog/preferences/home in ignored local scratch.
Read only the owner's selected statement directory; do not discover data through
daily profiles, legacy databases, prior demos or root environment files.

Import evidence only. Do not infer accounts, bindings, categories, openings,
reconciliation decisions or journal entries. Keep original files unchanged.
Private originals, identifiers, filenames and per-file receipts remain inside
the ignored demo. Only aggregate counts/results belong in routine output or Git.
No contribution/upload, service, production signing, release or daily activation.

Primary owns preparation, intake, private local guide, this record and index.
Independent integrity review is read-only on the explicitly created artifact
and authorized sources; it must not mutate any financial profile or delegate.

## Result and review

Prepared `scratch/v2-success-demo-20261101` using the existing statement-pilot
tool. Initial schema 22, 23 fixture-signed declarations, zero sources, accounts,
bindings and journals. Its hash manifest pins the current public runtime; only
the ephemeral fixture public key is retained. The existing locked client Python
environment supplies interpreter/dependencies.

All 946 discovered eligible files imported successfully in 1,148.375 seconds.
The resulting profile contains 946 sources, 19,169 observations and 18,716 pending
activity rows across 21 exercised parser families. Profile size after intake was
255,832,064 bytes. The copied helper uses bounded ordinary import services and
flushed private receipts, checks original byte hashes before/after each import,
and never moves originals. All 946 original-preservation checks passed.

`Open-SUCCESS-demo.cmd` opens this isolated profile with its pinned runtime.
`START-HERE.txt` explains the review workflow; the private `SOURCE-INDEX.txt`
connects original filenames to document labels. No accounts, bindings, categories,
opening entries or journal entries were authored; all 28 authored-state tables
are empty. Imports remain unposted evidence awaiting explicit owner review.

## Verification

Preparation command:

```powershell
& .\client\.venv\Scripts\python.exe -B devtools/v2_statement_pilot/prepare_pilot.py --prepare-at scratch/v2-success-demo-20261101
```

Intake uses the copied helper with `--import-archive <owner-selected directory>
--pilot scratch/v2-success-demo-20261101`. Its output contains aggregate progress;
detailed paths and results stay under the ignored artifact's `imports/` folder.

Focused existing-tool checks used the locked client interpreter, isolated
synthetic temporary profiles and null keyring:

```powershell
$env:PYTHONPATH='.;client/src;client'
$env:QT_QPA_PLATFORM='offscreen'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider devtools/v2_statement_pilot/test_statement_pilot.py -q
```

Result: 9 passed in 8.97 s, covering source-preservation/retry, restore/recovery,
bounds, overwrite refusal, runtime isolation and launcher failure behavior.
Independent public-artifact review confirmed all 290 runtime hashes match current
working-tree bytes, the fixture signature and 23 declaration bytes are valid, the
runtime contains only expected public files and both preferences remain off.
Its private aggregate report is under the new demo's `integrity-review/` folder.

Completed-profile verification matched successful per-file receipts to retained
sources and validated document/evidence projections. A verified baseline snapshot
at `verification/baseline.dbb` reopened as an independent restored database with
all 946 sources and matching observations. Original recovery from the profile
matched source hashes for one document from each of the 21 exercised parser
families. These checks left the main profile byte-for-byte unchanged.

The actual `Open-SUCCESS-demo.cmd` launcher passed with the Windows Qt backend
and display suppressed by an external verification hook. All 946 documents loaded,
zero accounts were present and the inventory became ready in 1.438 seconds.
All 110 imported first-party modules came from the pinned runtime. The profile
hash remained unchanged. This establishes populated startup, not a visible native
interaction walkthrough or owner acceptance.

Independent completed-artifact review rehashed all 946 authorized originals:
every current size/hash matched its intake receipt. Exact receipt/source/snapshot
inventories matched; retained bytes, definition identities, strict evidence and
the full observation indexes passed pinned read-only store validation. SQLite
integrity and foreign-key checks passed. The reviewer independently confirmed
all 28 authored tables empty, all 290 runtime files unchanged, all 23 signed
catalog declarations valid and the friendly launcher identical to the generated
launcher. The main profile hash remained unchanged across that review.

## Remaining work

Demo preparation and agent verification are complete. Import success does not
establish complete capture, reconciled books or accepted accounting. Owner account
assignment and accounting review remain explicit actions inside this isolated demo.
