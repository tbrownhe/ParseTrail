# Review the guided interface with the owner's statement archive

Date: 2026-10-26. Roadmap IDs: V2-3/6/UX/7, P2-4/5.
Branch/components: feature/client-financial-insights; local disposable demo.
Authorization: owner approved the improved interface, requested cohesive commits before further work, and selected their V1 SUCCESS archive as the new demo's source material.
Implementation: complete; new isolated archive-backed demo ready.
Automated verification: 946 imports, all-original rehash, baseline backup/recovery and actual populated Windows launcher passed.
Design verification: reuses the verified guided interface from f92c025; no UI changes selected.
Independent review: runtime/catalog and complete retained evidence/receipts/authored-state verification passed.
Owner acceptance: owner reported the preceding synthetic interface looks much better; actual archive accounting review not performed.
Release authorization: not authorized; not part of this task.

## Scope and decisions

The previous integrated UI/performance refinement was committed first as
`f92c025` (Guide desktop document review and load reports responsively), with all
commit hooks passing and a clean working tree. Initial commit hooks normalized
mixed line endings; no hook was bypassed.

Create a new independent schema-22 demo from the specifically selected archive,
using the committed guided interface and existing reviewed bounded import tools.
Archive originals, V1 databases/settings and existing V2 demos/pilots remain
unchanged. Do not discover data through root .env or daily settings.

Import evidence only. No authored accounts, bindings, categories, opening values
or journals are inferred. The user confirms those financial choices in the demo.
Successful extraction does not establish full capture, reconciliation or accepted
accounting. A new local fixture-signing key is used only for the engineering
catalog; its private portion is discarded. Production keys/services are unused.

Private source bytes, account identifiers, filenames and detailed receipts remain
in the ignored local demo; only aggregate evidence belongs in Git/routine output.
The new demo contains confidential originals and should be kept private.

Primary owns actual read-only archive intake, artifact preparation, this record,
public index/planning updates and commits. Integrity independently reviews the
specific new artifact, manifest, receipts and retained evidence read-only; no
recursive delegation. No specialist changes application code.

## Preparation and verification

Prepared `scratch/archive-demo-f92c025` with the existing
`devtools/v2_statement_pilot/prepare_pilot.py --prepare-at` command from the
locked client interpreter. Initial verification: schema 22, 23 catalog
definitions, zero sources/accounts/bindings/journals. Public runtime and launcher
are pinned separately from the financial profile; preferences and application
home are isolated.

The copied runtime helper runs `--import-archive <owner-selected archive>
--pilot scratch/archive-demo-f92c025`. It discovered 946 eligible sources.
Use its actual bounded services, before/after input hashes and imported-digest
guards. Preserve completed imports on failure; local receipts retain all outcomes.

After intake: reconcile receipts with saved sources, verify every source and
snapshot/observation inventory against the pinned signed catalog, rehash originals,
confirm authored tables remain empty, verify backup/reopen/recovery proportionately,
and exercise the actual populated pinned Windows entry and inventory loading.
Do not emit private screenshots or source descriptions in routine output.

## Result

The launcher is `scratch/archive-demo-f92c025/Open-statement-pilot.cmd`.
Private `START-HERE.txt` explains document discovery, account setup/confirmation,
pending source rows, explicit review and initially empty reports. `SOURCE-INDEX.txt`
maps original filenames to current friendly document labels, dates and diagnostic
digests; `CATALOG-ACCOUNTS.txt` provides the institution-key/class reference without
authoring assignments. A verified pre-review backup is at `verification/baseline.dbb`.

Independent pre-intake-completion runtime review passed: all 275 manifest files
match their sizes/hashes and source commit f92c025 (246 client Python modules).
The 23 catalog definitions and signed account contexts match that commit; local
fixture signature/admission verifies release 1 and the exact source revision.
Launcher review confirms separate home/preferences/catalog, explicit fixture
trust and no V1 database/settings, backend/auth or production trust discovery.
The interpreter and third-party packages use the shared locked development
environment; the demo is a pinned source runtime, not an installed release.

### Actual archive intake

The exact copied helper completed with exit 0: all 946 eligible CSV/PDF files
imported as 946 unique sources; zero failures, skipped inputs or reused sources.
Discovery found one directory and no other files. Observed duration was
1205.848 seconds; profile size 255,832,064 bytes with 219,458,039 retained original
bytes. This is an actual intake duration, not an isolated performance benchmark.

Primary independently rehashed all 946 originals after the complete run and
matched every size/digest to its successful receipt and saved source digest.
No original file was changed. Baseline backup reopened with the same complete
source/observation sets; recovering one source per exercised parser family from
that backup produced 21 exact original hashes. Both backup and demo profile
remained byte-identical across the read/recovery checks. No V1 database/settings,
other private pilot or existing runtime was opened or modified.

### Independent completed-artifact review

Read-only verification passed in 4.10 seconds on the exact new pinned profile:

- 946 receipts, retained sources and evidence snapshots correspond exactly.
- 21 exercised parser definitions match exact bytes in the verified 23-definition
  fixture catalog; the remaining two definitions are not exercised by this archive.
- All 19,169 observations and complete source/definition/evidence inventories
  validate; 18,716 activity rows remain pending and unassigned.
- SQLite integrity and foreign-key checks passed. All 28 non-evidence tables have
  zero rows: no authored accounts, bindings, reviews, openings or journals.
- Document-summary pending counts and empty account positions are consistent.
  The profile's streaming SHA-256 was unchanged after the complete independent read.

Independent evidence remains in ignored
`scratch/ux-audit-archive-runtime-f92c025/{runtime-result,profile-result}.json`.
Primary aggregate verification is in the demo's `verification/primary-result.json`;
detailed source receipts and all private material stay inside the ignored demo.

### Populated Windows launcher

The exact `Open-statement-pilot.cmd` passed on actual Windows Qt with external
test-only display suppression: exit 0, inventory ready with 946 documents and zero
accounts, all 98 loaded first-party modules under the pinned runtime, profile
hash unchanged. The asynchronous inventory finished in 1.275 seconds in that run;
this is one warm source measurement, not cold/installed/native usability acceptance.
No private screenshot or statement text was emitted. Evidence is in the private
demo's `launcher-check/result.json` and its local harness logs.

No application source changed for this task. The existing import/recovery/runtime
tools were already covered by the preceding 17-test disposable integration run;
verification here exercised the actual selected archive and resulting artifact.
Public documentation links/whitespace and commit hooks passed at closeout.

## Limits and remaining work

Owner accounting choices and visible usability review of the populated archive
remain separate from import/runtime verification. No daily-profile activation,
installation, signing/publication or other release action is authorized here.
Storage integrity/import correspondence does not independently establish printed
extraction parity, complete source capture or accounting accuracy. Imported source
balances remain evidence; Reports contains no posted money until explicit review.
