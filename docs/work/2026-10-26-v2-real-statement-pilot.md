# Validate the V2 import workflow against the owner's V1 statement archive

Date: 2026-10-26. Roadmap IDs: V2-3/4/5/6/UX/7, P2-4/5.
Branch/runtime: feature/client-financial-insights, isolated development pilot.
Authorization: owner selected the real-statement pilot after checking roadmap dependencies, then requested the entire V1 archive.
Implementation: archive intake and evidence-only pilot complete; owner accounting review pending.
Automated verification: all 946 selected files imported; originals, retry, backup/restore, recovery and populated launcher verified.
Independent review: tooling findings fixed; all saved source/catalog/evidence inventories and empty authored state verified.
Owner acceptance: functional synthetic walkthrough completed separately; real-statement review pending.
Release authorization: not authorized.

## Scope and controlling decisions

The owner asked whether architectural roadmap work should precede UI/UX and
authorized the real-statement pilot if it is the natural next step. The roadmap's
initial V2 store/ledger/finite-parser architecture is implemented. Later service,
forecasting, encryption and additional-platform work is not a prerequisite for
this pilot. Further interface redesign remains for its later pass.

The owner chose to provide a local path and clarified that they intend the entire
V1 statement archive, rather than only a small representative set. Read only the
explicitly supplied archive; do not load root `.env`, daily settings or a legacy
database to discover inputs. Recursively enumerate eligible CSV/PDF originals
without following symlinks/junctions, preserve originals and retain unsupported
formats/failures as explicit counts. Do not mutate archives or any V1 profile.

Create one new disposable V2 profile, separate preferences/catalog/application
home, public copied runtime and a logged Windows launcher under ignored scratch.
Use the reviewed public definitions in an explicitly local engineering catalog
signed by an ephemeral fixture key; retain only its public trust. Production
keys, unsigned activation bypasses and service publication remain outside scope.
The existing accepted synthetic demo remains separate.

Import source evidence through existing bounded workers/services in supported
batch sizes. No account bindings, opening values, categories or journals are
invented. Verify import/retry/reopen integrity and backup/recovery; extraction,
capture, account matching, accounting/reconciliation and owner interpretation
remain separate claims. Entire-archive extraction success cannot establish
financial completeness or source parity by itself.

Primary owns the selected scope, this record, shared contracts/roadmap/TODO and
the actual confidential archive run. An evidence specialist owns only the new
pilot devtool and backward-compatible runtime-pinner changes; no financial/store
schema edits. Independent review uses public tooling/synthetic evidence and
only specifically assigned confidential reads if needed. No recursive delegation.
Private paths, filenames, account data and statement contents stay out of Git and
routine logs; confidential per-file results remain only in ignored local output.

## Result and review

New `devtools/v2_statement_pilot` prepares an empty schema-22 profile with all 23
required declarations, independent default-off preferences, isolated home and an
in-memory fixture-key signed catalog. The private key is discarded. The public
runtime is copied with a per-file hash manifest, and the logged launcher points
to that copy. Existing demo-pinner callers retain their original defaults; only
bounded relative helper and launcher names are added for this pilot. Generated
catalog access inherits its existing local parent permissions, as verified in
the earlier Windows handoff fix; production cache behavior is unchanged.

Recursive archive intake is bounded to 100,000 files and 20,000 directories,
never follows links/junctions, refuses overlapping input/output and preserves
normal per-source decoder/size limits. Existing single-file services are grouped
within supported batch bounds. Completed imports persist normally for retries;
flushed confidential per-file receipts stay under ignored pilot `imports/`.
Routine progress contains aggregate counts, elapsed time and profile size only.
The bulk command refuses already authored accounts, bindings or journals to
keep the first archive intake separate from later owner accounting review.

Independent review found and resolved bounds on directory/hash-read accumulation,
queued-directory growth and a provenance race: before/after equality alone cannot
prove that the bytes imported in between were the checked original. Successful
imports must also return that exact SHA-256. A changed input cannot yield a
successful run summary; earlier completed evidence remains available for review.
No hostile-filesystem authenticity guarantee is made.

The existing workspace opens the profile per file, with full SQLite quick/foreign-
key checks over the growing database. That can cause substantial bulk overhead.
It is an observed code path, not yet a measured blocker; preserve the integrity
gates and measure the real run before selecting an optimization.

Concrete pilot prepared from clean source
`a43ad1f342dcaaf9a35728cd991c29c99c09ac1c` under
`scratch/v2-statement-pilot-a43ad1f`. Its `Open-statement-pilot.cmd` and
`PILOT-GUIDE.txt` are ready. At preparation the profile had schema 22, 23 catalog
definitions and zero sources, accounts, bindings and journals. Runtime-manifest SHA-256:
`1be2a4051ab33ff2f02ea28b8df5daa187280ec7644a6709d59e877a4058fedb`.
Later closeout changes correct one receipt-timing docstring only; they do not
change the pinned artifact or behavior. A blank profile alone is not a completed
real-statement pilot; actual archive intake is recorded below.

## Verification

Windows AMD64/Python 3.13.15, `PYTHONPATH=.;client/src;client`, Qt offscreen;
commands use `client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider ...
-q --tb=short`:

- Initial new pilot plus existing demo integration: **12 passed in 46.78s**.
- Final expanded pilot suite after review findings: **6 passed in 7.33s**;
  independent rerun **6 passed in 7.05s**.
- Final combined `devtools/v2_statement_pilot devtools/v2_review_demo`:
  **14 passed in 48.98s**.
- Independent existing `client/tests/test_v2_profile_store.py` and
  `client/tests/test_v2_catalog_import.py`: **24 passed in 13.88s**.

Tests cover the empty 23-definition profile, pinned startup/no overwrite, real
public CSV/PDF imports and retry, unknown-source refusal, exact originals,
backup/restore/source recovery with zero authored state, archive/output bounds,
directory queue bounds, helper path injection and the imported-byte hash guard.
The Windows leaf-symlink branch is unavailable when OS privilege is denied; no
native leaf-symlink coverage is claimed. Changed-file Ruff/format, whitespace and
local document links passed. These preparatory tests used public synthetic inputs;
subsequent confidential intake is recorded below.

The actual prepared pinned helper passed `--smoke-ui` offscreen with unchanged
profile bytes. Primary also exercised the **exact CMD launcher** under Windows
Qt with an external display-suppression shim: exit 0, all 96 loaded first-party
modules pinned to the copied runtime and profile unchanged. Ignored evidence:
`scratch/pilot-launcher-probe-a43ad1f/result.json`. This is native initialization
and invocation evidence, not visible owner acceptance or an installed release.

Independent final artifact inspection verified all 274 copied runtime files'
hashes/sizes and the manifest digest, repeated pinned zero-state verification,
and confirmed that the selected catalog directory plus both files inherit the
owner's read permission. The earlier Windows handoff defect does not recur.
No profile copies or private-key files were found in the public runtime tree.

During populated-pilot review, integrity noted that the optional smoke helper's
before/after fingerprint used `read_bytes()`, allocating the entire growing
profile. Current tooling now streams that fingerprint with `hashlib.file_digest`;
ordinary workspace behavior and the running pinned intake are unchanged. Focused
pilot checks after this change: **6 passed in 7.09s**; Ruff/format passed.
Populated-profile validation uses streaming hashes and ordinary pinned `--open`
under external display suppression, avoiding the older pinned smoke allocation.

## Confidential archive intake and verification

The owner supplied the SUCCESS archive path directly in chat. All 946 files in
the supplied directory were eligible CSV/PDFs: no subdirectories, skipped links,
unsupported files or unreadable entries. Private paths, filenames, account data
and raw reports remain outside Git.

Windows AMD64/Python 3.13.15, pinned source
`a43ad1f342dcaaf9a35728cd991c29c99c09ac1c`, `--import-archive`/`--pilot`:
**exit 0, 946 imported unique sources, zero failures or reused/skipped inputs**.
Elapsed **1183.444 seconds**; profile 255,832,064 bytes, embedded originals
219,458,039 bytes. This is observed pilot timing, not an isolated benchmark.
Whole-database integrity checks did not block completion; none was bypassed and
no store optimization or architectural redesign was selected.

Each original was hashed before/after import and all 946 were rehashed after the
run; hashes match. Every successful stored digest matches the checked original.
Primary verified every saved source, definition, evidence snapshot and observation
inventory: **946 sources and 19,169 observations**. The actual files exercise
**21 parser IDs** of 23 catalog definitions; real-source coverage of the other
two declarations is not established by this archive.

One actual original per exercised parser was re-imported: **21 already-imported
results**, profile bytes unchanged. A verified full backup and restore-as-new
retained all 946 sources and 19,169 observations. Recovering one representative
embedded original per exercised parser from the restored profile yielded **21
exact hashes**. All checks left the imported profile unchanged. Financial
accounts, bindings and journals remain zero; no reviewed openings or activity
were invented.

Independent read-only verification passed in 5.04s: all 946 file receipts
reconcile with the unique saved sources, every retained definition matches the
pinned signed catalog, all source/evidence hashes and observation inventories
validate, and every authored-state table remains empty. Profile streaming hash
was unchanged. Independent original-preservation review used the receipts;
primary's all-original post-run rehash supplies the direct filesystem check.
Local evidence: `independent-verification.json` under the ignored pilot root.

Independent recovery corroboration then reopened both full backup and restored
profiles, revalidated every saved import and the same source/observation sets and
empty authored state, and independently hashed all 21 recovered originals against
their embedded sources. It passed with no unresolved findings; local evidence is
`independent-recovery-verification.json`.

The actual populated `Open-statement-pilot.cmd` passed under Windows Qt with
external display suppression: **exit 0, all 96 first-party modules pinned,
profile unchanged**, using streaming outer hashes. Ignored evidence is in
`scratch/pilot-populated-launcher-probe-a43ad1f/result.json`. This verifies native
initialization, not visible owner accounting acceptance or installed release.

The local `SOURCE-INDEX.txt` maps original filenames to displayed source hashes;
`CATALOG-ACCOUNTS.txt` gives the institution field reference. `PILOT-GUIDE.txt`
explains account assignment, unknown openings, explicit activity review and why
reviewed reports initially have no posted money. Full backup, restored profile,
representative recovered originals and aggregate report are under `verification/`.
These indices, receipts, profile, backups and recovered sources are confidential
local artifacts and remain ignored by Git.

## Remaining work

Owner reviews imported evidence and authors accounts, bindings, openings and
activity before assessing posted reports. Full-page capture, reconciliation,
complete financial history and correctness of those future accounting choices
remain separate from successful import. Further UI/UX refinement, supported-
platform/installed acceptance and explicitly authorized signing/release actions
retain their separate scope.
