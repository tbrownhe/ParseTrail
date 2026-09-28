# Disposable ledger conversion and review

This is L4's first shadow conversion and the L5a read-only review surface. It does
not migrate an active application database, activate a ledger, or change reports.
Use the inactive output of a verified [recovery restore](../recovery/README.md).

```powershell
client/.venv/Scripts/python.exe devtools/ledger_audit/migrate_shadow.py --source scratch/restore/database.db --archive scratch/restore/archive --source-id stable-local-database-id --approved-preview scratch/private-audit/hsa-correction-preview.json --output scratch/private-shadow
client/.venv/Scripts/python.exe devtools/ledger_audit/review_shadow.py --folder scratch/private-shadow
```

Keep `--source-id` stable for this database across reruns and use a different
identity for an unrelated database. Output must be a new directory. Active WAL
databases are refused. The command retains `legacy.db` byte-for-byte, including
all IDs, annotations, categories, memberships, schemas and source metadata. It
creates a separate `ledger.db`, `plan.json`, `source-corrections.json`, and
`report.json`. All are private financial records and must stay out of Git.

## Interpretation rules

- Financial-account identity follows the declared legacy account type: Asset and
  TangibleAsset map to Asset, Debt to Liability. Recorded signed account movements
  retain the existing debit-positive convention; no rule guesses class from a
  positive/negative current balance. Non-USD/unknown account classes fail.
- Each existing transaction ID becomes at most one observation, regardless of
  how many statements reference it. Existing income/expense categories produce
  balanced **unreviewed** interpretations on supported cash/loan/card accounts.
  Legacy category verification is retained separately and is not promoted to a
  newly reviewed journal assertion. Refund signs are preserved.
- Transfer labels never post a guessed counterpart. Equal/opposite amounts on
  different accounts within seven days are candidates only, even if unique.
  Candidates may have existing category interpretations requiring later correction.
- Manual closure instructions remain retained control evidence; they produce no
  cash posting. Synthetic loan origins, other manual entries, investment-scope
  activity and tangible-asset valuations require explicit review. Zero amounts
  remain preserved evidence but do not create nonzero ledger postings.
- The approved HSA source set is reparsed using the corrected source plugin.
  Account identity, statement period, file hash, every surviving legacy row, and
  exact printed-balance equation must agree. Additions and corrected endpoints
  must exactly match the owner-approved preview, including remaining continuity
  exceptions. Any drift blocks the run. Added rows remain uncategorized/unposted.
  An addition overlapping another observation is rejected for identity review,
  rather than silently merged or double-booked.
- Only the HSA endpoints are freshly source-verified by this converter. Other
  historical endpoints are conservatively tagged `assumed` in the kernel and
  `legacy_unverified` in the manifest; this does not assert that their source PDFs
  lack independent balances. Their timing/provenance needs separate verification.
- Earliest-statement opening positions are **unposted proposals**, not silently
  approved equity entries. Their proposed date is a ledger boundary, not a
  confirmed origination date. No suspense account or balancing plug is created.

The conversion manifest records rule version, stable identities, mappings,
decisions, source additions, statement exceptions, candidate transfers and opening
proposals. SHA-256 fingerprints bind the plan and report to retained source and
ledger files. A batch validates all inputs in one transaction; any conflict or
invalid entry rolls back mappings, observations, memberships and entries together.
Replaying an identical plan changes no entries or allocations. Conflicting source
facts or reused keys fail instead of rewriting evidence.

Reconciliation results compare source equations, statement memberships, allocation
completeness and ledger endpoints. They remain private report artifacts tied to
the ledger-file checksum; this bulk preview does not append interactive kernel
reconciliation runs. Unverified endpoints and unresolved activity cannot be
presented as independently reconciled. Coverage/freshness and category review
remain separate. This first conversion is not report-cutover acceptance.

## Windows native acceptance

The review window loads only the selected shadow directory and verifies artifact
checksums. It does not load the active profile, credentials, plugins or network
services. The original client may remain closed. A full-source smoke check is:

```powershell
client/.venv/Scripts/python.exe devtools/ledger_audit/review_shadow.py --folder scratch/private-shadow --smoke
```

For owner acceptance, run without `--smoke` and check:

1. The window opens, resizes and closes normally. Search each tab and select rows;
   detail text follows the selected row after filtering and clearing the filter.
2. In Transactions, filter `Added from archived HSA statement` and inspect added
   activity. Filter `Transfer needs confirmation` and inspect possible counterparts;
   nothing is presented as a confirmed transfer or newly verified interpretation.
3. In Statements, filter `Reparsed printed balances`. Original and shadow closings
   are separate, and selected rows explain remaining reconciliation issues.
4. In Balance gaps, filter `Printed balances` to inspect the source-verified HSA
   discontinuities. Opening proposals are explicitly unposted and do not claim
   to establish actual loan disbursement dates.
5. There are no editing, posting, repair or live-database activation actions.

Persistent draft editing, confirmed transfer/split allocation, source repair,
posting/reversal controls, reviewed opening anchors, broader source validation
and report cutover remain subsequent L4/L5 chunks. The native walkthrough accepts
this read-only review surface only, not those future workflows.
