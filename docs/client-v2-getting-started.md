# Getting started with the V2 desktop workflow

Start in **Documents**, import a supported statement or activity export, then
check the document, account and dates shown. Statement periods and the span of an
activity export can differ. Keep the original available when checking evidence.

The Documents table shows accounts, institution, period, document type and review
status. Click a column heading to sort; use Find or **Filters** to narrow the table
by account, institution, type, review status or overlapping dates. **Clear filters**
restores the full inventory. A document containing multiple accounts matches either
account's filter. Select a document and use its review action, or press Enter.

Import asks **which account the document came from**. Choose a compatible existing
account, or **Create a new account…**, even if another account uses the same export
format. For a new account, enter a nickname and only the institution/product details
the document has not established. Product supplies asset/liability class and the
supported amount represented. Header compatibility alone never identifies an account.
Documents containing several accounts show each group, including groups beyond
the preview rows; choose an account for every group.

Next, **Review import** shows the automatically recognized activity, dates and
account assignments. CSV headers must match a declared format; your institution
and product choices narrow compatible formats without assigning columns. If more
than one format still matches, import is blocked. Check account details, use a
supported original export or install an updated signed catalog. Conflicting account
group structures are also refused. PDF format routing stays automatic.
**Back to accounts** keeps applicable choices. **Import
and assign** saves the original, unreviewed evidence, displayed new accounts and
assignments together. It adds no spending. Skip or cancel discards unsaved drafts;
completed batch files stay saved. Changed inputs require a refreshed confirmation.
Check the interpretation before saving: changing the format of an already
imported document is not supported yet. Selecting the exact file again reuses its
saved interpretation; you can cancel before importing if the preview is wrong.

During imports, a compact progress window shows the current file, phase, completed
count and outcomes. Account setup and review open only when input is needed, then
return to compact progress. The previous file's rows are never shown while the next
file is read. Cancel preserves completed imports and waits for the actual outcome;
the final report lists each file's result.

Large batches prepare up to four statements in the background. Account questions
and saved imports still follow your file order; a newly created account is available
to later statements. The progress count shows completed imports, not background
preparation. Cancel waits for background work to stop and keeps completed files.

Account setup and recognized review keep stable primary-action positions;
**Skip this file** stays separate beside Cancel. Alt+N continues to
review, Alt+I imports, Alt+B returns to accounts, Alt+S skips, and Alt+O opens the
original. Ordinary letters stay in text editors. Repeated Enter while waiting does
nothing; Tab reaches Cancel.

If a warning appears, compare the original with the displayed dates and amounts.
Import retains the evidence and warnings; it does not approve complete capture or
post transactions. Back can repair account choices. If the extraction is wrong,
skip that file and retry a supported original export or an updated statement format.
Extracted cells are read-only; editing a number would not repair missing source
content. Replacing the interpretation of a saved source is still a separate gap.

Open **Review** for the selected document to decide what its transactions mean.
Accounts created separately on the Accounts page still need explicit document/row
assignment. Creating or assigning an account adds no spending.

If you created separate records for replacement card numbers of the **same actual
account or obligation**, use **Accounts → Consolidate accounts**. Choose the record
to keep and the duplicate to combine, check the affected documents and identifiers,
then confirm they represent the same account. The original evidence and posted
history remain intact; future matching can use the retained numbers. The combined
account's review contains **Combined account records** with the decision history.
This adds no financial transaction and cannot be undone in the application; keep a
backup first. The preview explains conflicts, such as duplicate openings, to correct
before trying again. Use Transfers for payments or transfers between separate accounts.

Supported Fidelity 401(k), Vanguard and Fidelity HSA period summaries use **Review
statement value**. Their component totals remain evidence; recording the printed
closing value adds no transactions, transfers or budget spending. The separate
**Automatically record supported statement values** setting can record qualifying
future imports. Missing or conflicting values and material source warnings still
require review. This does not apply to HSA statements containing dated cash activity.

Choose an institution by its name when creating an account, or deliberately choose
**Institution not identified**. Selecting an existing account uses its saved
institution. A compatible generic CSV does not necessarily identify its bank, and
an institution being listed does not mean every format from it is supported.

Select a transaction and choose its type and category. In **Review set**, enter a
**shared reason** for all the rows you plan to post. It persists as you change
rows and stays separate from saved-entry correction reasons.
Use **Add category…** beside the category choice to create a category in context.
Use **Stage selected**, then **Review staged** and inspect the exact confirmation
before posting. One transaction and several use the same flow. Staging is an
unsaved proposal; it adds no spending. Transfers, card repayments and loan
principal have their own review routes because they are not additional expenses.

To categorize several unreviewed transactions together, use **Ctrl-click** for
separate rows or **Shift** for a range. The selected count and heading show the
scope. Choose their shared purpose, category and note, then **Stage N selected**
and **Review staged**. Nothing posts until the exact confirmation. Each row
keeps its own date; stage date overrides individually. Successful staging captures
the batch note; later unstaged or refused proposals do not change it. The captured
note applies to all staged rows, including any staged before changing a filter;
staging with a different note replaces that shared note. Already-reviewed entries
use individual correction.

The table identifies **Not staged**, **Staged · not saved**, and reviewed rows.
The separate review status still explains blockers. Editing a staged row shows
**Changes not staged**: stage it again to replace its proposal, or keep the earlier
proposal for confirmation. **Remove selected from review set** removes only those proposals;
**Clear review set**, under **Review set options**, empties the staged set. The staged count includes rows hidden by
filters. Canceling confirmation keeps the proposals. Staging is temporary and
closing a review asks before discarding it.

If a transaction may repeat one in another document, use **Review possible
repeated transactions…** beside the blocked choices. Compare both sources, then
explicitly decide whether they are separate transactions or the same transaction.
This decision posts no money. A supporting occurrence cannot post separately;
the retained occurrence can proceed once all required comparisons are resolved.
Closing the comparison returns to the selected row and keeps earlier staged work.
This review is separate from recognizing the file format at import.

The input colors describe your current choices:

| Appearance | Meaning |
| --- | --- |
| Pale red | A required choice is missing or needs correction. The nearby message explains what is needed. |
| Pale green | This choice is valid but has not been saved. Other fields or prerequisites can still need attention. |
| Light-blue action | An available next action. Its label and confirmation explain whether it prepares, saves or posts choices. |
| Neutral | A saved or retained choice, read-only source fact, or empty optional field. |
| Amber message | A prerequisite needs attention before the action can proceed. |

Green does not establish that an interpretation is correct, that the source is
complete, or that the account reconciles. Read the confirmation to see what will
be saved. Cancelling a confirmation retains the draft for further editing.

Use **View spending** to see reviewed spending for the document dates
across **all accounts in the profile**. Pending activity and incomplete source
coverage can limit the result. An empty reviewed report does not establish zero
spending. The qualifications beside the totals explain these limits.

To correct an entry, inspect the report's entries and open its source row.
**Saved review note** shows the reason retained with the active saved review;
it is read-only context. **Reason for correction** starts empty. Change the
category (or a supported card accounting date), then enter why you are changing
it. Opening the row alone does not create an unsaved correction. Cancelling the
confirmation keeps your changes and reason; saving refreshes the saved note and
clears the editable reason. Withdrawal also needs an explicitly entered reason
and its own confirmation. The original evidence and prior history remain
available. **Back to report** returns to the report context. Source details and
**Open original** provide supporting evidence when needed.

Open **Budget** to see monthly budget, reviewed spending and remaining across all
profile accounts. Select a category and choose **Edit selected budget…**, or use
**Set up budgets / categories…**. The editor opens in the same month and category;
use **Add category…** for a new category. Existing-category editing shows no
unrelated new-name validation. **View spending** from a document also selects its
first month for Budget; a multi-month document labels which month is shown.
Ordinary Budget/Reports navigation preserves your chosen month and report dates.

In **Categories and budgets**, use **Save monthly budget** to save an optional USD
budget from an effective month. It
continues until the next saved change. **Remove budget from month** ends it from
that month; it keeps earlier history. Budgets do not post transactions. Reports
compare them with reviewed spending, so pending activity still limits the result.
