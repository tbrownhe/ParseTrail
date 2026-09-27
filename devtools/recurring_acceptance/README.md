# Recurring-analysis acceptance

Run from `client/` on `feature/client-financial-insights`. This launches the real
source UI with a temporary profile and synthetic database. It disables networking,
uses a null credential backend, and never loads the normal or staging config.
No installer, publication, model training, or server connection is involved.
Close the window to discard the temporary profile. Exported CSVs selected through
Save Table are intentionally retained at the destination you choose.

```powershell
uv run --no-env-file --frozen python ../devtools/recurring_acceptance/launch.py
```

The default range is January 1 through March 31, 2026, and amount dispersion is
10%. Leave Include Amount unchecked for the first pass.

1. Select **Analyze**. Expect three Streaming subscription rows, each -19.99,
   one cluster, and Save Table enabled. Export and check dates/amounts if desired.
2. Select April 1 through June 30, 2026. At 10%, expect no matches for the
   variable -10/-100/-1000 debits, a useful status message, and Save Table disabled.
   At 200%, expect all three rows; then restore 10%.
3. Select July 1 through September 30, 2026. These descriptions contain only
   stopwords: expect no matches and no error dialog, with or without Include Amount.
4. Select October 1 through December 31, 2026. The positive 10/100/1000 series
   should behave like the negative series: excluded at 10%, admitted at 200%.
5. Select a range wholly in 2025. Expect No transactions, no stale results, and
   Save Table disabled. Return to January-March and confirm analysis still works.
6. Check labels, table readability/sorting, export, and closing the window.

Also exercise the review window:

```powershell
uv run --no-env-file --frozen python ../devtools/recurring_acceptance/launch.py --review
```

Click **Find Recurring Transactions** with the configured maximum dispersion
ratio of 0.1. Expect only the three Streaming subscription rows to receive cluster
IDs. Enter `streaming, subscription, variable, merchant, income` as extra
stopwords and repeat: expect a useful no-match status and cleared cluster IDs.
Auto-Categorize is disabled in this clustering-only rehearsal; review edits apply
only to the disposable database.

For confidential local usefulness acceptance, supply an explicit existing client
database. SQLite opens it read-only and snapshots it into the temporary profile;
any migration/review changes affect only that copy. No source path or financial
contents are printed by the launcher. Do not put private files in the checkout.

```powershell
uv run --no-env-file --frozen python ../devtools/recurring_acceptance/launch.py --database "C:/path/to/parsetrail.db"
```

On Intel macOS use the same command with its local database path. Select a covered
historical range (for example June-August 2026), check familiar stable payments,
and confirm clearly varying debits no longer pass a tight amount threshold.
Refund/mixed-sign and zero-valued groups are deliberately excluded by amount
filtering; this change does not claim new scheduling or forecasting capability.
Record only OS/architecture, commit, steps, and pass/fail observations, not private
transactions, account names, or paths.

Automated preparation checks use `--smoke-test`, optionally with `--review`, and
synthetic data only. These checks do not substitute for owner GUI acceptance.
C1 was accepted on Windows; a duplicate Intel walkthrough is not required for
routine features unless dependencies or platform-specific concerns warrant it.

## C2a-1 background-analysis acceptance

The launcher now shows a ticking GUI heartbeat in the window title. To make
Cancel and Close easy to exercise, add a five-second synthetic delay to each
worker calculation (no real financial data is needed):

```powershell
uv run --no-env-file --frozen python ../devtools/recurring_acceptance/launch.py --slow-seconds 5
```

1. Select Analyze. The title's heartbeat should keep ticking and the window
   should repaint/move normally while analysis controls are disabled. After
   roughly five seconds, expect the same three January-March subscription rows
   and Save Table enabled.
2. Analyze again and immediately select Cancel Analysis. Expect the canceling
   status while the simulated library step finishes, followed by Analysis
   canceled, an empty result table, disabled Save Table, and enabled controls.
   Analyze once more and let it complete to confirm retry works.
3. Start another analysis and press Escape, Close, or the window's X. The window
   should remain responsive while canceling, then close once the current step
   finishes. No crash or late result should appear.

Repeat Cancel and window-X with `--review --slow-seconds 5`. The loaded review
rows should stay intact, canceled analysis should leave no cluster IDs, and the
review controls should be restored to their previous enabled states. A fresh
completed analysis should still annotate the three subscription rows.

The delay intentionally represents a library call that cannot stop midway; it
is only a devtool option. Normal execution checks cancellation during text
preprocessing, between analysis stages, and between filter groups. No dependency,
schema, or server changes are part of C2a-1. Windows owner acceptance is requested;
repeat on Intel only if a concrete compatibility concern arises.
