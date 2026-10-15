# 2.0 source and evidence storage boundary

Status: **approved by the owner**. This is the V2-2/V2-3 format decision, not a
migration plan. The recent Citi PDF layout is a required 2.0 source family.
The disposable CSV-only `StoredEvidenceV1` is a proof of saved review, not the
released schema. Complete the [upstream boundary review](client-v2-upstream-boundary-review.md)
before implementing this store.

## Proposed smallest durable shape

Use one new SQLite database in a separate 2.0 profile. Its format marker must
be checked read-only before any schema initialization or write. A 1.x, unknown,
corrupt or newer database is refused. There is no 1.x reader, alias table or
automatic carry-forward. A fresh empty profile is the only creation path.

Store original source bytes, exact parser definition bytes and immutable
evidence output in the same database transaction. Keep each object's SHA-256
digest and size. This makes import atomic and keeps backup/restore to one
consistent file. A source digest identifies an exact imported document;
retrying identical bytes returns the existing import without reparsing,
duplicating observations or changing user decisions. A revised or overlapping
document is a new source requiring review.

The evidence output has one strict, versioned envelope for parser identity,
definition digest/revision, engine and extractor versions, source digest,
document kind, source-account identities, coverage limits, diagnostics and
source locations. Its document payload is typed by kind: statement, activity
export or other explicitly supported evidence. Rows retain exact signed minor
units, transaction and posting dates when observed, description, original
fields and all supporting source locations. Printed balances and derived
values have distinct provenance; absent values remain unknown. The envelope
does not contain categories, verification flags, journal entries or postings.

For recent Citi, the statement payload must retain the printed period,
account suffix, previous/new balances and their locations; each resolved row
and its table/text/fee source copies; supplemental detail rows; and dated and
dollar-line dispositions, including unreadable extraction artifacts. The
balance equation and source-capture checks are admission gates. The ten
archived recent-layout statements currently pass 486 dated starts/rows, ten
printed balance equations and 281 nontransaction dollar-sign lines with zero
unresolved; this is read-only pilot evidence, not native release acceptance.
The current path is still a development pilot that borrows recognition and
date/money patterns from the shipped 1.x parser. Runtime admission requires
those rules to move into the finite 2.0 definition/engine contract; the old
parser is only a read-only comparison baseline.

## Separation from accounting

Import stores evidence without posting. A source account is explicitly mapped
to a ledger asset or liability account; Citi must map to a liability and its
source sign convention must be confirmed from the printed balance and row
equation before creating ledger observations. A shared last-four suffix is a
review hint, not a globally unique account ID. No category, transfer, payment,
fee, refund or expense interpretation is inferred from the PDF. Later review
posts through the existing ledger kernel and preserves all authored decisions
separately from immutable source evidence.

The owner approved a global **Allow abbreviated account numbers to automatically
match to ledger** preference, off by default under File > Preferences. Evidence
now identifies Citi's account suffix as `last_four`; table exports remain `opaque`
until their account-number form is established. With the preference on, a suffix
can select a ledger account only when exactly one verified full account number
matches within the same institution and asset/liability class. With it off, the
same candidate is suggested for review and the review flow must offer to turn
the preference on. Ambiguous matches always require review. Full observed
numbers may match exactly without this preference. The isolated matching policy
is implemented; the inline review control awaits the 2.0 import UI.

The first runtime importer can support one source at a time. Parsing and
bounded extraction finish before the database transaction; the transaction
adds the source, definition, saved evidence and any admitted unposted
observations together. Cancellation or failure leaves no partial import.
Opening saved evidence validates its schema and stored hashes without
reparsing. A later explicit reparse compares new evidence against the saved
snapshot before any affected decision can be reused; catalog updates never
rewrite old snapshots silently.

## Next proof

The **single-database, immutable versioned evidence snapshot** boundary is
approved. The [2.0 source store](../client/src/parsetrail/core/v2_profile_store.py)
now implements the first proof: a fresh SQLite format marker is checked read-only
before reopening for writes; source bytes, definition bytes, strict evidence and
an unposted observation index save in one transaction. A synthetic CSV and Citi
statement shape reopen without reparsing. A temporary 2.0 profile also imported
and reopened ten recent Citi archive PDFs through the bounded pilot path (486
rows, 803 dispositions), with unchanged source hashes. Identical source bytes
are detectable before parsing and a retry leaves saved evidence intact. This is
source storage only; account mapping, reviewed ledger posting, full page capture,
signed catalog admission, native GUI and Intel Mac worker limits remain gates.
The separate source-store module is temporary. Before 2.0 activation, move its
schema and methods into the application's single user-database service so source
snapshots and ledger methods have one owner.
