# Desktop corresponding-source information

MDLogger selects the **GPL-3.0-only** alternative for PySide6-Essentials,
shiboken6 and their bundled Qt 6.12.0 libraries. The libraries are unmodified.
Python defaults to 3.15.1; the Linux Flatpak uses the Python 3.14 interpreter
provided by the Freedesktop 26.08 runtime. The platform inventories distinguish
these targets and must not be treated as interchangeable binary evidence.

## Verified Qt and PySide source archives

These archives were downloaded on 2026-10-24 and their SHA256 and sizes were
checked against the official `.meta4` metadata. Hash verification is not a claim
of detached-signature verification.

| Archive | Size (bytes) | SHA256 |
| --- | ---: | --- |
| `qt-everywhere-src-6.12.0.tar.xz` | 443394020 | `98ff4f44bac6ec3e1e62ee2a4316ae0e3d15badb015d753cc0268a20db52f165` |
| `pyside-setup-everywhere-src-6.12.0.tar.xz` | 18211772 | `099c1a597cf33c1b000e11cf68a0b82d216fb802bf81726efc720394f10c7751` |

- Qt source: <https://download.qt.io/official_releases/qt/6.12/6.12.0/single/qt-everywhere-src-6.12.0.tar.xz>
- Qt metadata: <https://download.qt.io/official_releases/qt/6.12/6.12.0/single/qt-everywhere-src-6.12.0.tar.xz.meta4>
- PySide source: <https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/pyside-setup-everywhere-src-6.12.0.tar.xz>
- PySide metadata: <https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/pyside-setup-everywhere-src-6.12.0.tar.xz.meta4>

The matching PySide source originals are retained under
`licenses/desktop/qt-for-python-6.12.0/`. The commercial license file shipped by
the Windows wheel is preserved as metadata evidence, not as the project's
selected license. The selected GPL text and the source's other license
alternatives and COPYING files are retained separately.

The verified Qt archive contains 374 `LICENSES` members with 69 distinct texts.
The byte hashes and originating archive members are recorded in
`licenses/desktop/qt-6.12.0/LICENSES-MANIFEST.json`. The attribution document in
the same directory contains 98 records and 61 referenced legal originals from
qtbase, qtdeclarative, qtlanguageserver, qtlottie, qtquicktimeline,
qtshadertools, qtsvg, qttools and qtwayland. This is a conservative source
superset including cross-platform records, not the wheel publisher's
exact-build SBOM. Tests/examples and unused Addons, WebEngine, Pdf and
Multimedia source modules are outside that scope.

## Essentials-only distribution

The umbrella `PySide6` dependency is not installed. Only
`PySide6-Essentials==6.12.0` and `shiboken6==6.12.0` are installed. These provide
QtCore, QtGui, QtWidgets and QtSvg used by the app, QtTest used by tests, and the
Qt modules loaded by pyqtgraph without requiring Addons.

QtWebEngine/Chromium, Qt Multimedia/FFmpeg and Qt Pdf runtimes are not shipped.
The Essentials wheel nevertheless contains orphan Designer/Pdf plugins that
depend on the absent optional runtimes. Flatpak explicitly removes
`PySide6/Qt/plugins/designer/libqwebengineview.so`,
`PySide6/Qt/plugins/imageformats/libqpdf.so` and
`PySide6/Qt/qml/QtQuick/Pdf/`. The final-image verifier rejects their presence.
Windows excludes the PDF bindings/plugin, orphan WebEngine Designer plugin,
Chromium `icudtl.dat` resource and unused software OpenGL renderer in
`MDLogger.spec`.

Every remaining Essentials ELF binding, Qt library, plugin and tool is recorded
in `licenses/inventory/qt-third-party-runtime-linux-flatpak.json`. The module
inventory records the larger Essentials payload, not merely the four direct
application imports. Windows must instead inspect its actual PyInstaller TOC.
Neither inventory is an exact upstream build-generated SBOM.

The Linux Essentials wheel also bundles **ICU 73.2**, verified directly using
`u_getVersion_73`, rather than a version inferred from Qt's source configuration.
Its exact release license, including dictionary and time-zone notices, is
retained at `licenses/desktop/icu-73.2/LICENSE` (SHA256
`f3005e195ff74d8812cc1f182a1c446fab678d70a10e3dada497585befee5416`).
Source: <https://github.com/unicode-org/icu/tree/release-73-2>.
The latest Qt wheel determines this native ABI dependency; it is not replaced
independently with an incompatible ICU release. Its three shared libraries have
separate wheel and final-image hashes, measured from the actual SDK build.

## Linux cryptography and OpenSSL source

The Python 3.14 Linux `cryptography==50.0.2` wheel ships exact OpenSSL and Rust
build-provenance SBOM files, retained under
`licenses/desktop/cryptography-50.0.2/sboms/`. They identify OpenSSL 4.0.3 built
with `no-shared` and 39 Rust build components. The Rust document is not an
object-level linker map. Python 3.15 uses a different wheel, so its installed
binary bytes must not be passed off as Flatpak evidence.

- cryptography source: <https://files.pythonhosted.org/packages/9d/af/182eb91b0df3fe75c4d9f26fe70684569566745f6ba7e5c9c73a862c5252/cryptography-50.0.2.tar.gz>
- cryptography SHA256: `7b46165bb56eb4704e2eaaf86f3c940d19154535d9b0ca7d6d590b04060e00d5`
- OpenSSL source: <https://github.com/openssl/openssl/releases/download/openssl-4.0.3/openssl-4.0.3.tar.gz>
- OpenSSL SHA256 from the wheel SBOM: `325b5c806167c13b40b1ffeadfe0248197c00eccc4cf123ec1e28d2d2fd216d9`

## NumPy native runtime source

NumPy 2.5.4 Linux wheels contain OpenBLAS/LAPACK, libgfortran and libquadmath.
The Windows wheel contains OpenBLAS/LAPACK and statically linked libgfortran.
Their platform-specific original notices are retained in
`licenses/desktop/numpy-2.5.4/licenses/LICENSE.txt` and `LICENSE-windows.txt`.
Other legal files declared by NumPy wheel metadata are also retained.

- NumPy source: <https://files.pythonhosted.org/packages/95/b0/c7453d0b6e2073c3264468b106ee1563750cecc910965e67357e3698c83e/numpy-2.5.4.tar.gz>
- NumPy SHA256: `9a94cf751c9ad8ebaa835bcd3d40dacf8534ad086b88c38029b65123c7999d2a`
- OpenBLAS/LAPACK upstream: <https://github.com/OpenMathLib/OpenBLAS/>
- GCC libgfortran/libquadmath upstream: <https://gcc.gnu.org/git/?p=gcc.git;a=tree>

Known limitation: the wheel notices do not identify the exact OpenBLAS or GCC
source revisions used by the wheel publisher. Do not describe these upstream
repository links as verified corresponding-source snapshots. If matching build
revisions become available, add their verified source URLs and hashes to these
directions and the release record. The current guidance does not resolve that
limitation.

## Windows runtime and build components

The Windows runtime is uv-managed **python-build-standalone 20261021 CPython
3.15.1**, not the python.org installer. The actual vendor archives were
downloaded and checked against the publisher's GitHub release asset digests.

- Installed runtime archive: <https://github.com/astral-sh/python-build-standalone/releases/download/20261021/cpython-3.15.1%2B20261021-x86_64-pc-windows-msvc-install_only_stripped.tar.gz>
- Installed runtime SHA256: `e7153a9f05921a72f7da1551d3bd374a88c4ffc0bbbea08776ddcb99b787d0f8`
- Matching full archive: <https://github.com/astral-sh/python-build-standalone/releases/download/20261021/cpython-3.15.1%2B20261021-x86_64-pc-windows-msvc-pgo-full.tar.zst>
- Full archive SHA256: `9553b8bf3b4b5da4148b504185b4069af1e4da5d10e65b64e17e7bbfa0d8ca1c`
- CPython source: <https://github.com/python/cpython/tree/v3.15.1>
- Vendor build source: <https://github.com/astral-sh/python-build-standalone/tree/20261021>

`licenses/desktop/cpython-3.15.1/` retains the installed runtime's composite
LICENSE, the matching full archive's native-library license originals and
`PYTHON.json` build manifest, CPython v3.15.1 `Doc/license.rst`, and a hashed
`VENDOR-MANIFEST.json`. The metadata describes build inputs and is not an exact
PyInstaller payload inventory. Native libraries include the compression,
SQLite, OpenSSL and libffi dependencies; Python 3.14 introduced the zstd runtime.
Microsoft Distributable Code terms remain in the composite LICENSE. tkinter
and pip are not represented as application runtime components.

PyInstaller 6.22.3 bootloader/loader code is distributed under
`GPL-2.0-or-later WITH Bootloader-exception`; its runtime hooks and
pyinstaller-hooks-contrib 2026.9 runtime hooks use `Apache-2.0`. Their originals
are retained in the corresponding versioned directories. Windows Qt includes
D3D12MemoryAllocator and Wintab; their exact Qt 6.12.0 source texts are retained.
Inno Setup 6 loader/uninstaller notices remain under `licenses/desktop/innosetup-6/`.

## Verification and release delivery

Recheck the official URLs, archive sizes and hashes for every release. For
example, `sha256sum qt-everywhere-src-6.12.0.tar.xz` must match the digest above.
Generate/check Linux native evidence using a Python 3.14 environment matching
Flatpak, not the default Python 3.15 environment. Run
`scripts/generate_desktop_licenses.py --check`, then verify both the wheel phase
and the stripped final Flatpak image using
`scripts/verify_flatpak_license_payload.py`. A final-image hash must come from
the actual SDK build; it must never be copied from an older release or assumed
equal to the raw wheel hash. Windows release hosts separately inspect their
PyInstaller and installed Inno Setup payloads.

MDLogger source and packaging files are available from the release's immutable
tag or commit in <https://github.com/dusten45/MDLogger>; GitHub Releases provide
the tag's `Source code (zip)` and `Source code (tar.gz)` downloads. The combined
desktop workflow retains its additional `MDLogger-<version>-source.tar.gz` and
release manifest as internal Actions artifacts, not as public release assets.
Internal artifacts are verification evidence, not a substitute for public
source access.

For unmodified third-party libraries, the current policy is to provide the
upstream URLs and recorded hashes above, not attach source archives to each
release. `scripts/release/third_party_source_delivery.json` records
`upstream_urls_documented_in_source_offer` and
`workflow_downloads_or_attaches_archives: false`. Its reference to
**GPL-3.0 Section 6(d)** describes the intended delivery approach, not a finding
that every source-delivery obligation has been met.

The canonical public source-information page is
<https://github.com/dusten45/MDLogger/blob/main/licenses/sources/desktop-source-offer.md>.
Distributed notices link there because Windows deliberately omits
`licenses/sources/`. This is a moving branch page; for an older binary, consult
this file at its actual release tag or commit rather than assume the current
versions match. Release directions should identify that revision and keep the
source-information link accessible alongside the object-code download.

The release reviewer must check equivalent, free source access and continued
availability for the applicable period. If a required upstream source becomes
unavailable, the distributor must address that gap; the current workflows do
not provide an automatic mirror. URLs and hashes alone do not establish legal
compliance or resolve the NumPy revision and Qt exact-build SBOM limitations
above. This document is source-location and provenance guidance, not a legal
compliance guarantee or a separate written source offer.
