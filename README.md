# MDLogger

Windows · Linux

An unofficial match logging and analytics tool for Yu-Gi-Oh! MASTER DUEL.

---

v2.1.1 fixes eight stability issues affecting Windows update handoff, local reset
recovery, conflict drafts, account sessions, and web record submission and history.
See the [release readiness and validation status](docs/release.md#v211-준비-상태).

Signed in-app updates were introduced in v2.1.0 for the Windows x64 installer edition.
Windows v2.0.0 does not contain an updater, so upgrading requires one manual
installation from [GitHub Releases](https://github.com/dusten45/MDLogger/releases).
The installed Windows app checks for later releases after startup; downloading and
installing an update requires a user action. Windows may still require administrator
approval or show SmartScreen warnings. The update signature does not replace Windows
Authenticode signing.

For a safer v2.1.0 to v2.1.1 transition, we recommend closing MDLogger and running
the new installer manually.
The updater fix does not modify the updater in an already installed v2.1.0 copy.

This release does not replace the Linux Flatpak bundle. Linux updates remain manual;
an MDLogger automatic-update Flatpak remote is not configured.

Visit the website at [mdlogger-web.dalimi4511-615.workers.dev](https://mdlogger-web.dalimi4511-615.workers.dev/).

## Disclaimer

**MDLogger is an unofficial match logging and analytics tool for Yu-Gi-Oh! MASTER DUEL. It is not affiliated with, endorsed by, sponsored by, or approved by KONAMI or the relevant rights holders. Rights in Yu-Gi-Oh! MASTER DUEL and related names, marks, and game assets belong to their respective rights holders.**

## License

This project is licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later). See [LICENSE](LICENSE) for details.
