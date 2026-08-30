# Desktop package legal files

Each versioned directory contains unmodified upstream license, COPYING, NOTICE,
author, or attribution material for the desktop runtime closure. Shared
Qt/PySide6 originals are stored once under `qt-for-python-6.11.1/` and referenced
by all four related distributions. Qt's package-specific source attributions
and their referenced originals are stored under `qt-6.11.1/`; they are a
conservative Linux source-tree superset, not an exact wheel-build SBOM. Exact
file paths and SHA256 digests are reviewed in
`scripts/desktop_license_policy.json`.

Do not add a package or legal file by relying only on `License` or
`License-Expression` metadata. Update the manual policy, preserve every bundled
component license, run the generator, and review the resulting inventory diff.
See `licenses/sources/desktop-license-provenance.md` for acquisition details and
`licenses/sources/desktop-source-offer.md` for Qt/PySide6 source information.
