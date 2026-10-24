# Open-Source Notices

## MDLogger

- Copyright: Copyright (C) 2026 dusten45 (노연우)
- License: `GPL-3.0-or-later` (`LICENSE`)
- Source: https://github.com/dusten45/MDLogger

MDLogger is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See `LICENSE` for the full license text.

Generated platform sections are delimited so desktop and web inventories can be maintained independently.

<!-- BEGIN GENERATED DESKTOP THIRD-PARTY NOTICES -->
## Desktop distributions

This section is generated from `uv.lock` and the manually reviewed
`scripts/desktop_license_policy.json`. It covers the supported Linux
Flatpak and Windows PyInstaller/Inno Setup distributions.

- Review status: lockfile closures, tracked legal files, and selected
  license expressions are reviewed. Final Windows payload inspection
  remains a Windows release-host check.
- Linux Flatpak resolver closure: 17 third-party distributions (Python 3.14).
- Windows resolver closure: 16 third-party distributions (Python 3.15). This is not
  represented as an exact PyInstaller payload inventory.
- Windows also inventories the uv-managed CPython runtime and standard library
  (python-build-standalone; exact vendor evidence is retained),
  PyInstaller bootloader and runtime hooks,
  pyinstaller-hooks-contrib runtime hooks, NumPy Windows OpenBLAS/LAPACK
  and libgfortran, Qt Windows D3D12MemoryAllocator and Wintab, and the
  Inno Setup 6 loader/uninstaller.
- Qt/PySide6 is distributed under the selected `GPL-3.0-only` path.
- Exact Qt/PySide6 corresponding-source instructions:
  `licenses/sources/desktop-source-offer.md`.
- Qt license corpus: 69 unique source texts; manifest `licenses/desktop/qt-6.12.0/LICENSES-MANIFEST.json`.
- Qt package-specific source attribution: 98 records and 61 referenced legal files.
  This is a conservative Essentials source-attribution superset (which also covers cross-platform
  QtCore/QtGui/QtWidgets/QtSvg third-party code on Windows), not an exact
  wheel-build SBOM.
- Only PySide6-Essentials and shiboken6 are installed. Addons, WebEngine,
  Pdf, Multimedia, Chromium and FFmpeg are absent. Every Essentials ELF
  binary is inventoried in `licenses/inventory/qt-third-party-runtime-linux-flatpak.json`.
- The PySide wheel publisher did not include an exact-build SBOM; the
  tracked evidence does not claim otherwise. Cryptography is separate: its
  Linux wheel ships exact OpenSSL and Rust build-provenance SBOM files under
  `licenses/desktop/cryptography-50.0.2/sboms/`; the Rust document is not
  an object-level linker map. These are Python 3.14 Flatpak wheel bytes,
  not Python 3.15 or Windows binary evidence.
- `PAL-relaxed.hex` and `PAL-relaxed_bright.hex` from pyqtgraph are
  excluded from both supported desktop distributions because their
  license and provenance could not be confirmed; `opengl32sw.dll`,
  `qpdf.dll`, and `Qt6Pdf.dll` are excluded from the Windows PyInstaller
  bundle.

### Runtime distributions
#### cffi 2.1.1

- Platforms: Linux, Windows
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

#### cryptography 50.0.2

- Platforms: Linux, Windows
- Dependency: direct
- Purpose: RSA update-manifest signature verification on Windows and Secret Service cryptographic transport used by keyring on Linux.
- Selected license: `BSD-3-Clause`
- Copyright/attribution: Copyright (c) Individual contributors
- Homepage: https://cryptography.io/
- Source: https://github.com/pyca/cryptography
- Local modifications: None
- Legal files: `licenses/desktop/cryptography-50.0.2/licenses/LICENSE`, `licenses/desktop/cryptography-50.0.2/licenses/LICENSE.APACHE`, `licenses/desktop/cryptography-50.0.2/licenses/LICENSE.BSD`
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

#### more-itertools 11.2.1

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: Iterator helpers used by jaraco packages.
- Selected license: `MIT`
- Copyright/attribution: Copyright (c) 2012 Erik Rose
- Homepage: https://more-itertools.readthedocs.io/
- Source: https://github.com/more-itertools/more-itertools
- Local modifications: None
- Legal files: `licenses/desktop/more-itertools-11.2.1/licenses/LICENSE`
- Review note: No additional note.

#### numpy 2.5.4

- Platforms: Linux, Windows
- Dependency: direct
- Purpose: Numerical arrays used by pyqtgraph.
- Selected license: `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`
- Copyright/attribution: Copyright (c) 2005-2025 NumPy Developers and bundled component authors
- Homepage: https://numpy.org/
- Source: https://github.com/numpy/numpy
- Local modifications: None
- Legal files: `licenses/desktop/numpy-2.5.4/licenses/LICENSE-windows.txt`, `licenses/desktop/numpy-2.5.4/licenses/LICENSE.txt`, `licenses/desktop/numpy-2.5.4/licenses/numpy/_core/include/numpy/libdivide/LICENSE.txt`, `licenses/desktop/numpy-2.5.4/licenses/numpy/_core/src/common/pythoncapi-compat/COPYING`, `licenses/desktop/numpy-2.5.4/licenses/numpy/_core/src/highway/LICENSE`, `licenses/desktop/numpy-2.5.4/licenses/numpy/_core/src/multiarray/dragon4_LICENSE.txt`, `licenses/desktop/numpy-2.5.4/licenses/numpy/_core/src/npysort/x86-simd-sort/LICENSE.md`, `licenses/desktop/numpy-2.5.4/licenses/numpy/_core/src/umath/svml/LICENSE`, `licenses/desktop/numpy-2.5.4/licenses/numpy/fft/pocketfft/LICENSE.md`, `licenses/desktop/numpy-2.5.4/licenses/numpy/linalg/lapack_lite/LICENSE.txt`, `licenses/desktop/numpy-2.5.4/licenses/numpy/ma/LICENSE`, `licenses/desktop/numpy-2.5.4/licenses/numpy/random/LICENSE.md`, `licenses/desktop/numpy-2.5.4/licenses/numpy/random/src/distributions/LICENSE.md`, `licenses/desktop/numpy-2.5.4/licenses/numpy/random/src/mt19937/LICENSE.md`, `licenses/desktop/numpy-2.5.4/licenses/numpy/random/src/pcg64/LICENSE.md`, `licenses/desktop/numpy-2.5.4/licenses/numpy/random/src/philox/LICENSE.md`, `licenses/desktop/numpy-2.5.4/licenses/numpy/random/src/sfc64/LICENSE.md`, `licenses/desktop/numpy-2.5.4/licenses/numpy/random/src/splitmix64/LICENSE.md`, `licenses/desktop/numpy-2.5.4/numpy/_core/include/numpy/random/LICENSE.txt`, `licenses/desktop/numpy-2.5.4/numpy/ma/LICENSE`, `licenses/desktop/numpy-2.5.4/numpy/random/LICENSE.md`
- Review note: All legal files declared by the Linux wheel and the platform-specific Windows native-runtime notice are preserved.

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

#### pycparser 3.12

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: C parser used by cffi.
- Selected license: `BSD-3-Clause`
- Copyright/attribution: Copyright (c) 2008-2022 Eli Bendersky
- Homepage: https://github.com/eliben/pycparser
- Source: https://github.com/eliben/pycparser
- Local modifications: None
- Legal files: `licenses/desktop/pycparser-3.12/licenses/LICENSE`
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

#### PySide6-Essentials 6.12.0

- Platforms: Linux, Windows
- Dependency: direct
- Purpose: Qt Core/Gui/Widgets/Svg and other essential Qt binaries.
- Selected license: `GPL-3.0-only`
- Copyright/attribution: Copyright (c) The Qt Company Ltd. and Qt contributors
- Homepage: https://pyside.org/
- Source: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Local modifications: None
- Legal files: `licenses/desktop/pyside6-essentials-6.12.0/windows/licenses/LicenseRef-Qt-Commercial.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/Apache-2.0.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/BSD-3-Clause.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/GFDL-1.3-no-invariants-only.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/GPL-2.0-only.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/GPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/LGPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/LicenseRef-Qt-Commercial.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/Qt-GPL-exception-1.0.txt`, `licenses/desktop/qt-for-python-6.12.0/sources/pyside6/COPYING`, `licenses/desktop/qt-for-python-6.12.0/sources/pyside6/PySide6/licensecomment.txt`, `licenses/desktop/qt-for-python-6.12.0/sources/shiboken6/AUTHORS`, `licenses/desktop/qt-for-python-6.12.0/sources/shiboken6/COPYING`, `licenses/desktop/qt-for-python-6.12.0/sources/shiboken6/COPYING.libsample`, `licenses/desktop/qt-for-python-6.12.0/sources/shiboken6/COPYING.libshiboken`
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

#### shiboken6 6.12.0

- Platforms: Linux, Windows
- Dependency: indirect
- Purpose: Python/C++ binding runtime required by PySide6.
- Selected license: `GPL-3.0-only`
- Copyright/attribution: Copyright (c) The Qt Company Ltd. and Shiboken contributors
- Homepage: https://doc.qt.io/qtforpython/
- Source: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Local modifications: None
- Legal files: `licenses/desktop/qt-for-python-6.12.0/LICENSES/Apache-2.0.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/BSD-3-Clause.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/GFDL-1.3-no-invariants-only.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/GPL-2.0-only.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/GPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/LGPL-3.0-only.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/LicenseRef-Qt-Commercial.txt`, `licenses/desktop/qt-for-python-6.12.0/LICENSES/Qt-GPL-exception-1.0.txt`, `licenses/desktop/qt-for-python-6.12.0/sources/pyside6/COPYING`, `licenses/desktop/qt-for-python-6.12.0/sources/pyside6/PySide6/licensecomment.txt`, `licenses/desktop/qt-for-python-6.12.0/sources/shiboken6/AUTHORS`, `licenses/desktop/qt-for-python-6.12.0/sources/shiboken6/COPYING`, `licenses/desktop/qt-for-python-6.12.0/sources/shiboken6/COPYING.libsample`, `licenses/desktop/qt-for-python-6.12.0/sources/shiboken6/COPYING.libshiboken`, `licenses/desktop/shiboken6-6.12.0/windows/licenses/LicenseRef-Qt-Commercial.txt`
- Review note: No additional note.

### Additional distributed components

#### ICU Unicode libraries from Qt Linux wheel 73.2

- Platforms: Linux
- Purpose: libicudata.so.73, libicui18n.so.73 and libicuuc.so.73 bundled by PySide6-Essentials; runtime version verified using u_getVersion_73.
- License: `Unicode-DFS-2016 AND ICU AND BSD-2-Clause AND BSD-3-Clause AND NAIST-2003 AND LicenseRef-IANA-TZ-Public-Domain`
- Copyright: Copyright 1991-2023 Unicode, Inc.; International Business Machines Corporation and dictionary/data authors named in the retained ICU license.
- Source: https://github.com/unicode-org/icu/tree/release-73-2
- Legal files: `licenses/desktop/icu-73.2/LICENSE`
- Review note: Exact release-73-2 license and supplemental notices retained, including dictionaries and public-domain time-zone data. Autoconf helper notices also occur in the source license but are not distributed runtime code. This older ICU is bundled by the latest Qt wheel; it is not independently substituted across its native ABI. No exact publisher build SBOM is claimed.

#### PyInstaller bootloader 6.22.3

- Platforms: Windows
- Purpose: Compiled bootloader, Python loader modules, and PyInstaller runtime hooks (pyi_rth_*.py, _pyi_rth_utils) embedded in the Windows executable by PyInstaller.
- License: `GPL-2.0-or-later WITH Bootloader-exception AND Apache-2.0`
- Copyright: Copyright (c) 2010-2023 PyInstaller Development Team; prior authors listed in COPYING.txt
- Source: https://github.com/pyinstaller/pyinstaller
- Legal files: `licenses/desktop/pyinstaller-6.22.3/licenses/COPYING.txt`
- Review note: Manually inventoried because the bootloader (GPL-2.0-or-later WITH Bootloader-exception) and embedded runtime hooks (Apache-2.0) are distributed build components, not runtime dependency edges in uv tree.

#### pyinstaller-hooks-contrib runtime hooks 2026.9

- Platforms: Windows
- Purpose: Community runtime hook (pyi_rth_pyqtgraph_multiprocess.py) embedded in the Windows executable by PyInstaller.
- License: `Apache-2.0`
- Copyright: Copyright (c) 2020-2026 PyInstaller Development Team
- Source: https://github.com/pyinstaller/pyinstaller-hooks-contrib
- Legal files: `licenses/desktop/pyinstaller-hooks-contrib-2026.9/licenses/LICENSE`
- Review note: Runtime hooks in _pyinstaller_hooks_contrib/rthooks/ are licensed under Apache-2.0 per upstream LICENSE.

#### NumPy Linux OpenBLAS and LAPACK 2.5.4 wheel bundle

- Platforms: Linux
- Purpose: Shared numerical library bundled in numpy.libs/libscipy_openblas64_-f48b354e.so.
- License: `BSD-3-Clause AND BSD-3-Clause-Open-MPI`
- Copyright: Copyright (c) 2011-2014 The OpenBLAS Project; LAPACK contributors listed in NumPy LICENSE.txt
- Source: https://github.com/OpenMathLib/OpenBLAS/
- Legal files: `licenses/desktop/numpy-2.5.4/licenses/LICENSE.txt`
- Review note: Known limitation: The exact OpenBLAS revision is not disclosed by the wheel; the retained NumPy LICENSE.txt identifies the bundled binary and notices.

#### GNU libgfortran runtime from NumPy Linux wheel 5.0.0 (wheel file)

- Platforms: Linux
- Purpose: Shared runtime library bundled as numpy.libs/libgfortran-83c28eba-468e71e5.so.5.0.0.
- License: `GPL-3.0-or-later WITH GCC-exception-3.1`
- Copyright: Copyright (C) 2002-2017 Free Software Foundation, Inc.
- Source: https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libgfortran
- Legal files: `licenses/desktop/numpy-2.5.4/licenses/LICENSE.txt`
- Review note: Known limitation: The exact GCC revision is not disclosed by the wheel; the retained NumPy LICENSE.txt identifies the bundled runtime and notices.

#### GNU libquadmath runtime from NumPy Linux wheel 0.0.0 (wheel file)

- Platforms: Linux
- Purpose: Shared runtime library bundled as numpy.libs/libquadmath-2284e583-a9307bba.so.0.0.0.
- License: `LGPL-2.1-or-later`
- Copyright: Copyright (C) 2010-2019 Free Software Foundation, Inc.
- Source: https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libquadmath
- Legal files: `licenses/desktop/numpy-2.5.4/licenses/LICENSE.txt`
- Review note: Known limitation: The exact GCC revision is not disclosed by the wheel; the retained NumPy LICENSE.txt identifies the bundled runtime and notices.

#### OpenSSL embedded in cryptography wheels 4.0.3

- Platforms: Linux, Windows
- Purpose: Cryptographic primitives bundled with cryptography, including Windows update signature verification. Linux static linkage is recorded in its wheel SBOM.
- License: `Apache-2.0`
- Copyright: Copyright 1998-2026 The OpenSSL Project Authors. All Rights Reserved.
- Source: https://github.com/openssl/openssl
- Legal files: `licenses/desktop/cryptography-50.0.2/licenses/LICENSE.APACHE`
- Review note: Exact source URL, SHA256 and build flags are validated from the Linux wheel SBOM. This is not Windows build-provenance evidence; the Windows release gate checks the loaded OpenSSL version separately.

#### NumPy Windows OpenBLAS and LAPACK 2.5.4 wheel bundle

- Platforms: Windows
- Purpose: Shared numerical library bundled in numpy.libs/libscipy_openblas64_*.dll in the locked Windows wheel.
- License: `BSD-3-Clause AND BSD-3-Clause-Open-MPI`
- Copyright: Copyright (c) 2011-2014 The OpenBLAS Project; LAPACK contributors listed in NumPy LICENSE-windows.txt
- Source: https://github.com/OpenMathLib/OpenBLAS/
- Legal files: `licenses/desktop/numpy-2.5.4/licenses/LICENSE-windows.txt`
- Review note: Known limitation: The exact OpenBLAS revision is not disclosed by the Windows wheel; the retained NumPy LICENSE-windows.txt identifies the bundled binary and notices.

#### GNU libgfortran runtime from NumPy Windows wheel 2.5.4 wheel bundle

- Platforms: Windows
- Purpose: GCC runtime library statically linked into numpy.libs/libscipy_openblas64_*.dll in the locked Windows wheel.
- License: `GPL-3.0-or-later WITH GCC-exception-3.1`
- Copyright: Copyright (C) 2009 Free Software Foundation, Inc.
- Source: https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=libgfortran
- Legal files: `licenses/desktop/numpy-2.5.4/licenses/LICENSE-windows.txt`
- Review note: Known limitation: The exact GCC revision is not disclosed by the Windows wheel; the retained NumPy LICENSE-windows.txt identifies the statically linked runtime and GCC Runtime Library Exception 3.1 notices.

#### CPython runtime and standard library 3.15.1 (python-build-standalone 20261021)

- Platforms: Windows
- Purpose: uv-managed Windows CPython 3.15.1 interpreter, standard library, Microsoft Visual C++ Distributable Code and bundled native libraries, including zstd added in Python 3.14. The matching vendor PYTHON.json describes build inputs; the Windows PyInstaller TOC remains the final payload authority.
- License: `PSF-2.0 AND 0BSD AND Apache-2.0 AND MIT AND BSD-2-Clause AND BSD-3-Clause AND Zlib AND bzip2-1.0.6 AND blessing AND CC0-1.0 AND LicenseRef-Microsoft-Distributable-Code`
- Copyright: Python Software Foundation, Microsoft Corporation, and third-party authors identified in the retained vendor and CPython license originals.
- Source: https://github.com/python/cpython
- Legal files: `licenses/desktop/cpython-3.15.1/Doc-license.rst`, `licenses/desktop/cpython-3.15.1/LICENSE.txt`, `licenses/desktop/cpython-3.15.1/licenses/LICENSE.bzip2.txt`, `licenses/desktop/cpython-3.15.1/licenses/LICENSE.cpython.txt`, `licenses/desktop/cpython-3.15.1/licenses/LICENSE.expat.txt`, `licenses/desktop/cpython-3.15.1/licenses/LICENSE.libffi.txt`, `licenses/desktop/cpython-3.15.1/licenses/LICENSE.liblzma.txt`, `licenses/desktop/cpython-3.15.1/licenses/LICENSE.mpdecimal.txt`, `licenses/desktop/cpython-3.15.1/licenses/LICENSE.openssl-3.txt`, `licenses/desktop/cpython-3.15.1/licenses/LICENSE.sqlite.txt`, `licenses/desktop/cpython-3.15.1/licenses/LICENSE.zlib-ng.txt`, `licenses/desktop/cpython-3.15.1/licenses/LICENSE.zlib.txt`, `licenses/desktop/cpython-3.15.1/licenses/LICENSE.zstd.txt`, `licenses/desktop/cpython-3.15.1/PYTHON.json`, `licenses/desktop/cpython-3.15.1/VENDOR-MANIFEST.json`
- Review note: Originals extracted from verified python-build-standalone 20261021 Windows install-only and matching pgo-full archives, plus CPython v3.15.1 Doc/license.rst. These are not python.org installer SPDX evidence. tkinter is excluded from the app bundle; unrelated vendor license files and pip build-tool notices are not represented as runtime components.

#### Qt Windows D3D12 Memory Allocator 6.12.0

- Platforms: Windows
- Purpose: Direct3D 12 memory allocation library bundled in QtGui on Windows.
- License: `MIT`
- Copyright: Copyright (c) 2019-2026 Advanced Micro Devices, Inc. All rights reserved.
- Source: https://github.com/GPUOpen-LibrariesAndSDKs/D3D12MemoryAllocator
- Legal files: `licenses/desktop/qt-6.12.0/windows-3rdparty/D3D12MemoryAllocator/LICENSE.txt`
- Review note: Windows-specific Qt 6.12.0 qtbase third-party component; opengl32sw.dll (Mesa/LLVM) and qpdf.dll/Qt6Pdf.dll are explicitly excluded in MDLogger.spec.

#### Qt Windows Wintab API 6.12.0

- Platforms: Windows
- Purpose: Wintab tablet interface headers used by the Qt Windows QPA plugin.
- License: `LicenseRef-Lcs-Telegraphics`
- Copyright: Copyright (c) 1991-1998 by LCS/Telegraphics.
- Source: https://download.qt.io/official_releases/qt/6.12/6.12.0/single/qt-everywhere-src-6.12.0.tar.xz
- Legal files: `licenses/desktop/qt-6.12.0/LICENSES/LicenseRef-Lcs-Telegraphics.txt`
- Review note: Windows-specific Qt 6.12.0 qtbase third-party component.

#### Inno Setup runtime loader and uninstaller 6

- Platforms: Windows
- Purpose: Installer stub and uninstaller (unins000.exe) embedded in MDLogger-Setup.exe by Inno Setup 6.
- License: `LicenseRef-Inno-Setup`
- Copyright: Copyright (C) 1997-2026 Jordan Russell. All rights reserved. Portions Copyright (C) 2000-2026 Martijn Laan. All rights reserved.
- Source: https://github.com/jrsoftware/issrc
- Legal files: `licenses/desktop/innosetup-6/LICENSE.txt`
- Review note: Reviewed permissive BSD-style Inno Setup license covering the setup loader and uninstaller.
<!-- END GENERATED DESKTOP THIRD-PARTY NOTICES -->

<!-- BEGIN GENERATED WEB THIRD-PARTY NOTICES -->
## Web production distribution

This section summarizes the reviewed Vite browser bundle, PWA registration
helper, and generated Workbox service worker inventory. The complete plain-text
notice is published as `web/public/third-party-notices.txt` and deployed at
`/third-party-notices.txt`.

- Runtime package count: 22.
- Reviewed runtime license expressions: `MIT`, `0BSD`.
- Package-specific originals: `web/public/licenses/`.
- Actual bundle evidence is checked from temporary Vite production sourcemaps.
- Sharp/libvips and other icon-generation, build, test, lint, and deploy tools
  are excluded because they are not present in the production browser or
  service-worker runtime.

### Web runtime packages

- **@supabase/auth-js 2.118.0** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/auth-js/LICENSE`
- **@supabase/functions-js 2.118.0** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/functions-js/LICENSE`
- **@supabase/phoenix 0.4.5** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/phoenix/LICENSE.md`
- **@supabase/postgrest-js 2.118.0** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/postgrest-js/LICENSE`
- **@supabase/realtime-js 2.118.0** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/realtime-js/LICENSE`
- **@supabase/storage-js 2.118.0** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/storage-js/LICENSE`
- **@supabase/supabase-js 2.118.0** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/@supabase/supabase-js/LICENSE`
- **iceberg-js 0.8.1** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/iceberg-js/LICENSE`
- **react 19.3.1** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/react/LICENSE`
- **react-dom 19.3.1** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/react-dom/LICENSE`
- **react-router 7.18.4** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/react-router/LICENSE.md`
- **react-router-dom 7.18.4** — `MIT`; evidence: `tree-shaken-facade`; legal files: `web/public/licenses/react-router-dom/LICENSE.md`
- **rolldown 1.2.15** — `MIT`; evidence: `rolldown-generated-helper`; legal files: `web/public/licenses/rolldown/LICENSE`, `web/public/licenses/rolldown/THIRD-PARTY-LICENSE`
- **scheduler 0.28.0** — `MIT`; evidence: `main-sourcemap`; legal files: `web/public/licenses/scheduler/LICENSE`
- **tslib 2.8.1** — `0BSD`; evidence: `main-sourcemap`; legal files: `web/public/licenses/tslib/LICENSE.txt`
- **vite 8.3.5** — `MIT`; evidence: `vite-generated-helper`; legal files: `web/public/licenses/vite/LICENSE.md`
- **vite-plugin-pwa 2.0.0** — `MIT`; evidence: `pwa-virtual-module`; legal files: `web/public/licenses/vite-plugin-pwa/LICENSE`
- **workbox-core 7.4.1** — `MIT`; evidence: `service-worker-sourcemap`; legal files: `web/public/licenses/workbox-core/LICENSE`
- **workbox-precaching 7.4.1** — `MIT`; evidence: `service-worker-sourcemap`; legal files: `web/public/licenses/workbox-precaching/LICENSE`
- **workbox-routing 7.4.1** — `MIT`; evidence: `service-worker-sourcemap`; legal files: `web/public/licenses/workbox-routing/LICENSE`
- **workbox-strategies 7.4.1** — `MIT`; evidence: `service-worker-sourcemap`; legal files: `web/public/licenses/workbox-strategies/LICENSE`
- **workbox-window 7.4.1** — `MIT`; evidence: `pwa-window-sourcemap`; legal files: `web/public/licenses/workbox-window/LICENSE`
<!-- END GENERATED WEB THIRD-PARTY NOTICES -->
