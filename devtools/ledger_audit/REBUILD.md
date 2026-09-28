# Fresh archive rebuild and category preservation

This development-only workflow creates a breaking evidence database beside an
inactive recovery snapshot. It uses the repository's current source parsers and
normal deterministic routing/validation. It does not load the active profile,
credentials, production plugin manager, or network services. Production signed
plugin verification is unchanged. No new dependency is required.

From the repository root, with the client environment installed:

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/rebuild.py `
  --source <verified-restored-database> --archive <restored-managed-archive> `
  --output <new-private-directory>
& client/.venv/Scripts/python.exe devtools/ledger_audit/review_shadow.py `
  --fresh --folder <new-private-directory>
```

Use ignored private storage. Output must not exist. The source must be inactive
without journal/WAL/SHM sidecars. Retain the complete recovery bundle and original
archive. Files referenced by legacy successful statements are hash-verified and
reparsed once per content hash, including multi-account files. Other managed files
are inventoried for later handling, not silently imported. Failed sources, unknown
account mappings, changed account coverage and parser warnings remain explicit.
There is no fallback to old transaction rows when fresh parsing fails.

## New format

- `legacy.db` preserves the original snapshot bytes.
- `plan.json` records rule version, parser source hashes/versions, retained metadata,
  fresh observations, source membership, complete category decisions and totals.
- `fresh.db` contains the isolated ledger schema plus immutable source evidence,
  category definitions/hierarchy, legacy decisions and restored verified category
  assertions. Account mappings are retained; no journal entries are created yet.
- `report.json` binds the plan/database/retained-source checksums and reports replay
  status and exact signed annotation totals by account, category and currency.

Canonical evidence identity includes account, dates, exact amount/currency,
description, balance and occurrence. Identical overlapping observations converge;
duplicate occurrences remain separate. Distinct balances remain distinct evidence.
This is not evidence that all source duplicates represent separate economic events;
ambiguous groups still need interpretation before posting.

Category carry-forward requires shared source membership and an exact account,
posting date, amount, currency and description match. An existing transaction date
must also agree; an absent legacy transaction date imposes no additional constraint.
Running balances are excluded from category matching because parser corrections
can change them. Row positions and fuzzy descriptions never establish identity.
Matches must be unique in both directions, considering even unverified old rows.
Conflicts, changed/split/merged output, warnings and manual-only decisions remain
pending. The old decision is always retained. Category verification neither confirms
a transfer nor reconciles a statement. ML cannot overwrite these immutable assertions.

Replaying into an existing output is refused rather than appended or overwritten.
Separate clean runs must reproduce evidence and annotations. Source checksums are
verified again at completion. Failed output is incomplete and must not be activated.

## Windows acceptance

The review window verifies artifact checksums, then opens without the active profile.

1. In **Category totals**, check familiar accounts/categories. Original counts and
   signed amounts must equal restored plus pending, including refunds.
2. In **Restored categories**, filter for a familiar purchase and verify its category.
   Select it to inspect the retained legacy decision and matched evidence identity.
3. In **Pending categories**, inspect reasons. No pending row has been automatically
   marked verified in the fresh database; its original decision is retained.
4. In **Source replay**, inspect failures and warnings. **Other archive files** shows
   retained files outside this replay's scope.
5. Close with X. There are no activation, save, or posting controls.

For automated selection/filter/detail/close checks, add `--smoke` to the review
command. This does not replace native owner acceptance.

This is the first fresh-import checkpoint, not an application/report cutover.
Historical parser compatibility, ambiguous category matches, opening anchors,
transfer/split interpretation, valuations, manual controls, and independent balance
provenance remain gates. The normal application continues using the old database.
