# Publish preserved artifact output

Client and plugin builders produce signed dry runs. Publication is a separate
`publish-existing` operation that uses the saved files and public trust keys.
It never rebuilds an installer, executes a parser, compiles plugins, re-signs,
rewrites the inventory, or opens the private signing key. The native builder
publication switches, including Windows `-DeployOnly`, have been retired.

## Preserve the build evidence

After a successful tagged dry run, retain the complete output directory and the
printed **Inventory SHA-256** with your release record. That directory contains
the installer or compiled plugins, manifest, detached signature, and
`release-inventory.json`. Use a separate saved directory for each candidate;
later builds may replace the current output directory's catalog and inventory.

The inventory hash anchors the record reviewed after the build. Do not calculate
a replacement hash just to get changed output accepted. For existing reviewed
output created before this hash was printed, inspect and record it locally:

```powershell
Get-FileHash -Algorithm SHA256 '<release-dir>/release-inventory.json'
```

On macOS use `shasum -a 256 '<release-dir>/release-inventory.json'`. The publication
argument requires the digest in lowercase. Preserve the evidence outside the
public artifact directories as well as alongside the release.

The manifest signature authenticates artifacts and installer target/version.
Plugin manifests additionally authenticate their source commit. Client source
and native build evidence are inventory records, not signed build attestations;
their integrity during this workflow depends on the recorded inventory hash.
Matching a Git tag is not proof of reproducible output or native acceptance.

## Review without a signing drive or server connection

Use a trusted ParseTrail checkout containing the release's Git tag, public trust
store, and an already installed client environment. Publishing preserved output
does not require that tag at `HEAD` or a clean worktree, and the publishing host
can differ from the installer target. It does not provision Python, synchronize
dependencies, or require NSIS, Homebrew, Xcode, or create-dmg.

Copy `client/publish-config.example.json` to ignored `client/publish-config.json`
and enter the intended SSH destination and HTTPS API base URL. This minimal
config has no signing-key or local build-directory fields. The existing full
`release-config.json` also works; publication never resolves its private-key or
build paths. The repository `.env` is not loaded.

From `client/`, review a saved Intel Mac release:

```bash
uv run --no-env-file --script scripts/release_bootstrap.py \
  --config publish-config.json publish-existing \
  --kind client --platform macos-x86_64 \
  --release-dir '<saved-release-directory>' --tag client-v1.4.0 \
  --inventory-sha256 '<recorded-lowercase-digest>'
```

In PowerShell use backticks for line continuation. Windows uses
`--platform windows-x86_64`. Plugins use `--kind plugins`, their explicit source
tag, and no `--platform` argument. The direct module equivalent is
`uv run --no-env-file --no-sync --no-python-downloads python -m scripts.release`.

The default operation verifies a temporary private copy, then prints the exact
destination, source tag/commit, target, sequence, inventory digest, and every
published file's size/hash. It makes no remote connection. Verification requires:

- the recorded inventory digest and exact manifest/signature/artifact checksums;
- a signature trusted by the public key store, safe regular files, and a complete
  inventory describing exactly the signed release;
- an inventory source tag/commit matching the explicit local Git tag;
- build Python matching `.python-version` at that commit, and plugin bytecode
  tags matching that Python minor version;
- one installer matching the requested channel, architecture, version, and
  `client-v<version>` tag, or a plugin catalog with its signed source commit.

Unknown keys, changed bytes, missing inventory, source/target disagreements, and
unsupported installer targets fail locally. The temporary copy ensures that
changes in the builder output during confirmation cannot alter approved bytes.
It needs free disk space for one copy of the release and is removed on exit.

## Activate and verify

After reviewing the summary and native acceptance evidence, repeat the same
command with **`--activate`**. It verifies again, prints the summary, and requires
the exact displayed `publish <kind> <target> <sequence>` phrase. Declining or
closing input leaves the remote untouched. Rehearse on staging before the
[1.4 API/website transition](client-release-contract.md).

SSH/SCP must be available locally. The existing Linux artifact host needs `sh`,
`stat`, `sha256sum`, `head`, `cut`, `mv`, and `flock`; no service configuration or
deployment is performed by this command. Publication:

1. Rejects a reused immutable directory, malformed active pointer, or sequence
   that is not greater than the active sequence, before uploading anything.
2. Uploads every reviewed file into a new `releases/<sequence>` and checks its
   remote size and SHA-256 digest.
3. Verifies a temporary pointer, takes the channel's `.publish.lock`, and compares
   the original pointer before atomically replacing it. A competing activation
   cannot be overwritten by a writer that observed the earlier pointer.
4. Reads the authoritative pointer, including after an interrupted SSH move,
   then compares exact public manifest/signature bytes and checks the plugin
   listing or installer range response.

All publishers and manual pointer changes must honor the same channel lock.
The lock file may remain on disk; `flock` releases the lock when its process ends.

An incomplete upload never changes the active pointer. Its immutable directory
is preserved for diagnosis and cannot be reused by this command. Do not delete
or overwrite it to bypass the guard. Reconcile a failed candidate before deciding
on a new signed sequence.

If activation succeeds but public smoke fails, the error explicitly reports that
the release **is active**. Investigate routing/caches/API compatibility and use
the [rollback runbook](artifact-rollback.md) when appropriate; re-running
publication cannot reuse that sequence. If SSH also prevents reading the pointer,
the outcome is **unknown**: read `current-release.json` once connectivity returns
before retrying or rolling back. An automatic rollback is not attempted.
