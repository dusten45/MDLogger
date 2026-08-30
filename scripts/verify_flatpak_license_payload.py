#!/usr/bin/env python3
"""Verify the final Flatpak runtime and distributed license corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "scripts" / "desktop_license_policy.json"
SITE_PACKAGES = "venv/lib/python3.13/site-packages"
NORMALIZE_PATTERN = re.compile(r"[-_.]+")
INVENTORY_DIRECTORY = "share/licenses/mdlogger/inventory"


class ComplianceError(RuntimeError):
    """Raised when a Flatpak final image differs from its reviewed policy."""


def normalize_name(value: str) -> str:
    """Return the PEP 503 comparison key used for distribution names."""

    return NORMALIZE_PATTERN.sub("-", value).lower()


def sha256_file(path: Path) -> str:
    """Return a file's SHA256 digest."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_policy(path: Path) -> dict[str, Any]:
    """Load the generated desktop license policy."""

    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComplianceError(f"Cannot load desktop license policy: {path}") from error
    if not isinstance(policy, dict):
        raise ComplianceError("Desktop license policy must be a JSON object")
    return policy


def installed_distributions(site_packages: Path) -> dict[str, str]:
    """Return non-project distribution names and versions from the final image."""

    distributions: dict[str, str] = {}
    for dist_info in sorted(site_packages.glob("*.dist-info")):
        metadata_path = dist_info / "METADATA"
        if not metadata_path.is_file():
            raise ComplianceError(f"Distribution metadata is missing: {metadata_path}")
        with metadata_path.open("rb") as stream:
            metadata = BytesParser(policy=compat32).parse(stream)
        name = (metadata.get("Name") or "").strip()
        version = (metadata.get("Version") or "").strip()
        normalized = normalize_name(name)
        if not normalized or not version:
            raise ComplianceError(f"Invalid distribution metadata: {metadata_path}")
        if normalized == "mdlogger":
            continue
        if normalized in distributions:
            raise ComplianceError(f"Duplicate installed distribution: {name}")
        distributions[normalized] = version
    return distributions


def verify_distribution_closure(app_root: Path, policy: dict[str, Any]) -> None:
    """Require the installed Flatpak distribution closure to match the policy."""

    expected = {
        normalize_name(str(package["name"])): str(package["version"])
        for package in policy["packages"]
        if "linux" in package["platforms"]
    }
    actual = installed_distributions(app_root / SITE_PACKAGES)
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    version_drift = sorted(
        f"{name}: expected {expected[name]}, found {actual[name]}"
        for name in set(expected) & set(actual)
        if expected[name] != actual[name]
    )
    if missing or unexpected or version_drift:
        details = []
        if missing:
            details.append(f"missing={', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected={', '.join(unexpected)}")
        if version_drift:
            details.append(f"version drift={'; '.join(version_drift)}")
        raise ComplianceError(
            "Flatpak distribution closure differs: " + "; ".join(details)
        )


def verify_absent_unreviewed_content(app_root: Path) -> None:
    """Reject build tools and data explicitly excluded from the final image."""

    site_packages = app_root / SITE_PACKAGES
    forbidden = (
        site_packages / "pip",
        *site_packages.glob("pip-*.dist-info"),
        app_root / "venv/bin/pip",
        app_root / "venv/bin/pip3",
        app_root / "venv/bin/pip3.13",
        site_packages / "pyqtgraph/colors/maps/PAL-relaxed.hex",
        site_packages / "pyqtgraph/colors/maps/PAL-relaxed_bright.hex",
    )
    present = [str(path) for path in forbidden if path.exists()]
    if present:
        raise ComplianceError(
            "Excluded Flatpak files are present: " + ", ".join(present)
        )


def deployed_desktop_path(app_root: Path, policy_path: str) -> Path:
    """Map a repository desktop-license path to its Flatpak installation path."""

    repository_path = Path(policy_path)
    expected_prefix = Path("licenses/desktop")
    if repository_path.parts[:2] != expected_prefix.parts:
        raise ComplianceError(
            f"Unsafe or unsupported desktop license path: {policy_path}"
        )
    return (
        app_root
        / "share/licenses/mdlogger/desktop"
        / repository_path.relative_to(expected_prefix)
    )


def deployed_inventory_path(app_root: Path, filename: str) -> Path:
    """Return a safe path to a Linux-only deployed inventory document."""

    candidate = Path(filename)
    if candidate.name != filename or candidate.suffix != ".json":
        raise ComplianceError(f"Unsafe deployed inventory filename: {filename}")
    return app_root / INVENTORY_DIRECTORY / candidate


def load_deployed_inventory(app_root: Path, filename: str) -> dict[str, Any]:
    """Load a JSON inventory copied into the final Flatpak image."""

    path = deployed_inventory_path(app_root, filename)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComplianceError(f"Cannot load Flatpak inventory: {path}") from error
    if not isinstance(value, dict):
        raise ComplianceError(f"Flatpak inventory must be an object: {path}")
    return value


def verify_qt_payload_files(
    app_root: Path, records: Sequence[Mapping[str, Any]], *, label: str
) -> None:
    """Verify hashes for Qt binary records declared in a deployed inventory."""

    if not records:
        raise ComplianceError(f"Flatpak {label} payload inventory is empty")
    seen_paths: set[str] = set()
    site_packages = app_root / SITE_PACKAGES
    for record in records:
        relative = Path(str(record.get("path", "")))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or relative.parts[0] != "PySide6"
        ):
            raise ComplianceError(f"Unsafe Flatpak {label} payload path: {relative}")
        relative_text = relative.as_posix()
        if relative_text in seen_paths:
            raise ComplianceError(f"Duplicate Flatpak {label} payload path: {relative}")
        seen_paths.add(relative_text)
        size = record.get("size")
        digest = record.get("sha256")
        if not isinstance(size, int) or size <= 0 or not isinstance(digest, str):
            raise ComplianceError(f"Invalid Flatpak {label} payload record: {relative}")
        path = site_packages / relative
        if not path.is_file():
            raise ComplianceError(f"Flatpak {label} payload is missing: {relative}")
        if path.stat().st_size != size:
            raise ComplianceError(f"Flatpak {label} payload size drift: {relative}")
        if sha256_file(path) != digest:
            raise ComplianceError(f"Flatpak {label} payload hash drift: {relative}")


def verify_deployed_legal_files(
    app_root: Path, records: Sequence[Mapping[str, Any]], *, label: str
) -> None:
    """Verify deployed legal originals that correspond to runtime evidence."""

    for record in records:
        relative = str(record.get("path", ""))
        expected_hash = str(record.get("sha256", ""))
        deployed = deployed_desktop_path(app_root, relative)
        if not deployed.is_file() or sha256_file(deployed) != expected_hash:
            raise ComplianceError(f"Flatpak {label} legal-file hash drift: {relative}")


def verify_qt_module_inventory(app_root: Path) -> None:
    """Compare the final full PySide6 wheel contents with its Linux inventory."""

    inventory = load_deployed_inventory(app_root, "qt-modules-linux-flatpak.json")
    if inventory.get("platform") != "linux-flatpak-x86_64":
        raise ComplianceError("Flatpak Qt module inventory platform drift")

    actual_distributions = installed_distributions(app_root / SITE_PACKAGES)
    distribution_records = inventory.get("distributions", [])
    if not isinstance(distribution_records, list):
        raise ComplianceError("Flatpak Qt module distributions are invalid")
    expected_names = {"pyside6-essentials", "pyside6-addons"}
    observed_names: set[str] = set()
    for record in distribution_records:
        if not isinstance(record, Mapping):
            raise ComplianceError("Flatpak Qt module distribution record is invalid")
        name = normalize_name(str(record.get("name", "")))
        version = str(record.get("version", ""))
        observed_names.add(name)
        if actual_distributions.get(name) != version:
            raise ComplianceError(f"Flatpak Qt module distribution drift: {name}")
    if observed_names != expected_names:
        raise ComplianceError("Flatpak Qt module distribution inventory drift")

    site_packages = app_root / SITE_PACKAGES
    files = {
        path.relative_to(site_packages).as_posix()
        for path in (site_packages / "PySide6").rglob("*")
        if path.is_file()
    }
    actual = {
        "binding_modules": sorted(
            Path(file).name.split(".abi3", 1)[0].split(".", 1)[0]
            for file in files
            if file.startswith("PySide6/Qt") and file.endswith((".abi3.so", ".pyd"))
        ),
        "qt_libraries": sorted(
            Path(file).name
            for file in files
            if file.startswith("PySide6/Qt/lib/") and "Qt6" in Path(file).name
        ),
        "plugins": sorted(
            file.removeprefix("PySide6/Qt/plugins/")
            for file in files
            if file.startswith("PySide6/Qt/plugins/")
        ),
        "qml_module_roots": sorted(
            {
                file.removeprefix("PySide6/Qt/qml/").split("/", 1)[0]
                for file in files
                if file.startswith("PySide6/Qt/qml/")
            }
        ),
        "translation_file_count": sum(
            file.startswith("PySide6/Qt/translations/") for file in files
        ),
        "resource_file_count": sum(
            file.startswith("PySide6/Qt/resources/") for file in files
        ),
    }
    for field, value in actual.items():
        if inventory.get(field) != value:
            raise ComplianceError(f"Flatpak Qt module inventory drift: {field}")


def verify_qt_runtime_inventory(app_root: Path, policy: dict[str, Any]) -> None:
    """Verify the final QtWebEngine and FFmpeg binaries and their legal files."""

    inventory = load_deployed_inventory(
        app_root, "qt-third-party-runtime-linux-flatpak.json"
    )
    runtime = policy["qt_runtime_attributions"]
    if inventory.get("exact_build_sbom_available") is not False:
        raise ComplianceError("Flatpak Qt runtime exact-build SBOM status drift")

    chromium = inventory.get("chromium", {})
    chromium_policy = runtime["chromium"]
    if chromium.get("runtime_version") != chromium_policy["runtime_version"]:
        raise ComplianceError("Flatpak Chromium runtime version drift")
    source_credits = chromium.get("source_credits", {})
    if (
        source_credits.get("component_count")
        != chromium_policy["source_credits_component_count"]
        or source_credits.get("scope") != chromium_policy["source_credits_scope"]
    ):
        raise ComplianceError("Flatpak Chromium source-credit scope drift")
    if chromium.get("legal_files") != [
        record["path"] for record in chromium_policy["files"]
    ]:
        raise ComplianceError("Flatpak Chromium legal-file inventory drift")
    verify_qt_payload_files(
        app_root, chromium.get("payload_files", []), label="Chromium"
    )
    verify_deployed_legal_files(app_root, chromium_policy["files"], label="Chromium")

    ffmpeg = inventory.get("ffmpeg", {})
    ffmpeg_policy = runtime["ffmpeg"]
    for field in (
        "version",
        "runtime_license",
        "selected_license_expression",
        "aggregate_attribution_expression",
        "configure",
        "source_url",
        "source_sha256",
    ):
        if ffmpeg.get(field) != ffmpeg_policy[field]:
            raise ComplianceError(f"Flatpak FFmpeg runtime inventory drift: {field}")
    if ffmpeg.get("components") != ffmpeg_policy["components"]:
        raise ComplianceError("Flatpak FFmpeg component attribution drift")
    if ffmpeg.get("legal_files") != [
        record["path"] for record in ffmpeg_policy["files"]
    ]:
        raise ComplianceError("Flatpak FFmpeg legal-file inventory drift")
    verify_qt_payload_files(app_root, ffmpeg.get("payload_files", []), label="FFmpeg")
    verify_deployed_legal_files(app_root, ffmpeg_policy["files"], label="FFmpeg")


def verify_cryptography_wheel_evidence(app_root: Path, policy: dict[str, Any]) -> None:
    """Require the final cryptography wheel SBOM files to equal copied evidence."""

    evidence = policy["cryptography_wheel_sbom_evidence"]
    site_packages = app_root / SITE_PACKAGES
    for record in evidence["files"]:
        installed_path = Path(str(record["installed_path"]))
        if installed_path.is_absolute() or ".." in installed_path.parts:
            raise ComplianceError("Unsafe cryptography wheel SBOM path")
        installed = site_packages / installed_path
        deployed = deployed_desktop_path(app_root, str(record["path"]))
        expected_hash = str(record["sha256"])
        if not installed.is_file() or sha256_file(installed) != expected_hash:
            raise ComplianceError(
                f"Flatpak cryptography wheel SBOM hash drift: {installed_path}"
            )
        if not deployed.is_file() or sha256_file(deployed) != expected_hash:
            raise ComplianceError(
                f"Flatpak copied cryptography SBOM hash drift: {record['path']}"
            )


def verify_native_payload(
    app_root: Path, policy: dict[str, Any], *, payload_phase: str
) -> None:
    """Verify wheel or post-processed final-image native library payload pins."""

    records = policy.get("flatpak_linux_native_payload", [])
    if not records:
        raise ComplianceError("Missing Flatpak Linux native-payload policy")
    if payload_phase not in {"wheel", "final_image"}:
        raise ComplianceError(f"Unsupported Flatpak payload phase: {payload_phase}")
    for record in records:
        relative = Path(str(record.get("path", "")))
        expected = record.get(payload_phase)
        if relative.is_absolute() or ".." in relative.parts:
            raise ComplianceError(f"Unsafe Flatpak native-payload path: {relative}")
        if not isinstance(expected, Mapping):
            raise ComplianceError(
                f"Missing Flatpak {payload_phase} native-payload pin: {relative}"
            )
        size = expected.get("size")
        digest = expected.get("sha256")
        if not isinstance(size, int) or size <= 0 or not isinstance(digest, str):
            raise ComplianceError(
                f"Invalid Flatpak {payload_phase} native-payload pin: {relative}"
            )
        path = app_root / relative
        if not path.is_file():
            raise ComplianceError(f"Flatpak native payload is missing: {relative}")
        if path.stat().st_size != size:
            raise ComplianceError(
                f"Flatpak {payload_phase} native payload size drift: {relative}"
            )
        if sha256_file(path) != digest:
            raise ComplianceError(
                f"Flatpak {payload_phase} native payload hash drift: {relative}"
            )


def verify_qt_attributions(app_root: Path, policy: dict[str, Any]) -> None:
    """Verify the deployed Linux Qt source-attribution corpus byte-for-byte."""

    expected = policy["qt_source_attributions"]
    file_record = expected["file"]
    attribution_path = deployed_desktop_path(app_root, str(file_record["path"]))
    if not attribution_path.is_file():
        raise ComplianceError(f"Flatpak Qt attribution is missing: {attribution_path}")
    if sha256_file(attribution_path) != file_record["sha256"]:
        raise ComplianceError("Flatpak Qt attribution hash drift")

    document = json.loads(attribution_path.read_text(encoding="utf-8"))
    source_archive = document.get("source_archive", {})
    if source_archive.get("sha256") != expected["source_archive_sha256"]:
        raise ComplianceError("Flatpak Qt attribution source archive hash drift")
    if document.get("exact_build_sbom_available") is not False:
        raise ComplianceError("Flatpak Qt exact-build SBOM status drift")
    records = document.get("records", [])
    if len(records) != expected["record_count"]:
        raise ComplianceError("Flatpak Qt attribution record count drift")

    legal_files: dict[str, str] = {}
    for record in records:
        for legal_file in record.get("legal_files", []):
            path = str(legal_file["path"])
            digest = str(legal_file["sha256"])
            previous = legal_files.setdefault(path, digest)
            if previous != digest:
                raise ComplianceError(f"Flatpak Qt legal-file hash conflict: {path}")
    if len(legal_files) != expected["legal_file_count"]:
        raise ComplianceError("Flatpak Qt attribution legal-file count drift")
    for path, expected_hash in legal_files.items():
        deployed = deployed_desktop_path(app_root, path)
        if not deployed.is_file():
            raise ComplianceError(f"Flatpak Qt legal file is missing: {deployed}")
        if sha256_file(deployed) != expected_hash:
            raise ComplianceError(f"Flatpak Qt legal-file hash drift: {deployed}")


def verify_documents(app_root: Path) -> None:
    """Require only Linux evidence and all user-facing legal documents."""

    required = (
        app_root / "share/licenses/mdlogger/LICENSE",
        app_root / "share/doc/mdlogger/THIRD_PARTY_NOTICES.txt",
        app_root / "share/doc/mdlogger/THIRD_PARTY_NOTICES.md",
        app_root / "share/doc/mdlogger/sources/desktop-source-offer.md",
        app_root / "share/licenses/mdlogger/inventory/desktop-linux.json",
        app_root / "share/licenses/mdlogger/inventory/qt-modules-linux-flatpak.json",
        app_root
        / "share/licenses/mdlogger/inventory/qt-third-party-runtime-linux-flatpak.json",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ComplianceError(
            "Flatpak legal documents are missing: " + ", ".join(missing)
        )
    windows_inventory = (
        app_root / "share/licenses/mdlogger/inventory/desktop-windows.json"
    )
    if windows_inventory.exists():
        raise ComplianceError("Flatpak must not ship the Windows resolver inventory")


def verify(
    app_root: Path, policy_path: Path, *, payload_phase: str = "final_image"
) -> None:
    """Verify every reviewed runtime and legal-file boundary of a Flatpak image."""

    policy = load_policy(policy_path)
    verify_distribution_closure(app_root, policy)
    verify_absent_unreviewed_content(app_root)
    verify_documents(app_root)
    verify_native_payload(app_root, policy, payload_phase=payload_phase)
    verify_qt_module_inventory(app_root)
    verify_qt_runtime_inventory(app_root, policy)
    verify_qt_attributions(app_root, policy)
    verify_cryptography_wheel_evidence(app_root, policy)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument(
        "--payload-phase",
        choices=("wheel", "final_image"),
        default="final_image",
        help="verify pre-finish wheel bytes or post-processed final-image bytes",
    )
    return parser.parse_args()


def main() -> int:
    """Run the Flatpak image verifier and print an actionable result."""

    args = parse_args()
    try:
        verify(args.app_root, args.policy, payload_phase=args.payload_phase)
    except ComplianceError as error:
        print(f"Flatpak license compliance failed: {error}")
        return 1
    print("Flatpak license payload verified successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
