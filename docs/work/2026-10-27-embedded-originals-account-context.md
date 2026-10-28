# Embedded originals, document-backed account context and draft protection

Date: 2026-10-27. Branch: feature/client-financial-insights.
Scope: owner-reported original-open failure, requested memory-only PDF reader,
document context for new accounts, last-four default names and discard confirmation.
Implementation: complete in development; verified public runtime handoff prepared.
Automated verification: integrated 151 tests passed; focused final password/controller suite 6 passed.
Design/native verification: actual Windows Qt PDF rendering and integrated account/batch journey passed.
Owner acceptance: prior external-open attempt failed; this replacement not reviewed.
Release authorization: not selected.

## Decisions and ownership

The user needs to distinguish accounts within a multi-account statement while
creating an account. Default original access will use a built-in read-only viewer
from verified DB bytes, without temporary copies or external dispatch. PDF uses
Qt PDF/QBuffer with lazy pages, navigation, fit/zoom and selectable page text;
CSV uses a bounded original-string reader. The current V2 admission remains PDF/CSV.
Add the matching Qt Addons dependency/lock; packaging and third-party notices must
reflect PDF support. No new source parser, XLSX import or schema changes selected.

New account shows selected immutable identity, qualified period, printed endpoint
values/scope and source page, with a built-in original action inside the modal
form. Missing printed product labels remain unknown. Do not infer checking,
savings or credit-line class from account digits, order or balances. Existing
OCCU evidence does not retain product heading text and excludes the personal
credit-line section from admitted accounting; the full original remains inspectable.
Defaults use institution plus the last up to four contiguous visible digits;
existing names and stored full-number/identity fields remain unchanged.

Batch closing asks to discard user-edited choices or staged accounts. Keep working
is the default. Automatic proposals alone are not edits. Explicitly reverting
choices removes dirty status; successful Apply clears saved drafts. Explicit
application Quit also protects unsaved work and can be cancelled. Forced parent
destruction/interpreter teardown retains cancellation/rollback without a prompt.

Primary owns account-form/source-context presentation, embedded-read facade,
dependency/lock/notices, integration/tests, contracts/planning, commits and pinned
demo handoff. Desktop owns the new memory viewer and tests. Evidence owns account
draft context/naming and new context tests. Ledger owns batch discard interaction
and its tests. ui_ux designs then inspects actual screens; integrity reviews actual
memory/privacy/context/lifecycle paths. No recursive delegation or shared writers.

Use public synthetic fixtures and disposable profiles only. Do not read private
archive content, apply batches to the owner demo, or launch private originals.
Public runtime handoff may read its schema marker only and must preserve its
existing profile/catalog/preferences/review state and earlier runtimes.

## Verification criteria

- Real valid synthetic PDF loads from QBuffer, renders and navigates without
  filesystem materialization or OS app calls; malformed/encrypted/unsupported
  inputs provide a visible error and recovery. CSV preserves strings and shows
  truncation/decoding limits. Reads/parsing remain off the main UI thread where needed.
- Worker/device/PDF/renderer lifetimes drain on close, parent destruction and
  interpreter/app exit. No late viewer after cancellation or implicit network
  links, reimport, source mutation or financial posting.
- Selected second-section context stays selected; zero differs from unknown and
  derived/assumed dates remain labeled. Context/name suggestions do not change
  matching identity, financial class or exact amounts.
- Nested original close preserves unsaved name/kind edits and staging; discard
  No preserves the whole batch, Yes writes nothing, Escape/Cancel/X agree.
- Inspect actual Windows Qt with readable fonts at representative sizes, long
  labels, loading/error/empty states and keyboard navigation. Native agent checks
  do not attest owner acceptance, macOS or installed-release behavior.

## Results

Installed and locked `PySide6-Addons==6.11.2` alongside the existing matching
Essentials/Shiboken packages. `uv lock --project client` and
`uv sync --project client --extra dev --frozen` succeeded. Existing PyInstaller
QtPdf/QtPdfWidgets hooks collect their native libraries; direct imports require
no hidden-import workaround. Notices identify Qt PDF/PDFium and authoritative
component/source inventories. The earlier generic default-app error does not
identify its underlying failure; default preview now exercises a separate,
verified memory path instead of relying on external dispatch or temporary paths.

`V2DocumentViewer` uses a read-only QBuffer with QPdfDocument/QPdfView, single-page
lazy rendering, page/zoom/fit controls, search and selectable current-page text.
Password-protected PDFs accept a session-only password, including retry, without
writing it or the source. CSV parsing runs on a worker and keeps strings intact,
including leading zeros, negative zero, multiline fields and formulas as text;
row/column/cell limits and unsupported decoding are explicit. Corrupt hashes,
unsupported formats and unavailable Qt PDF show failure states. No embedded path
calls external apps, temporary-file materialization or network services.

The existing external adapter is isolated in `gui/v2_external_document.py` with
its previous tests, rather than silently falling back from memory preview. The
default `gui/v2_original_document.py` owns captured DB reads, cancellation and
viewer/controller lifetime. Closing clears the transferred reader references,
PDF device/document, password, copied text and source/model state. Local original
recovery remains a separate deliberate save action.

Account drafts retain immutable selected source hash/locations, DateValue origins
and MoneyValue endpoints. Per-target context is captured during the same verified
batch pass; creating an account from the selected second document uses its draft
without another profile scan. The form labels dates neutrally as Document dates
for both statements and activity exports, shows printed/derived/unknown values
truthfully, and exposes the full original on the selected page. Short editable
names do not alter matching keys or stored full numbers. No legacy profile,
parser/schema migration or automatic accounting interpretation was introduced.

Batch discard protection distinguishes automatic proposals from explicit choices
and skips. Keep working is the default and Escape action for Cancel, Escape and
window close. Reverting a choice clears dirtiness; skips survive Reload. Apply
consumes only saved drafts; unused drafts remain protected. Actual modal Enter
and Escape tests verify the default, not only configured widget properties.

Verification uses locked client Python, isolated HOME/USERPROFILE/null keyring,
public synthetic fixtures and disposable profiles:

- Integrated viewer/facade, account context/core, batch core/GUI, inline creation,
  original recovery/external adapter, workspace and browser suite: **151 passed
  in 114.00s**. Final focused encrypted-controller suite: **6 passed in 4.15s**.
  Context/matching: 19 passed; public OCCU/family admission: 33 passed; batch GUI:
  18 passed, including exact selected document and no additional profile read.
- Real valid two-page PDF renders from exact retained QBuffer bytes; navigation,
  search, page text, encrypted unlock/retry, failure states, CSV limits and
  app/interpreter worker drainage pass. No external/temp operation is allowed
  by the embedded tests. The reader/controller stays retained until viewer close.
- Native Windows actual Qt PDF rendering at 1024x768 produced nonblank glyph
  samples, and page 2 text/search/CSV string checks passed. Evidence:
  `scratch/memory-viewer-native-20261027/`.
- Independent ui_ux inspected actual Windows/Segoe UI 10 form/viewer states at
  default 500x620, 680x730, 1024x768 and 1280x850. Selected second-section values,
  zero/unknown/component scope, nested child-modal preview, Escape returning to
  unchanged form edits, dirty Keep working/Discard, invalid PDF and multiline
  original CSV cells passed with unchanged profile bytes. Evidence:
  `scratch/embedded-context-ux-28d460d5/`. These paired public fixtures establish
  UI/context behavior, not extraction parity against private originals.

Independent review identified the activity-span wording (corrected to Document
dates), representative-first batch context (corrected to per-target context), and
password-required facade completion (now nonterminal until successful unlock or
close). Explicit application Quit protects unsaved work: independent real
Qt-event probes show Keep working leaves the application alive with visible dirty
choices; a second Quit with explicit Discard exits 0. Forced no-event-loop
interpreter teardown with a staged draft exits 0 without a prompt and leaves the
exact profile hash unchanged. The same reviewer independently rechecked encrypted
password waiting as nonterminal, then exactly one successful completion after
unlock, with no external/temp calls. Evidence:
`scratch/ux-audit-embedded-context-fixed-20261027/`.

Narrow actual Windows PyInstaller onedir probe of the implemented viewer passed:
initial build 31.24s and exact-final-source refresh 22.895s; real two-page rendering and nonblank glyph samples; exact/released
QBuffer; exit 0 and empty stderr. Runtime PATH contains Windows system directories
only, excluding development Qt. The bundle contains Qt6Pdf/Qt6PdfWidgets DLLs,
their Python bindings and qpdf plugin. Evidence:
`scratch/memory-viewer-frozen-20261027-a/result.json`. This is component frozen
readiness, not a new full application release, signing or installed acceptance.

Final viewer suite: **21 passed in 3.51s**, including CSV close/release hardening;
the independent reviewer reran that final regression and inspected the retained
reader/controller and Qt device lifetimes. Independent review reports no remaining
material financial, evidence, privacy or lifecycle blocker. PDF renderer shutdown
probes with actual app.exec/quit and no event loop both exit 0 with no source temp
or external calls; the event-loop case confirms released buffer/source before
return. Evidence: `pdf-shutdown-result.json` in the final independent audit directory.

Prepared the new public runtime:
`scratch/archive-demo-f92c025/runtime-updates/20261027-embedded-originals-context/Open-updated-demo.cmd`.
It copies **283** public code/resource files and reads only the existing demo's
schema marker (22), targeting the same profile/catalog/preferences/home. Earlier
runtimes remain unchanged and the owner launcher was not executed. A separate
disposable pinned-module journey stages/applies two source sections and one account
with zero journals, then renders a valid retained PDF on page 2, verifies exact
QBuffer bytes and close release with zero OS dispatch. Evidence:
`scratch/embedded-pinned-check-911ef3dd/result.json`. The runtime uses the updated
locked local Python environment; it is not a dependency-frozen release artifact.

No private original was opened or batch applied to the owner's existing demo.
Agent native checks do not attest owner acceptance, macOS, DPI/screen-reader or
installed-release behavior. The original external handoff's earlier mocked OS
tests are not presented as embedded-render evidence.
