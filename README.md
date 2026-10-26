# MDLogger

An unofficial match logging and analytics tool for Yu-Gi-Oh! MASTER DUEL, with a Korean interface.

- Record ranked, rating, and event matches; view personal results and statistics.
- Windows and Linux desktop apps keep records in local, separate guest/account databases. Registered accounts support cross-device synchronization and conflict resolution.
- The web/PWA requires an account and a network connection for match operations. Installing the PWA does not enable offline match storage.
- Desktop exports include CSV, Excel, and portable game archives. Account JSON export is separate and is not a complete application backup.
- Guest mode can upload observation data after the data notice is accepted; guest notes remain local. See the [privacy policy](docs/privacy-policy.md) for data handling.

## Get MDLogger

- [Desktop downloads](https://github.com/dusten45/MDLogger/releases): Windows x64 installer and Linux x86_64 Flatpak bundles. A Windows-only release does not replace the Linux bundle.
- [Web application](https://mdlogger-web.dalimi4511-615.workers.dev/): browser access and PWA installation.

Windows installer editions from v2.1.0 check for signed updates after startup; downloading and installing requires user action. For the v2.1.0 to v2.1.1 transition, close the app and run the new installer manually. Versions before v2.1.0 also require manual installation.

Update signatures do not replace Windows Authenticode signing: administrator approval or SmartScreen warnings may still appear. Linux updates remain manual; no MDLogger automatic-update Flatpak remote is configured. See [update verification limits](docs/release.md#업데이트와-검증).

## Source and Documentation

The desktop uses Python/uv, PySide6 and SQLite; the web uses React/TypeScript; both connect to Supabase. Runtime versions are pinned in [`.python-version`](.python-version), [`pyproject.toml`](pyproject.toml) and [`.nvmrc`](.nvmrc).

- [Build and release](docs/release.md)
- [Web development and PWA behavior](web/README.md)
- [Backend setup and data contracts](supabase/README.md)
- [Privacy policy](docs/privacy-policy.md) and [terms of service](docs/terms-of-service.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md) and [source information](licenses/sources/desktop-source-offer.md)

## Disclaimer

**MDLogger is an unofficial match logging and analytics tool for Yu-Gi-Oh! MASTER DUEL. It is not affiliated with, endorsed by, sponsored by, or approved by KONAMI or the relevant rights holders. Rights in Yu-Gi-Oh! MASTER DUEL and related names, marks, and game assets belong to their respective rights holders.**

## License

This project is licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later). See [LICENSE](LICENSE) for details.
