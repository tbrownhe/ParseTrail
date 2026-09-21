# Offline client acceptance

Offline acceptance covers startup with an empty profile and local work when
signed parsers and a trained model are already available. Bundling parsers for a
new offline user is the separate F1 proposal; it is not implemented by this gate.

## Automated source and frozen diagnostic

The client entry point accepts an explicit release diagnostic:

```bash
uv run --no-env-file --no-sync python src/parsetrail/main.py \
  --offline-session-smoke-test fresh
```

Repeat with `cached` and `network-failure`. Source regression tests run all three
through subprocesses with a 75-second limit. Both native builders run the same
modes against their actual frozen executable before packaging/signing, with a
75-second deadline per mode. The separate native-library smoke retains its
30-second deadline.

| Mode | Initial local prerequisites | Expected result |
| --- | --- | --- |
| `fresh` | No database, parser catalog, or model | Real schema initialization, all five onboarding pages, persisted completion, first paint and heartbeat beyond the update delay; no network attempts. |
| `cached` | A synthetic signed cached parser and locally trained model | Startup re-verifies and loads the parser, imports synthetic exact-money rows, preserves a copied source, detects duplicate import, predicts with the existing model, and trains/saves/reloads another local model; no network attempts. |
| `network-failure` | The same synthetic cache/model; automatic updates enabled | Only the client/plugin manifest GETs are attempted, after first paint and the configured delay, on background threads. A heartbeat continues during each injected connection failure and the same local import/model operations succeed afterward. |

The diagnostic creates its own temporary profile **before settings/logging/auth
imports**, clears inherited settings/profile overrides, uses an in-memory/null
credential backend, and intercepts Python network entry points. It cannot select
an existing profile or accept external statements, parser source, or model files.
The only parser is a small synthetic fixture compiled and signed with a fresh
in-memory key. Its public key is injected into this diagnostic's `PluginManager`;
normal startup still uses only the distributed public trust store. This is not
a supported parser installation path for users.

The entry point still performs icon setup, UI hook registration, real window
construction, and `QApplication.exec()`. A timer advances the real onboarding
wizard and accepts the new-database information message. The database file
chooser is supplied its temporary default path. Native file dialogs and OS
credentials remain owner checks. Windows respects an explicitly selected Qt
platform, allowing these probes to use the offscreen platform.
The message check uses its temporary database path, parent, icon, and buttons;
it cannot rely on a window title because
[Qt ignores message-box titles on macOS](https://doc.qt.io/qt-6/qmessagebox.html#setWindowTitle).

Resource checks use the actual source layout or PyInstaller `_MEIPASS` resources:
icon decoding, bundled public keys, Alembic configuration, and schema migration
files. A source probe does not pretend to be frozen. The result reports
`frozen: true` only inside the packaged application.

Success prints a JSON summary. For a windowed Windows executable, or to retain
the result, add `--offline-smoke-report <new-report-path>`; it writes only to a
new file in an existing directory and refuses to overwrite one. Windows builds
validate the report's mode, `passed`, and `frozen` fields. A failed Windows gate
retains its report path in the build error. Mac inventories preserve the mode
list and result under `native_build.frozen_smoke.offline_session`.

Progress messages include elapsed startup time. At 60 seconds an independent
watchdog dumps Python thread stacks, even if Qt is blocked; the outer limit
remains 75 seconds. With `--offline-smoke-report`, progress and stacks go to a
new `<report-path>.log` beside the report. The log is removed on success and
retained on failure or an outer timeout; existing logs are never overwritten.
Without a report path, diagnostics go to stderr. Source test failures and Mac
build failures include captured diagnostics; Windows build failures name the
retained log. A failure during a startup modal unwinds subsequent dialogs and
prevents entry into another main event loop.

To investigate a platform failure, first rerun only the empty-profile case from
`client/` and retain the full failure text:

```bash
QT_QPA_PLATFORM=offscreen uv run --no-env-file --no-sync --no-python-downloads \
  pytest -q -x 'tests/test_offline_session.py::test_real_entrypoint_offline_session_ignores_existing_profile[fresh]'
```

Run all modes again after resolving the first failure. A timeout alone does not
identify a hardware, toolchain, or application defect; use the stage timings
and stacks to locate the stalled operation.

These probes inject failures before an HTTP connection and do not establish OS
firewall behavior, native installation, actual Keychain/Credential Locker use,
or a real restart on the owner's existing profile. No financial fixture is
needed. The installed walkthrough below closes those gaps.

## Owner installed-app walkthrough

Use the exact tagged candidate and its saved release inventory. Work in a
disposable OS account/profile or the isolated staging profile; keep production
financial data and credentials separate. Record target, OS version, app/Python
version, source commit, installer hash, and pass/fail without statement contents,
account identifiers, credentials, or private paths.

1. **Empty profile:** disable networking before first launch. Create a new local
   database, complete the guide, and use the empty dashboard/settings after at
   least ten seconds. Record that parsers and a model are absent. Close/restart;
   the selected database and guide completion should persist without a login
   prompt or blocked window.
2. **Installed parsers:** temporarily restore networking, log into staging, and
   install a signed catalog. Verify the OS credential store across a restart.
   Disable automatic update checks in Preferences, close the app, disable
   networking, and reopen. After ten seconds, import an authorized local fixture
   whose parser is installed. Check exact rows/balances and the selected source
   copy/archive/retention behavior. Repeat with an overlapping export.
3. **Trained model:** create/review local categories and verified training rows,
   train/save a model, then close/restart while offline. Predict categories for
   another local import and review the results. Record the no-model guidance
   separately from a successful trained-model prediction.
4. **Updates enabled:** enable automatic update checks and restart while still
   disconnected. The window should paint promptly and remain usable through
   background failures. Open local views and import a supported statement after
   the checks fail. No automatic login dialog or installer-ready message should
   appear for a failed update.
5. **Intel Mac runtime:** repeat without Homebrew/compiler directories on `PATH`.
   Retain the native bundle audit and frozen-smoke evidence. A development Mac
   with sanitized `PATH` does not prove operation on a separate machine where
   build tools are physically absent; retain that limitation explicitly.

The remaining P2.2 native walkthrough also covers folder import, explicit
statement contribution, database backup/test restore, and the 1.3-to-1.4 manual
upgrade. Those steps are separate from the automated diagnostic.

### Intel 1.4.0 candidate: installation and first offline launch

Use the preserved signed DMG identified in the
[acceptance record](engineering-acceptance.md#signed-intel-mac-candidate-september-19-2026).
Keep its complete release directory and original inventory digest. A separate
candidate installation under `~/Applications` permits native bundle testing
alongside an existing app. The later 1.3-to-1.4 upgrade check remains pending.

Create a new destination, open it in Finder, and open the preserved DMG:

```bash
mkdir -p "$HOME/Applications" &&
mkdir "$HOME/Applications/ParseTrail-1.4.0-candidate" &&
open "$HOME/Applications/ParseTrail-1.4.0-candidate"
```

Drag `ParseTrail.app` from the mounted DMG into that folder, then eject the DMG.
The destination should contain `ParseTrail.app`, whose executable is used below.
Record any macOS launch prompt encountered.

The empty-profile gate requires that
`~/Library/Application Support/ParseTrail-Staging` is new; use a separate macOS
test account if that staging profile already contains data.

Disable Wi-Fi and any other network connection, then run:

```bash
env -u QT_QPA_PLATFORM PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  "$HOME/Applications/ParseTrail-1.4.0-candidate/ParseTrail.app/Contents/MacOS/ParseTrail" \
  --staging https://api.staging.parsetrail.com/api/v1
```

This starts the installed GUI with its native Qt platform and system tools on
`PATH`, using the isolated staging data and credential namespace. Confirm the
`STAGING` marker, use the offered staging database location, and complete all
five guide pages. After at least ten seconds, switch views and open Preferences.
Quit normally, then run the same command while still offline. The database and
guide completion should persist, with no login prompt or blocked window.

Report installation/launch, the staging marker, completed onboarding, responsive
local views, and restart behavior separately. Record any launch prompt or first
error. Signed parser installation, Keychain persistence, local fixture import,
trained-model use, and the broader P2.2 workflow follow the initial empty-profile
check above.

### Windows 1.4.0 candidate: installation and first offline launch

Use the preserved signed installer identified in the
[Windows candidate record](engineering-acceptance.md#signed-windows-candidate-september-19-2026).
The owner approved upgrading this PC after the
[verified backup and fresh staging preparation](engineering-acceptance.md#windows-upgrade-safeguards-september-20-2026).
The NSIS installer replaces the registered application machine-wide. A different
Windows account or installation directory alone does not preserve the old app.

The following local handoffs have been prepared on the owner's Windows checkout.
Keep ParseTrail closed and run from the repository directory:

```powershell
powershell -NoProfile -File .\scratch\install-windows-1.4.0.ps1
```

Complete the administrator prompt and installer. The handoff verifies the
backup and candidate before installation, then checks the installed executable.
Verification prints its file-check count and elapsed time every two seconds;
the recorded complete check took about 35 seconds. Let it finish before the
administrator prompt. Ctrl+C cancels before installation. To check preparation
without launching the installer, add `-VerifyOnly` to the same command. The
helper invokes the pinned Python directly; no Conda activation is required.
Report any error or Windows prompt. It does not launch the app automatically.
Use the staging launcher below for acceptance; ordinary shortcuts open the
production profile.

Disconnect Wi-Fi/Ethernet and other network connections before the first launch:

```powershell
powershell -NoProfile -File .\scratch\launch-windows-1.4.0-staging.ps1
```

Confirm the **STAGING** marker, accept the offered database path inside the new
staging profile, and complete all five guide pages. After at least ten seconds,
switch local views and open Preferences. Quit normally, then run the same
launcher while still disconnected. The chosen database and guide completion
should persist, with no blocking login or frozen window.

Report installer/launch prompts, STAGING marker, onboarding, responsiveness, and
offline restart. Preserve the backups and the parked previous staging profile.
Signed plugin installation, Credential Locker persistence/sign-out/relogin, and
synthetic contribution subsequently passed; results are in the
[Windows installed record](engineering-acceptance.md#windows-installed-offline-acceptance-september-20-2026).
One-off imports, duplicate/overlap handling, and Copy retention also passed.
Folder import, Move/Leave choices, model operations, and backup/restore remain.
This local installation does not complete the separate staging
API/website/artifact transition rehearsal.

### Windows synthetic import fixtures

Use the corrected local set under
`scratch/windows-1.4.0-native-fixtures/routing-checked`: preserve `originals`,
import from `working`, and compare with `expected.json`. These files were routed
and parsed against the complete installed signed catalog, not just passed
directly to one parser. This matters because CSV detection examines raw text;
the MOHELA export's HTML marker must match before its decoded cells reach the
parser. The first generated set had extra CSV quote escaping and failed that
step. Keep that set only as diagnostic evidence.

With updates disabled and networking disconnected, copy `01-first.csv` to the
archive, repeat it to check duplicate handling, then copy `02-overlap.csv` to
the archive using the same synthetic account. Expect 8 then 10 canonical
transactions, balances −396.00 then −495.00 USD, and both working files retained.
The later files add two transactions each. Retain separate checks for managed
folder import, Move/Leave choices, model training and predictions on new rows,
offline use after failed automatic checks, and database backup/test restore.

The first two corrected files passed installed offline acceptance: two statements,
10 canonical transactions, 18 memberships, and both sources retained with matching
archive hashes. The missing-model dialog occurs after the import commits; this
candidate currently reports `Auto-categorization Failed` with a log reference.
The imported rows remain available for manual categorization and training.

For the next stage, one verified copy of `03-folder.csv` is prepared in the staging
database's managed import directory. **Statements > Import All** moves that copy
into the archive; the synthetic master and working copies are preserved. Expect
12 transactions and −594.00 USD. Import `04-training.csv` and
`05-training-more.csv` using **Copy to Archive** to reach 16 transactions and
−792.00 USD. Keep the last two files unimported until after training so predictions
are tested on new rows.
