# Windows 1.4.2 installed acceptance

Use the preserved signed candidate from commit
`4585f4c57d20101c1c6ac4f625b726e51913e562`, tag `client-v1.4.2`, release sequence
`20260922070935`. The [candidate record](engineering-acceptance.md#windows-142-candidate-september-21-2026)
contains the installer and inventory hashes. Intel replacement-candidate
acceptance has passed; this is the remaining Windows artifact walkthrough.

## Prepared local upgrade

The owner authorized replacing this PC's registered application after verified
backups. With all ParseTrail windows closed on September 26, preparation copied
and verified **4,643 files / 817,266,779 bytes**, including the installed 1.4.0
application, both profiles, and their configured data/model/archive locations.
Two SQLite snapshots passed integrity, foreign-key, and logical-source comparison
checks. Two application registry exports were preserved. OS credentials were
not exported. No app/profile was moved or selected during preparation.

The private backup is
`scratch/windows-1.4.2-upgrade-backup-20260926T234341Z`; its manifest SHA-256 is
`b054ce0897df9590fd4d30370e6cd4769e570a233adec9c6cc3bbe584975dff9`.
The existing staging configuration selects the previously authorized private
working copy, with its paths inside the staging profile and automatic update
checks disabled. It does not select the production database.

The local installer helper's verification-only run passed **9,296 checks**:
backup files and unchanged originals, registered 1.4.0 installation, selected
staging copy, pinned release inventory and all listed files, and independent
public-key verification of the signed candidate. No installer or app was launched.
These local helpers and confidential evidence remain ignored under `scratch`.

## Owner installation and walkthrough

Close ParseTrail and run from the repository root:

```powershell
powershell -NoProfile -File .\scratch\install-windows-1.4.2.ps1
```

The helper rechecks the backup and signed artifact before opening the interactive
installer. Complete the administrator prompt and installation. The helper then
compares installed files with the built candidate, checks executable/metadata
hashes and registered version, and verifies profiles/data still match the backup.
Report any error before launching. `-VerifyOnly` checks preparation without
starting the installer and is intended for use before the upgrade.

Disconnect networking, then use this launcher for every acceptance restart:

```powershell
powershell -NoProfile -File .\scratch\launch-windows-1.4.2-staging.ps1
```

It verifies the installed identity and staging working-copy selection, then
launches native Qt with system-only `PATH`. Ordinary shortcuts open the production
profile; use this prepared launcher for the walkthrough.

- Confirm **STAGING 1.4.2** and Help > About
  `client-v1.4.2 (4585f4c57d20)`.
- Check the existing copied data and responsive local views after ten seconds.
  Select All must select and clear items in Category Spending and Balance History.
- Check Budgets in Month and Custom Range, grouped by Category and Type, using
  dates containing transactions. Transaction Review must display `YYYY-MM-DD`
  dates and sort in both directions.
- Quit normally and reopen with the same launcher while still offline. Data and
  settings should persist without blocking login or a missing-model error.
- Quit again and report the results. The Windows agent will verify current
  entries in the configured custom log and compare preserved data/model/plugin
  evidence after the app closes. Keep financial contents and detailed logs local.

The previous full synthetic import/model/credential/backup walkthrough remains
accepted; these checks confirm the replacement installer and repaired controls.
No fresh onboarding or repeated synthetic upload is required here. After this
walkthrough passes, rehearse exact-byte publication and the 1.3-to-1.4 API/website
transition on staging before public activation. Apple Silicon remains deferred.
