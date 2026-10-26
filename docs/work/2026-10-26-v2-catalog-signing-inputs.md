# Prepare reviewable starter-catalog signing inputs

Date: 2026-10-26. Roadmap IDs: P2-4/5, V2-7.
Authorization: continuing approved initial V2/P2 development; DEC-2 local catalog first.
Implementation: tooling and exact final-code unsigned starter inputs complete.
Automated verification: focused client/pilot and whole-client integration passed.
Independent review: complete; two findings fixed, no outstanding trust-boundary findings.
Owner acceptance: pending starter-catalog/release review.
Release authorization: no production signing, installation, publication or deployment.

## Scope and controlling decisions

Prepare exact unsigned catalog bytes and a readable review manifest without
opening a private key, using the shipped public catalog key identity, explicit
release sequence and exact source revision. Include only the reviewed required
declarations/account contexts. Keep this output visibly unsigned; the runtime
must refuse it for activation until its detached signature verifies normally.
No signature bypass or new production trust override is permitted.

Refactor the existing offline catalog builder around deterministic unsigned
assembly, preserving `signed_catalog_bytes` and its callers. Provide a separate
prepare CLI, finite metadata/declaration validation, exact payload digest and
new-directory publication. The existing offline signing CLI may accept the
prepared input so the owner can later sign those exact reviewed bytes, instead
of rebuilding from a mutable directory. Preserve encrypted outside-repository
key requirements, shipped-key matching, strict final verification and atomic
output. Agent tests use ephemeral in-memory fixture keys only. Do not load root
`.env`, search for signing material, prompt for a passphrase or execute a real
production signing command.

An evidence specialist owns only catalog scripts and their focused tests;
primary owns this record, contracts/roadmap, concrete final-revision candidate
generation and integration. Coordinate any proposed runtime-verifier edit before
touching it; unsigned parsing cannot become an activation route. Preserve the
existing signing function's API while the separate runtime diagnostic uses it.
One writer per file; no recursive delegation. Public repository definitions and
synthetic/disposable inputs only. No service/catalog publication work.

## Result and review

The previous tool required a private key even to assemble bytes. The new public-
key-only `unsigned_catalog_bytes` and prepare CLI produce exact `catalog.json`,
`catalog.sha256` and readable `review.json`, explicitly unsigned with no signature.
`UnsignedCatalog` is distinct from authenticated runtime catalog types. The
runtime verifier/cache is unchanged and continues to require a detached signature.
Existing `signed_catalog_bytes` callers retain their API and exact wire assembly.

The offline signing CLI optionally accepts prepared bytes and requires their
reviewed SHA-256. It validates/captures the complete input before prompting for an
encrypted outside-repository key, checks the shipped public identity, then signs
those exact captured bytes and fully verifies the result. Mutating the input file
during the mocked prompt cannot substitute another payload. Agent checks used
ephemeral fixture keys only; no real signing command or private-key search occurred.

Independent review found two inherited/tooling boundary defects and verified the
fixes: account-context size must be checked against a bounded captured read, not
only a prior stat; directory publication must refuse a racing empty destination
on POSIX as well as Windows. The tool now reads at most 16KiB+1 and uses exclusive
native rename (Windows `os.rename`, Darwin `renamex_np(RENAME_EXCL)`, Linux
`renameat2(RENAME_NOREPLACE)`), refusing unsupported APIs without an unsafe fallback.
The native flags were checked against [Apple's header](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/sys/stdio.h)
and [Linux documentation](https://man7.org/linux/man-pages/man2/rename.2.html).

## Verification

Windows 11 AMD64/Python 3.13.15; `PYTHONPATH=.;client/src;client`,
`QT_QPA_PLATFORM=offscreen`, `client/.venv/Scripts/python.exe -m pytest
-p no:cacheprovider ... -q --tb=short`.

- New preparation/existing catalog focused checks: **50 passed, 1 skipped in
  0.87s**. Eight client/pilot catalog/import/fixture/family modules: **115 passed,
  1 skipped in 71.40s**. All current declarations and existing fixture callers pass.
- Independent preparation/cache/catalog/fixture checks: **71 passed, 1 skipped
  in 28.57s**. Covers strict metadata, duplicate keys, finite JSON/base64/hash/
  declaration/account-context admission, exact reviewed-byte signing, changed-file
  prompt race, unsigned activation refusal with no cache writes and path/digest
  refusal. The reproduced 20KiB account-context growth now refuses without output.
- Actual Windows no-replace publication and mocked Darwin/Linux flags/errors/API
  absence passed. Native Intel/Linux publication has not been run. The skip was
  unavailable native leaf-symlink creation. No hostile-authenticity claim is made.
- Ruff, formatting and owned whitespace checks passed. Integrated whole-client
  run **2121 passed, 4 skipped in 977.04s**; parser pilot **262 passed in 84.59s**.
  Concrete final-revision candidate results are recorded below.

Final input was generated from clean code freeze
`1e61bec33af214930d42396c6ff5f3b9a146e6d4` using the actual prepare CLI and shipped
public ID `data-ed25519-85bb107180ef75ab92b9debcbc16472e`, sequence 1. The curated
23 required declaration files and only their account contexts are copied under
`scratch/v2-release-review-1e61bec/catalog-definitions`. Review artifacts are in
`scratch/v2-release-review-1e61bec/unsigned-catalog-1`: exact `catalog.json`,
`catalog.sha256` and readable `review.json`. Payload SHA-256:
`3d6574d5646003ff995c8c6663fd3b8b526b0221a08312abcfbb591f5cc3e2bc`.
The offline validator confirms source revision, public ID and 23 definitions;
`catalog.sig` is absent. This is explicitly not activatable until the reviewed
bytes receive a valid detached signature. No private key or passphrase was used.

## Remaining work

Production detached signing and installed/offline signed
catalog acceptance retain their explicit owner/release gates.
