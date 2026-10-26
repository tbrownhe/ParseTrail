# Preserve the independent 1.x installation during V2 packaging

Date: 2026-10-26. Roadmap IDs: V2-1/7.
Authorization: approved fresh-profile/fallback contract and available native readiness work.
Implementation: distinct identities and compile preparation complete; no installer executed.
Automated verification: native NSIS fixture compile and portable Mac checks passed.
Independent review: complete; two packaging findings fixed and rechecked.
Owner acceptance: pending actual supported-platform installation/UX gates.
Release authorization: no version change, production signing, installation or publication.

## Scope and controlling decisions

Give V2 a distinct installation identity so packaging does not target the retained
1.4.2 application. Windows install directory, application/uninstall registry keys
and shortcuts must use `ParseTrail 2`; upgrade detection may target only that V2
identity. Keep the inner executable/build directory and public artifact naming
contracts stable. Mac packaging emits `ParseTrail 2.app` with its own bundle ID.
Do not change the application version during the pilot or run an installer on
this workstation. Existing 1.x data/application/shortcuts remain untouched.

Allow explicit NSIS source/output overrides for an unsigned development compile
without replacing production build output. Defaults retain the release builder's
normal inputs/artifact path. Prepare/build only reviewable disposable artifacts;
actual release version/signing/publication retain their selected scope. Preserve
dependency/native smoke checks and all required notices/resources.

Primary exclusively owns `client/scripts/win64_installer.nsi`,
`client/build_client_macos.sh`, `client/scripts/macos_release.py`, focused identity/
Mac release checks and this record/contracts.
No other agent edits these files. Public source/synthetic build artifacts only;
no installed application/profile/registry mutation or private signing material.

## Result and review

The previous NSIS script used `ParseTrail` for install/uninstall registry lookup,
directory and shortcuts, and ran the previous installation's uninstaller. The
Mac builder emitted the same `ParseTrail.app` name. Those shared identities cannot
preserve the existing installation as the required independent fallback. Changing
ordinary startup alone does not resolve this packaging boundary.

NSIS now uses `ParseTrail 2` throughout directory/registry/shortcut/upgrade and
uninstall identity, keeping the existing inner executable and public artifact
naming. Explicit source/output macros permit disposable compilation. Independent
review caught an unquoted source macro for spaced paths; it is quoted and the
native fixture compile now uses spaces in both source and output paths.

Mac packaging emits `ParseTrail 2.app` with bundle ID `com.parsetrail.client.v2`.
Independent review caught audit/smoke consumers still hardcoding the old executable
name. They now use the bundle's validated `CFBundleExecutable`: bounded metadata,
plain local filename and regular in-bundle file, with malformed/missing/oversized/
nonlocal paths refused before execution. Portable fixtures exercise both old and
new spaced names; this is a read-only artifact audit, not a legacy runtime alias.

## Verification

Windows 11 AMD64/Python 3.13.15. `test_macos_release.py` and
`test_v2_installation_identity.py`: primary **87 passed, 1 skipped in 3.57s**;
independent rerun **87 passed, 1 skipped in 4.18s**. The skip is the native Bash
builder integration on non-Darwin. Both declared bundle executables reach audit/
smoke consumers in portable fixtures. Invalid metadata is refused before commands.

The portable [official NSIS 3.13 archive](https://sourceforge.net/projects/nsis/files/NSIS%203/3.13/)
was downloaded to ignored scratch and measured SHA-256
`ba63dffc4410ee89193e1cb5a41989991bd77c61068da17e3156d136b7b0b3d8`.
Its compiler reports `v3.13` and Authenticode `NotSigned`; no authenticity/signing
claim beyond the documented download provenance is made. Using
`PARSETRAIL_TEST_NSIS_COMPILER` to select that local tool, checks run native
`/SAFEPPO` preprocessing and compile a public inert fixture installer, verify
expanded targets exclude the 1.x identity, and never execute the installer.
See the [compiler CLI reference](https://nsis.sourceforge.io/Docs/Chapter3.html).
Git Bash `-n` verifies Mac shell syntax. Integrated whole-client checks:
**2121 passed, 4 skipped in 977.04s**, including the native compiler fixture cases.
The frozen candidate remains a separate check.

No installer, registry, shortcut, live/1.x profile or installed application was
mutated. Native Intel/actual installation acceptance remains unperformed; these
portable/native-compiler checks do not establish it.

## Remaining work

Prepare the final unsigned frozen probe.
Keep exact-candidate installed/offline and supported-platform acceptance separate,
without modifying the retained installed 1.x application.
