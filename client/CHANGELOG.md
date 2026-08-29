Unreleased
==========
- Prompt immediately when saved credentials are rejected during a plugin update
  and resume the same signed catalog operation after successful authentication
- Separate statement import persistence, deduplication, and archive state from Qt
  prompts and progress behind a characterized headless application service
- Move category queries and atomic add, update, rename, and merge operations behind
  a characterized headless service with typed failures
- Move account queries, mutations, deletion constraints, and account-number
  assignment behind a characterized headless service with typed failures
- Do not silently store a zero appreciation rate after invalid input or select an
  unrelated account when the create-account dialog adds nothing
- Move budget range queries, grouping, sign handling, and proration behind a
  characterized headless reporting service
- Move transaction-review filtering, atomic edits, and model-category compatibility
  retry behind a characterized headless service with typed failures
- Move transaction range and latest-balance queries plus atomic manual entry behind
  a characterized headless service
- Report manual-entry duplicates accurately and make empty recurring-analysis results
  and category columns safe in the transaction dialog

1.3.1
=====
- Make macOS release regression tests deterministic with explicit Qt worker
  synchronization and transport-independent upload cancellation checks

1.3.0
=====
- Store money as integer minor units with explicit currency codes
- Use typed calendar dates and UTC import timestamps
- Replace ambiguous MD5 transaction keys with framed, versioned SHA-256 fingerprints
- Represent overlapping statement membership with a statement-transaction join table
- Enforce SQLite foreign keys and explicit delete behavior on every connection
- Validate and migrate shadow database copies before atomic replacement
- Require exact-Decimal parser output and client 1.3 compatibility for updated plugins
- Bound and sanitize HTTP failures, retry only idempotent requests, and keep network
  workflows off the Qt thread with cancellable authenticated staging
- Store server access tokens in the OS credential store and retire the legacy
  same-profile Fernet key
- Launch installers through shell-free Windows, macOS, and Linux adapters

1.2.2
=====
- Move the supported desktop runtime to Python 3.13.15
- Replace GPL-only PyQt5 with the official LGPLv3 PySide6 binding
- Preserve the Windows and macOS frozen-runtime smoke gates
- Require deterministic, unique parser classification using format, optional PDF
  metadata, page headers, and body markers
- Return headless typed parser results with explicitly accepted warnings and
  redacted failures
- Correct the Synchrony/Amazon plugin identity and remove its malformed `.py.pyc`
  artifact name
- Remove NLTK's startup corpus download and bundle deterministic English stop
  words for local clustering
- Delay automatic update checks until after first paint and make them optional
- Add network-denied module-import and fresh-database startup regression tests

1.2.1
=====
- Make uv the sole owner of the release Python environment
- Pin Windows and macOS builds to Python 3.10.19
- Smoke-test frozen runtime imports before packaging
- Prevent versioned installers from being overwritten accidentally

1.2.0
=====
- Require plugins to be accompanied by a  signed manifest

1.0.0
=====
- Initial Release

1.0.1
=====
- Fix NSIS installer loop bug
- Fix dynamic ftypes detection
- Refine build scripts

1.0.2
=====
- Add FILENAME to local plugin metadata to allow obsolete plugin deletion
