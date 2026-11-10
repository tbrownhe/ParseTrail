# Archived Qt heap-corruption reproducer

Retained at the owner's request on November 9, 2026. Active crash investigation
was set aside so ordinary desktop work can continue. This archive is **not part
of the normal test suite**, and process-isolated journey tests do not fix the
underlying defect. Run this only when intentionally resuming diagnosis.

## What is preserved

- `original_short_review_cycle.py`: byte-for-byte copy of the smallest
  consistently failing scenario found (176 lines plus shared helpers). SHA-256:
  `478a7d32dfa9df448f8ba1e01fbc16e9ddaae7e8169e879d0e1eb5480cbf7415`.
- `short_review_cycle.py`: runnable copy with only its support-module import
  changed to the archived snapshot, avoiding the normal suite's process wrapper.
- `journey_snapshot.py`, `qt_journey_helpers.py`,
  `qt_account_import_helpers.py`: contemporaneous scenario/fixture/helper support.
  The snapshot's declaration path points to the adjacent frozen synthetic JSON.
- `synthetic-posted-cash-definition.json`: the exact synthetic CSV declaration.
- `observed_failure.txt`: one original failure log with machine-local repository
  and Python installation prefixes replaced by placeholders.
- `snapshot-hashes.json`: original and archived hashes, historical environment,
  outcome and exact adaptation/verification limits.

These diagnostic files intentionally retain their original formatting and line
numbers. Local Ruff configuration excludes the frozen Python files from routine
formatting/lint changes; Git attributes and the line-ending hook exemption retain
the original source bytes on checkout. None of their basenames matches normal test discovery;
the runnable diagnostic is selected explicitly below. The original full snapshot
contains historical test functions for context but is not selected by the command.

## Reproduction

From the repository root, use the locked client environment and synthetic data:

```powershell
$env:PYTHONPATH='.;client/src;client'
& .\client\.venv\Scripts\python.exe -u -m pytest -p no:cacheprovider -p client.tests.conftest devtools/qt_heap_crash/short_review_cycle.py -vv
```

This deliberately repeats four fresh-profile review/correction cycles within
one QApplication/process. Do not add per-case process isolation, pacing, forced
GC, GC suppression or indefinite QObject retention when comparing the baseline.
The scenario creates disposable signed catalogs and synthetic statements only;
do not substitute a live profile or private statement. It imports current
application/parser/service code, so a different repository revision or runtime
may change or remove the failure.

The observed original environment was Windows 11 x64, Python 3.13.15,
PySide6/Qt 6.11.2, pytest 9.1.1, pytest-qt 4.5.0, offscreen rendering and normal
automatic GC. Three fresh runs completed three cycles, then aborted with
`0xc0000374` (heap corruption) / exit `-1073740940` in the fourth cycle's
post-correction wait at line 174. The wait is where corruption was detected,
not an identified invalid-free site. Single-cycle and three-cycle controls passed.
This is an empirical workflow minimum, not a binding-only or absolute minimum.

The archived import/path adaptation is collection-checked only; no additional
crash run was required to close this task. Changing import/allocation order can
change repeatability. The byte-for-byte original is retained for that reason.

For a non-executing check, append `--collect-only`: four cases should collect.
Single-cycle control selects `::test_expense_review_correction[0]`. Keep any new
logs or screenshots under the repository's ignored `scratch/` directory.

Broader evidence, the same-profile and one-second-pacing failures, and the
owner's successful manual two-statement attempt remain in the
[single work record](../../docs/work/2026-11-07-v2-core-desktop-journey.md).
This archive does not attest general native stability or human acceptance.
