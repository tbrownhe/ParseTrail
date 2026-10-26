# Prepare the integrated disposable UI/UX walkthrough

Date: 2026-10-26. Roadmap IDs: V2-UX, V2-6/7.
Authorization: continuing roadmap development; owner offered an early UI/UX pass.
Implementation: final six-source walkthrough and pinned launcher prepared; Windows catalog handoff corrected.
Automated verification: signed imports, pinned reopening/startup and cross-principal ACL propagation passed.
Independent review: acceptance specialist prepared and verified synthetic artifacts.
Owner acceptance: walkthrough otherwise worked; step-12 cash-movement discrepancy reported, exact owner settings unconfirmed.
Release authorization: not authorized.

## Scope and controlling decisions

Prepare a repeatable disposable daily-workflow example using public synthetic
sources, an ephemeral test-signed local catalog, separate preferences/application
home and a fresh profile. Never select daily/1.x state or production trust keys.
Provide a simple Windows-session launcher and short expected-result walkthrough.
Keep native owner UX acceptance separate from automated/offscreen validation.
The primary owns the tracked devtool, this record and shared roadmap status;
`readiness_audit` owns only ignored disposable preparation/verification artifacts.

On October 26 the owner offered to test workflows while development continued.
A schema-20 example was prepared after HSA development and shared. The owner
reported that its command launcher failed, provided no error detail, and explicitly
said to continue and do UI/UX at the end. This is a failed launch attempt, not
feature acceptance. Investigate the available local startup path autonomously and
prepare a corrected final example after the remaining accounting/runtime changes.
Do not repeatedly ask the owner to run intermediate demos.

## Result and review

Initial example: three public synthetic sources imported through signed routing
and bounded workers; October spending 400 and income 1000 minor units, checking
position 100600, HSA cash 110010, unresolved clearing 10000, known zero savings,
card liability -10000 and unknown investment opening with separate nonposting
value 500000. Pending Tea expense and unbound next-import file permit actual review.

The initial artifact was additionally pinned to a copied schema-20 runtime to
preserve it during schema evolution. This snapshot passed automated imports and
construction checks but did not establish that the owner's native launcher worked.
The specialist could not reproduce the owner's exact unseen error. The original
live helper later reproduced `unsupported_profile_format` after the checkout
advanced to schema 21; this confirms the changing-checkout design flaw, without
claiming it caused the owner's earlier failure. The pinned launcher avoids that
mismatch. It now logs combined startup output, preserves a nonzero Python exit
status and displays the log on failure. Generated profiles/runtime copies remain
ignored. Final owner startup must still be confirmed during the requested pass.

The reusable [preparation tool](../../devtools/v2_review_demo/README.md) creates a
new example, pins copied public source/scripts/assets with a hash manifest, fixes
parent and bounded-worker imports to that copy, and provides a logged launcher.
It checks profile/runtime schema before copying and refuses existing runtimes or
destinations. No private key is retained. `--smoke-ui` exercises the same helper
window construction with display suppressed and checks unchanged profile bytes.

The integrated seed now includes six actual public signed imports and both loan
workflows. Payment checking starts at 100000 and ends at 76000 minor units. A
reviewed independent Capital opening -970000 becomes principal -950000 after its
printed 20000 principal/2000 interest payment; the original PDF opening remains
unknown and its activity date has no added source guess. Yamaha's source-backed
opening -100000 becomes whole liability -99000 after a 1000 Vehicle charge and
2000 repayment. January expense is 2000 and February expense 1000; original
October/HSA values remain unchanged. Saved date preferences remain off, with the
Capital assumption retained as an explicit historical fixture-author decision.
Separate source closing points add no money. The walkthrough provides actual
hash-prefix navigation for the workspace's source labels and covers exact dated
clearing, category correction, values, backup/reopen and all six source recoveries.

## Verification

Windows AMD64/Python 3.13.15/schema 20: acceptance specialist verified exact
reopening/report values, offscreen workspace/reports/positions/coverage/settlement
construction, snapshot/restore-as-new and exact embedded-source recovery. The
prepared owner profile remained byte-identical. A restored copy admitted extra
synthetic CSV/retry and PDF via two real bounded decoder processes using copied
runtime paths. None of these checks is native owner launch acceptance.

Tracked preparation-tool integration check: `PYTHONPATH=.;client/src;client`,
`QT_QPA_PLATFORM=offscreen`, `client/.venv/Scripts/python.exe -m pytest
-p no:cacheprovider devtools/v2_review_demo/test_review_demo.py -q --tb=short`:
Initial **1 passed in 4.76s**; final pinned-runtime/startup version **1 passed in
8.73s**. It prepares real signed source imports, verifies exact books
after reopening and checks that preparing at an existing destination fails without
altering the profile. The final check also verifies every copied file hash,
reopens through the copied helper, and checks suppressed-display Qt startup with
unchanged profile bytes. The earlier artifact's exact command path separately
passed offscreen and native Windows Qt startup with display suppressed; intentional
argument failure retained exit code 2 and a successful run returned 0. The owner's
earlier error remains unconfirmed. The final-schema example is recorded below;
the owner pass remains pending.

Primary also prepared a fresh schema-21 pinned example and ran its copied helper
with `QT_QPA_PLATFORM=windows --smoke-ui DEMO_DIRECTORY`: **exit 0**, JSON reports
`platform: windows`, `startup: passed`, `profile_unchanged: true`. Window display
was suppressed. This verifies native Windows Qt initialization and helper startup,
not the owner's earlier error or product/release/UX acceptance.

After retaining the six-source helper and its focused tests, full
`devtools/v2_review_demo` checks: **4 passed in 41.35s**. These include copied-runtime
reopening/hash verification, no-overwrite preparation, exact backup/restore and all
six original recoveries, retained loan/transfer histories, native Windows helper
startup and hidden loan/register/report dialog construction. Final source-revision
artifacts are recorded below; owner acceptance remains unperformed as requested.

Final review artifacts bind to clean code freeze
`1e61bec33af214930d42396c6ff5f3b9a146e6d4` under
`scratch/v2-release-review-1e61bec/demo`. Launch `Open-review-demo.cmd`; read
`WALKTHROUGH.txt`. `runtime-manifest.json` SHA-256 is
`5a6ec116e7ee9f255e0193efa93ff13e88fe6236578ca112eee717df4c152c53`.
The companion `review-index.json` in the parent records source revision, exact
initial values and the unsigned starter payload identity. The earlier 25294e2
artifacts remain historical; the final walkthrough uses the corrected build freeze.

Primary exercised the **exact CMD launcher**, its quoted arguments/cwd and copied
helper under native Windows Qt using an external test-only display-suppression
shim. Exit 0, all 96 loaded first-party modules resolved under the copied runtime,
and profile bytes remained unchanged. The launcher writes `last-launch.log` for
startup diagnosis. Test evidence is in ignored
`scratch/final-launcher-probe-1e61bec/result.json`; the shim is not part of normal
launching or the pinned runtime. This rechecks invocation after the owner's earlier
failed attempt while leaving actual visible owner acceptance unperformed.

## Owner startup traceback and Windows handoff correction

The owner subsequently supplied `CatalogError: catalog_cache_shape` from
`load_current()` reading the prepared release's `catalog.json`. Inspection found
the renamed temporary catalog directory had a protected Windows DACL for its
sandbox creator, SYSTEM and Administrators; the containing demo allowed the owner
access, but that permission did not reach the two release files. Same-principal
startup checks missed this handoff defect. This is a failed startup, not UX
acceptance.

The devtool now enables inheritance on only the newly generated public synthetic
catalog release directory using the existing parent ACL. Existing explicit rules
are preserved. It refuses unexpected files, symlinks/junctions or multiple releases
and fails preparation on ACL-operation failure. Ordinary runtime catalog protection
and application/financial code are unchanged. No Everyone/Users grant is added.

The existing `scratch/v2-release-review-1e61bec/demo` was repaired at its same path,
without replacing the pinned runtime, catalog bytes or profile. Independent
acceptance review inspected the directory and both files: all now unprotected,
with the owner's inherited read permission. Catalog SHA-256 remains
`61f1a70154cec4bdd9e0904f259d6afadad543226bb27acc34258b0865e96dbf`, runtime-manifest
SHA-256 remains `5a6ec116e7ee9f255e0193efa93ff13e88fe6236578ca112eee717df4c152c53`,
and profile SHA-256 remains `7bebf77ccea3c27d8b8879e6ccbb7cc8ffe19f5f20d95ce3170929a0d28b43c1`.
The ignored `catalog-permission-repair.json` retains the before/after identity.

Windows AMD64/Python 3.13.15, `PYTHONPATH=.;client/src;client`, Qt offscreen:
`client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider
devtools/v2_review_demo -q --tb=short`: **7 passed in 42.92s**. The new native test
adds a distinctive inheritable read ACE to a disposable parent, reproduces
protected mode-0700 staging, and checks that the directory and both files acquire
the ACE after repair, with all content/profile hashes unchanged. Additional tests
verify refusal before an ACL operation for unexpected contents and propagation
of ACL-command failure. Independent regression rerun: **3 passed in 3.51s**;
read-only code review found no actionable findings.

The exact existing CMD launcher passed again under Windows Qt with external
test-only display suppression: exit 0, all 96 first-party modules pinned, profile
unchanged. Evidence is in `scratch/final-launcher-permission-fix/result.json`.
Ruff, formatting, changed-document links and whitespace checks passed. These
checks repair and verify access; they do not establish visible owner acceptance.

Python documents the [Windows mode-0700 restriction](https://docs.python.org/3.13/library/os.html#os.mkdir);
Microsoft documents [enabling inherited ACLs](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls).

## Owner walkthrough feedback and cash-movement instructions

The owner reported: everything worked except step 12; other transactions appeared
instead of the specified payment, and the demo otherwise seemed to work fine.
This establishes successful visible startup and the remainder of the consolidated
walkthrough as reported. It does not establish successful owner verification of
step 12, native Intel/installed acceptance or release authorization.

Primary and independent acceptance review read the existing owner-edited demo
through the pinned runtime without changing profile bytes. With only the
`payment-checking` checkbox checked, both the common service and actual offscreen
dialog show exactly one January 14 bank record -22000 minor units (principal
-20000/expense -2000) for January 1–February 1, 2026, and exactly one February 9
record -2000 for February 1–March 1, classified as whole-liability repayment.
No missing-entry report defect was reproduced; the owner's exact screen/settings
and the cause of the differing result remain unknown.

The original instructions omitted exact control, table and year details. Report
scope uses checked account boxes, not row highlighting or the Inspect account
selector. January's upper summary has two purpose totals while the middle table
has one cash record; the lower details carry the split. Full-source previews show
all original statement rows regardless of report period. January offers bank and
Capital previews; February offers the bank preview and retains the Yamaha
counterpart date in details. The earlier claim of both previews for each month
was too broad.

Step 12 now names the precise menu, checkbox, 2026 inclusive/exclusive dates,
middle-table descriptions/dates/amounts and detail/source expectations. The
existing `WALKTHROUGH.txt` is updated in place; no runtime, catalog, profile or
financial-report code is changed. A prepared-demo GUI regression covers that
exact path, including switching away from a previously checked HSA scope.
Windows AMD64/Python 3.13.15, `PYTHONPATH=.;client/src;client`, Qt offscreen:
`client/.venv/Scripts/python.exe -m pytest -p no:cacheprovider
devtools/v2_review_demo -q --tb=short`: **8 passed in 39.68s**. The new test uses
actual pinned-runtime GUI checkbox/date controls, verifies highlighted versus
checked scope, the single bank record and exact purposes in each month, source
choices/counterpart context and unchanged profile bytes. Independent read-only
service/GUI reproduction agrees on the owner-edited artifact. Primary's ignored
`scratch/review-cash-step12.json` retains exact rows, totals, details and limits.
Changed-file Ruff check/format, local document links and whitespace checks passed.

## Remaining work

The rest of the owner walkthrough worked as reported. Owner confirmation of the
clarified step 12 remains open; initial authorized development is complete and
platform/release gates remain separately tracked.
