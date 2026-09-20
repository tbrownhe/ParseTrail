# Intel Mac acceptance handover

The completed Mac results and remaining release gates are in the
[return note](intel-mac-return-note.md). The staging profile now contains
acceptance data; preserve it rather than repeating the fresh-profile setup.

Prepared September 19, 2026. The owner is transferring the Mac portion of
ParseTrail acceptance to an assistant running on their Intel Mac, then returning
the results to the Windows assistant. Take over the local Mac work below. The
Windows assistant will wait for the return note rather than edit concurrently.

## Read first and stay within scope

Read [README](../README.md), [TODO](../TODO.md), and the [client guide](../client/README.md)
first, followed by [offline acceptance](client-offline-acceptance.md) and the
[signed Intel candidate record](engineering-acceptance.md#signed-intel-mac-candidate-september-19-2026).
The [client review](client-development-review.md) explains the chunk IDs and the
[release target contract](client-release-contract.md) explains 1.4's one-time
manual upgrade. Older acceptance sections are historical; the latest Intel
signed-build record supersedes their pending build status.

The owner approved **P1.5 release reliability, P1.6 offline acceptance, and P2.2
native walkthroughs**. Continue local acceptance and focused fixes in that scope.
Commit and push focused branches as work proceeds. Ask the owner for GUI actions
or observations, account login, Keychain prompts, and passphrase entry when your
tools cannot perform them. Routine local checks and fixes are already authorized.

Boundaries to preserve:

- Active targets are Windows x64 and Intel macOS x86_64. Apple Silicon is deferred
  because no native test hardware is available. This is a 2020 Intel MacBook Air.
- Server P0 hardening is complete. Keep this handover on client work; report any
  interface problem exposed by the client with its exact reproduction.
- **C1/C2a/C2b/C3 correctness/cleanup proposals remain unapproved. F1–F4 client
  feature proposals require further discussion.** Do not start those projects.
- Financial fixtures referenced by the local `.env` are authorized for
  confidential local testing. Use working copies and keep contents, account
  identifiers, databases, and logs out of commits and shared reports. That local
  authorization does not authorize uploading real statements. Use synthetic
  data for the contribution walkthrough and its explicit confirmation flow.
- Leave artifact activation/publication, release-tag pushes, merging to `main`,
  API/website deployment, and the coordinated 1.3-to-1.4 transition for the later
  release follow-up. No public or staging deployment has been performed by this
  client work. Inspecting staging client behavior is in scope.
- Apple Developer ID signing/notarization is deferred. The owner has no Apple
  Developer certificate; none was needed for the successful dry build.

## Branch and preserved candidate

The shared branch is **`test/client-offline-session`**. The last commit before
this handover document was `7456fa8` (acceptance docs). Pull the handover branch
after inspecting local changes. Keep uncommitted owner work intact. Create a
focused branch such as `test/intel-macos-native-acceptance` for results/fixes,
and return its name and pushed commit IDs.

The artifact was built from an earlier, pinned commit. Later documentation
commits do not change it:

| Identity | Value |
| --- | --- |
| Client version / target | `1.4.0` / `macos-x86_64` |
| Local candidate tag | `client-v1.4.0` |
| Build source commit | `42a3dac970459327d8f3144f40195f4166a98cc9` |
| Signed release sequence | `20260919222343` |
| Inventory SHA-256 | `dff66e320cf2d97c3e8924707f1104de13f693926a7735808fd827c87776a655` |
| Installer | `parsetrail_1.4.0_macos-x86_64_setup.dmg` |
| Actual saved release directory | `~/dev/parsetrail-resources/clients/macos-x86_64` |

Expected local paths, to verify rather than overwrite:

- Checkout: `~/dev/ParseTrail` (use the actual checkout/case on this machine).
- Release files: the DMG, `client-manifest.json`, `client-manifest.sig`, and
  `release-inventory.json` in the directory above. Preserve the complete set.
- Intended installed candidate:
  `~/Applications/ParseTrail-1.4.0-candidate/ParseTrail.app`.
- Staging profile: `~/Library/Application Support/ParseTrail-Staging`.
- Native staging credential service: `ParseTrail-Staging` in macOS Keychain.
- Existing encrypted release key:
  `~/.local/share/parsetrail-release-keys/plugin-signing-key.pem`. This is
  ParseTrail's Ed25519 PEM, unrelated to an Apple Developer certificate. Keep it
  outside the checkout/artifact folders; the owner enters its passphrase locally.
  Verification and installed-app checks do not need the private key.

The actual output is the `parsetrail-resources` sibling directory, not the
`~/parsetrail-release-artifacts` path in the example config. Preserve the owner's
ignored `client/release-config.json` and its existing paths.

The `client-v1.4.0` tag was created locally on the Windows and Mac checkouts and
has not been pushed by the Windows assistant. Verify its resolution on the Mac;
do not move an existing tag. Branch HEAD may be newer because of documentation
updates. A release build at that newer HEAD would fail the exact-tag gate; a
rebuild is not needed to test the preserved installer.

## Accepted evidence

- macOS **15.7.9, build 24G830**, native **x86_64**.
- Updated Command Line Tools preflight passed with Apple clang **17.0.0
  (`clang-1700.6.4.2`)**, SDK **26.2**, Rust/Cargo **1.98.0**, Homebrew OpenSSL
  **3.6.3** with static archives, pkg-config **3.0.6**, and create-dmg **1.2.3**.
  The selected tools path was `/Library/Developer/CommandLineTools`. No further
  tools upgrade is pending.
- Locked CPython **3.13.15**, uv **0.12.5**, PySide6/Qt **6.11.2**. An earlier
  clean cryptography **49.0.0** source build passed, followed by **371 passed,
  2 skipped** in that earlier full client suite.
- All three offline source modes initially timed out. The harness wrongly
  identified a message box by its title, which Qt ignores on macOS, then could
  enter another event loop after a failed startup modal. Commit `fc273e5` fixed
  both issues and added progress/stack diagnostics. The owner then reported
  **10 passed** for `tests/test_offline_session.py`.
- The final Mac builder completed the locked sync, full source tests, public
  trust-store check, thin Intel executable gate, library audit, native runtime
  smoke, all three frozen offline modes, DMG creation, manifest signing and
  verification, and inventory creation. Its final output confirmed sequence
  `20260919222343`, one signed artifact, and the inventory hash above.
- The Windows assistant received the final success lines, not the complete Mac
  inventory or test output. Inspect local records now to capture the DMG digest,
  native evidence, and any available exact test summary.
- For context only, the latest Windows source suite was **451 passed, 3 skipped**;
  an unsigned Windows diagnostic freeze passed all three offline modes. The
  final tagged Windows installer remains pending.

The first installed Mac GUI check was proposed but **no result has been reported**.
The owner confirmed the staging profile was new immediately before this handover.
Inspect its current state: do not erase it or claim another fresh run if it has
since been used. Hosted CI results are also pending; the last GitHub check found
no open PR or Actions runs for this work branch.

## Work in this order

### 1. Inspect the preserved release locally

From the checkout's `client/` directory:

```bash
git status --short --branch
git rev-parse 'client-v1.4.0^{commit}'
shasum -a 256 "$HOME/dev/parsetrail-resources/clients/macos-x86_64/release-inventory.json"
uv run --no-env-file --no-sync --no-python-downloads python -m scripts.client_release verify \
  --release-dir "$HOME/dev/parsetrail-resources/clients/macos-x86_64"
```

Compare the tag and inventory digest with the recorded values. Investigate any
mismatch; do not substitute a new digest for the accepted one. Read the
inventory's `source_commit`, `source_tag`, `target_platform`, `version`,
`release_sequence`, `files`, and `native_build`. Confirm the expected source,
DMG hash, native audit evidence, and
`native_build.frozen_smoke.offline_session` results. Capture a compact summary
for the return note. These checks need no rebuild, dependency sync, private key,
or server connection.

### 2. Install and check a fresh offline GUI session

Follow [the Intel candidate procedure](client-offline-acceptance.md#intel-140-candidate-installation-and-first-offline-launch).
Inspect whether the destination already exists before creating/copying. Install
**from the preserved DMG** into the separate candidate folder so the owner can
retain an existing installation. Eject the DMG after copying.

Have the owner disconnect Wi-Fi and any other network connection. Launch the
installed GUI with the native Qt platform and system-only tool path:

```bash
env -u QT_QPA_PLATFORM PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  "$HOME/Applications/ParseTrail-1.4.0-candidate/ParseTrail.app/Contents/MacOS/ParseTrail" \
  --staging https://api.staging.parsetrail.com/api/v1
```

Confirm the **STAGING** marker, use the offered staging database location, and
complete the five guide pages. Wait at least ten seconds, switch local views,
and open Preferences. Quit normally and restart with the same command while
offline. Verify the same database, persisted onboarding completion, responsive
views, and absence of a blocking login dialog. Record macOS launch prompts and
the actual results. Offscreen probes do not establish visible GUI observations.

An empty profile has no installed parsers or trained model. That is the current
contract; a bundled offline parser pack is the unapproved F1 proposal.

### 3. Complete the remaining Mac offline and P2.2 checks

Proceed through the [installed-app walkthrough](client-offline-acceptance.md#owner-installed-app-walkthrough)
and client guide, coordinating native actions with the owner:

1. Restore networking and use the staging endpoint above for login and signed
   plugin installation. Verify that a restart restores login from the native
   Keychain. Record sign-out behavior without exposing tokens.
2. Disable automatic update checks, disconnect networking, and restart. Import
   a supported fixture using a working copy. Check exact rows/balances,
   duplicate/overlap handling, and the selected source-file retention.
3. Exercise folder import using disposable copies. Check that copy/archive/move
   choices are explained and that the original fixture collection is preserved.
4. Train/save a local model using reviewed categories, restart offline, and
   predict on another import. Record no-model guidance separately.
5. Enable automatic update checks, restart offline, and confirm background
   failures preserve responsive local use without a login or installer dialog.
6. Exercise explicit statement contribution against staging using synthetic
   data and the normal confirmation. Upload of a real financial fixture requires
   the owner's explicit approval for that upload.
7. Use **File > Back Up Database** and **Test Database Backup**. If exercising
   **Restore Database**, restore into a new path within the staging profile and
   preserve the original. Verify rows/schema and restart on the restored copy.
   Staging database/backup destinations must remain within its profile.

If staging is unreachable, credentials/catalog access are missing, or the old
service lacks a requested 1.4 client route, record the exact step/endpoint/status
and continue independent local checks. The service and public artifact channels
have not been upgraded as part of this work. Report service prerequisites as
blockers rather than inventing client success or starting infrastructure work.
Do not fall back to production credentials/data.

Keep the 1.3-to-1.4 manual-upgrade/API/website transition for the coordinated
staging rehearsal. This side-by-side installation does not complete that gate.
Sanitized `PATH` testing also does not prove operation on a machine where build
tools are physically absent; do not uninstall development tools for this check.

### 4. Fix exposed client defects and return evidence

Diagnose the first failure and make a focused fix within the approved scope.
Useful starting points are:

- `client/src/parsetrail/core/offline_smoke.py` and `client/tests/test_offline_session.py`;
- `client/scripts/macos_release.py`, `client/build_client_macos.sh`, and
  `client/scripts/release_architecture.py`;
- `client/src/parsetrail/core/profile.py`, `client/src/parsetrail/core/credentials.py`,
  and `client/src/parsetrail/gui/database_tools.py`.

The offline diagnostic records stage timing, has a 35-second GUI deadline,
dumps stacks independently at 60 seconds, and has a 75-second parent timeout.
With a report path it retains `<report>.log` on failure. Diagnose the stalled
operation rather than extending timeouts without evidence. For a relevant
offline regression, run:

```bash
QT_QPA_PLATFORM=offscreen uv run --no-env-file --no-sync --no-python-downloads \
  pytest -q -x tests/test_offline_session.py
```

Run other tests appropriate to the actual change. Documentation-only updates
do not require another full suite or release build. Source edits do not modify
the preserved installed app. If a runtime fix needs another frozen build,
preserve the existing candidate, use a new unused version/local tag and separate
output, and report the changed identity. Do not move `client-v1.4.0` or overwrite
its reviewed signed files. Have the owner enter signing passphrases in their own
terminal, never in chat or command arguments.

Update [engineering acceptance](engineering-acceptance.md) with durable results
and reduce [TODO](../TODO.md) to remaining incomplete checks. Keep Windows,
hosted CI, publication, and unapproved work open. Commit and push your focused
branch, then give the owner the return note below. If a native interaction or
service blocks progress, complete independent work and name the exact remaining
owner action; do not mark those checks passed.

## Return note for the Windows assistant

Use `PASS`, `FAIL`, `BLOCKED`, or `NOT RUN` for each check; include brief evidence
and limitations. Keep private fixture contents and credentials out of the note.
Fill in this template and point to committed acceptance details:

```text
Mac handover result

Branch / pushed commits:
Acceptance document and section:
Machine / macOS / architecture:
Tested app version / source commit / tag:
Release sequence:
Inventory SHA-256 (compared with recorded value):
DMG SHA-256 (verified against signed manifest):
Any replacement candidate identity and why:

Saved release identity/signature/native inventory:
DMG installation and macOS launch prompts:
Fresh offline first start / STAGING marker / onboarding:
Offline restart / database and onboarding persistence:
Responsive local GUI with system-only PATH:
Staging login / Keychain across restart / sign-out:
Signed plugin install / offline cached-parser import:
One-off / folder / duplicate / overlap import and source retention:
Local model train/save/reload/predict offline:
Enabled update checks failing in the background:
Synthetic explicit contribution to staging:
Database backup / test restore / optional restore to new path:

Defects and fixes (reproduction, change, relevant tests):
Still blocked or not run, with required next action:
TODO entries completed and remaining:
Publications/deployments/merges: none (explain any separately authorized exception)
Recommended next Windows/coordinated release step:
```
