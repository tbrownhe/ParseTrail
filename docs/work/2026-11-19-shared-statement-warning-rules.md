# Shared Wells statement sections and bounded HSA/loan warning proofs

Date: 2026-11-19. Baseline: `c886f92`. Scope: V2-3/P2-4.
Implementation, integration and independent verification completed. Owner/release
acceptance remains separate.

## Agreed outcome

Implement the approved first pass from the
[family review](2026-11-18-import-warning-family-review.md): shared Wells personal/
business tail and fee-section recognition plus the ten HSA/loan proof cases. Use
bounded typed source sections, not filename/hash/real-amount exemptions. Citi
graphic-caption provenance, its full-year-date failures and unrelated text variants
remain separate work. Do not target a review count by suppressing unknown evidence.

Wells personal should reuse existing verified tail roles and both adapters should
share fee/waiver/deposit/balance/transfer/age/context recognition with complete
printed frames. Auxiliary fee cycles keep their own valid dates rather than being
forced to end on the financial statement date. Unknown money/date/activity-shaped
rows, incomplete frames, extra tokens and unresolved summaries stay reviewable.

HealthEquity's alternate complete empty-cash rate/fee layout and wrapped source
closure date are context only. Source closure never closes an authored account.
Wells loan emptiness requires explicit located no-activity wording, a complete
register, equal observed endpoints and exterior checks; equality alone is not proof.
Unknown period start remains unknown. Capital Amount Financed origination may
qualify its missing-opening warning without inventing an opening or bypassing
the separate origination posting review. Source opening arithmetic stays unverified.

## Ownership and data

Wells evidence owner: shared dispositions, personal/business source adapters and
Wells synthetic tests. Small-family evidence owner: HSA source/line modules, Wells
loan source module, import-warning policy and their tests. Only the latter writes
the shared warning-policy file; new Wells role names are coordinated explicitly.
Primary owns integration tests, current contracts/planning and this record.
Independent integrity reviews actual code and negative proofs with public fixtures.
One writer per file; no recursive delegation, branch switching or independent commits.

Use locked client Python, isolated app data/null keyring and synthetic disposable
profiles. The private baseline report is
`scratch/import-audit-20261118-f1f03ecf.json`; its index stays ignored. Authorized
originals are the exact affected formats listed there in the owner-selected SUCCESS
directory, read-only in memory, including clean family comparisons. A final shallow
945-PDF audit of that same selected directory measures change and unrelated-family
regressions. No source/extracted-text/evidence copies, original renders, private
routine logs, owner profile/trial/catalog/log access, root .env or service access.
Only known public fresh-test helper code may be reused for another empty candidate.
No signing/publication or daily-profile activation.

## Acceptance criteria

- Preserve complete financial account evidence: observation IDs/occurrences,
  dates/provenance, raw fragments, locations, signed amounts/components, endpoints
  and periods. Original hashes and printed equations unchanged; capture unverified.
- Source-role output revisions use explicit stable financial identity namespaces;
  no engine-marker change may accidentally create different financial occurrences.
  Existing evidence/snapshots remain untouched. No profile schema change.
- Test whole source frames and adversarial mutations: missing headings/rows,
  orphan fields, unframed totals, extra/malformed amounts/dates, activity after stop,
  source/account mismatch, fee dates independent of statement dates, nonzero
  unexplained current HSA fees, invalid closure date and equal-balance-only emptiness.
- Preserve old audited empty-HSA qualification while admitting the new proven role
  version. Keep origination review, unknown opening and source-period qualifications.
- Measure remaining review *files* and occurrence classes against baseline, with
  exact financial/source parity for affected families and no unrelated regressions.
  Baseline: 943 recognized, 275 require review, two Citi failures among 945 PDFs.
- Meaningful parser/warning/import/accounting integration checks, proportionate
  native public import verification, independent review and changed-file lint/hooks.
  Passing tests or reduced warnings do not establish owner/other-platform acceptance.

## Result and verification

Shared Wells roles are implemented in the existing auditor and both adapters.
Personal output is wells-personal-source-pilot-2 with financial namespace1;
business uses its unchanged table engine2 and statement-v3 wrapper. Current account
context explicitly admits reviewed business wrappers v2/v3 and rejects unknown ones,
preserving the printed-product setup defaults. No filename/hash/actual-value rules.

Fee frames require observed headings, typed fields, valid independent auxiliary
period and same-section source correspondence. Blank/totals/ending and complete
balance/contact/context roles remain distinct. Cropped correspondence preserves
numeric, currency, sign and date/decimal punctuation content; ambiguous or unrelated
equal-value matches are not inherited. Optional footer conversion/range failures
stay unresolved rather than refusing an otherwise valid financial statement.

Read-only, numerically redacted source renders established a legacy presentation:
raw3 is a hollow annotation box and raw34 is a composite boxed mark in a separate
annotation column after the two observed value columns. They are retained as finite
opaque annotations in complete typed fee-context rows, for met or unmet criteria.
No checkbox, eligibility or fee-correctness fact is emitted and raw data is not
normalized into Yes/No. Requiring the numerical criterion to be met would impose an
unsupported interpretation of that annotation. Currency/decimal suffixes, other
numbers, missing frames, sign loss and extra dates/amounts remain material. No
per-cell fuzzy correspondence extension was used.

HSA engine3 uses financial namespace2; its alternate complete frame and valid
wrapped source closure metadata retain the existing empty proof and no authored
closure. Wells loan engine2 uses namespace1 and emits located explicit empty-register
proof with exterior auditing. Capital loan-history engine2 is unchanged: only the
warning projection admits the exactly evidenced financed-amount shape. Financial
origination review, unknown opening and unverified opening arithmetic remain.

### Checks completed

- Small-family line/source/warning suite: 124 passed, 2.84s. Independent repeat:
  124 passed, 3.12s plus 30 direct boundary probes. All131 relevant originals
  (60 HSA/45 Wells loan/26 Capital) retained entire financial account payloads,
  periods, observation IDs/raw fragments/dates/amounts/endpoints, balance/capture
  flags and unchanged original hashes matching the baseline report. Ten review
  files now have no required import-preview warnings; no errors in that replay.
- Wells initial broader geometry/bounded/source-pipeline checks: 96 passed, 8.23s.
  Final focused tail/adapter tests: 74 passed, 0.31s; independent repeat 74 passed,
  0.29s plus 11 direct context probes. Four independent baseline comparisons
  preserve complete bank/HSA/loan accounts, IDs, periods and qualifiers.
- Root complementary admission/summary/value/HSA-accounting/liability-register/
  loan-automation integration selection: 233 passed, one stale baseline assertion
  failed in 61.24s. A public Git archive at c886f92 reproduced the same failure:
  the Yamaha register test expected no builtin Loan interest category, although
  it is now seeded. The test now snapshots the complete existing row and requires
  it unchanged after register review; all financial/journal/consumption assertions
  remain. The full register module then passed18 checks, 7.40s. No financial code
  was changed for that correction; independent review accepted the test change.
- Final root combined affected parser/warning/integration selection: 290 passed,
  6.56s, raw0. Missing/duplicate frames, extra malformed money/dates, optional
  amount overflow, source/crop mismatch, legacy annotation syntax, unsupported
  engines, false empty claims and origination shape mutations remain protected.
- Native Windows/integration run: 17 passed, 7.25s, raw0. Actual public-PDF auto
  import of origination skips the benign source preview but does not post, even
  with loan-payment automation enabled; opening remains unknown. Saved retries
  do not reparse. Two native loan landings show the blue Review loan origination
  action at1050x700/1100x650. Business creation retains printed nickname/product
  defaults with wrapperv3. Valid/invalid HSA closure dates were imported/bound in
  disposable profiles; neither creates lifecycle decisions, journals or openings.
  Normal GC and explicit GUI-thread invalidation retained. Evidence beneath
  scratch/shared-statement-rules-20261119/native; locked Python3.13.15,
  Qt6.11.2 Windows plugin, SegoeUI9, DPI96/DPR1. Qt test events are not owner input.

Independent integrity review reports no outstanding actionable finding. Its new
empty-loan exterior named-date repro was fixed and checked in both parser audit
and warning proof. It verified context rather than eligibility interpretation of
legacy annotations, complete frame binding and no cross-section borrowing. Its
source checks used public synthetic data only; full private replay counts remain
implementer/integrator evidence, not independent owner acceptance.

Privacy qualification: one initial specialist diagnostic masked numeric/account
fields but retained a nonfinancial city/state fragment in internal tool output.
No names, address numbers, account identifiers, amounts, source copies or Git
content were emitted. Later probes were restricted to public role labels and
aggregate codes/counts; the fragment is not repeated here. No private source or
render files were retained.

Final Wells replay checked all177 originals. Complete financial account payloads,
IDs/raw fragments/locations/amounts/dates/provenance, endpoints, periods and balance/
capture flags matched c886f92; all source hashes were unchanged. Personal activity
remains6618 rows and business225. Reviews fell148→140 personal and24→21 business.
Unresolved tail occurrences fell5281→1977 and327→120 respectively. This clears11
Wells files and resolves3511 occurrences; it does not claim all fee-section sources
are fully supported. The formerly unmatched ending summary is now covered by a
general typed signed-summary rule. No fuzzy per-cell extension was added.

### Full selected-directory audit

Actual CLI, four workers, the same shallow945 selected PDFs and development
definitions; report is private and ignored:
`scratch/import-audit-20261119-shared-rules-731d0ecd.json`.

| Measure | Baseline | Current |
| --- | ---: | ---: |
| Selected/completed | 945 | 945 |
| Recognized | 943 | 943 |
| Files requiring review | 275 | 254 |
| Hard failures (deferred Citi) | 2 | 2 |
| Wells unresolved tail occurrences | 5608 | 2097 |
| New review cases | - | 0 |

All945 source hashes and the same two failure records match. For all943 recognized
sources, parser/definition identity, extractor, row/group counts and typed periods
are unchanged. Entire metadata records of unrelated formats are identical. The
only review-file reductions are HSA5→0, Wellsloan4→0, Capital1→0, personal-bank148→140
and business24→21. Current material occurrences are2097 Wells tails,384 unchanged
Citi monetary lines and five unchanged Citi empty captures. No cancellation,
ambiguity, remaining files or metadata truncation occurred; exit1 is expected for
remaining review/failures. This is measured clearance, not extrapolation from line
counts or the150-source fee-section cohort.

Remaining254 review files are161 Wells and93 Citi. Unsupported Wells legal/policy
and source-context variants remain unresolved; the shared fee auditor does not
globally suppress them. Citi caption/graphics/provenance, full-year-date failures
and its remaining source variants stay deferred as agreed. No per-document
exception was used. Warnings are reduced without declaring complete capture.

All19 changed/new Python files pass Ruff check/format and whitespace checks. Hooks
and fresh pinned test closeout follow below. No schema or saved-evidence mutation
is selected; owner, other supported platforms and release gates remain separate.
