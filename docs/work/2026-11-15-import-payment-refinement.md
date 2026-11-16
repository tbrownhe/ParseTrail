# Import convenience and pending payment review

Date: 2026-11-15. Roadmap: V2-UX, V2-3/4/5. Branch: feature/client-financial-insights.
Authorization: owner requested committing the previous diff, then implementing the
agreed import/payment refinements. Implementation: complete. Focused automated,
native-render and agent design checks passed. Independent financial/evidence
review: passed within the recorded scope. Owner
acceptance: feedback on the previous candidate supplied; this pass not accepted.
Release authorization: not requested.

## Scope and controlling decisions

Prior work committed with normal hooks: `a369fd0` category/import/evidence
presentation; `2ee49d3` shared review/Budget workflow and recovery; `6c4ab9e`
documentation/verification and owner-test preparation. Working tree clean before
this pass. Existing private owner test remains pinned and untouched.

Agreed outcomes:

1. Open original document while naming/creating an import account; retain drafts.
2. Offer contextual access to the global abbreviated-account matching preference.
   Unique full-number matching already exists; ambiguity still requires a choice.
   A stored partial identifier must never become an invented full account number.
3. Configure import preview as Always / Only when attention is needed. Account
   ambiguity, unknown assignments and material interpretation warnings require
   review; hard parse/validation failures cannot be overridden. Automatic source
   import saves unreviewed evidence, never automatic category postings.
4. Verify Capital One Auto total/principal/interest on a shared printed line and
   expose the appropriate loan review workflow, rather than a generic asset-cash
   scope error. Preserve exact components, dates, source locations and unknowns.
5. Open dropdown lists on whole-control clicks while retaining searchable editing,
   keyboard operation, explicit choices and owner-scoped Qt lifetime behavior.
6. Persist Transfer/card-repayment designation without launching matching UI or
   inventing a counterpart/posting. Both sides require explicit designation for
   ordinary automatic matching in this pass. Counterpart details remain optional;
   actual matching/posting requires explicit confirmation. Keep loan components
   separate. Changes to saved decisions require a new correction reason.
7. Prefill the initial shared review reason with exactly **Initial Review**;
   preserve edits/cancellation and start the next fresh set with that default.
   Corrections/withdrawals start blank and remain required. This replaces the
   previously discussed optional-reason preference. No ML work is selected.

Permitted data: synthetic/disposable profiles and ephemeral fixture catalogs.
Owner additionally authorizes read-only CAPONE*.pdf under the named SUCCESS archive,
starting with CAPONE-AUTO_20240722_20240821.pdf, for the parser check. Evidence
specialist alone handles those inputs; no private statement content, amounts,
identifiers or plaintext extracts in Git/routine logs. Do not inspect the owner's
test database, other private archives, root `.env`, production or signing material.
No original modification, daily-profile activation, migration, deployment or release.

Ownership: primary integrates scope/contracts/record, preferences/import pipeline
and assigned GUI work. ui_ux establishes the journey and actual-render recheck.
Evidence owns the bounded Capital declaration/handler and synthetic regressions;
ledger exclusively owns authoritative profile-store/schema and transfer-intent/
matching services with headless tests. GUI ownership will be divided after the
interaction/API model is established. Specialists do not delegate or commit and
must preserve disjoint concurrent edits. Independent integrity and fresh goal-based
acceptance follow integration; native focus slots are serialized.

Observable criteria: original accessible without losing account drafts; matching
opt-in explains partial/ambiguous identity; optional preview visibly separates
import from posting and pauses on actionable problems; lender components and correct
next action visible; transfer designation remains in the current review and survives
restart without money; eligible counterparts generate truthful proposals only;
changed/withdrawn decisions have explicit reasons/history; initial reason fast path
never authorizes corrections; populated/empty/blocked/cancel/retry states usable at
1050×700 and 1280×800, with keyboard and full-control dropdown access.

## Result and review

All seven selected outcomes implemented. No service, production or release changes.
Implementation commits with normal hooks: `d3a7bda` pending-transfer services,
`828b234` inline ordinary/repayment review, `dc9c1fd` import/original/dropdown/loan
integration. Contracts, planning status and this verification record follow together.

- Naming and preview both expose the original. The selected-file reader checks
  bounded regular bytes, digest and file identity on a worker; the memory viewer
  explicitly distinguishes not-yet-imported bytes from saved evidence. Returning
  preserves account drafts and the pending decision. PDF queue/lifetime rules remain.
- Matching/preview preferences are available contextually and in Settings, apply
  to subsequent files and acknowledge persisted state or roll back controls on error.
  Verified remembered partial identities remain partial. A conflicting full-number
  suffix or multiple account matches always requires manual selection.
- Always is the preview default. When-needed import requires one recognized,
  routine interpretation and complete automatic existing-account choices. Material
  warnings across **all** rows, new/unknown accounts, ambiguity or changed inputs
  pause for review. Forced preview states why. Final parsing/write revalidates live
  preferences/source/catalog/accounts. Source import creates no financial entries.
- The authorized named Capital original was read-only checked in memory: its
  total/principal/interest already parse separately from the shared printed line,
  with retained locations. The original digest stayed unchanged. No production
  parser change was necessary. Synthetic repeated/shared-line/ambiguous-shape
  regressions were added. Supported lender documents now open a source-focused
  component view with correct whole-payment handoff, waiting-bank instructions,
  observed versus assumed dates, principal-only scope and unknown-opening limits.
- Whole-control dropdown opening is owner-scoped, includes dynamic controls and
  retains editable search, explicit selection, keyboard and disposal behavior.
- Schema **25** retains append-only pending transfer revisions. Designation makes
  no journal/allocation/clearing, remains in Review and survives restart. Mixed
  confirmation separately describes category posting and designation; the service
  validates/saves both atomically. Both legs must be explicitly designated for
  ordinary proposals. Manual transfer review remains available. Final matching
  requires confirmation. Saved intent corrections, withdrawal and reclassification
  require a fresh reason; matching history does not silently revive old intent.
- Initial shared reason is exactly **Initial Review**, editable and preserved with
  the review set. Its default alone is not dirty state. Saved notes and initially
  blank correction/withdrawal reasons remain separate. Initial loan review uses
  the same default; saved loan-event correction remains blank.

The earlier private owner-test candidate remains unchanged and pinned to schema 24.
Schema 25 requires a fresh disposable development profile; there is no migration.
No private owner profile or other archive was opened.

Design review preceded implementation. Final actual-render reviews resolved:
forced-preview explanation, staged-card date/status contradiction, outdated payment
instructions and waiting-transfer next action. Primary also removed a loan status
reference to a nonexistent preference above. No significant unresolved finding
was observed in final inspected screens.

Independent integrity review found and verified fixes for conflicting remembered
versus current suffix matches; material disposition codes whose warning token is
not a prefix; and source-focused loan history offering another source's event while
hiding its components. The latter now scopes history/event resolution to the source;
same-source Wells siblings remain visible and checked together. Exact source,
amount, date, revision/basis, whole-event and transaction guards were retained.

## Verification

Windows AMD64, Python 3.13.15, Qt 6.11.2; native screenshots use Windows Qt,
software test events, Segoe UI 9 at 96 DPI. Synthetic profiles/catalogs, isolated
home/null keyring. Counts below overlap; they are not a combined total.

- Evidence: **21 passed, 38 deselected**, bounded parser/decoder/proof checks;
  authorized Capital input read-only/digest unchanged, no private values logged.
- Ledger specialist: **56 passed** ordinary/transfer/planning/pending tests,
  **20 passed** read-performance checks; further source-integrity/selection/retry
  probes passed. Schema 24 refusal leaves bytes unchanged.
- Independent integrity: **43 passed** pending/ordinary, **36 passed** transfer/
  planning/import checks, plus two-connection compare-and-swap and preference/
  account-change probes. Same-source Wells, mismatched event/source and actual
  saved synthetic PDF opening independently checked after GUI integration.
- Ordinary desktop: **68 passed** existing focused GUI checks; new **7 passed**
  offscreen and **7 passed in 15.00s native, raw exit 0**. Final affected card case
  **1 passed in 2.27s native, raw exit 0**. Existing match dialog actual 1250×750.
- Original/dropdown specialist: **34 passed** focused offscreen checks and
  **6 native** convenience cases; final dynamic-control checks passed. An earlier
  combined native run had 18 pass/1 Windows path-length setup error; the excluded
  MOHELA case separately passed raw 0. That unchanged batch is not claimed as pass.
- Primary: **42 passed in 53.38s** import-automation/pending/ordinary checks,
  including warning suffixes and an assumed date beyond the five-row preview;
  **27 passed in 37.07s** core-journey/loan/dialog checks before the bounded history
  fix, followed by the new regression and final integration sequence below.
- Final combined native sequence: **22 passed in 28.98s, raw exit 0**, one process,
  ordinary pending/mixed review, import/original/PDF/dropdowns, integrated loan
  source/history/evidence and core journey. Normal GC/assertions retained. Actual
  main surfaces 1050×700 and 1280×800; original-viewer captures 1024×768.
- A later workspace/import/loan offscreen regression exposed test-window activation
  loss after popup completion: the requested editor/action held the dialog's
  logical focus, but offscreen Qt deactivated it and left a hidden QFrame active.
  Traces confirmed the nickname target did receive focus before deactivation;
  the production focus protocol was unchanged. The focused harness now asserts
  the logical target, reactivates only the offscreen task window and still requires
  actual focus/typing. First run stopped at 10 pass/1 focus failure; the next
  completed 44 pass/2 analogous Next-action activation failures. After applying
  that assertion consistently, the **exact workspace/import/loan command passed
  all 46 cases in 61.30s, raw exit 0 / 0x0**. No application timing changes, skipped
  assertions, GC changes or retry-to-pass workaround. Traces and all prior failures
  remain under `import-ui/focus-*`.
- Fresh acceptance specialist independently checked designation cancellation,
  persistence across **two separate Python processes**, explicit second-side
  designation, optional matching/final confirmation and zero spending. Each
  process passed one assisted offscreen test and exited 0. Final native wrapper,
  card, pending and forced-preview screenshots were independently inspected.
- Ruff check/format and diff whitespace checks cover changed Python files.
  Normal commit hooks remain enabled.

Artifacts: `scratch/import-payment-refinement-20261115/` (`import-ui`, `ordinary`,
`loan`, `final2`, `combined`, `integrity`, `ledger`, `acceptance`). Scratch artifacts
are disposable and untracked. Keep agent verification distinct from owner acceptance.

## Remaining limits

No selected implementation item remains. Owner feedback on this exact pass is
still needed as human acceptance; no release is authorized. Existing broader
platform/accessibility/installed/release gates remain separate.

Fresh uncoached native control could not start: Computer Use returned
"product policy blocks this app: python.exe". No alternate OS-control workaround
was used. The agent-owned acceptance launcher was stopped through its exec session,
so it has no graceful-shutdown attestation; repository native test sequences above
completed with raw exit 0. Fresh task-discovery/actual-user comprehension and native
manual keyboard behavior remain unverified. Screenshot inspection is evidence of
layout/wording, not human comprehension. The original viewer's 700-high layout,
long-list behavior and independent loan loading/error/missing-evidence discovery
were not assessed; focused service/GUI missing-bank behavior passed.
