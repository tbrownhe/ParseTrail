# Simplifying desktop releases

The owner requested a simpler release process on September 26, 2026 and made
it a prerequisite for publishing 1.4.2. Windows and Intel macOS installed
acceptance is complete. Preserve the accepted installers while improving the
workflow; a tooling change alone does not require rebuilding them.

## Intended operator experience

1. Select a version/tag and start one GitHub Actions workflow. It builds and
   tests Windows x64 and Intel macOS and retains both installers with their
   source/build identity and results.
2. Perform one short installed-app check on each available native platform.
   Repeat broader workflows for relevant changes or failed checks.
3. Use one local release command to retrieve and verify the selected CI run,
   sign both manifests, and manage reviewed staging/public promotion using
   those same bytes. A saved release record supplies paths, hashes, sequences,
   and completion state instead of requiring manual transcription.

Keep the existing encrypted signing key on the owner's machine/removable drive.
CI builds without that key. Detached signatures are added locally without
changing installer bytes. Reuse the current public API and immutable artifact
store; a hosting migration or signing credentials in CI is unnecessary.

GitHub provides Windows x64 and Intel macOS hosted runners, including
`windows-2025` and `macos-15-intel`; existing client CI already tests both
architectures. See [GitHub's runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
Apple Silicon remains deferred. A manually dispatched workflow must first be
on the default branch; see [workflow dispatch](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch).

## Testable implementation chunks

- **R4a — CI installer builds:** supported build-only mode in both builders,
  without a key or prompt; one tag-pinned workflow retaining installers,
  checksums, native reports and test results. Failed jobs cannot produce a
  complete candidate. The build's architecture and frozen/offline gates remain.
- **R4b — One local release record and command:** retrieve both targets from a
  successful CI run, or adopt the already signed 1.4.2 outputs. Verify source,
  target, exact bytes and provenance before signing once. Preserve the native
  builder's metadata when signing on another OS. Reuse publication checks and
  record completion per target so interruption does not require rebuilding or
  re-signing. Reject wrong runs, missing targets and changed files.
- **R4c — Short release guide:** make the normal path work without bespoke
  `scratch` scripts, copied hashes, repeated manual toolchain checks, or Mac-to-PC
  transfers. Keep historical evidence by link and generate new release summaries.

These are release-workflow changes within the approved client release scope.
Unrelated client features remain deferred.

The implementation branch adds the build-only native modes and CI workflow,
`scripts.desktop_release` for paired preparation/adoption/publication, and the
[short operator guide](client-releases.md). The focused automated tests cover
wrong/failed CI runs, archive boundaries, changed artifacts, source/target
disagreement, one signing prompt, unchanged adoption, cross-host provenance,
staging-before-production, and interrupted paired publication. Both hosted native
packaging jobs subsequently passed in [run 36282715627](https://github.com/tbrownhe/ParseTrail/actions/runs/36282715627).
Real-artifact adoption/publication review remains pending the Mac transfer; the
validation outputs are not replacements for the accepted signed 1.4.2 pair.

## One-time contract transition

The 1.3-to-1.4 target change still requires the coordinated staging rehearsal in
[the client contract](client-release-contract.md). Ordinary desktop releases
should not require a server rebuild/deployment when that contract is unchanged.

Read-only operator inspection found legacy Windows 1.3.0 and Mac 1.3.1 channels
in both environments, with no new target channels. Deployment evidence currently
enumerates only `win64` and `macos`. The transition needs an audit of the explicit
1.4 targets and an explicitly reviewed staging candidate, retaining plugin and
production isolation and rollback evidence. Do not bypass parity checks or
publish to production first merely to make staging match it.

Windows 1.4.2 passed local publication review against staging. The Mac output
remains on its builder; an empty private inbox is prepared under
`/srv/parsetrail-staging/release-input/client-v1.4.2-artifacts/macos-x86_64`.
No candidate has been published.
