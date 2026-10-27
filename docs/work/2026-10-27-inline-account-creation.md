# Create a document-backed account without leaving Review

Date: 2026-10-27. Roadmap IDs: V2-4/UX/6.
Branch/components: feature/client-financial-insights; desktop and local account suggestions.
Authorization: owner requested New account in the review account selector, prefilled from the selected document and editable; ongoing cohesive commits are authorized.
Implementation: complete; versioned public demo update prepared.
Automated verification: 20 new feature tests, 31 related checks and 103 integration checks passed; actual Windows synthetic modal journey passed.
Design verification: ui_ux reviewed the plan and actual integrated Qt renderings; primary inspected final default-size Windows forms.
Independent review: source/context/save/lock checks and public runtime handoff passed; final commit source comparison recorded at closeout.
Owner acceptance: owner praised the preceding interface; this feature's human review not performed.
Release authorization: not authorized; no release actions selected.

## Scope and decisions

Baseline: clean source at 335bd39; guided client implementation f92c025. Add
New account beside the account selector in initial printed-identity and
accountless-row/file review. Reuse the existing account form through a shared
module, preserving standalone Accounts Add/Edit behavior. Source, institution,
kind and scope remain editable account suggestions rather than posting decisions.

Use the selected statement section's identity and balance scope, not another
section or the institution's generic business description. Institution/kind may
prefill only from the exact verified catalog declaration's parser ID, revision
and hash. Yamaha's account-total liability remains distinct from a principal-only
Capital account and cash-only HSA. For known accountless loan exports, existing
finite supported-loan rules can suggest principal scope; otherwise unknown fields
require explicit user selection. No amount-sign or filename heuristic.

Masked/last-four/opaque identities stay visible as document context and in the
editable suggested name. Full account number stays blank unless the evidence
actually supplies a complete unmasked identity; missing digits are never
invented or silently stored as a full number. The example mask is illustrative;
this UI task does not alter parser admission syntax.

Saving creates an account only and selects it in the original review dropdown.
Use this account / Assign remains the explicit source association. Cancellation
writes nothing and preserves prior selection; save failure keeps entered values
for retry. Creating an account does not bypass locked assignment/correction
prerequisites, post money or change matching/date preferences. No schema change.

## Ownership and data

Desktop owns the pure draft helper, shared form, workspace import/caller wiring,
source/accountless review controls and focused tests. Primary owns integration,
this record, lasting documentation/planning links, final checks/commit and
versioned public demo-runtime handoff. ui_ux designs/critiques; evidence researched
current handler/identity/scope rules; integrity independently reviews the actual
diff. Specialists do not recurse or commit, and respect disjoint ownership.

Use public synthetic fixtures/disposable profiles for all behavioral tests and
screenshots. No original archive, private statement content, V1 settings/database
or root .env is needed. A later public runtime bundle may read only the existing
archive demo's schema marker and reuse its explicit paths/trust when preparing
the launch handoff; do not replace its profile, catalog, preferences or prior
runtime, or discard any review state the owner may have added.

## Design and verification criteria

New account is discoverable beside an empty or populated dropdown. The form
shows selected-document identity, editable suggestions and a concise explanation
that saving does not assign or post. Cancel returns to the same review context;
successful save selects the new account and focuses the existing assignment
action. Preserve selected accountless rows across list/model reloads.

Check full/masked/last-four identities, Yamaha/Capital/HSA scopes, missing or
mismatched catalog context, multiple document accounts, accountless exports,
cancel, save failure/retry, locked assignments and zero journals/bindings until
explicit confirmation. Run existing account form/window/binding/matching and
relevant demo integration regressions. Inspect actual Qt with readable fonts at
representative desktop sizes and keyboard focus; native/owner acceptance remains
distinct. Commit the cohesive feature after checks; prepare a separate versioned
public runtime for the current demo rather than recreating its financial profile.

## Implemented result

Added `core/v2_account_creation.py` with a pure immutable suggestion draft and
exact signed-context checks. `gui/v2_financial_account.py` now owns the shared
editable account form and account-only save/retry helper; the existing import
through `v2_workspace_window` and standalone Add/Edit defaults remain compatible.
New account is available next to both initial review account selectors. The
source identity and selected rows/current row survive creation and list reloads;
the new account is selected and the existing assignment action receives focus.

Drafts use selected statement section scope (including whole-liability Yamaha,
principal-only Capital and cash-only HSA). Known finite accountless loan families
use their existing supported principal rule only with exact signed liability
context. Unknown fields use explicit placeholders. Full numbers prefill only
when complete/unmasked; printed partial identifiers remain visible and are
included in the editable name. Source facts and existing matching policy do not
change. No parser or schema change; schema stays 22.

Cancel writes nothing; failed save retains entries and a stable account ID for
retry. Creation remains possible while an assignment is locked, but Use/Assign
stays disabled and correction prerequisites still apply. Corrected form wording
explains that account creation does not change an existing assignment, rather
than claiming every source is unassigned. The draft form has a comfortable
minimum width and an explicit Create account button.

## Verification and review

Windows source with the locked client Python/PySide6; pytest uses
`PYTHONPATH=.;client/src;client`, `QT_QPA_PLATFORM=offscreen`,
`-p no:cacheprovider -q --tb=short` unless native rendering is stated.

- New `client/tests/test_v2_inline_account_creation.py`: **20 passed in 13.13s**.
  Covers full/masked/last-four/opaque identifiers, selected multi-account scope,
  exact/missing/mismatched context, unknown scope, accountless exports, editable
  values, cancel, failed-save retry, stable ID and existing assignment locks.
- Related source/accountless bindings, signed matching context, anchors and
  workspace integration: **31 passed in 37.98s**.
- Primary `test_v2_workspace_window.py`, `test_v2_profile_startup.py`,
  `test_v2_binding_corrections.py`, `test_v2_binding_corrections_dialog.py`,
  `devtools/v2_review_demo` and `devtools/v2_statement_pilot`:
  **103 passed in 121.55s**. No broad redundant whole-client run was needed.
- Independent feature/accountless/scope selection: **27 passed in 36.22s**;
  latest selected-row restoration checks **2 passed in 2.24s**. A separate
  synthetic probe verified second-section scope, unchanged evidence, zero
  implicit assignment/journals and failed-save cancellation with unchanged
  profile hash. No actionable integrity finding remained.
- Actual Windows Qt, Segoe UI 10pt, public synthetic Yamaha: exercised real
  nested modal Cancel and Create, edited the account name, confirmed the created
  account remained unassigned, then explicitly used it with zero journals.
  Cancellation preserved profile bytes. Default review 720x480 and creation
  form 500x401 were readable; all editable account fields remained editable.
  Primary evidence: ignored `scratch/inline-account-qa-b2f40703` and harness
  `scratch/inspect-inline-account-creation.py --native`.
- ui_ux inspected real synthetic renderings. Its preserved-assignment wording
  finding was fixed; no clipping/material visual issue remained. Native input,
  screen-reader and Intel macOS acceptance were not established.
- Ruff check/format and whitespace checks passed. Only line endings were
  normalized before public runtime copying; no behavioral change followed checks.

Independent evidence remains in ignored
`scratch/ux-audit-inline-account-creation-20261027`. No private statements or
financial demo/profile tables were inspected for feature verification.

## Versioned demo handoff

Prepared the public update under
`scratch/archive-demo-f92c025/runtime-updates/20261027-inline-account-creation`.
Close the currently open demo and use `Open-updated-demo.cmd` there. It opens the
same original demo `review.db`, catalog, preferences, explicit public fixture
trust and isolated home. No profile copy, reset, migration or re-import occurs;
existing review state is not touched. The original runtime/launcher remains
available and the new version has its own startup log.

Independent public artifact audit verified all **277 manifest files**, including
248 client Python modules, exact hashes/sizes/inventory and current source bytes.
The original 275-file runtime and launcher also still match their original
manifest/expected invocation. New runtime contains no private profile or secrets.
The pinner read only the profile's schema marker; no financial tables were opened
and the owner's launcher was not executed by agents. Behavioral/native testing
used disposable synthetic profiles. Local artifact evidence is in
`scratch/ux-audit-inline-runtime-handoff-20261027/result.json`.

Runtime manifest SHA-256:
`7852e9bc03f770b59c58014a3b828b03380a4ec886dbec3f5efd6aadb0fef993`.
The final commit hook and post-commit source comparison complete provenance;
Git retains the cohesive feature commit identity.

## Remaining limits

The full account number can remain unknown when only masked text was printed;
the feature does not reconstruct hidden digits. Creating account metadata is not
account assignment, reviewed posting or reconciliation. Batch review, parser or
schema/matching-policy changes, daily-profile activation and release are outside
this packet. No new per-feature owner approval gate is introduced.
