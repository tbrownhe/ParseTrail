# Intel Mac 1.4.2 release candidate handover

Read the root README, TODO, client README, and this handover first. This replaces
the on-hold [1.4.1 build handover](intel-mac-1.4.1-handover.md). Preserve the
[original Intel acceptance](intel-mac-return-note.md), installed app, artifacts,
and populated staging profile.

## Source and scope

PR #38 is merged into main at `7bf64c7f453ea9c0ec46986cba3196664a9861d5`.
The owner accepted the existing feature set after Windows source retests. This
release includes the corrected embedded provenance, Select All controls, budget
date conversion and small-category aggregation, configured logging, and review
date rendering/sorting. A new version preserves the signed 1.4.0/1.4.1 bytes.

| Field | Required value |
| --- | --- |
| Fetch branch | `release/client-1.4.2` |
| Exact build commit | `4585f4c57d20101c1c6ac4f625b726e51913e562` |
| Local build tag | `client-v1.4.2` |
| Version / target | `1.4.2` / `macos-x86_64` |
| Suggested result branch | `test/intel-macos-1.4.2-acceptance` |

The branch can advance with documentation. Build the exact commit above in a
clean isolated worktree, not a later branch HEAD. The tag is initially local to
the Windows build host. If absent on the Mac, create it locally at that exact
commit; if present, verify it and never move it. Do not push the release tag from
this handover. No feature development, Apple Silicon build, Apple signing or
notarization, production deployment, or artifact activation belongs to this task.

## Preserve prior candidates and build

1. Inspect local changes, fetch the branch, and create a clean worktree at the
   pinned commit, for example `scratch/intel-1.4.2-candidate`. Keep the working
   checkout used for the return note separate from the tagged build checkout.
2. Preserve the original signed release at
   `~/dev/parsetrail-resources/clients/macos-x86_64`, its installed app, and any
   later candidates. The original inventory hash is
   `dff66e320cf2d97c3e8924707f1104de13f693926a7735808fd827c87776a655`.
   Record all prior candidate file checksums before building and compare afterward.
3. Create a separate empty output root, such as
   `~/dev/parsetrail-resources/candidates/client-v1.4.2/clients`. Copy the existing
   ignored release config to a new ignored file and change `clients_dir` to that
   absolute output path. Resolve relative paths against the old config's directory.
   Keep the existing encrypted ParseTrail Ed25519 key outside the repository and
   artifact trees; the owner enters its passphrase privately at the signing prompt.
4. From the tagged worktree's `client` directory, run:

   ```bash
   uv run --no-env-file --script scripts/release_bootstrap.py \
     --config /absolute/path/to/new-release-config.json client --platform macos-x86_64
   ```

   Retain the full local build log. This runs native interpreter/toolchain checks,
   locked synchronization, the source suite, native build and loader audit, frozen
   provenance/runtime smoke, all three offline modes, DMG packaging, signing,
   independent signature verification, and inventory recording. Do not bypass a
   failed gate. No Apple Developer certificate is required.
5. Independently verify the manifest using the public trust store and compare all
   inventory sizes/hashes. Verify canonical build metadata identifies the exact
   source/tag/version/target above. Preserve the printed inventory SHA-256.
6. Install the DMG's app in a separate candidate location, for example
   `~/Applications/ParseTrail-1.4.2-candidate/ParseTrail.app`. Preserve the older
   installed app and compare the new bundle with the built bytes. Confirm its
   executable is thin x86_64.

## Native acceptance

With ParseTrail closed, back up the existing staging profile before the first
1.4.2 launch and verify the copies. Keep the production profile untouched. Run
the installed runtime and three offline diagnostics in temporary profiles with
native Qt, retaining their results separately from the builder's offscreen gates.

Launch the candidate using the staging URL, native Qt, and a system-only `PATH`,
with networking disconnected. The original full synthetic walkthrough need not
be repeated; ask the owner to check the replacement artifact and repaired flows:

- Window identifies STAGING 1.4.2. Help > About shows
  `client-v1.4.2 (4585f4c57d20)`.
- Existing synthetic accounts, transactions, plugins, categories, and model remain
  available. Local views respond after the background-check delay, without a
  blocking login. Quit and reopen once while still offline.
- Select All selects and clears every item in Category Spending and Balance
  History. Budgets refreshes in Month and Custom Range, grouped by Category and
  Type. Use a date range containing synthetic transactions.
- Transaction Review displays `YYYY-MM-DD` dates; the Date header sorts oldest
  first and newest first.
- The configured log file exists and receives current entries. To verify a custom
  location, select an unused log path inside the staging profile, restart, and
  verify new entries there. Preserve the prior log and saved configuration.

Do not upload real statements. Existing synthetic credential/upload acceptance
does not need repetition during these repaired-UI checks. If any defect appears,
preserve diagnostics and stop the release handoff at that failure.

A system-only `PATH` does not prove operation on a machine where build tools are
physically absent. Keep the existing R2 acceptance gap open; do not remove the
owner's development tools to simulate it. Apple Silicon remains deferred.

## Return evidence

Commit and push a return note on the focused result branch, including exact
source/tag, test summary, architecture/native audit and smoke outcomes, release
sequence, inventory/DMG hashes and size, installed About text, owner GUI results,
offline restart, configured logging, preserved older-candidate checksums, and
any unresolved defect. Update engineering acceptance and remove only completed
TODO items. Keep keys, passphrases, financial data, models, detailed logs, and
local generated configs out of commits.

Return the note to the Windows counterpart for the combined publication review.
The next stage is the preserved-artifact and 1.3-to-1.4 API/website transition
rehearsal on staging; public activation is a separate reviewed operator step.
