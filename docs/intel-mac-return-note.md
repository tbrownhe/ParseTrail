# Mac handover result

Completed September 19, 2026. This fills the
[handover return template](intel-mac-handover.md#return-note-for-the-windows-assistant).
Durable evidence is in [engineering acceptance: Intel installed candidate
verification](engineering-acceptance.md#intel-installed-candidate-verification-september-19-2026).

```text
Mac handover result

Branch / pushed commits:
  test/intel-macos-native-acceptance
  Acceptance-result commits, oldest first:
  7482a4c, 0adeb06, f0f6727, ec69756, 2a3f8e5, ab7c971, 0142c20.
  This return note is a subsequent documentation commit on the same branch.
Acceptance document and section:
  docs/engineering-acceptance.md
  "Intel installed candidate verification: September 19, 2026"
Machine / macOS / architecture:
  Owner's 2020 Intel MacBook Air / 15.7.9 (24G830) / native x86_64.
Tested app version / source commit / tag:
  1.4.0 / 42a3dac970459327d8f3144f40195f4166a98cc9 / client-v1.4.0.
Release sequence:
  20260919222343.
Inventory SHA-256 (compared with recorded value):
  PASS — dff66e320cf2d97c3e8924707f1104de13f693926a7735808fd827c87776a655.
DMG SHA-256 (verified against signed manifest):
  PASS — 679b1e431cda4711146394a17662f70c19040142a006255dbd815d4d6c04b781.
  parsetrail_1.4.0_macos-x86_64_setup.dmg; 126452768 bytes.
Any replacement candidate identity and why:
  None. Original candidate, tag, release files, and ignored config preserved.

Saved release identity/signature/native inventory:
  PASS — public-key verification, pinned tag and original inventory digest
  reconfirmed after acceptance. Inventory records 379 Mach-O files, one
  cryptography extension, runtime smoke, and all three frozen offline modes.
  Actual build: CPython 3.13.15, uv 0.12.7, PyInstaller 6.21.0.
  Exact final source-suite count was not recovered.
DMG installation and macOS launch prompts:
  PASS — read-only DMG mount, separate candidate folder, ditto copy, bundle
  comparison, eject, and installed thin x86_64 executable inspection.
  Owner reported no launch errors; individual prompt wording was not supplied.
  Finder drag-and-drop itself was NOT RUN; installation used ditto.
Fresh offline first start / STAGING marker / onboarding:
  PASS — initially absent profile; owner completed the native offline checklist.
  STAGING marker and five-page onboarding accepted; saved onboarding version 1.
Offline restart / database and onboarding persistence:
  PASS — owner confirmed offline restart without blocking login; saved database
  stays inside the staging profile. Preserve this now-populated profile.
Responsive local GUI with system-only PATH:
  PASS — native installed owner walkthrough and three isolated native probes.
  Probe heartbeats: 190/189/190; intercepted requests: 0/0/2.
  A machine with development tools physically absent remains NOT RUN.
Staging login / Keychain across restart / sign-out:
  PASS — authenticated plugin download, restart followed by successful synthetic
  submission without another login, then sign-out followed by a login request
  that the owner canceled. Keychain presence/deletion confirmed without reading
  token contents; no plaintext access token in config.
Signed plugin install / offline cached-parser import:
  PASS — 22 installed artifacts independently reverified for signature, exact
  sizes/digests, and runtime compatibility; catalog sequence 20260829091732.
  Owner completed offline imports through the installed signed MOHELA parser.
One-off / folder / duplicate / overlap import and source retention:
  PASS — final audit: 7 statements, 20 canonical transactions, 98 memberships;
  exact synthetic dates, amounts, running balances, and final -990.00 USD balance.
  Copy preserves sources and creates matching archives; managed folder import
  consumes its input copy. Separate final Move removes its working source and
  retains a matching archive; Leave preserves its source without an archive.
  All seven synthetic master originals remain. Integrity/foreign keys pass.
Local model train/save/reload/predict offline:
  PASS — owner training/restart/prediction and independent model reload.
  Saved model retains 16 training samples and 2 categories; four subsequent new
  rows predict correctly without retraining. Earlier nine verified rows remain
  verified. No-model guidance was included in the owner's initial passed checks.
Enabled update checks failing in the background:
  PASS — owner reported responsive local use/imports with networking disabled;
  no blocking login or installer dialog. Saved preference is enabled. Native
  injected-failure probe independently confirms two background manifest requests.
Synthetic explicit contribution to staging:
  PASS — generated one-page "ParseTrail smoke" PDF, normal confirmation, and
  server-accepted popup; no real financial fixture uploaded.
Database backup / test restore / optional restore to new path:
  PASS — current-schema staging backup creation/test reported; retained empty
  pre-import snapshot independently restored with exact parity for every table
  row and valid integrity. It correctly differs from the now-populated live DB.
  An earlier tested backup was outside staging and used an older schema; it was
  preserved and was not used as evidence of current backup creation.
  Optional installed switch to a newly restored database path: NOT RUN.

Defects and fixes (reproduction, change, relevant tests):
  No client runtime fix or rebuild required. Missing local staging API hostname
  mapping caused curl exit 6/HTTP 000. Owner added the documented hosts entry;
  ordinary HTTPS plugin-manifest access then returned HTTP 200.
  FAIL — an extra sandboxed offscreen frozen probe aborted in Qt's Mac wizard
  with NSInvalidArgumentException / nil NSBundle URL. All native Qt probes and
  owner sessions passed. Platform-plugin versus sandbox cause was not isolated;
  the installed walkthrough uses native Qt as required.
  Initial walkthrough order varied and Copy was used for the proposed Move/Leave
  files. A precise final offline checklist and filesystem/database audit closed
  both retention checks and prediction on new rows after model reload.
  Documentation checks: git diff --check. No unnecessary full suite/rebuild.
Still blocked or not run, with required next action:
  BLOCKED — staging GET /api/v1/clients/macos-x86_64/manifest returns HTTP 404;
  provide the coordinated 1.4 API/artifact channel in the later release rehearsal.
  NOT RUN — Windows tagged build/native walkthrough, fresh hosted CI evidence,
  artifact activation/publication, and the 1.3-to-1.4 upgrade transition.
  NOT RUN — Mac without physically installed build tools (needs another suitable
  environment), optional restore-to-new-path, and Apple Silicon (deferred).
TODO entries completed and remaining:
  Intel installed P1.6 and P2.2 gates complete. R2 sanitized-PATH/build evidence
  accepted; physically tool-free environment limitation retained. Windows,
  hosted CI, publication/transition, and all unapproved proposals remain open.
Publications/deployments/merges:
  None. Only focused branch commits were pushed; no release tags were pushed.
Recommended next Windows/coordinated release step:
  Fetch/review this branch's evidence. Complete the tagged signed Windows dry run,
  frozen/native offline checks and P2.2 walkthrough; collect hosted CI results.
  Then rehearse preserved-byte publication and the API/website/manual-upgrade
  transition on staging before the separately coordinated public release.
```
