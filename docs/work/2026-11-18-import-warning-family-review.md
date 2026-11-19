# Family-level import-warning review

Date: 2026-11-18. Baseline: `2021394`. Scope: V2-3/P2-4 investigation.
Read-only review complete. Parser implementation, owner acceptance and release are
not claimed by this record.

## Intent and boundaries

The owner requests review of the 945-source audit and identification of easy wins
that apply across statement families, avoiding 275 per-statement exceptions. This
pass groups evidence and proposes bounded source-role rules; it does not silently
waive review or change financial extraction. No filename/hash/amount allowlists.
Unknown money, activity-like dates, missing rows and invalid balance equations stay
material. Benign source limitations remain separate from accounting defects.

Primary owns grouping, cross-family policy, conclusions and this record. Evidence
specialists investigate Wells tails, Citi content and small families/failures in
disjoint read-only scopes. Independent review checks the proposed proof boundaries
after the initial findings. No shared-file writers or recursive delegation.

Authorized inputs are the owner-provided private audit
`scratch/import-audit-20261118-f1f03ecf.json`, its ignored derived metadata index,
and the exact attention/failure sources listed there under the owner-selected
SUCCESS directory, plus minimal clean comparison samples in those same formats.
No broader private enumeration, profile/trial/catalog/log inspection, root .env,
source/extracted-text/evidence copies or persisted original screenshots. Read PDFs
only in memory with bounded decoders. Retain only sanitized pattern/count/proof
findings in Git; metadata indexes and reports remain private and ignored. Across
specialists, limit concurrent decode operations to four. No live writes, signing,
publication or daily-profile activation.

## Baseline and questions

The audit has 943 recognized sources, 275 requiring review, two failures and zero
unattempted/ambiguous files. Occurrence counts are not file counts:

| Format/group | Total recognized | Review files | Material triggers |
| --- | ---: | ---: | --- |
| Wells personal bank | 148 | 148 | 5281 unresolved_after_stop occurrences |
| Wells business | 29 | 24 | 327 unresolved_after_stop occurrences |
| Older Citi | 131 | 93 | 384 unclassified monetary lines; five empty captures within those files |
| HealthEquity cash | 60 | 5 | 25 empty-table exterior occurrences |
| Wells personal loan | 45 | 4 | Four no-activity captures |
| Capital auto | 26 | 1 | One unavailable principal balance check |

These six groups account for all 275 review files. Determine reusable table/section
frames, benign disclosures, mathematical/source proof and unsupported content.
For each candidate rule, quantify coverage and define boundary-negative cases.
Equal endpoints and zero captured rows alone never establish an empty statement;
missing offsetting activity is possible. An origination may lack an opening without
authorizing an invented zero opening or bypassing financial origination review.

## Findings and proposed sequence

Read-only census and candidate-rule assessment are complete. No import-rule
changes have been applied in this review pass.

### Wells: shared tail audit, not blanket suppression

The personal adapter unconditionally labels every table-crop row after the first
empty/Ending terminator unresolved_after_stop. It has no tail-role classifier;
the business adapter already has a finite one. Over-wide table crops retain blank
cells, totals, balance explanations and fee/disclosure sections below activity.

The full 177-source Wells replay (148 personal, all 29 business including five
clean comparators) retained original hashes, verified balance equations and
unverified capture; no activity-date-shaped tail rows were found. Personal unknown
rows include 2101 blanks, 148 Totals and 101 Ending-shaped summaries. Probing the
existing business classifier in memory labels 2401 of 5281 personal occurrences
(2101 blank, 248 verified summaries, 52 balance prose), fully clears seven sources
and leaves 2880 occurrences across 141 sources. The one summary-shaped candidate
not verified by the current rule is under investigation, not assumed correct.

Of the remaining personal content, 1084 digit/dollar-containing rows occur across
140 sources; one source has only nonnumeric residuals. Business retains 327 rows
across 24 sources, including 106 numeric rows across 18; six have only nonnumeric
residuals. Therefore simply reusing blank/summary rules is a seven-file immediate
win, not a claim that all 172 Wells review sources can be waived. A shared section
auditor with complete typed fee/threshold/unit and prose frames is the larger task.
Unknown money or dated activity outside those frames must remain material.

Existing Wells boundary tests passed 13 cases in 0.69s: bad balances, unresolved
pre-stop rows, retained dated post-stop rows, malformed/truncated/mismatched footer
amounts, missing headings, extra unknown money and product proof. No code changes.

### Citi: distinguish labelled structures from missing context

The full 93-source attention census reproduced all 384 unknown monetary occurrences
with original hashes unchanged. The largest groups are 119 bare amounts across 80
files (82 page1 and 37 page2 occurrences), 58 exact Interest labels, 37 standalone
No Late Fee labels and 30 parallel minimum-annual-purchase lines. Remaining cases
are principally APR/disclosure layout variants. These are occurrence groups, not
disjoint file groups. Five sources also have zero captured rows.

Bare first-page amounts do not satisfy the currently proved repayment equation;
nearby equal numbers do not establish a source role. Missing/split captions need
further source-coordinate/section investigation. Labelled sidebar/APR/legal frames
are candidates for general rules, but cannot honestly be claimed to clear all 80
files that contain unlabelled money. Both hard failures route to the same older
Citi engine and fail resolving a dated start; those need extraction diagnosis,
not a warning waiver.

### Small groups: explicit proof rather than absence

Four Wells loan statements have explicit no-activity wording, a complete small
transaction frame with immediate ending principal, equal observed endpoints and
no intervening dated rows. That supports a candidate empty-statement proof; equal
endpoints/zero captures alone remain insufficient. The Capital source is an already
supported Amount Financed origination, not an incomplete payment; its missing
opening check can be treated as inapplicable with exact shape proof while the
separate financial origination review remains required and no zero opening is made.
All five HSA sources are valid empty cash statements whose interleaved rate/total
layout falls outside the current complete-frame recognizer. Their other exterior
pair is an exact wrapped HealthSavingsAccount(Closed heading and valid closure date.
That is printed status metadata, not authority to close the authored account.

## Final assessment and implementation priorities

### 1. First text/proof pass: 17 strong candidates

| Improvement | Candidate files | Required scope |
| --- | ---: | --- |
| Reuse verified Wells tail roles in personal adapter | 7 | Existing blank/summary/public-prose proofs, no global unresolved_after_stop waiver |
| Complete alternate HSA rate/fee frame and wrapped closure-date metadata | 5 | All headings/rows/totals/dates retained; malformed or unexplained extra content stays material |
| Explicit empty loan-register proof | 4 | Located no-transaction wording plus complete register/exterior proof; unknown period start remains unknown |
| Origination-specific missing-opening qualification | 1 | Observed Amount Financed principal/gross/closing equality and source date; opening arithmetic unverified, separate posting review required |

These are replay-supported candidates, not an applied 17-file reduction. Each
needs synthetic positive/negative tests and post-change replay. The HSA empty-table
helper currently binds a specific engine version; a source-role engine revision
must not accidentally disable that proof. No financial event, closure or opening
may be invented by the warning qualifications.

### 2. Shared Wells section auditor: largest repeated text opportunity

Second bounded census covered the remaining 3207 Wells occurrences. Monthly-fee
sections account for 2060 (1813 personal/247 business), including 883 of the 1190
digit/dollar-containing rows. Such sections occur in 134 personal and 16 business
files. Repeated field families are printed fee cycle/current fee, minimum/average
balance thresholds, qualifying deposits, automatic transfers, age eligibility,
waiver/calendar explanations, and contact/control/legal notices.

Implement one bounded shared auditor over typed labelled sections, with small
normalization adapters for the two table geometries. Every amount/date in each
accepted frame must have a role; unmatched tokens, missing headings and dated
activity after the stop remain material. The 150 section-present sources are an
affected cohort, not a forecast of full clearance: other notices can still block.

The current exact fee-period-end == statement-end requirement rejects auxiliary
fee cycles ending earlier in 16 personal and 13 business printed periods, all
calendar-valid with 0–45-day durations. A labelled auxiliary fee cycle should be
validated and retained independently of the financial statement period. This must
not loosen journal/account-balance dates. One unmatched ending-summary crop still
lacks complete grammar proof and must remain unresolved; no mismatch was proved.

### 3. Citi benefit box: common decoder/provenance gap, not a quick regex

In-memory visual inspection of a representative first-page bare amount shows it
inside a Savings Spotlight / lifetime-benefit panel. The caption/artwork is an
embedded image, so text extraction retains the number without its semantic label.
Eighty sources share that first-page fixed-column pattern and each has a later
textual lifetime-savings label. For 59, a unique adjacent labelled footer amount
is recoverable by current text geometry and exactly matches the first-page value.
The other 21 merge/shift APR/prose columns and need spatial handling. Two other
first-page bare occurrences are a separate layout case.

The 80-source benefit-box cohort accounts for 346 of 384 unknown lines; the other
13 sources contain 38. Its 80 first-page amounts, 58 Interest labels, 37 No Late Fee
labels and 37 second-page bare totals make 212 direct benefit-layout signatures;
other lines in the same sources include APR/disclosure variants. Current
conservative component/labelled-total proof can
explain 42 unknown lines across 17 sources, but none fully clears because its
first-page graphic-caption amount remains unresolved. Period benefits and lifetime
benefits are distinct: do not force period components to equal a lifetime total.

The general capability is bounded caption/graphic recognition, anchored geometry
and independently labelled benefit-value proof. Column position/equal numbers alone
are insufficient. A static artwork identity, if used, is format-template evidence,
never a per-document hash exemption or a claim of generic OCR. Current source
locations have line/table/chars/annotation types but no embedded-caption proof;
the decoder and provenance representation need deliberate extension. Negative
cases include missing/changed artwork, moved or unrelated equal values, ambiguous
or mismatched totals, and extra unexplained money. Benefits remain non-activity;
capture remains unverified. The 80-source cohort is not an implemented clearance
estimate. Other Citi APR/annual-purchase/legal layout variants need complete finite
text frames and should be grouped with the same source-section work.

All five zero-activity Citi cases have observed equal endpoints but still need a
positive empty-table proof. They are already included in these 93 sources, not
five additional review files. Reuse a common empty-statement policy supplied by
family-specific located proof/frame/exterior checks; do not waive zero captured
rows or infer completeness from endpoint equality. The HSA and Wells loan source
frames differ, but the acceptance principle is shared.

### 4. Two Citi failures: repair extraction with table context

Both correctly route to the older Citi parser and decode successfully. A global
full-year date-start guard then refuses one full-year date-only line and one
full-year date plus APR-related text/amount in the ordinary activity area. Keep
failure until table/continuation context establishes the role and complete row
interpretation. Do not delete the guard or skip full-year date lines globally.
These are a shared extraction-boundary problem, not two file exceptions.

## Verification and recommendation

Independent integrity review validated the grouping (172 Wells + 93 Citi + 10
smaller = 275; two separate failures), proof boundaries and proposed staging.
It ran 141 existing public synthetic tests in 4.02s, raw0; no rule changes were
made, so these are baseline boundary checks, not acceptance of proposed classifiers.
Wells and Citi censuses retained unchanged original hashes and existing financial
balance/capture qualifications; no original renders or extracted-text copies were
persisted. Private census indexes/reports remain ignored.

Recommend implementing the 17-candidate text/proof pass first, then the shared Wells
fee-section auditor for the largest text cohort. Treat Citi graphic-caption proof
as a separate bounded decoder/provenance feature and its full-year-date failures
as extraction work. Measure remaining *files*, not only occurrence counts, after
each stage. No target count justifies suppressing unknown source money.

For disposition-only changes, preserve the complete financial account evidence,
row IDs, raw fragments, signs, typed dates, locations and unknowns. Wells personal
currently hashes ENGINE_VERSION into row IDs; use an intentional stable financial
identity namespace when source-role output changes, as already done for Citi.
Recheck all affected original hashes and printed equations. Any genuine financial
extraction change needs separate exact proof/expected differences. No changes to
saved snapshots, authored accounting, schema or UI are implied by this review.

This review is complete; parser changes and their acceptance remain pending.
