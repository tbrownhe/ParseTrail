# Successful synthetic source admission across current families

Date: 2026-10-25. Roadmap IDs: P2-3/4.
Authorization: approved roadmap and continued development; test-only bounded packet.
Implementation: complete, test-only.
Automated verification: 285 parser/catalog/import checks passed.
Independent review: complete; no findings in the synthetic admission claims.
Owner acceptance: not performed; consolidated/native gates remain open.
Release authorization: not authorized.

## Scope and controlling decisions

Generate small valid synthetic PDFs/CSVs in memory and admit every current family
through real bounded decoders, one test-signed full catalog and a disposable V2
profile. Current channel-only fixtures and expected-source-refusal checks do not
establish that success path. Reuse existing raw-PDF generation patterns and
source facts without adding a rendering dependency. Assert independent expected
rows/money/dates/scopes/unknowns and retained byte/declaration provenance, plus
unique routing, retry/reopen and no automatic journal postings.

Evidence specialist owns new synthetic builder/test modules under
`devtools/parser_engine_pilot/` and necessary test-only helpers. No runtime,
declaration, profile schema or client GUI edits without primary coordination.
Primary owns contracts/roadmap/TODO/record. No private archive replay, `.env`,
signing keys, live profiles, builds/installers or recursive delegation. Ephemeral
test signing stays in memory. This proves bounded synthetic source admission,
not private-source parity, full-page capture, frozen/installed success or
production catalog readiness. Those gates retain their distinct evidence.

## Result and review

New `synthetic_family_sources.py` and `test_family_source_admission.py` admit all
23 unchanged current declarations: 21 complete in-memory Courier PDFs and two
MOHELA CSV definitions. Each passes unique routing, actual bounded worker decode,
test-signed full-catalog admission and disposable-profile import. Independent
expected amounts, dates, roles, scopes, identities, endpoints and provenance are
checked, together with retained source/definition/evidence bytes, retry, reopen
and zero automatic journals. No runtime or declaration changes were needed.

Boundary checks cover ambiguous routing, truncated source, cancellation, failed
arithmetic, genuine equal occurrences and OCCU annotation date fallback.
Independent integrity review inspected the success matrix and real decoder use,
then reran all 29 new checks (37.71 seconds) without findings. These fixtures do
not establish private-source parity, full-page capture or packaged admission.

## Verification

Windows 11 AMD64, Python 3.13.15, synthetic/disposable data only:

```powershell
$env:PYTHONPATH='.;client/src;client'
& .\client\.venv\Scripts\python.exe -m pytest -p no:cacheprovider devtools/parser_engine_pilot client/tests/test_v2_catalog_import.py client/tests/test_v2_data_catalog.py client/tests/test_v2_catalog_release.py client/tests/test_v2_worker_entry.py -q
```

285 passed in 52.36 seconds. The targeted admission/worker-entry run passed 32
checks in 26.38 seconds. Changed-file Ruff check and format passed. Repository
hooks run before commit. Signing keys were ephemeral test fixtures; no private
sources, production trust or live profiles were accessed.

## Remaining work

Exact-candidate frozen/installed/platform admission, production starter catalog
and consolidated owner/native/release gates remain separate.
