# Third-party notices

ParseTrail is distributed under the MIT License. Its desktop packages also
contain the following separately licensed components.

## Qt for Python and Qt

- PySide6 Essentials 6.11.2 and Shiboken6 6.11.2
- Copyright The Qt Company Ltd. and other contributors
- License selected for this distribution: GNU Lesser General Public License
  version 3.0 (the packages also offer GPL and commercial alternatives)
- Project source: <https://code.qt.io/cgit/pyside/pyside-setup.git/>
- Qt 6.11.2 source: <https://download.qt.io/archive/qt/6.11/6.11.2/submodules/>

A copy of the LGPLv3 is installed in `licenses/LGPL-3.0.txt`. ParseTrail uses
the unmodified shared libraries supplied by the official PySide6 wheels. In a
Windows installation those libraries remain separate under
`_internal/PySide6`; the macOS application has the equivalent separate
frameworks in its application bundle. Nothing in ParseTrail's license or
installer forbids reverse engineering for the purpose of debugging a modified
version of those LGPL-covered libraries.

Qt and PySide include additional third-party components under their own
licenses. The authoritative component notices and corresponding source are
available from the Qt source link above for the bundled Qt 6.11.2 release.
