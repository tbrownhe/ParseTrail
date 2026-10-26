# Prepare the integrated disposable UI/UX walkthrough

Date: 2026-10-26. Roadmap IDs: V2-UX, V2-6/7.
Authorization: continuing roadmap development; owner offered an early UI/UX pass.
Implementation: repeatable preparation/startup diagnostics implemented; final pass remains open.
Automated verification: signed imports, pinned runtime reopening and suppressed-display startup passed.
Independent review: acceptance specialist prepared and verified synthetic artifacts.
Owner acceptance: not performed; launcher failed and owner deferred the pass to the end.
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
earlier error remains unconfirmed. Final-schema example and owner pass are pending.

Primary also prepared a fresh schema-21 pinned example and ran its copied helper
with `QT_QPA_PLATFORM=windows --smoke-ui DEMO_DIRECTORY`: **exit 0**, JSON reports
`platform: windows`, `startup: passed`, `profile_unchanged: true`. Window display
was suppressed. This verifies native Windows Qt initialization and helper startup,
not the owner's earlier error or product/release/UX acceptance.

## Remaining work

Rebuild the disposable example at the final integrated runtime and confirm native
owner startup using the captured diagnostics if needed. Owner
then reviews import/binding, explicit review and correction, reports/budgets/
positions, unknown/pending/error states, backup/reopen and layout/wording. Record
feedback and disposition here. Continue unrelated roadmap development meanwhile.
