# Desktop legal-file provenance

`licenses/desktop/` contains unmodified upstream legal files and attribution
evidence. Exact paths and SHA256 values are pinned in
`scripts/desktop_license_policy.json`; the generator fails on missing files,
extra/missing wheel legal files, or hash drift.

## Wheel and source evidence

For installed Linux distributions, legal files are collected through
`importlib.metadata.Distribution.files` from the wheels synchronized by the
current `uv.lock`. Flatpak evidence targets Python 3.14, not the default
Python 3.15.1 environment or Windows wheels. The manual policy records the
exact Core Metadata license field or classifier reviewed; the selected license
expression is a separate field, not automatic approval of package metadata.

The following lock-pinned source archives supplied originals that were absent
from, or needed to supplement, the installed wheel evidence:

- openpyxl 3.1.5 sdist:
  <https://files.pythonhosted.org/packages/3d/f9/88d94a75de065ea32619465d2f77b29a0469500e99012523b91cc4141cd1/openpyxl-3.1.5.tar.gz>
  (`sha256:cf0e3cf56142039133628b5acffe8ef0c12bc902d2aadd3e0fe5878dc08d1050`)
- et_xmlfile 2.0.0 sdist:
  <https://files.pythonhosted.org/packages/d3/38/af70d7ab1ae9d4da450eeec1fa3918940a5fafb9055e934af8d6eb0c2313/et_xmlfile-2.0.0.tar.gz>
  (`sha256:dab3f4764309081ce75662649be815c4c9081e88f0837825f90fd28317d4da54`)
- pywin32-ctypes 0.2.3 sdist:
  <https://files.pythonhosted.org/packages/85/9f/01a1a99704853cb63f253eea009390c88e7131c67e66a0a02099a8c917cb/pywin32-ctypes-0.2.3.tar.gz>
  (`sha256:d162dc04946d704503b2edc4d55f3dba5c1d539ead017afa00142c38b9885755`)

Qt/PySide6 6.12.0, cryptography 50.0.2, NumPy 2.5.4 and Windows CPython 3.15.1
source/vendor URLs and verification hashes are recorded in
[desktop-source-offer.md](desktop-source-offer.md).

## Current Qt evidence

Only `PySide6-Essentials 6.12.0` and `shiboken6 6.12.0` are installed. The
umbrella PySide6 package and Addons are absent; WebEngine, Pdf, Multimedia,
Chromium and FFmpeg runtimes are not shipped. Shared PySide originals are under
`licenses/desktop/qt-for-python-6.12.0/`. Windows commercial-license metadata
is retained as evidence, not as the selected license; MDLogger selects
`GPL-3.0-only` for Qt/PySide6.

The verified `qt-everywhere-src-6.12.0.tar.xz` supplied 374 module-level
`LICENSES` members with 69 distinct texts. Their source-member mappings and
SHA256 values are in `licenses/desktop/qt-6.12.0/LICENSES-MANIFEST.json`.
`QT-THIRD-PARTY-ATTRIBUTIONS.json` in that directory records 98 attributions
and 61 referenced legal originals under `third-party-source-files/`.
Its scope includes cross-platform records from the Essentials source modules,
but excludes tests/examples and unused Addons, WebEngine, Pdf and Multimedia.
It may over-disclose components absent from the publisher's actual build.

`licenses/inventory/qt-third-party-runtime-linux-flatpak.json` records the
remaining Essentials ELF bindings, libraries, plugins and tools with exact
wheel paths, sizes and hashes. ICU 73.2 is verified through `u_getVersion_73`;
its full release license is retained under `licenses/desktop/icu-73.2/`.
The Qt publisher's exact-build SBOM is unavailable. Neither source attributions
nor binary inventories substitute for it; Windows requires separate inspection
of its PyInstaller payload.

## Windows runtime and build components

Windows uses uv-managed python-build-standalone 20261021 CPython 3.15.1,
not the python.org installer. `licenses/desktop/cpython-3.15.1/` retains the
verified install-only archive's composite LICENSE, matching full-archive
native-library originals and `PYTHON.json`, CPython's `Doc/license.rst`, and
`VENDOR-MANIFEST.json`. These describe vendor build inputs, not an exact
PyInstaller payload. Microsoft Distributable Code terms and native-library
notices, including zstd introduced with Python 3.14, remain intact.

The policy also inventories distributed build components even though their
packages are development dependencies:

- PyInstaller 6.22.3 bootloader/loader code: `GPL-2.0-or-later WITH
  Bootloader-exception`; embedded runtime hooks: `Apache-2.0`.
- pyinstaller-hooks-contrib 2026.9 runtime hooks: `Apache-2.0`, including
  `pyi_rth_pyqtgraph_multiprocess.py`.
- Inno Setup 6 loader/uninstaller: `LicenseRef-Inno-Setup`.
- Qt 6.12.0 Windows D3D12MemoryAllocator: `MIT`; Wintab:
  `LicenseRef-Lcs-Telegraphics`.

Their original texts remain in the corresponding versioned directories;
the policy records every path and hash.

## Composite package review

- `cryptography 50.0.2`: upstream metadata is `Apache-2.0 OR BSD-3-Clause`;
  MDLogger explicitly selects `BSD-3-Clause` for the Python package and retains
  the umbrella file plus both upstream alternative texts. The Python 3.14 Linux
  wheel also carries exact wheel SBOM evidence under
  `licenses/desktop/cryptography-50.0.2/sboms/`: `sbom.json` identifies a
  statically built OpenSSL 4.0.3 (`no-shared`), while
  `cryptography-rust.cyclonedx.json` records 39 Rust build components. The Rust
  SBOM is retained as wheel build provenance, not as an object-level linker map.
- `et_xmlfile 2.0.0`: the metadata says MIT, but `LICENCE.python` discloses
  Python standard-library-derived code. MIT and the Python Software Foundation
  license are both retained.
- `NumPy 2.5.4`: all legal files reported by the Linux wheel plus the
  Windows wheel's `LICENSE-windows.txt` are retained,
  including libdivide, pythoncapi-compat, Highway, Dragon4, x86-simd-sort,
  SVML, pocketfft, LAPACK, masked arrays, and random-generator components. The
  actual Linux wheel also ships `numpy.libs/libscipy_openblas*.so`,
  `libgfortran*.so`, and `libquadmath*.so`; its retained `LICENSE.txt` preserves
  the OpenBLAS, LAPACK, GCC Runtime Library Exception/GPL-3.0-or-later, and
  libquadmath LGPL-2.1-or-later notices. The locked Windows wheel ships
  `numpy.libs/libscipy_openblas*.dll` with OpenBLAS, LAPACK, and statically
  linked GCC `libgfortran` runtime code; its retained `LICENSE-windows.txt`
  preserves those notices. Both Linux and Windows native runtime components are
  listed in the policy rather than being hidden by NumPy's package-level
  metadata expression. The exact OpenBLAS/GCC source revisions remain unknown;
  generic upstream links are not verified corresponding-source snapshots.
- `pyqtgraph 0.14.0`: the package MIT license, CC-BY-4.0 CET license,
  ColorCET/Peter Kovesi attribution, CC0 legal code, turbo Apache-2.0 marker and
  full Apache text are retained.

## Packaging exclusions

Both PyInstaller's pyqtgraph hook and the Flatpak's full wheel would normally
include all of `pyqtgraph/colors/maps`. The files `PAL-relaxed.hex` and
`PAL-relaxed_bright.hex` contain no copyright, attribution, or SPDX identifier,
and the upstream tag does not provide enough evidence to determine their
license. MDLogger does not use either palette, so the developer decided to
exclude them from both supported desktop distributions.

`MDLogger.spec` filters both palette files from PyInstaller's collected data;
Flatpak removes and checks them after wheel installation. Windows also excludes
unused `opengl32sw.dll`, PDF bindings/plugin/runtime, the orphan WebEngine
Designer plugin and Chromium `icudtl.dat`. Flatpak removes orphan WebEngine/Pdf
plugins and QtQuick/Pdf QML. These exclusions are enforced by packaging tests
and payload verification; no packaging change is implied by this document.

## Historical acquisition evidence

The earlier Qt 6.11.1/Addons, CPython 3.13 and PyInstaller 6.21.0 review is
preserved with its original paths, hashes and source directions in
[commit a0d62bf3511a7be3a3313d2db7b1a4948b5209c9](https://github.com/dusten45/MDLogger/tree/a0d62bf3511a7be3a3313d2db7b1a4948b5209c9/licenses).
It is historical evidence, not a description of the current payload.

That Qt source review recorded 402 `LICENSES` members, 83 distinct texts,
123 attributions and 88 referenced legal files. The old Addons wheel reported
QtWebEngine 6.11.1, Chromium 140.0.7339.225 and FFmpeg 7.1.3 (LGPL 2.1 or later);
its Qt source recorded Chromium base 140.0.7339.264 with security patches through
148.0.7778.96. Chromium's official license tool generated the 262-component
Linux source-credit superset twice with SHA256
`dcff1f0db5c1c9a52d633a50504d68483bb916a9e6356ef7e8641f579aa96816`.
Those source supersets were not exact-build SBOMs either.
