# C1 recurring-analysis acceptance

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
Background execution/cancellation remains C2a.
