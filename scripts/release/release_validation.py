#!/usr/bin/env python3
"""Shared, platform-independent checks for desktop release artifacts."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

WINDOWS_REQUIRED_FILES = (
    "MDLogger.exe",
    "LICENSE",
    "THIRD_PARTY_NOTICES.txt",
    "licenses/inventory/desktop-windows.json",
    "licenses/sources/desktop-source-offer.md",
)
WINDOWS_FORBIDDEN_FILES = ("PAL-relaxed.hex", "PAL-relaxed_bright.hex")
WINDOWS_FORBIDDEN_PATHS = (
    "licenses/inventory/desktop-linux.json",
    "licenses/inventory/qt-third-party-runtime-linux-flatpak.json",
)


class ReleaseValidationError(RuntimeError):
    """Raised when a release artifact violates a required invariant."""


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regular file."""

    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_checksum_file(path: Path, checksum_path: Path) -> None:
    """Require a standard single-file checksum sidecar to match ``path``."""

    if not path.is_file():
        raise ReleaseValidationError(f"Artifact is missing: {path}")
    if not checksum_path.is_file():
        raise ReleaseValidationError(f"Checksum sidecar is missing: {checksum_path}")

    expected_line = f"{sha256_file(path)}  {path.name}\n"
    actual_line = checksum_path.read_text(encoding="ascii")
    if actual_line != expected_line:
        raise ReleaseValidationError(
            f"Checksum sidecar does not match artifact: {checksum_path}"
        )


def verify_windows_payload(root: Path) -> None:
    """Validate the legal-file and exclusion contract of an installed Windows payload."""

    if not root.is_dir():
        raise ReleaseValidationError(f"Windows payload directory is missing: {root}")

    missing = [
        str(root / relative)
        for relative in WINDOWS_REQUIRED_FILES
        if not (root / relative).is_file()
    ]
    if missing:
        raise ReleaseValidationError(
            "Windows payload is missing required files: " + ", ".join(missing)
        )

    unexpected = [
        str(root / relative)
        for relative in WINDOWS_FORBIDDEN_PATHS
        if (root / relative).exists()
    ]
    if unexpected:
        raise ReleaseValidationError(
            "Windows payload contains Linux-only license evidence: "
            + ", ".join(unexpected)
        )

    palettes = sorted(
        str(path)
        for path in root.rglob("*")
        if path.is_file() and path.name in WINDOWS_FORBIDDEN_FILES
    )
    if palettes:
        raise ReleaseValidationError(
            "Windows payload contains excluded pyqtgraph palettes: "
            + ", ".join(palettes)
        )


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description="Validate desktop release artifacts")
    commands = parser.add_subparsers(dest="command", required=True)

    windows = commands.add_parser("windows-payload")
    windows.add_argument("--root", type=Path, required=True)

    checksum = commands.add_parser("checksum")
    checksum.add_argument("--artifact", type=Path, required=True)
    checksum.add_argument("--sidecar", type=Path, required=True)

    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    """Run one shared release validation command."""

    args = parse_args(arguments)
    try:
        if args.command == "windows-payload":
            verify_windows_payload(args.root)
        else:
            verify_checksum_file(args.artifact, args.sidecar)
    except ReleaseValidationError as error:
        print(f"ERROR: {error}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
