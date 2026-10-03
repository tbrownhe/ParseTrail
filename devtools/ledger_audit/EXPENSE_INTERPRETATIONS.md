# Unposted expense/refund interpretations

`ExpenseInterpretations` explicitly classifies wholly unallocated eligible cash/card
evidence using existing expense categories and exact positive minor-unit splits.
It covers movements without ordinary proposals and movements whose original proposal
was rejected. Pending proposals must first be accepted or explicitly rejected in the
ordinary review workflow. Source exceptions, zero amounts, other account types and
partly/wholly allocated evidence remain outside this service.

No classification follows from the sign or description alone. The caller explicitly
chooses expense/refund treatment. Negative source movements debit expenses; positive
movements credit expenses as refunds. Income, transfers/card payments, loan principal,
asset purchases and mixed interpretations require their own workflows. The caller must
not use an expense category merely to clear an unresolved row.

Preview and inventory use committed read snapshots and write nothing, including schema.
Preview binds the candidate workspace, source observation/description, original proposal
and decision, date provenance, chosen category mappings, exact split and audit reason.
Splits must total the entire movement; repeated categories, floats, nonpositive amounts,
income categories and incompatible category mappings are rejected. New ordinary
classification has an optional note and a standard audit reason. Reinterpreting a rejected
proposal requires an explicit reason; its rejection remains immutable history.

Application revalidates the preview in the write transaction, creates needed expense
account mappings, posts one balanced reviewed imported journal, consumes the whole
observation exactly once and saves the interpretation plan in append-only
`ExpenseInterpretations`. Schema, category mapping, journal, allocation and decision
commit together. A competing posting/transfer, partial allocation, changed provenance or
tampered preview prevents application. Exact retries after reopen return the original
journal without duplication, even if that journal was later corrected.

The source account, amount, date, description and event identity are preserved. Verified
category annotations, original proposals and rejection history are unchanged. The posted
entry becomes available in the accepted expense correction editor; subsequent changes
use reversal/replacement. Reconciliation becomes stale after posting. Classification
does not certify source balances, coverage or estimated posting dates.

Synthetic tests cover expense/refund signs, read-only preview/inventory, exact amounts,
optional/required reasons, scope rejection, stale/tampered previews, concurrent transfer
and partial allocation, competing interpretations, atomic rollback including new schema,
retry/reopen, correction chains, preserved evidence/history and reconciliation invalidation.
The service precedes its UI and Windows owner acceptance. All archive exercises use
fresh disposable copies; sample decisions are not financial approvals.
