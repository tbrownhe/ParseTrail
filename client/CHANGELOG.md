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
