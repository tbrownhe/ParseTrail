# Opening-position readiness audit

This read-only service follows the accepted transfer workflow. It inspects the
immutable [fresh rebuild](REBUILD.md) and [cash/card candidate plan](PROPOSALS.md),
not the disposable GUI test decisions or the live profile.

```powershell
& client/.venv/Scripts/python.exe devtools/ledger_audit/openings.py `
  --rebuild <verified-rebuild-directory> --candidates <verified-candidate-directory> `
  --output <new-private-output-directory>
```

The output must not exist. The command verifies plan/database/retained-source
checksums, rejects database sidecars, verifies the candidate-to-rebuild binding,
checks deterministic replay and rechecks all input hashes before publishing its
completion report. It never opens a database for writing or changes accepted files.
Private filenames, dates, balances, account names and source hashes stay in ignored
`readiness.json` and `report.json` artifacts.

## Opening candidates

For each scoped checking/savings/card account, the audit gathers **all** statements
with the earliest source period start. It retains their filenames, parser manifest,
source balances, original provenance and kernel eligibility. It never skips a failed
earliest statement to use a more convenient later opening. Conflicting earliest
balances yield no proposed amount. Missing statements, earlier unmatched movements,
incomplete source replay and unavailable kernel statements remain explicit blockers.

An agreed earliest opening amount retains its exact sign. A conditional cutoff is
shown immediately before the earliest inclusive statement period, according to the
kernel convention. This is a proposal requiring source timing verification, not an
assertion of when the real account opened. A nonzero liability opening is neither
income nor spending; eventual posting must use opening equity. A zero opening needs
no zero-valued journal but still needs provenance and timing review.

Every candidate remains unreviewed and unposted. The service deliberately keeps
`ready_for_opening_posting` and `ready_for_cutover` false. It does not upgrade
`assumed` endpoints just because a parser succeeded or adjacent amounts agree.
No opening-entry controls are exposed by this audit.

## Continuity and limitations

An interval sweep compares each next statement against the furthest covered prior
endpoint. Nested periods cannot manufacture false gaps. Multiple statements ending
at the same frontier all participate, so conflicting closing balances cannot be
resolved by arbitrary row order. Results distinguish adjacent agreements, adjacent
balance differences, coverage gaps, overlapping periods and conflicting prior
closings. Agreement is an exact comparison of parser output, not independent
statement reconciliation.

A gap records its inclusive missing dates and uncovered-day count. Equal balances
on either side still leave a coverage gap. A changed balance across a gap is not an
invented transaction or an equity adjustment. Overlapping boundaries are not treated
as consecutive closing/opening amounts.

Known date limitations are retained explicitly. The current Chase parser exposes
only source transaction dates and uses statement-bounded posting-date proxies. Those
are not established bank posting dates, even though earlier transfer handling
preserved the normalized dates exactly. Other parser dates have not been independently
certified by this audit. The next source-provenance chunk must carry these distinctions
into opening review and date-sensitive reconciliation without rewriting raw evidence.

The reference archive's unused-file inventory was also inspected during development;
no missing card-period source was identified there. This does not establish that
those statements never existed or cannot be obtained from their institutions.

Next: explicit source balance/date provenance and reviewed opening anchors, preserving
unresolved gaps and estimated dates. Transfer/ordinary GUI test decisions remain
confined to their disposable workspaces. No new native GUI test is needed for this
read-only calculation/report chunk.
