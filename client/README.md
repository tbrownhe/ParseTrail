# ParseTrail Client

ParseTrail is a Windows and macOS desktop application that parses financial
statements, stores financial data in a local SQLite database, and talks to the
FastAPI backend for authenticated plugin distribution, application updates, and
optional encrypted statement submission.

Current development and native release acceptance target Windows x64 and Intel
macOS (x86_64). The owner has an Intel Mac; Apple Silicon (arm64) development,
packaging, and acceptance are deferred until test hardware is available. The
lock's arm64 resolution does not establish native support. Client 1.4 uses the
explicit `windows-x86_64` and `macos-x86_64` release targets. Its version-2 signed
installer contract requires a one-time manual upgrade from 1.3; see the
[target contract and transition](../docs/client-release-contract.md).

## Requirements

uv provisions the exact Python patch release declared in `.python-version` and
installs the locked project environment. Installer creation uses native tools;
Intel Mac source builds also need the toolchain in
[Intel Mac release gates](#intel-mac-release-gates).

- Python 3.13.15 (provisioned by uv; do not substitute another patch release)
- PySide6 Essentials 6.11.2 / Qt 6.11.2
- Windows 10 1809 or newer, or macOS 13 or newer
- [uv](https://docs.astral.sh/uv/)
- [NSIS](https://nsis.sourceforge.io/Main_Page) for Windows installers
- [create-dmg](https://github.com/create-dmg/create-dmg) for macOS installers

PySide6 replaced PyQt5 because ParseTrail is MIT-licensed while the freely
downloadable PyQt bindings are GPL-licensed. Desktop packages include the
PySide/Qt third-party notice and LGPLv3 text. Keep Qt libraries dynamically
replaceable when changing the packaging layout.

### Windows development environment

```powershell
cd client
uv sync --extra dev --frozen
```

### macOS development environment

```bash
cd client
uv sync --extra dev --frozen
```

## Run and test

Run the normal UI:

```bash
uv run --frozen python src/parsetrail/main.py
```

Run the automated suite:

```bash
uv run --frozen pytest
```

Exercise source plugins against local statement fixtures:

```bash
uv run --frozen python src/parsetrail/run_plugins_locally.py
```

The parser-development launcher explicitly enables unsigned local plugins and
logs that mode. The normal application has no unsigned mode.

## Local database and exact financial values

Client 1.3 stores monetary values as integer minor units with an explicit
currency code. Parser and application code use `Decimal`; conversion to float
occurs only at chart presentation boundaries. USD (two minor-unit digits) is the
only admitted currency today, so an unsupported currency fails explicitly
instead of being silently treated as dollars. Calendar-only statement and
transaction dates have no invented time zone. Generated import timestamps are
aware UTC values.

Transactions and statements have many-to-many membership. Overlapping CSV/XLSX
exports can therefore share one canonical transaction while both statements
retain their full row counts. Transaction identity uses a versioned,
length-framed SHA-256 fingerprint. New statement files use SHA-256 content
digests; migrated MD5 content digests remain only for duplicate-file
compatibility.

Database upgrades run against a same-directory shadow copy. ParseTrail validates
SQLite integrity, foreign keys, and the Alembic revision before atomically
replacing the original, and creates a collision-safe `.dbb` recovery copy first.
This precise-schema migration is intentionally not downgradable in place. To
recover, close ParseTrail, preserve the failed database for diagnosis, copy the
newest pre-migration `.dbb` beside it, and give the recovery copy the configured
`.db` filename.

Run a read-only, redacted preflight without printing account numbers,
descriptions, filenames, or balances:

```powershell
uv run --frozen python scripts/audit_client_database.py C:\path\to\client.db
```

## Offline startup and update checks

Parsing, categorization, clustering, and SQLite storage use bundled resources
and do not download package data. In particular, recurring-transaction
clustering uses ParseTrail's versioned English stop-word set instead of an NLTK
corpus.

By default, ParseTrail schedules a client/plugin update check three seconds
after the window is initialized. It never delays construction or first paint,
and a network failure does not prevent local use. Disable **Check for Client and
Plugin Updates After Startup** in Preferences for a completely network-silent
launch; manual update checks and optional statement submission remain available.

An empty profile still needs a signed parser catalog before its first import,
and automatic categorization needs a locally trained model. Installed plugins
and models remain usable offline. A bundled starter catalog is a proposal in
[the client review](../docs/client-development-review.md), not a current package
feature.

## Imports and recovery

One-off imports offer copy-to-archive, move-to-archive, and leave-in-place choices
before changing the original. The default retains the selected original and
creates a managed archive copy. Files placed in the managed import folder keep
the move-to-archive contract; managed failures and duplicates use `FAIL` and
`DUPLICATE` respectively.

`StatementImportService` commits statement rows, canonical transactions, and
statement membership before applying the source-file action. A failure to archive
after commit reports a recoverable pending archive. Keep the source in place and
retry: the committed file digest and canonical archive name let the retry finish
the archive without inserting the financial data again. Startup detects pending
archives in the managed import folder and directs the user to Import All
Statements. Recovery appears separately from duplicates in the import summary.

One physical multi-account statement has one file identity and canonical archive
but one `Statements` row per account. Overlapping statements reuse canonical
transactions and retain their own membership/row counts. Duplicate handling is
performed before inserting conflicting rows and is checked at flush time; a
fingerprint matching different canonical fields fails explicitly.

Tests inject failures around persistence and archive boundaries. The
[import acceptance sandbox](../devtools/import_acceptance/README.md) rehearses
overlap, multi-account import, cancellation, and failed-archive recovery on a
disposable copy of an authorized client database.

## First run and database backups

Help > Getting Started reopens the first-run guide. It explains local storage,
installed institution support, plugin installation, explicit contributions,
backups, and server-visible metadata. Parser errors distinguish unsupported
formats, missing/ambiguous matches, changed layouts, incompatible output, and
failed safety checks without including extracted statement contents.

File > Back Up Database uses SQLite's online backup API for a consistent copy.
File > Test Database Backup restores into a disposable database and checks
integrity and relationships. File > Restore Database writes to a new path and
preserves the active database. File > Database Location and Privacy shows the
database and managed statement locations. These backups are local plaintext and
exclude statement archives; back up the managed folders separately.

## Application service boundaries

GUI modules delegate database queries and mutations to headless services. Preserve
the characterization tests and explicit transaction owner when extending a flow:

| Service | Responsibility |
| --- | --- |
| `StatementImportService` | Parse/import persistence, deduplication, statement membership, and archive recovery; `StatementImportController` supplies Qt decisions/progress. |
| `CategoryService` | Category queries, atomic add/update/rename/merge, and archived-category behavior. |
| `AccountService` | Account queries/mutations, deletion constraints, and account-number assignment. |
| `BudgetQueryService` | Date ranges, grouping, signs, proration, and inactive-category semantics. |
| `TransactionReviewService` | Review filters, atomic edits, stale/missing references, and model-category compatibility retry. |
| `TransactionService` | Transaction ranges, latest balances, and atomic manual entry with truthful duplicate results. |
| `DashboardQueryService` | Deterministically ordered balances/checklists, chart/discrepancy inputs, and verified training data. |
| `ArtifactService` | Account-config exports and spreadsheet reports; account-config files are replaced atomically. |
| `StatementSubmissionService` | File validation, memory-only encryption, cancellation, upload/response cleanup, and server confirmation. |

`PluginManager` and the plugin/client manifest/store modules own artifact trust
and compatibility. Reusable dashboard canvas/table models live in
`gui/dashboard_widgets.py`; review table/filter models live in
`gui/review_models.py`. Services expose typed failures, while GUI boundaries show
bounded messages and retain chained diagnostics. These boundaries do not imply
that every local calculation already runs in a background worker.

Networking uses bounded connect/read timeouts, bounded retries for idempotent
requests only, and centralized error translation. Submission encryption/uploads,
plugin synchronization, and installer downloads run off the Qt thread. Plugin
synchronization works with progress UI disabled. Rejected stored credentials
permit exactly one UI-thread login retry while preserving the selected signed
catalog. Cancellation never reports a partial installer as ready. Installer
launch adapters avoid command-shell interpretation, and the app quits only after
the launch call succeeds. There is no remote model-sync workflow.

## Desktop login storage

ParseTrail stores its API access token in the operating system credential store:
Windows Credential Locker, macOS Keychain, or a supported Linux Secret Service or
KWallet backend. The token is never serialized into `config.json`. On a Linux
desktop without a secure keyring backend, the login remains in memory for the
current run and ParseTrail asks again after restart rather than falling back to a
plaintext or app-decryptable file.

Client 1.3 migrates an existing file-encrypted token once, rewrites the config
without it, and removes the obsolete `~/.parsetrail.key`. Clearing or invalidating
the login also deletes the OS credential.

## Signed plugin releases

Plugins are compiled into `.pyc` files and authenticated as one catalog. The
release manifest contains each plugin's safe filename, exact byte size, SHA-256
digest, Python bytecode identity, plugin version, and minimum client version.
The exact manifest bytes receive one detached Ed25519 signature.

The server stores immutable release directories, but it never receives the
private signing key and cannot create a plugin or installer release an installed
client will trust. The same offline Ed25519 release key currently signs both
artifact types; distributed clients contain only its public key.
Python bytecode is not encryption or obfuscation: signing detects unauthorized
changes but does not prevent decompilation.

### Provision the initial signing key

Choose a private-key location outside this repository and outside any
server-synchronized artifact directory. An encrypted removable drive is
recommended.

From `client/`, run:

```powershell
uv run --frozen python -m scripts.plugin_release generate-key `
    --private-key "X:\ParseTrail\plugin-signing-key.pem"
```

The command:

- prompts twice for a passphrase;
- writes an encrypted Ed25519 private key only to the explicit external path;
- adds only its public key to
  `src/parsetrail/assets/plugin-release-keys.json`; and
- refuses to put the private key anywhere inside the repository.

Back up the encrypted private key separately and commit the public trust-store
change. Never copy the private key to `parsetrail.com`, CI, this repository,
`parsetrail-resources`, or a client package. Do not store its passphrase in
`.env`, command arguments, or logs.

The provisioned release key has separate password-manager recovery copies of
the encrypted key and its passphrase. Recovery copies follow the same separation
from the server, repository, and distributed client.

### Configure a local release builder

The release entry point is a standalone uv script with no project dependencies.
Its [inline script metadata](https://docs.astral.sh/uv/guides/scripts/)
requires stable uv >= 0.12.5. Before any project sync, it validates the native
Windows x64/Intel macOS host, explicitly provisions the exact `.python-version`
CPython with uv, and inspects the executable's version, implementation, OS,
architecture, bitness, and standard (non-free-threaded) ABI. All later build
commands use that verified interpreter path with automatic downloads disabled.
The native builders invoke the same bootstrap when run directly.

Check just the bootstrap, without client package installation, release config,
signing keys, or publication:

```powershell
uv run --no-env-file --script scripts/release_bootstrap.py check --platform windows-x86_64
```

On Intel macOS, substitute `--platform macos-x86_64`. This can download the pinned
interpreter; it does not build an installer or load the repository `.env`.
Use the script entry point below rather than wrapping the release module in a
project-aware `uv run`, which could install dependencies before preflight.

Copy `release-config.example.json` to the ignored
`release-config.json` and enter explicit local artifact directories, the
external signing-key path, and optional SSH deployment values. Build scripts do
not read the repository `.env`. The config contains no passphrase; signing
always prompts through the terminal.

Every release requires a clean worktree and an exact tag at `HEAD`. Client tags
are derived from `src/parsetrail/version.py`, for example:

```powershell
git tag client-v1.4.0
```

Plugin tags are explicit operator-chosen identifiers, such as
`plugins-2026.08.29.1`. Push a tag only after the dry run succeeds.

### Run a plugin release

From `client/`, the same command works on Windows and macOS:

```powershell
uv run --no-env-file --script scripts/release_bootstrap.py `
    --config release-config.json plugins `
    --tag plugins-2026.08.29.1
```

The default is a dry run: it validates the clean tagged source, synchronizes the
locked Python patch release, runs all client tests, compiles the complete plugin
catalog, removes stale compiled output, prompts for the offline-key passphrase,
signs, independently verifies, and writes `release-inventory.json`. It does not
connect to or change the public server.

Preserve the dry-run directory and the printed inventory SHA-256. Use the shared
[publish-existing workflow](../docs/artifact-publication.md) to review those exact
bytes with public keys and explicitly activate them. Publication does not repeat
the build or signing step and does not require the signing drive.

For key rotation, first release a client that contains both old and new public
keys. Only start signing catalogs with the new key after that client is
available.

### Client trust behavior

The normal application:

- verifies the manifest signature before trusting catalog metadata;
- downloads every listed plugin into a staging release;
- enforces bounded reads, network timeouts, safe filenames, Python
  compatibility, exact sizes, and SHA-256 digests;
- changes the active release only after the complete catalog verifies;
- re-verifies every plugin before each startup and dynamic import; and
- rejects rollback, reused release sequence numbers, legacy unsigned plugins,
  partial downloads, and tampered local files.

Existing unsigned `.pyc` files are left in place but ignored. Cancellation or
any failed artifact preserves the previously verified release.

## Isolated staging profile

An installed client can target the LAN/VPN staging service without changing its
normal profile. Profile selection happens before settings, logging, database, or
keyring modules are imported.

Windows:

```powershell
& 'C:\Program Files\ParseTrail\ParseTrail.exe' --staging https://api.staging.parsetrail.com/api/v1
```

macOS:

```bash
/Applications/ParseTrail.app/Contents/MacOS/ParseTrail \
  --staging https://api.staging.parsetrail.com/api/v1
```

Staging uses a separate `ParseTrail-Staging` application-data directory, database
and managed archive, reports, logs, plugin catalog, submission-key cache,
downloads, config history, and OS credential service. All configurable staging
paths are constrained to that profile root. The window title and red status bar
remain marked `STAGING`; closing it and launching normally returns to the normal
profile. The complete server/client rehearsal is in
[docs/staging.md](../docs/staging.md).

## Build and release the desktop installer

Before building, update `src/parsetrail/version.py`, commit it, and create the
matching `client-v<version>` tag. Both platform builders refuse a dirty tree,
missing/mismatched tag, reused versioned installer, or empty public-key trust
store. The source commit is embedded in the installed app and included with tool
versions and file checksums in `release-inventory.json`.

Before launching the frozen smoke, both builders inspect the executable header
without running it. Windows requires a PE32+ AMD64 executable; Mac requires a
thin x86_64 Mach-O executable, with PyInstaller's target explicitly set to
`x86_64`. A wrong CPU/format, DLL, universal binary, or truncated header stops the
build before installer packaging/signing. To inspect a candidate directly with
the verified interpreter, use `scripts/release_architecture.py --platform
<target> --binary <executable>`; this package-free command does not launch it.

Hosted source tests select Windows x64 and `macos-15-intel` explicitly, provision
the exact native interpreter before dependencies, and assert the final client
environment's target. Intel CI also runs the native toolchain/static-input sync.
The [GitHub runner matrix](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job)
identifies generic `macos-latest` as ARM, so it is not the Intel acceptance job.
CI source tests do not replace native frozen builds or the owner walkthroughs.

Windows:

```powershell
uv run --no-env-file --script scripts/release_bootstrap.py `
    --config release-config.json client --platform windows-x86_64
```

This synchronizes the locked environment using the exact Python patch release in
`.python-version`, builds the PyInstaller application, smoke-tests the frozen
runtime, packages it with NSIS, prompts for the offline release-key passphrase,
and independently verifies the signed installer manifest. Install NSIS normally;
`makensis.exe` may be on `PATH` or in its standard installation directory. No
`MAKENSIS_PATH` setting is used.

Builders now stop after a signed dry run. Preserve the directory and printed
inventory SHA-256, then use [publish-existing](../docs/artifact-publication.md)
for either installer target or plugins. The old `--publish` / `-Publish` and
Windows `-DeployOnly` switches are retired. The new command verifies saved
output without rebuilding, re-signing, or requiring the private key; its default
is a local review, and `--activate` adds an explicit typed confirmation.

An interrupted upload cannot replace the active release. Activation compares the
original pointer under a channel lock, so a competing publisher cannot overwrite
a newer activation. If SSH drops during activation, the publisher reads the
authoritative pointer; an unreadable outcome or a public smoke failure is
reported separately. See the publication runbook for recovery and prerequisites.

macOS:

```bash
uv run --no-env-file --script scripts/release_bootstrap.py \
    --config release-config.json client --platform macos-x86_64
```

This builds the `.app` and a drag-and-drop `.dmg`, signs its ParseTrail release
manifest with the same offline key, verifies it, and smoke-tests the actual
frozen executable. Run this gate on a real supported Mac. Apple signing and
notarization are separate from ParseTrail's application-level artifact signature
and are not yet enabled.

### Intel Mac release gates

The common client release entry point and the direct Bash builder check the Mac
toolchain before the first project dependency operation. Install Xcode command
line tools (`xcode-select --install`) and the Homebrew build prerequisites if
missing:

```bash
brew install openssl@3 rust pkg-config create-dmg
```

From `client/`, inspect the toolchain independently of a signing key, release tag,
or project environment:

```bash
uv run --no-env-file --script scripts/macos_release.py preflight
```

Success prints the Intel target and running macOS version, OpenSSL version/static
archive hashes, Rust, Cargo, clang, macOS SDK, pkg-config, and create-dmg versions.
The command installs no tools or project packages. It requires stable
Rust >= 1.83.0, Intel OpenSSL 3
static archives and headers, and available Apple `lipo`/`otool` commands. The
running OS must be macOS 13 or newer for the prebuilt Qt runtime.

The SDK version and the running OS version describe different things. An older
selected SDK is not by itself evidence that the installed client is unsupported:
ParseTrail packages prebuilt Qt libraries. Qt's documented Xcode/SDK build matrix
applies when compiling Qt; see [Qt for macOS](https://doc.qt.io/qt-6/macos.html).
The native dependency build, library audit, and frozen smoke still need to pass.
For an Apple toolchain update, first inspect `sw_vers -productVersion` and
`xcode-select --print-path`; the latter may reveal that an older installed Xcode
is still selected. Use Apple's
[command line tools installation guide](https://developer.apple.com/documentation/xcode/installing-the-command-line-tools/)
and [Xcode compatibility table](https://developer.apple.com/xcode/system-requirements)
to choose a stable version supported by the running OS. A tools-only update does
not change ParseTrail's minimum supported macOS version.

If Software Update offers nothing while the selected tools are old, use Apple's
[More Downloads](https://developer.apple.com/download/more/) with an Apple Account
to obtain a compatible **Command Line Tools for Xcode** installer. For the
accepted Intel Mac running Sequoia 15.7.9, the selected update candidate is
**Command Line Tools for Xcode 26.3**. Open its DMG and run the included package,
then rerun the preflight from `client/` to record the compiler and SDK actually
selected. When `xcode-select --print-path` already reports
`/Library/Developer/CommandLineTools`, no developer-directory switch is needed.
Do not delete that directory merely because Software Update offers no update.

Source builds receive `OPENSSL_STATIC=1` and explicit OpenSSL directories from
`brew --prefix openssl@3`, including the target-qualified Rust build variables.
The final builder reinstalls cryptography with uv's cache disabled so an older
locally built dynamic wheel cannot be reused. Upstream compatible wheels remain
eligible; source builds use the inspected static inputs. Subsequent project
commands use `--no-sync` to preserve that environment. See the upstream
[cryptography build instructions](https://cryptography.io/en/stable/installation/#building-cryptography-on-macos)
for the static-linking requirement.

Before DMG creation/signing, the builder inspects each packaged Mach-O image's
Intel load commands. It accepts system libraries and resolved bundle-relative
libraries, rejects absolute workstation paths, escaping/broken symlinks,
unresolved libraries and rpaths, and rejects a cryptography extension linked to
dynamic OpenSSL. The audit resolves each image's own rpaths and the main
executable's rpaths; an unusual layout requiring another loader's inherited
rpaths must be reviewed instead of bypassing the gate. The inventory records
these audit results and the native build inputs without local build-directory
paths. This is build evidence, not an additional signed attestation.

The frozen smoke then has a **30-second deadline**, a temporary profile, and only
system tool directories on `PATH`; it removes Python and dynamic-loader
overrides. It checks the native credential backend and executes synthetic
cryptographic signing, SQLite, XLSX, PDF text/rendering, Qt image, scientific,
and model fit/predict operations. Fixtures stay in memory and no financial files
are opened. A timeout or any failed operation stops packaging.

Owner acceptance remains necessary: run the preflight on the Intel Mac, then
run the normal tagged dry build and retain its `release-inventory.json`. Install
the resulting DMG and exercise startup/local use with networking disabled and
build-tool directories absent from `PATH`. The automated audit and sanitized
smoke do not replace a native installed-app walkthrough or prove acceptance on
a machine where the build toolchain is physically absent. Keep the latter gate
open until that environment is available; do not remove your development tools
just to run the smoke test. Apple Silicon remains deferred.

Client 1.3 understands the plugin manifest's signed source-commit field. Publish
the 1.3 client before the first plugin catalog generated by this release command;
older clients reject that catalog and retain their previously verified plugins.

See [artifact rollback](../docs/artifact-rollback.md) for restoring an earlier
immutable release without rebuilding or deleting release evidence.

## Plugin architecture

Plugins remain decoupled from the client release so parsers can be updated
without shipping a new application:

- Source lives under `src/parsetrail/plugins` for development and IDE support.
- Release plugins are loaded at runtime with `importlib` only after
  authentication.
- Plugins may import stable interfaces from the client codebase.
- The signed manifest carries compatibility metadata, so a plugin never needs
  to execute merely to determine whether it can be loaded.
- Parsing is headless: the core returns typed results, warnings, and redacted
  failures. GUI and batch adapters independently decide how to present or accept
  warnings.
- Routing walks suffix, optional PDF metadata, normalized page-header markers,
  and body-text expressions, then refuses zero or multiple matches.
- Expressions use parentheses, then `&&`, then `||` precedence, with quoted
  literals supported. Strict syntax is validated at plugin build and load time;
  CSV, XLSX, and PDF use the same routing contract.

Native release and private-fixture acceptance history is preserved in the
[engineering acceptance record](../docs/engineering-acceptance.md). Current
unfinished release, offline, and workflow work lives in [TODO](../TODO.md).
