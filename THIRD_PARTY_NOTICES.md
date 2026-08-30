# Third-Party Notices

Generated platform sections are delimited so desktop and web inventories can be maintained independently.

<!-- BEGIN GENERATED DESKTOP THIRD-PARTY NOTICES -->
## Desktop distributions

This section is generated from `uv.lock` and the manually reviewed
`scripts/desktop_license_policy.json`. It covers the supported Linux
Flatpak and Windows PyInstaller/Inno Setup distributions.

- Review status: lockfile closures, tracked legal files, and selected
  license expressions are reviewed. Final Windows payload inspection
  remains a Windows release-host check.
- Linux Flatpak resolver closure: 19 third-party distributions.
- Windows resolver closure: 15 third-party distributions. This is not
  represented as an exact PyInstaller payload inventory.
- Windows also embeds the PyInstaller bootloader 6.21.0 as a manually
  inventoried build component.
- Qt/PySide6 is distributed under the selected `GPL-3.0-only` path.
- Exact Qt/PySide6 corresponding-source instructions:
  `licenses/sources/desktop-source-offer.md`.
- The 83 unique license texts from all 402 Qt 6.11.1 source archive
  `LICENSES` entries are preserved under `licenses/desktop/qt-6.11.1/`.
- Qt package-specific source attribution: 123 records and 88 referenced
  legal files under `licenses/desktop/qt-6.11.1/`. This is a conservative
  Linux source-attribution superset, not an exact wheel-build SBOM.
- The full Linux wheel also ships QtWebEngine with Chromium
  `140.0.7339.225` and Qt Multimedia with FFmpeg `7.1.3`; exact binary
  evidence is in `licenses/inventory/qt-third-party-runtime-linux-flatpak.json`.
- Chromium's 262-component credits are a conservative Linux source-tree
  superset generated without the unavailable wheel publisher GN
  dependency graph: `licenses/desktop/qt-6.11.1/qtwebengine/
  chromium-source-credits.html`.
- FFmpeg 7.1.3 attribution covers FFmpeg, libjpeg, zlib, and Boost; its
  aggregate expression and all texts are under
  `licenses/desktop/qt-6.11.1/qtmultimedia/ffmpeg/`.
- The PySide wheel publisher did not include an exact-build SBOM; the
  tracked evidence does not claim otherwise. Cryptography is separate: its
  Linux wheel ships exact OpenSSL and Rust build-provenance SBOM files under
  `licenses/desktop/cryptography-50.0.0/sboms/`; the Rust document is not
  an object-level linker map. Codec patent obligations
  can vary by format and distribution country and are not granted by Qt.
- `PAL-relaxed.hex` and `PAL-relaxed_bright.hex` from pyqtgraph are
  excluded from both supported desktop distributions because their
  license and provenance could not be confirmed.

### Runtime distributions
#### cffi 2.1.1

- Platforms: Linux
- Dependency: indirect
- Purpose: Foreign-function interface used by cryptography.
- Selected license: `MIT-0`
- Copyright/attribution: Armin Rigo, Maciej Fijalkowski and contributors
- Homepage: https://cffi.readthedocs.io/
- Source: https://github.com/python-cffi/cffi
- Local modifications: None
- Legal files: `licenses/desktop/cffi-2.1.1/licenses/LICENSE`
- Review note: No additional note.

#### colorama 0.4.6

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: Cross-platform terminal color compatibility used by pyqtgraph.
- Selected license: `BSD-3-Clause`
- Copyright/attribution: Copyright (c) 2010 Jonathan Hartley
- Homepage: https://github.com/tartley/colorama
- Source: https://github.com/tartley/colorama
- Local modifications: None
- Legal files: `licenses/desktop/colorama-0.4.6/licenses/LICENSE.txt`
- Review note: No additional note.

#### cryptography 50.0.0

- Platforms: Linux
- Dependency: indirect
- Purpose: Secret Service cryptographic transport used by keyring.
- Selected license: `BSD-3-Clause`
- Copyright/attribution: Copyright (c) Individual contributors
- Homepage: https://cryptography.io/
- Source: https://github.com/pyca/cryptography
- Local modifications: None
- Legal files: `licenses/desktop/cryptography-50.0.0/licenses/LICENSE`, `licenses/desktop/cryptography-50.0.0/licenses/LICENSE.APACHE`, `licenses/desktop/cryptography-50.0.0/licenses/LICENSE.BSD`
- Review note: The BSD-3-Clause alternative is explicitly selected; LICENSE and both upstream alternative texts are preserved.

#### et-xmlfile 2.0.0

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: Streaming XML support used by openpyxl.
- Selected license: `MIT AND Python-2.0`
- Copyright/attribution: Copyright (c) 2010 openpyxl; Python Software Foundation contributors
- Homepage: https://openpyxl.pages.heptapod.net/et_xmlfile/
- Source: https://foss.heptapod.net/openpyxl/et_xmlfile
- Local modifications: None
- Legal files: `licenses/desktop/et-xmlfile-2.0.0/AUTHORS.txt`, `licenses/desktop/et-xmlfile-2.0.0/LICENCE.python`, `licenses/desktop/et-xmlfile-2.0.0/LICENCE.rst`
- Review note: The wheel metadata says MIT, while bundled Python standard-library-derived code also requires the Python license; both originals are preserved.

#### jaraco.classes 3.4.0

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: Class helpers used by keyring.
- Selected license: `MIT`
- Copyright/attribution: Jason R. Coombs and contributors
- Homepage: https://github.com/jaraco/jaraco.classes
- Source: https://github.com/jaraco/jaraco.classes
- Local modifications: None
- Legal files: `licenses/desktop/jaraco.classes-3.4.0/LICENSE`
- Review note: No additional note.

#### jaraco.context 6.1.2

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: Context helpers used by keyring.
- Selected license: `MIT`
- Copyright/attribution: Jason R. Coombs and contributors
- Homepage: https://github.com/jaraco/jaraco.context
- Source: https://github.com/jaraco/jaraco.context
- Local modifications: None
- Legal files: `licenses/desktop/jaraco.context-6.1.2/licenses/LICENSE`
- Review note: No additional note.

#### jaraco.functools 4.6.0

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: Function helpers used by keyring.
- Selected license: `MIT`
- Copyright/attribution: Jason R. Coombs and contributors
- Homepage: https://github.com/jaraco/jaraco.functools
- Source: https://github.com/jaraco/jaraco.functools
- Local modifications: None
- Legal files: `licenses/desktop/jaraco.functools-4.6.0/licenses/LICENSE`
- Review note: No additional note.

#### jeepney 0.9.0

- Platforms: Linux
- Dependency: indirect
- Purpose: D-Bus transport used by SecretStorage.
- Selected license: `MIT`
- Copyright/attribution: Copyright (c) 2017 Thomas Kluyver
- Homepage: https://jeepney.readthedocs.io/
- Source: https://gitlab.com/takluyver/jeepney
- Local modifications: None
- Legal files: `licenses/desktop/jeepney-0.9.0/licenses/LICENSE`
- Review note: No additional note.

#### keyring 25.7.0

- Platforms: Linux, Windows
- Dependency: direct
- Purpose: Operating-system credential storage abstraction.
- Selected license: `MIT`
- Copyright/attribution: Kang Zhang and contributors
- Homepage: https://github.com/jaraco/keyring
- Source: https://github.com/jaraco/keyring
- Local modifications: None
- Legal files: `licenses/desktop/keyring-25.7.0/licenses/LICENSE`
- Review note: No additional note.

#### more-itertools 11.1.0

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: Iterator helpers used by jaraco packages.
- Selected license: `MIT`
- Copyright/attribution: Copyright (c) 2012 Erik Rose
- Homepage: https://more-itertools.readthedocs.io/
- Source: https://github.com/more-itertools/more-itertools
- Local modifications: None
- Legal files: `licenses/desktop/more-itertools-11.1.0/licenses/LICENSE`
- Review note: No additional note.

#### numpy 2.4.6

- Platforms: Linux, Windows
- Dependency: direct
- Purpose: Numerical arrays used by pyqtgraph.
- Selected license: `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`
- Copyright/attribution: Copyright (c) 2005-2025 NumPy Developers and bundled component authors
- Homepage: https://numpy.org/
- Source: https://github.com/numpy/numpy
- Local modifications: None
- Legal files: `licenses/desktop/numpy-2.4.6/licenses/LICENSE.txt`, `licenses/desktop/numpy-2.4.6/licenses/numpy/_core/include/numpy/libdivide/LICENSE.txt`, `licenses/desktop/numpy-2.4.6/licenses/numpy/_core/src/common/pythoncapi-compat/COPYING`, `licenses/desktop/numpy-2.4.6/licenses/numpy/_core/src/highway/LICENSE`, `licenses/desktop/numpy-2.4.6/licenses/numpy/_core/src/multiarray/dragon4_LICENSE.txt`, `licenses/desktop/numpy-2.4.6/licenses/numpy/_core/src/npysort/x86-simd-sort/LICENSE.md`, `licenses/desktop/numpy-2.4.6/licenses/numpy/_core/src/umath/svml/LICENSE`, `licenses/desktop/numpy-2.4.6/licenses/numpy/fft/pocketfft/LICENSE.md`, `licenses/desktop/numpy-2.4.6/licenses/numpy/linalg/lapack_lite/LICENSE.txt`, `licenses/desktop/numpy-2.4.6/licenses/numpy/ma/LICENSE`, `licenses/desktop/numpy-2.4.6/licenses/numpy/random/LICENSE.md`, `licenses/desktop/numpy-2.4.6/licenses/numpy/random/src/distributions/LICENSE.md`, `licenses/desktop/numpy-2.4.6/licenses/numpy/random/src/mt19937/LICENSE.md`, `licenses/desktop/numpy-2.4.6/licenses/numpy/random/src/pcg64/LICENSE.md`, `licenses/desktop/numpy-2.4.6/licenses/numpy/random/src/philox/LICENSE.md`, `licenses/desktop/numpy-2.4.6/licenses/numpy/random/src/sfc64/LICENSE.md`, `licenses/desktop/numpy-2.4.6/licenses/numpy/random/src/splitmix64/LICENSE.md`, `licenses/desktop/numpy-2.4.6/numpy/_core/include/numpy/random/LICENSE.txt`, `licenses/desktop/numpy-2.4.6/numpy/ma/LICENSE`, `licenses/desktop/numpy-2.4.6/numpy/random/LICENSE.md`
- Review note: All 20 legal files reported by the wheel are preserved, including bundled random generators, SIMD code, LAPACK, libdivide, and compatibility components.

#### openpyxl 3.1.5

- Platforms: Linux, Windows
- Dependency: direct
- Purpose: Spreadsheet export.
- Selected license: `MIT`
- Copyright/attribution: Copyright (c) 2010 openpyxl; Eric Gazoni, Charlie Clark and contributors
- Homepage: https://openpyxl.readthedocs.io/
- Source: https://foss.heptapod.net/openpyxl/openpyxl
- Local modifications: None
- Legal files: `licenses/desktop/openpyxl-3.1.5/AUTHORS.rst`, `licenses/desktop/openpyxl-3.1.5/LICENCE.rst`
- Review note: No additional note.

#### pycparser 3.0

- Platforms: Linux
- Dependency: indirect
- Purpose: C parser used by cffi.
- Selected license: `BSD-3-Clause`
- Copyright/attribution: Copyright (c) 2008-2022 Eli Bendersky
- Homepage: https://github.com/eliben/pycparser
- Source: https://github.com/eliben/pycparser
- Local modifications: None
- Legal files: `licenses/desktop/pycparser-3.0/licenses/LICENSE`
- Review note: No additional note.

#### pyqtgraph 0.14.0

- Platforms: Linux, Windows
- Dependency: direct
- Purpose: Interactive charts and bundled colour maps.
- Selected license: `MIT AND CC-BY-4.0 AND CC0-1.0 AND Apache-2.0`
- Copyright/attribution: Copyright (c) 2012 University of North Carolina at Chapel Hill and Luke Campagnola; Peter Kovesi/ColorCET; Anton Mikhailov et al.
- Homepage: https://www.pyqtgraph.org/
- Source: https://github.com/pyqtgraph/pyqtgraph
- Local modifications: None
- Legal files: `licenses/desktop/pyqtgraph-0.14.0/Apache-2.0.txt`, `licenses/desktop/pyqtgraph-0.14.0/COLORCET-ATTRIBUTION.txt`, `licenses/desktop/pyqtgraph-0.14.0/colors/maps/CC-BY license - applies to CET color map data.txt`, `licenses/desktop/pyqtgraph-0.14.0/colors/maps/CC0 legal code - applies to virids, magma, plasma, inferno and cividis.txt`, `licenses/desktop/pyqtgraph-0.14.0/colors/maps/turbo.csv`, `licenses/desktop/pyqtgraph-0.14.0/licenses/LICENSE.txt`
- Review note: MIT code, CC-BY-4.0 CET maps, CC0 maps, and Apache-2.0 turbo are preserved. PAL-relaxed files are excluded from both supported desktop distributions because their license and provenance could not be confirmed.

#### PySide6 6.11.1

- Platforms: Linux, Windows
- Dependency: direct
- Purpose: Qt for Python metapackage.
- Selected license: `GPL-3.0-only`
- Copyright/attribution: Copyright (c) The Qt Company Ltd. and Qt contributors
- Homepage: https://pyside.org/
- Source: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Local modifications: None
- Legal files: `licenses/desktop/qt-for-python-6.11.1/LICENSES/Apache-2.0.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/BSD-3-Clause.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GFDL-1.3-no-invariants-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GPL-2.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/LGPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/Qt-GPL-exception-1.0.txt`, `licenses/desktop/qt-for-python-6.11.1/sources/pyside6/COPYING`, `licenses/desktop/qt-for-python-6.11.1/sources/pyside6/PySide6/licensecomment.txt`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/AUTHORS`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING.libsample`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING.libshiboken`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/libshiboken/embed/qt_python_license.txt`
- Review note: The GPL-3.0-only alternative is explicitly selected.

#### PySide6-Addons 6.11.1

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: Full Qt add-on modules and binaries installed by PySide6.
- Selected license: `GPL-3.0-only`
- Copyright/attribution: Copyright (c) The Qt Company Ltd. and Qt contributors
- Homepage: https://pyside.org/
- Source: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Local modifications: None
- Legal files: `licenses/desktop/qt-for-python-6.11.1/LICENSES/Apache-2.0.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/BSD-3-Clause.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GFDL-1.3-no-invariants-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GPL-2.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/LGPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/Qt-GPL-exception-1.0.txt`, `licenses/desktop/qt-for-python-6.11.1/sources/pyside6/COPYING`, `licenses/desktop/qt-for-python-6.11.1/sources/pyside6/PySide6/licensecomment.txt`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/AUTHORS`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING.libsample`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING.libshiboken`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/libshiboken/embed/qt_python_license.txt`
- Review note: The full wheel is retained. It can contain modules that are GPL-only under open-source distribution; these are not hidden or pruned.

#### PySide6-Essentials 6.11.1

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: Qt Core/Gui/Widgets/Svg and other essential Qt binaries.
- Selected license: `GPL-3.0-only`
- Copyright/attribution: Copyright (c) The Qt Company Ltd. and Qt contributors
- Homepage: https://pyside.org/
- Source: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Local modifications: None
- Legal files: `licenses/desktop/qt-for-python-6.11.1/LICENSES/Apache-2.0.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/BSD-3-Clause.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GFDL-1.3-no-invariants-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GPL-2.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/LGPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/Qt-GPL-exception-1.0.txt`, `licenses/desktop/qt-for-python-6.11.1/sources/pyside6/COPYING`, `licenses/desktop/qt-for-python-6.11.1/sources/pyside6/PySide6/licensecomment.txt`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/AUTHORS`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING.libsample`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING.libshiboken`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/libshiboken/embed/qt_python_license.txt`
- Review note: No additional note.

#### pywin32-ctypes 0.2.3

- Platforms: Windows
- Dependency: indirect
- Purpose: Windows credential API adapter used by keyring.
- Selected license: `BSD-3-Clause`
- Copyright/attribution: Copyright (c) 2014 Enthought, Inc.
- Homepage: https://github.com/enthought/pywin32-ctypes
- Source: https://github.com/enthought/pywin32-ctypes
- Local modifications: None
- Legal files: `licenses/desktop/pywin32-ctypes-0.2.3/LICENSE.txt`
- Review note: No additional note.

#### SecretStorage 3.5.0

- Platforms: Linux
- Dependency: indirect
- Purpose: Linux Secret Service backend used by keyring.
- Selected license: `BSD-3-Clause`
- Copyright/attribution: Copyright 2012-2025 Dmitry Shachnev
- Homepage: https://secretstorage.readthedocs.io/
- Source: https://github.com/mitya57/secretstorage
- Local modifications: None
- Legal files: `licenses/desktop/secretstorage-3.5.0/licenses/LICENSE`
- Review note: No additional note.

#### shiboken6 6.11.1

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: Python/C++ binding runtime required by PySide6.
- Selected license: `GPL-3.0-only`
- Copyright/attribution: Copyright (c) The Qt Company Ltd. and Shiboken contributors
- Homepage: https://doc.qt.io/qtforpython/
- Source: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Local modifications: None
- Legal files: `licenses/desktop/qt-for-python-6.11.1/LICENSES/Apache-2.0.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/BSD-3-Clause.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GFDL-1.3-no-invariants-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GPL-2.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/GPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/LGPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.11.1/LICENSES/Qt-GPL-exception-1.0.txt`, `licenses/desktop/qt-for-python-6.11.1/sources/pyside6/COPYING`, `licenses/desktop/qt-for-python-6.11.1/sources/pyside6/PySide6/licensecomment.txt`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/AUTHORS`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING.libsample`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/COPYING.libshiboken`, `licenses/desktop/qt-for-python-6.11.1/sources/shiboken6/libshiboken/embed/qt_python_license.txt`
- Review note: No additional note.

### Additional distributed components

#### PyInstaller bootloader 6.21.0

- Platforms: Windows
- Purpose: Compiled bootloader embedded in the Windows executable by PyInstaller.
- License: `GPL-2.0-or-later WITH Bootloader-exception`
- Copyright: Copyright (c) 2010-2023 PyInstaller Development Team; prior authors listed in COPYING.txt
- Source: https://github.com/pyinstaller/pyinstaller
- Legal files: `licenses/desktop/pyinstaller-6.21.0/licenses/COPYING.txt`
- Review note: Manually inventoried because the bootloader is a distributed build component, not a runtime dependency edge in uv tree.

#### NumPy Linux OpenBLAS and LAPACK 2.4.6 wheel bundle

- Platforms: Linux
- Purpose: Shared numerical library bundled in numpy.libs/libscipy_openblas64_-32a4b2a6.so.
- License: `BSD-3-Clause AND BSD-3-Clause-Open-MPI`
- Copyright: Copyright (c) 2011-2014 The OpenBLAS Project; LAPACK contributors listed in NumPy LICENSE.txt
- Source: https://github.com/OpenMathLib/OpenBLAS/
- Legal files: `licenses/desktop/numpy-2.4.6/licenses/LICENSE.txt`
- Review note: Known limitation: The exact OpenBLAS revision is not disclosed by the wheel; the retained NumPy LICENSE.txt identifies the bundled binary and notices.

#### GNU libgfortran runtime from NumPy Linux wheel 5.0.0 (wheel file)

- Platforms: Linux
- Purpose: Shared runtime library bundled as numpy.libs/libgfortran-040039e1-0352e75f.so.5.0.0.
- License: `GPL-3.0-or-later WITH GCC-exception-3.1`
- Copyright: Copyright (C) 2002-2017 Free Software Foundation, Inc.
- Source: https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libgfortran
- Legal files: `licenses/desktop/numpy-2.4.6/licenses/LICENSE.txt`
- Review note: Known limitation: The exact GCC revision is not disclosed by the wheel; the retained NumPy LICENSE.txt identifies the bundled runtime and notices.

#### GNU libquadmath runtime from NumPy Linux wheel 0.0.0 (wheel file)

- Platforms: Linux
- Purpose: Shared runtime library bundled as numpy.libs/libquadmath-96973f99-934c22de.so.0.0.0.
- License: `LGPL-2.1-or-later`
- Copyright: Copyright (C) 2010-2019 Free Software Foundation, Inc.
- Source: https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libquadmath
- Legal files: `licenses/desktop/numpy-2.4.6/licenses/LICENSE.txt`
- Review note: Known limitation: The exact GCC revision is not disclosed by the wheel; the retained NumPy LICENSE.txt identifies the bundled runtime and notices.

#### OpenSSL embedded in cryptography Linux wheel 4.0.1

- Platforms: Linux
- Purpose: Statically built into cryptography _rust.abi3.so according to the wheel SBOM (no-shared).
- License: `Apache-2.0`
- Copyright: Copyright 1998-2026 The OpenSSL Project Authors. All Rights Reserved.
- Source: https://github.com/openssl/openssl
- Legal files: `licenses/desktop/cryptography-50.0.0/licenses/LICENSE.APACHE`
- Review note: Exact source URL, SHA256 and build flags are validated from the wheel SBOM.
<!-- END GENERATED DESKTOP THIRD-PARTY NOTICES -->

<!-- BEGIN GENERATED WEB THIRD-PARTY NOTICES -->
## Web production distribution

This section summarizes the reviewed Vite browser bundle, PWA registration
helper, and generated Workbox service worker inventory. The complete plain-text
notice is published as `web/public/third-party-notices.txt` and deployed at
`/third-party-notices.txt`.

- Runtime package count: 21.
- Reviewed runtime license expressions: `MIT`, `0BSD`.
- Package-specific originals: `web/public/licenses/`.
- Actual bundle evidence is checked from temporary Vite production sourcemaps.
- Sharp/libvips and other icon-generation, build, test, lint, and deploy tools
  are excluded because they are not present in the production browser or
  service-worker runtime.

### Web runtime packages

- **@supabase/auth-js 2.112.3** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/auth-js/LICENSE`
- **@supabase/functions-js 2.112.3** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/functions-js/LICENSE`
- **@supabase/phoenix 0.4.5** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/phoenix/LICENSE.md`
- **@supabase/postgrest-js 2.112.3** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/postgrest-js/LICENSE`
- **@supabase/realtime-js 2.112.3** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/realtime-js/LICENSE`
- **@supabase/storage-js 2.112.3** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/storage-js/LICENSE`
- **@supabase/supabase-js 2.112.3** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/supabase-js/LICENSE`
- **iceberg-js 0.8.1** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/iceberg-js/LICENSE`
- **react 18.3.1** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/react/LICENSE`
- **react-dom 18.3.1** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/react-dom/LICENSE`
- **react-router 7.18.2** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/react-router/LICENSE.md`
- **react-router-dom 7.18.2** — `MIT`; evidence: `tree-shaken-facade`; legal files: `web/public/licenses/react-router-dom/LICENSE.md`
- **scheduler 0.23.2** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/scheduler/LICENSE`
- **tslib 2.8.1** — `0BSD`; evidence: `main-sourcemap`; legal files: `web/public/licenses/tslib/LICENSE.txt`
- **vite 6.4.3** — `MIT`; evidence: `vite-generated-helper`; legal files: `web/public/licenses/vite/LICENSE.md`
- **vite-plugin-pwa 1.3.0** — `MIT`; evidence: `pwa-virtual-module`; legal files: `web/public/licenses/vite-plugin-pwa/LICENSE`
- **workbox-core 7.4.1** — `MIT`; evidence: `service-worker-sourcemap`; legal files: `web/public/licenses/workbox-core/LICENSE`
- **workbox-precaching 7.4.1** — `MIT`; evidence: `service-worker-sourcemap`; legal files: `web/public/licenses/workbox-precaching/LICENSE`
- **workbox-routing 7.4.1** — `MIT`; evidence: `service-worker-sourcemap`; legal files: `web/public/licenses/workbox-routing/LICENSE`
- **workbox-strategies 7.4.1** — `MIT`; evidence: `service-worker-sourcemap`; legal files: `web/public/licenses/workbox-strategies/LICENSE`
- **workbox-window 7.4.1** — `MIT`; evidence: `pwa-window-sourcemap`; legal files: `web/public/licenses/workbox-window/LICENSE`
<!-- END GENERATED WEB THIRD-PARTY NOTICES -->
