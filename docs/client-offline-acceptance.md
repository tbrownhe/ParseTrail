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
