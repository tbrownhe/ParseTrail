# Isolated ledger kernel

The kernel implements the [ledger contract](client-ledger-contract.md) on explicit
inputs. It is not connected to the current application's database, import path,
or reports. L4 will provide reviewed source mappings and shadow conversion; L5
will provide the review UI. Never point this prototype at the live client file.

`core.ledger` defines immutable account, observation, allocation, posting and
journal inputs. `core.ledger_store.LedgerStore(path, create=True)` creates a new
isolated SQLite file and refuses existing paths. Opening an existing store requires
its own ledger version table; it does not initialize a legacy database. Closing
the context manager closes the connection. No application settings, credentials,
ORM migrations, or network clients are imported.

## Posting and evidence

Amounts are signed integer USD minor units: debit positive, credit negative.
Accounts explicitly declare Asset/Liability/Equity/Income/Expense and optionally
map to one unique legacy financial-account identity. Clearing, suspense and
opening-equity purposes remain explicit; suspense's account class must be selected
by the approved migration policy, not inferred by the kernel. Non-USD posting is
blocked pending quantity/FX design.

An observation identifies one canonical movement. Repeated statement memberships
refer to that observation rather than duplicating it. Allocations preserve its
account, sign, posting date and denomination. Imported financial postings must
be fully allocated; an observation can be split across entries but cannot be
consumed beyond its exact amount. Remaining allocations are queryable and never
silently finalized. Source observation and mapping identities are immutable.

`post` validates the complete entry and persists entry, allocations and idempotency
identity under `BEGIN IMMEDIATE`. A repeated identical key returns the existing
entry; changed contents under that key fail. Invalid proposals can exist as input
objects but are never posted. Persistent draft editing belongs to the later UI.
Manual and opening entries require explicit review and a reason. Opening equity
cannot create current-period income or expenses. Unknown counterpart movements
may use an explicitly configured suspense account, but cannot be marked reviewed.

Use separate balanced entries with the same `event_id` for different posting
dates: sending account to clearing, then clearing to receiving account. The kernel
does not identify transfers or guess counterparts. Reports can query balances at
a calendar cutoff without moving either bank's observed date.

## Corrections and review

`correct` atomically adds a reversal at the original accounting date, a replacement,
and the reason/link. It releases the original interpretation's evidence only in
that same transaction. History remains physically present; balances include the
original and offsetting reversal. Repeated identical correction requests are
idempotent; conflicting requests fail. Corrections preserve economic-event identity.
Posted records, mappings, evidence and audit rows reject SQL updates/deletes via
triggers. All mutation must use the service API; this is not a security boundary
against a process that can replace the database or drop its triggers.

Creation times for entries, corrections, reviews and reconciliation runs are UTC
timestamps, distinct from calendar posting dates. `review` appends a separate
interpretation decision and reason; it does not claim statement reconciliation.
Reclassifying a posted entry uses a correction. Account renaming/reclassification
is not yet an exposed operation and cannot silently rewrite history.

## Statement reconciliation

`StatementEvidence` declares one account's inclusive period, opening immediately
before that period, closing at its end, canonical observations, and reported/
derived/assumed provenance for each balance. L4 must establish source timing and
signs before constructing these inputs. Membership validates account/date ownership
and cannot repeat a canonical observation within one statement. Different,
overlapping statements can share observations without additional postings.

`reconcile` compares the independent source equation, ledger opening and closing,
allocation completeness, and financial postings supported by that statement's
membership. Derived or assumed endpoints always leave an explicit independence
exception. Unknown opening positions, uncovered manual postings and unexplained
differences stay exceptions; no adjustment is manufactured. It neither proves
coverage outside the declared period nor validates whether a category is correct.

Every run is retained with a fingerprint of posted entry versions. Any new journal
entry conservatively marks earlier results stale, including corrections whose
balances happen to stay unchanged. Rechecking appends a new result. This broad
invalidation is deliberate for the initial kernel; narrower account/period
invalidation can follow. Entry-level status leaves statement reconciliation
unspecified because it is an account/statement result, not a category-review flag.

The synthetic regression suite covers purchases/repayments, refunds, loan splits,
fees, cross-month transfers, partial allocation, duplicate processing, unsupported
currency, opening equity, unknown counterpart suspense, immutable history,
correction rollback, overlapping statements, missing/derived balance evidence,
reconciliation invalidation and refusal to initialize an application database.
