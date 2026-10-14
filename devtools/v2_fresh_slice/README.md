# Fresh 2.0 import-to-review stop/go slice

This isolated service experiment creates a new disposable profile from one
synthetic posted-cash CSV. It has no 1.x database reader, migration path,
account alias layer, server call or live-profile write. It uses the table parser
pilot and the existing exact double-entry ledger kernel.

The source declaration explicitly marks `Date` as a **posting date**. The slice
refuses an activity-date declaration, multiple source accounts and component
exports. It stores the original CSV bytes, exact declaration and parsed evidence
in the new profile, and loads nonzero rows as **unposted** ledger observations.
The reported row balance remains source evidence; it does not create a statement
opening/closing balance or reconciliation claim.

`review_items()` lists pending rows. `accept_expense()` posts one negative asset
movement only after an explicit category and reason are provided. A positive
credit remains pending because the slice cannot decide whether it is income,
a refund or a transfer. The kernel enforces balanced postings and prevents an
observation from being consumed twice. The synthetic check also verifies that
exact retries are idempotent and changed source bytes are refused.

Reopening validates the stored version-1 evidence snapshot against its source
and definition hashes, then reads that snapshot without running the parser
again. The snapshot retains raw fields and cell locations; review uses its
saved row IDs, dates and amounts. Tests confirm review and posting still work
when reparsing is disabled, and that an unknown evidence schema, legacy file or
newer profile format is refused before a ledger write.

Run the proof from the repository root:

```powershell
client/.venv/Scripts/python.exe -m pytest -q devtools/v2_fresh_slice
```

This is a stop/go **service slice**, not the runtime import UI or a released
2.0 database format. It handles one new profile and one source. A production
profile still needs a released snapshot schema and migration policy for later
2.x revisions. Ongoing import, source overlap, archive recovery, signed
definitions, decoder resource limits,
account/category editing and native GUI acceptance remain release gates.
