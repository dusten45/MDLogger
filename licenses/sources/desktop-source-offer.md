# Desktop corresponding-source information

This document records the exact upstream source archives corresponding to the
Qt/PySide6 6.11.1 binaries distributed by MDLogger. MDLogger selects the
**GPL-3.0-only** alternative for PySide6, PySide6-Essentials,
PySide6-Addons, shiboken6, and the bundled Qt libraries.

MDLogger has not modified Qt, PySide6, shiboken6, or their build system. The
archives below are the upstream source releases matching the distributed
6.11.1 wheels. For every published desktop or web release, the MDLogger source
and packaging files must be archived from the exact release commit in
<https://github.com/dusten45/MDLogger>, recorded with its commit identifier and
SHA256, and published beside that release's binary or static assets.

## Qt 6.11.1 source

- Archive: `qt-everywhere-src-6.11.1.tar.xz`
- Official URL: <https://download.qt.io/official_releases/qt/6.11/6.11.1/single/qt-everywhere-src-6.11.1.tar.xz>
- Official MirrorBrain metadata: <https://download.qt.io/official_releases/qt/6.11/6.11.1/single/qt-everywhere-src-6.11.1.tar.xz.mirrorlist>
- IETF Metalink metadata: <https://download.qt.io/official_releases/qt/6.11/6.11.1/single/qt-everywhere-src-6.11.1.tar.xz.meta4>
- Size recorded by MirrorBrain: `1017723080` bytes
- SHA256: `252acef8c5ae68074d91cadba2ee4a83465051bbb970dd26e8f0daa0f3904e03`

## Qt for Python / PySide 6.11.1 source

- Archive: `pyside-setup-everywhere-src-6.11.1.tar.xz`
- Official URL: <https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.1-src/pyside-setup-everywhere-src-6.11.1.tar.xz>
- Official MirrorBrain metadata: <https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.1-src/pyside-setup-everywhere-src-6.11.1.tar.xz.mirrorlist>
- IETF Metalink metadata: <https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.1-src/pyside-setup-everywhere-src-6.11.1.tar.xz.meta4>
- Size recorded by MirrorBrain: `17963432` bytes
- SHA256: `6ffd9835bb0dd2c56f061d62f1616bb1707cfc0202b80e3165d6be087f3965e2`

## FFmpeg 7.1.3 source

Qt Multimedia's shipped FFmpeg shared libraries report version `7.1.3` and
`LGPL version 2.1 or later`. The exact source URL comes from Qt 6.11.1's
`qtmultimedia/src/3rdparty/ffmpeg/qt_attribution.json`.

- Archive: `FFmpeg-n7.1.3.tar.gz`
- Source URL: <https://github.com/FFmpeg/FFmpeg/archive/refs/tags/n7.1.3.tar.gz>
- SHA256: `e0b04c4b43d7e6d67cb6710334fb513adf13ac860532f30e1d0ac4c231f232fb`
- Qt build configuration reported by the shipped binary:
  `--disable-programs --disable-doc --disable-debug --enable-network
--disable-lzma --enable-pic --disable-vulkan --disable-v4l2-m2m
--disable-decoder=truemotion1 --enable-shared --disable-static
--enable-openssl --prefix=/usr/local/FFmpeg-n7.1.3`

The configuration does not report `--enable-gpl`, `--enable-nonfree`, or
`--enable-version3`. Qt's exact attribution, including libjpeg, zlib, and Boost
notices, is under `licenses/desktop/qt-6.11.1/qtmultimedia/ffmpeg/`.

## Linux cryptography 50.0.0 and OpenSSL 4.0.1 source

The Linux cryptography wheel carries `sbom.json`, which identifies a statically
built (`no-shared`) OpenSSL 4.0.1 component. MDLogger retains byte-for-byte
copies of that SBOM and its 39-component Rust CycloneDX build-provenance document
under `licenses/desktop/cryptography-50.0.0/sboms/`. The Rust document is not an
object-level linker map and does not claim that every build input is separately
linked into the final extension.

- cryptography source archive: `cryptography-50.0.0.tar.gz`
- Source URL: <https://files.pythonhosted.org/packages/de/41/6cbdcf9142d00fe82836fbb51e503e58088575cf7a0fe1dbff6695bf0840/cryptography-50.0.0.tar.gz>
- SHA256: `eeac2acb5a20ed25e0ad6d1df9891a520b78b404266b6d11778f25d5d691a6c9`
- OpenSSL source archive: `openssl-4.0.1.tar.gz`
- Source URL: <https://github.com/openssl/openssl/releases/download/openssl-4.0.1/openssl-4.0.1.tar.gz>
- SHA256: `2db3f3a0d6ea4b59e1f094ace2c8cd536dffb87cdc39084c5afa1e6f7f37dd09`

## Linux NumPy 2.4.6 and native runtime source

The Linux NumPy wheel contains OpenBLAS/LAPACK, libgfortran, and libquadmath
shared libraries. Their copyright notices and complete license texts are in the
wheel's retained `licenses/desktop/numpy-2.4.6/licenses/LICENSE.txt`.

- NumPy source archive: `numpy-2.4.6.tar.gz`
- Source URL: <https://files.pythonhosted.org/packages/d0/ad/fed0499ce6a338d2a03ebae59cd15093910c8875328855781952abf6c2fe/numpy-2.4.6.tar.gz>
- SHA256: `f3a3570c4a2a16746ac2c31a7c7c7b0c186b95ce902e33db6f28094ed7387dda`
- OpenBLAS/LAPACK upstream: <https://github.com/OpenMathLib/OpenBLAS/>
- GCC libgfortran/libquadmath upstream: <https://gcc.gnu.org/git/?p=gcc.git;a=tree>

The NumPy wheel does not identify the exact OpenBLAS or GCC source revision used
to build its bundled Linux native libraries. This is a known limitation. Do not
describe the upstream URLs as corresponding-source snapshots; the retained NumPy
license text identifies the distributed libraries and their notices. If the wheel
publisher or release build evidence later supplies matching revisions and source
hashes, record them with the release and publish the verified source archives
beside the binary.

## Verification procedure

At every release, open both Qt/PySide official archive URLs and both
`.mirrorlist` pages again. Confirm that the requested version is still
accessible and that MirrorBrain reports the expected filename, size, and
SHA256. Also download the FFmpeg URL recorded above. Download without following
instructions from an untrusted mirror page, then verify locally:

```bash
sha256sum qt-everywhere-src-6.11.1.tar.xz
sha256sum pyside-setup-everywhere-src-6.11.1.tar.xz
sha256sum FFmpeg-n7.1.3.tar.gz
```

The expected output digests are the values recorded above. A standard-library
alternative is:

```bash
python -c "from hashlib import file_digest; from pathlib import Path; print(file_digest(Path('qt-everywhere-src-6.11.1.tar.xz').open('rb'), 'sha256').hexdigest())"
python -c "from hashlib import file_digest; from pathlib import Path; print(file_digest(Path('pyside-setup-everywhere-src-6.11.1.tar.xz').open('rb'), 'sha256').hexdigest())"
python -c "from hashlib import file_digest; from pathlib import Path; print(file_digest(Path('FFmpeg-n7.1.3.tar.gz').open('rb'), 'sha256').hexdigest())"
```

As of 2026-08-28, the official 6.11.1 directory indexes and MirrorBrain pages
list hashes, Metalink, torrent, and magnet metadata but do **not** list a
separate detached `.asc` or `.sig` signature for either archive. Do not claim
detached-signature verification for these files. Recheck this fact for every
release because the official publication format can change.

The license texts under `licenses/desktop/qt-for-python-6.11.1/` were extracted
from the verified PySide source archive because the PySide6 wheels do not carry
those originals. `LICENSES/GPL-3.0-only.txt` is the selected license text;
LGPL/GPL alternatives and source-level COPYING notices are retained as upstream
evidence rather than as a different MDLogger license choice.

The verified Qt archive contains 402 module-level `LICENSES` entries. Their 83
unique byte contents and a source-member/SHA256 manifest are distributed under
`licenses/desktop/qt-6.11.1/`. The same archive supplied 123 package-specific
attribution records for source modules represented in the complete Linux
PySide6 wheels and 88 referenced legal files. They are distributed as
`QT-THIRD-PARTY-ATTRIBUTIONS.json` and `third-party-source-files/` under that
directory. This is a conservative Linux source-attribution superset, not the
wheel publisher's exact-build SBOM, and may over-disclose records excluded by
the publisher's build configuration. Adjacent FFmpeg originals and Chromium
scanner credits are retained separately because the module-level corpus alone
does not cover all full-wheel attribution evidence.

## Release source delivery

Do not rely only on upstream URLs remaining available. When publishing a
Windows installer, Flatpak bundle, or web static deployment, publish every
verified source archive listed above with equivalent access from the same
release/download location. Also create the MDLogger source archive from the
exact release commit, record that commit and the archive SHA256 in the release
notes, and include the packaging files used for the binary or static assets.
The NumPy native-runtime caveat above is a known limitation: preserve its
notices and state that the exact OpenBLAS and GCC source revisions are not
recorded. If matching revisions become available, record them and publish the
verified source archives too.
Keep those source downloads available for as long as the corresponding binary
is offered and for any longer period required by the selected licenses.

The Qt source archive contains the QtWebEngine and vendored Chromium source used
by the 6.11.1 release. The project has not rebuilt the PySide publisher wheel
and does not claim to possess its exact build-generated SBOM; the binary
inspection manifest records this limitation.

## Full-wheel and GPL-only module disclosure

The Linux Flatpak intentionally retains the full `PySide6` dependency. The
`PySide6` metapackage installs both `PySide6-Essentials` and
`PySide6-Addons`, and those wheels contain Qt binaries beyond the modules that
MDLogger imports directly. MDLogger directly imports QtCore, QtGui, QtWidgets,
and QtSvg, while the unpruned Addons wheel can also contain GPL-only
open-source modules including Qt Graphs, Qt Charts, Qt Data Visualization, and
Qt Quick 3D. Qt's 6.11 documentation identifies each of those modules as
commercial-or-GPLv3. They are not represented as LGPL-only or omitted from the
inventory.

Relevant official module pages:

- <https://doc.qt.io/qt-6/qtgraphs-index.html#licenses-and-attributions>
- <https://doc.qt.io/qt-6/qtcharts-index.html#licenses-and-attributions>
- <https://doc.qt.io/qt-6/qtdatavisualization-index.html#licenses-and-attributions>
- <https://doc.qt.io/qt-6/qtquick3d-index.html#licenses-and-attributions>
- Qt 6.11 third-party code index: <https://doc.qt.io/qt-6/licenses-used-in-qt.html>

The selected GPL-3.0-only path applies to these Qt modules. The distributed
`licenses/` tree includes the curated Qt source-attribution superset and its
referenced originals, plus separate QtWebEngine/Chromium and FFmpeg evidence.
Those 123/88, Chromium, and FFmpeg runtime findings are Linux evidence only;
the Windows PyInstaller package must not represent them as a Windows payload
inventory. A release audit must still compare the actual PyInstaller TOC and
Flatpak installed files with the tracked inventories; source-derived evidence
is not an exact publisher build manifest, and a source URL alone does not waive
attribution or source-availability duties.
