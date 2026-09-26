# Intel Mac 1.4.2 handover result

Build/signing and owner installed GUI acceptance completed September 26, 2026, following the
[1.4.2 handover](intel-mac-1.4.2-handover.md). The
[original Intel acceptance](intel-mac-return-note.md) is preserved.

| Field | Recorded value |
| --- | --- |
| Result branch | `test/intel-macos-1.4.2-acceptance` |
| Exact build source | `4585f4c57d20101c1c6ac4f625b726e51913e562` |
| Local build tag | `client-v1.4.2` |
| Version / target | `1.4.2` / `macos-x86_64` |
| Host | Intel x86_64, macOS 15.7.9 (24G830) |
| Signed release sequence | `20260926200410` |
| DMG | `parsetrail_1.4.2_macos-x86_64_setup.dmg` |
| DMG size | `126446802` bytes |
| DMG SHA-256 | `b3a25c5b6f1f0611acefb41fa29187883064eb1abff4b40b7526e93d4a07e7b5` |
| Inventory SHA-256 | `677c6cc99eccacf8956010cc1758ea71e37fb14d9d4848f841731284ec2311ae` |
| Canonical metadata SHA-256 | `7ed3c82aacd42765a45bb0daf7ec73e7bdb9240b87e4364f361a25e372f333af` |

The release branch was fetched, and the local tag was created at the pinned
commit. The clean detached build checkout is `scratch/intel-1.4.2-candidate`.
The results checkout is separate. The tag has not been pushed.

The ignored release config was copied to
`scratch/intel-1.4.2-evidence/release-config.json`, resolving local paths and
setting `clients_dir` to the newly empty
`~/dev/parsetrail-resources/candidates/client-v1.4.2/clients`. The existing
encrypted Ed25519 key remains outside the repository and artifact trees.

## Preservation and staging backup

Before building, a local size/SHA-256 and symlink inventory recorded all eight
existing release files (legacy 1.3.1 and Intel 1.4.0), the installed 1.4.0 bundle,
and the original ignored release config. No local 1.4.1 candidate was present.
The baseline is `scratch/intel-1.4.2-evidence/preserved-before.json`, SHA-256
`7d6458969b40bc2a23b9c95f102436c7ce9fc6232692433dde281b6ffa15fa2f`.
The original 1.4.0 inventory still matches
`dff66e320cf2d97c3e8924707f1104de13f693926a7735808fd827c87776a655`.
The post-build comparison passed for every recorded file and symlink, including
the original installed app and release config.

With ParseTrail closed, all 44 files in the staging profile were copied into
the ignored `scratch/intel-1.4.2-evidence/staging-profile-before` directory.
Source and backup size/hash/symlink inventories matched. The copied database
passed SQLite integrity and foreign-key checks; its synthetic data contains
1 account, 20 transactions, 4 categories, 1 plugin record, and 7 statements.
The transaction date range is September 1–10, 2026. Saved configuration, logs,
model, and cached plugins are included in the backup. The production profile
was not used for these checks.

## Build and acceptance

**PASS — signed build:** the unmodified handover command completed from the tagged
checkout with exit 0. The native bootstrap, locked sync with freshly compiled
static-OpenSSL cryptography, and clean source/tag validation passed. The source
suite reported **470 passed, 5 skipped in 530.37 seconds**. Public trust-store
validation, PyInstaller packaging, thin x86_64 architecture inspection, loader
audit (**379 Mach-O files, 1 cryptography extension**), frozen provenance/runtime
smoke, all three offline modes, and DMG packaging passed. The runtime gates used
temporary profiles and system-only `PATH`; offline modes force offscreen Qt.
The owner supplied the signing passphrase privately in Terminal. No gate was
bypassed and no source change or rebuild was required.

Actual tools: CPython **3.13.15**, uv **0.12.7**, PyInstaller **6.21.0**,
create-dmg **1.2.3**, Rust/Cargo **1.98.0**, Apple clang **17.0.0**, SDK **26.2**,
and static OpenSSL **3.6.3**. PyInstaller's local ad-hoc bundle signing is not
Apple Developer signing or notarization.

**PASS — independent verification:** the public trust store verified the signed
manifest and DMG. All three inventory file sizes and SHA-256 digests matched.
The inventory digest matches the builder's printed value, and canonical metadata
identifies the exact source/tag/version/target above. The build checkout remains
clean. Full local output is `scratch/intel-1.4.2-evidence/build.log`, SHA-256
`95eb20b8bf44af75d83571f220e4f005b24111fa123bfdc562cc5307a0c2da10`.
Machine-readable verification is in
`scratch/intel-1.4.2-evidence/signed-verification.json`.

**PASS — separate installation:** mounted the verified DMG read-only, installed
with `ditto` to `~/Applications/ParseTrail-1.4.2-candidate/ParseTrail.app`, and
ejected it. All **2,141 file/symlink entries** matched between the built app, DMG,
and installed bundle. The installed executable passed thin x86_64 inspection;
its SHA-256 is
`6495a4ba67a2c98ac7c780a5e93b72e45cead941da4d847d8d51f1eabcb7e2a9`.
Finder drag-and-drop was not used.

**PASS — installed automated diagnostics:** system-only `PATH`, temporary
profiles, and no externally forced Qt backend were used. Runtime smoke passed
in **12.51 seconds**. The internally offscreen `fresh`, `cached`, and
`network-failure` probes passed in **32.27 / 27.61 / 26.01 seconds**, with
**189 / 190 / 189** heartbeat ticks and **0 / 0 / 2** intercepted requests.
All reported frozen execution and five onboarding pages; cached modes completed
synthetic import/model operations. Separate JSON/log files are retained under
`scratch/intel-1.4.2-evidence/installed-*`. Before the owner launch, the staging
profile still matched the backup exactly. The final older-file comparison passed.

**PASS — owner native GUI acceptance:** after completing the prepared offline
checklist, the owner confirmed, "Confirmed, all tests pass". The launcher used
native Qt, the staging URL, and system-only `PATH`, waiting for networking to be
disconnected before launch. This accepts:

- STAGING 1.4.2 window identity and installed Help > About text
  `client-v1.4.2 (4585f4c57d20)`.
- Existing synthetic accounts, transactions, plugins, categories, and model;
  responsive local views after the background-check delay without blocking login.
- Select All selecting and clearing every item in Category Spending and Balance
  History; Budgets refreshing in September 2026 Month and September 1–10 Custom
  Range, grouped by Category and Type.
- Transaction Review dates rendered as `YYYY-MM-DD`, with ascending and descending
  Date-header sorting.
- Configured logging, selecting the unused staging path
  `logs/intel-1.4.2-custom.log`, and current entries after restarting offline.
- Offline quit/reopen with saved data and responsive local views, without a
  blocking login. No defect or launch error was reported; individual macOS
  prompt wording was not supplied.

**PASS — post-walkthrough verification:** with the app closed, the configured
custom log existed (**1,739 bytes**, **15** entries dated September 26, latest
**16:31:02**). The prior log still exists, and the original configuration/log
copies remain in the checksum-verified 44-file backup. SQLite integrity and
foreign-key checks passed; all application-table rows match the backup. Only
SQLite's internal `sqlite_stat1` query-planner statistics changed. Cached plugin
and model bytes remain unchanged, as do all preserved older release/app/config
files. Local evidence is
`scratch/intel-1.4.2-evidence/owner-acceptance-verification.json`.

The prepared offline owner walkthrough is
`scratch/intel-1.4.2-evidence/owner-checklist.md`. It covers About identity,
preserved synthetic data/model/plugins, Select All, both budget date/grouping
modes, review-date rendering/sorting, configured logging, and offline restart.

**Acceptance limitation:** the pinned
`client/src/parsetrail/core/offline_smoke.py` explicitly assigns
`QT_QPA_PLATFORM=offscreen` in `run_offline_session_smoke`. Therefore launching
the installed offline diagnostics with that variable unset does not establish
native Qt execution. Record those probes as offscreen, separately from the
owner's native GUI walkthrough. The handover's three native offline diagnostic
runs remain unmet. The same forced setting exists in the 1.4.0 source, so the
earlier return note's native-diagnostic characterization should not be relied on
as proof of the Qt backend; its owner GUI evidence remains separate.

The signed build, installation, and native owner walkthrough are accepted;
the release handoff retains the diagnostic limitation. Resolve the native
probe requirement explicitly before accepting that gate; this task did not
change diagnostic code or the pinned release source.

Physical absence of development tools remains the existing R2 acceptance gap.
Apple Silicon, production deployment, publication/activation, and the coordinated
1.3-to-1.4 staging transition are outside this build/acceptance checkpoint.
TODO now records the completed Intel build/signing and owner GUI acceptance;
Windows installed acceptance and the Intel diagnostic gap remain open.

## Return to the Windows counterpart

Fetch `test/intel-macos-1.4.2-acceptance`. Commit `2970fc5` records the signed
build and installed automated checks; this subsequent documentation commit
records the owner walkthrough and post-walkthrough verification. Both belong
to the focused result branch; no release tag was pushed.

Complete Windows 1.4.2 installed acceptance and resolve the native diagnostic
coverage requirement during combined publication review. Then rehearse the
preserved-artifact and 1.3-to-1.4 API/website transition on staging. Public
activation remains a separate reviewed operator step. No artifact activation,
deployment, source fix, or replacement of prior signed candidates was performed.

## Windows review disposition: September 26, 2026

The Windows counterpart reviewed the pinned diagnostic and the original
[offline acceptance contract](client-offline-acceptance.md). That contract uses
automated source/frozen probes plus a separate native owner walkthrough. The
1.4.2 handover incorrectly added a requirement for native Qt in the three
automated offline modes, although they intentionally force offscreen Qt.

The handover and acceptance guide now state the actual backend explicitly.
Installed offscreen probes and the separate native runtime/owner checks passed,
so the Intel replacement-candidate gate is accepted with that documented
coverage. The original report above is retained; no native automated offline
run is claimed and no signed source or artifact changed. Physical absence of
build tools remains the separate R2 gap. Windows installed acceptance and the
staging release-transition rehearsal remain pending.
