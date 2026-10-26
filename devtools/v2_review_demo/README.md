# Disposable integrated V2 review

From the repository root, run:

```powershell
& .\client\.venv\Scripts\python.exe devtools/v2_review_demo/prepare_demo.py
```

The command creates a new directory under ignored `scratch/`, prints its path,
and writes `Open-review-demo.cmd` and `WALKTHROUGH.txt`. Double-click the launcher
in your Windows session. No existing profile is selected or overwritten. Use
`--prepare-at NEW_DIRECTORY` for another explicit disposable location.

The fixed August/October 2026 examples use public synthetic source bytes through
the actual signed-catalog importer and bounded workers. A new ephemeral fixture
key signs the local catalog; only its public key is retained. Catalog, preferences,
application home and profile are separate from daily state. A copied public
runtime and hash manifest pin the launcher and its parser workers to that schema;
the existing virtual environment supplies only the interpreter/dependencies.
Startup output goes to `last-launch.log`, and failures preserve their exit status.
The initial profile contains reviewed cash/category history, unknown and zero openings, HSA cash-only
reconciliation, nonposting dated values and an owned outflow awaiting its receipt.
It also includes an evidenced Capital principal/interest payment and a Yamaha
whole-register charge/repayment. January interest is $20; February Vehicle charge
is $10. Six public synthetic originals remain embedded. Date preferences stay off;
the seeded Capital accounting-date assumption is retained as an explicit historical
fixture-author review, separate from its unchanged source activity date.
The walkthrough gives expected exact totals and pending review actions.

`--verify DEMO_DIRECTORY` checks the initial seeded state after reopening; after
interactive edits, that initial-state check can legitimately fail. Closing keeps
the demo available. `--smoke-ui DEMO_DIRECTORY` checks the helper's window startup
with display suppressed, then exits and verifies that the profile is unchanged.
Re-run preparation for another fresh example. The profile follows the pinned
runtime's pre-release schema compatibility rules. This tool is not daily-profile
activation or a supported-platform release acceptance result.
