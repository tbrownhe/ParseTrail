# Intel Mac 1.4.1 candidate handover

Read the root README, TODO, and client README first. This handover supersedes
the build instructions in the original [Intel handover](intel-mac-handover.md)
for the new candidate only. Preserve its [1.4.0 return note](intel-mac-return-note.md)
and all original acceptance artifacts.

## Purpose and source

Windows and Intel **P1.6/P2.2 native walkthroughs are complete**. The Windows
walkthrough exposed a packaging defect: valid build metadata was bundled with a
random filename, so About reported development provenance. The fix uses the
canonical filename and adds a shared frozen smoke requirement for readable
metadata matching the running version and target. Mac already used the correct
filename; its new candidate must pass the stricter shared gate at the same version.

| Field | Required value |
| --- | --- |
| Fetch branch | `release/client-1.4.1` |
| Exact build commit | `0261f1f9d4efc4ba6aa7e7e31df4f421ef628ebd` |
| Local build tag | `client-v1.4.1` |
| Version / target | `1.4.1` / `macos-x86_64` |
| Suggested result branch | `test/intel-macos-1.4.1-acceptance` |

The branch can advance with documentation after the build commit. Build the
exact commit above in a clean isolated worktree; do not substitute branch HEAD.
The Windows assistant created the tag locally and has not pushed it. If the tag
is absent locally, create it at the exact commit above after fetching the branch.
If it already exists, verify its commit; never move an existing tag.

Apple Silicon, Apple Developer signing/notarization, C1–C3 cleanup, and F1–F4
features remain outside this task. Do not publish artifacts, push release tags,
merge into main, or deploy the API/website. The 1.3-to-1.4 transition and hosted CI
remain separate release gates. Keep private keys, passphrases, financial data,
databases, models, and detailed application logs out of commits and return notes.

## Preserve the accepted 1.4.0 state

Retain the complete original directory:
`~/dev/parsetrail-resources/clients/macos-x86_64`.
Its inventory SHA-256 must remain
`dff66e320cf2d97c3e8924707f1104de13f693926a7735808fd827c87776a655`.
Preserve its signed DMG, manifest, signature, installed app, local tag, and the
populated `~/Library/Application Support/ParseTrail-Staging` profile. Recheck the
old release hashes after the new build.

Create a separate empty output root, for example
`~/dev/parsetrail-resources/candidates/client-v1.4.1/clients`.
The builder will create `macos-x86_64` beneath it. Copy the existing ignored
release configuration into a new ignored local file and change only `clients_dir`
to that absolute output root. Resolve any relative paths against the original
configuration before copying. Keep the old config unchanged. The current encrypted
Ed25519 key can be reused; the owner enters its passphrase privately when prompted.

## Build and inspect

1. Inspect local changes before fetching. Create a worktree such as
   `scratch/intel-1.4.1-candidate` at the pinned source. Verify its clean status,
   version, and exact tag. Prepare the new config/output location before building.
2. From that worktree's `client` directory, run the normal release command with
   the new config's absolute path:

   ```bash
   uv run --no-env-file --script scripts/release_bootstrap.py \
     --config /absolute/path/to/new-release-config.json client --platform macos-x86_64
   ```

   This performs the interpreter/toolchain checks, locked sync, source suite,
   native build/audit, runtime smoke, all three frozen offline modes, DMG creation,
   signing, verification, and inventory. Do not bypass failed gates. Keep the full
   local build log and report the exact source-test summary.
3. Independently verify the saved manifest with public keys and check every file
   against the inventory. Confirm the embedded canonical `build-metadata.json`
   names the pinned source, tag, version, and Intel target. Record the native audit
   and smoke results, release sequence, inventory/DMG hashes, and tool versions.
4. Install the new DMG into a separate candidate location such as
   `~/Applications/ParseTrail-1.4.1-candidate/ParseTrail.app`. Preserve the 1.4.0 app.
   Compare installed bundle hashes with the build and inspect its x86_64 binary.

## Short owner GUI check

Back up the existing staging profile before its first 1.4.1 launch and keep the
production profile untouched. The previous full native walkthrough remains valid;
this check covers the replacement artifact and the changed provenance gate.

Launch the new app with native Qt, system-only PATH, the staging URL, and networking
disconnected, using the launch pattern in the original handover with the new app
path. Ask the owner to confirm:

- The window shows **STAGING 1.4.1**, and **Help > About** shows
  `client-v1.4.1 (0261f1f9d4ef)` rather than development provenance.
- The existing synthetic database, signed plugins, categories, and model remain
  available, local views respond after the update delay, and no blocking login
  appears. Quit and reopen once while still offline.

Run the installed runtime/offline diagnostics in temporary profiles with the new
executable and native Qt. Preserve any failure diagnostics and distinguish these
results from both owner GUI observations and the earlier sandboxed/offscreen Mac
limitation. The Mac assistant can run these diagnostics directly.

A system-only PATH check still does not establish operation on a machine where
build tools are physically absent. Keep that separate outstanding R2 item honest.

## Return evidence

Commit and push results on the focused result branch, without changing the tagged
worktree. Add a new return note and the durable evidence to engineering acceptance.
Include exact source/tag, signed sequence, inventory/DMG hashes and size, source
suite count, architecture/native audit, all smoke outcomes, installed About text,
offline restart result, preserved 1.4.0 hashes, and any unresolved defects. Keep
TODO limited to unfinished work. No publication or release-tag push is authorized
by this handover.
