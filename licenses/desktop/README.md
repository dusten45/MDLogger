# Desktop package legal files

Each versioned directory contains unmodified upstream license, COPYING, NOTICE,
author, or attribution material for the desktop runtime closure. Current
Qt/PySide6 6.12.0 originals are stored under `qt-for-python-6.12.0/` for
PySide6-Essentials and shiboken6. Addons, WebEngine, Pdf, Multimedia, Chromium
and FFmpeg runtimes are not distributed.

Qt's package-specific attributions and referenced originals under `qt-6.12.0/`
are a conservative cross-platform Essentials source superset, not an exact
wheel-build SBOM. Windows uses CPython 3.15.1 from python-build-standalone;
Flatpak uses the Freedesktop runtime's Python 3.14. Their binary evidence is
not interchangeable. Exact legal-file paths and SHA256 digests are reviewed in
`scripts/desktop_license_policy.json`; platform inventories are under
`licenses/inventory/`.

Do not add a package or legal file by relying only on `License` or
`License-Expression` metadata. Update the manual policy, preserve every bundled
component license, run the generator, and review the resulting inventory diff.
The policy and inventory paths above refer to repository records, not files
included in every installer. Public [acquisition details](https://github.com/dusten45/MDLogger/blob/main/licenses/sources/desktop-license-provenance.md)
and [source information](https://github.com/dusten45/MDLogger/blob/main/licenses/sources/desktop-source-offer.md)
remain accessible when Windows omits those directories. These records do not
by themselves establish legal compliance.
