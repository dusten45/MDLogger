#!/usr/bin/env python3
"""Create canonical platform records and the desktop draft-release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TOOL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
PLATFORMS = {"windows-x64", "linux-flatpak-x86_64"}
REQUIRED_PLATFORM_CHECKS = {
    "windows-x64": frozenset(
        {
            "onedir-license-payload",
            "onedir-secret-scan",
            "pyinstaller-analysis",
            "onedir-checksum",
            "installer-silent-installation",
            "installed-license-payload",
            "installed-secret-scan",
            "installer-checksum",
        }
    ),
    "linux-flatpak-x86_64": frozenset(
        {
            "final-image-license-payload",
            "final-image-secret-scan",
            "bundle-checksum",
            "bundle-installation",
            "installed-license-payload",
            "installed-entry-point",
        }
    ),
}
REQUIRED_PLATFORM_TOOLS = {
    "windows-x64": frozenset(
        {
            "python",
            "uv",
            "pyinstaller",
            "inno-setup",
            "runner-os",
            "runner-image-version",
        }
    ),
    "linux-flatpak-x86_64": frozenset(
        {
            "python",
            "uv",
            "flatpak",
            "flatpak-builder",
            "runtime",
            "runtime-commit",
            "sdk-commit",
            "runner-os",
            "runner-image-version",
        }
    ),
}
REQUIRED_SOURCE_ARCHIVES = frozenset(
    {
        "qt-everywhere-src-6.11.1.tar.xz",
        "pyside-setup-everywhere-src-6.11.1.tar.xz",
        "FFmpeg-n7.1.3.tar.gz",
        "cryptography-50.0.0.tar.gz",
        "openssl-4.0.1.tar.gz",
        "numpy-2.4.6.tar.gz",
    }
)
PACKAGING_INPUTS = (
    "uv.lock",
    "flatpak/io.github.dusten45.MDLogger.yaml",
    "MDLogger.spec",
    "scripts/installer_windows.iss",
    "scripts/desktop_license_policy.json",
)
LICENSE_EVIDENCE = (
    "THIRD_PARTY_NOTICES.txt",
    "licenses/inventory/desktop-windows.json",
    "licenses/inventory/desktop-linux.json",
    "licenses/sources/desktop-source-offer.md",
    "scripts/release/third_party_source_delivery.json",
)


class ReleaseManifestError(RuntimeError):
    """Raised when release artifacts or provenance input are inconsistent."""


def canonical_json(value: object) -> str:
    """Return stable JSON suitable for checksum and reproducibility comparison."""

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_json(path: Path, value: object) -> None:
    """Write canonical JSON, creating the output parent when needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value), encoding="utf-8", newline="\n")


def sha256_file(path: Path) -> str:
    """Return a SHA-256 digest for a regular file."""

    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_record(path: Path) -> dict[str, int | str]:
    """Return filename, byte size, and digest for a regular release file."""

    if not path.is_file():
        raise ReleaseManifestError(f"Required release file is missing: {path}")
    return {
        "filename": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def verify_checksum_sidecar(path: Path) -> None:
    """Require the existing checksum sidecar to describe exactly one artifact file."""

    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not path.is_file():
        raise ReleaseManifestError(f"Required release file is missing: {path}")
    expected = f"{sha256_file(path)}  {path.name}\n"
    try:
        actual = sidecar.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as error:
        raise ReleaseManifestError(
            f"Missing or invalid checksum sidecar: {sidecar}"
        ) from error
    if actual != expected:
        raise ReleaseManifestError(
            f"Checksum sidecar does not match artifact: {sidecar}"
        )


def read_json_object(path: Path, *, description: str) -> dict[str, Any]:
    """Load a JSON object and report a context-rich validation error."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseManifestError(f"Cannot read {description}: {path}") from error
    if not isinstance(value, dict):
        raise ReleaseManifestError(f"{description} must be a JSON object: {path}")
    return value


def read_context(path: Path) -> dict[str, str]:
    """Read validated tag identity without accepting arbitrary release metadata."""

    value = read_json_object(path, description="release context")
    tag = value.get("tag")
    version = value.get("version")
    tag_object_sha = value.get("tag_object_sha")
    commit_sha = value.get("commit_sha")
    if (
        not isinstance(tag, str)
        or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag)
        or not isinstance(version, str)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
        or tag.removeprefix("v") != version
        or not isinstance(tag_object_sha, str)
        or not re.fullmatch(r"[0-9a-f]{40,64}", tag_object_sha)
        or not isinstance(commit_sha, str)
        or not re.fullmatch(r"[0-9a-f]{40,64}", commit_sha)
    ):
        raise ReleaseManifestError(
            "Release context has invalid tag, version, or Git object data"
        )
    return {
        "tag": tag,
        "version": version,
        "tag_object_sha": tag_object_sha,
        "commit_sha": commit_sha,
    }


def parse_key_value(entries: list[str], *, label: str) -> dict[str, str]:
    """Parse repeatable ``name=value`` CLI options without silently replacing values."""

    values: dict[str, str] = {}
    for entry in entries:
        key, separator, value = entry.partition("=")
        if not separator or not TOOL_NAME_PATTERN.fullmatch(key) or not value:
            raise ReleaseManifestError(f"Invalid {label} entry: {entry}")
        if key in values:
            raise ReleaseManifestError(f"Duplicate {label} entry: {key}")
        values[key] = value
    return values


def create_platform_record(
    *,
    platform: str,
    asset: Path,
    checks: list[str],
    tools: list[str],
) -> dict[str, Any]:
    """Record the verified platform asset without trusting caller-provided hashes."""

    if platform not in PLATFORMS:
        raise ReleaseManifestError(f"Unsupported release platform: {platform}")
    if set(checks) != REQUIRED_PLATFORM_CHECKS[platform]:
        raise ReleaseManifestError(
            f"Platform verification checks are incomplete: {platform}"
        )
    tool_versions = parse_key_value(tools, label="tool version")
    if set(tool_versions) != REQUIRED_PLATFORM_TOOLS[platform]:
        raise ReleaseManifestError(f"Platform tool versions are incomplete: {platform}")
    verify_checksum_sidecar(asset)
    return {
        "asset": file_record(asset),
        "platform": platform,
        "tool_versions": tool_versions,
        "verification": {check: "passed" for check in sorted(checks)},
    }


def load_source_delivery(project_root: Path) -> dict[str, Any]:
    """Load the owner-approved, manual third-party source delivery contract."""

    path = project_root / "scripts/release/third_party_source_delivery.json"
    value = read_json_object(path, description="third-party source delivery policy")
    delivery = value.get("delivery")
    archives = value.get("archives")
    if value.get("schema_version") != 1:
        raise ReleaseManifestError(
            "Third-party source delivery schema version is unsupported"
        )
    if not isinstance(delivery, dict) or not isinstance(archives, list) or not archives:
        raise ReleaseManifestError("Third-party source delivery policy is incomplete")
    if delivery.get("automation_status") != "pending_manual_attachment":
        raise ReleaseManifestError(
            "Third-party source delivery must remain pending manual attachment"
        )
    if delivery.get("delivery_location") != "same_github_release":
        raise ReleaseManifestError(
            "Third-party source delivery location must be the same GitHub Release"
        )
    if delivery.get("manual_reviewer") != "repository_owner":
        raise ReleaseManifestError(
            "Third-party source delivery reviewer must be repository owner"
        )
    if (
        not isinstance(delivery.get("review_method"), str)
        or not delivery["review_method"]
    ):
        raise ReleaseManifestError(
            "Third-party source delivery review method is missing"
        )
    if delivery.get("workflow_downloads_or_attaches_archives") is not False:
        raise ReleaseManifestError(
            "Workflow must not download or attach third-party source archives"
        )

    seen_filenames: set[str] = set()
    for archive in archives:
        if not isinstance(archive, dict):
            raise ReleaseManifestError(
                "Third-party source archive record must be an object"
            )
        filename = archive.get("filename")
        url = archive.get("url")
        digest = archive.get("sha256")
        size = archive.get("size_bytes")
        if (
            not isinstance(filename, str)
            or not filename
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
            or filename in seen_filenames
            or not isinstance(url, str)
            or not url.startswith("https://")
            or not isinstance(digest, str)
            or not SHA256_PATTERN.fullmatch(digest)
            or (size is not None and (not isinstance(size, int) or size <= 0))
        ):
            raise ReleaseManifestError("Invalid third-party source archive record")
        seen_filenames.add(filename)
    if seen_filenames != REQUIRED_SOURCE_ARCHIVES:
        raise ReleaseManifestError(
            "Third-party source delivery archive set is incomplete"
        )
    return value


def require_expected_asset(path: Path, expected_name: str) -> dict[str, int | str]:
    """Require an artifact filename and sidecar to match the release naming contract."""

    if path.name != expected_name:
        raise ReleaseManifestError(
            f"Unexpected release asset name: expected {expected_name}, got {path.name}"
        )
    verify_checksum_sidecar(path)
    return file_record(path)


def validate_platform_record(
    record_path: Path, *, platform: str, asset: dict[str, int | str]
) -> dict[str, Any]:
    """Require platform evidence to describe exactly the independently checked asset."""

    record = read_json_object(record_path, description=f"{platform} platform record")
    if record.get("platform") != platform:
        raise ReleaseManifestError(
            f"Platform record has the wrong platform: {record_path}"
        )
    if record.get("asset") != asset:
        raise ReleaseManifestError(
            f"Platform record asset does not match downloaded artifact: {record_path}"
        )
    verification = record.get("verification")
    tools = record.get("tool_versions")
    if (
        not isinstance(verification, dict)
        or set(verification) != REQUIRED_PLATFORM_CHECKS[platform]
        or any(value != "passed" for value in verification.values())
    ):
        raise ReleaseManifestError(
            f"Platform record contains incomplete verification: {record_path}"
        )
    if (
        not isinstance(tools, dict)
        or set(tools) != REQUIRED_PLATFORM_TOOLS[platform]
        or any(not isinstance(value, str) or not value for value in tools.values())
    ):
        raise ReleaseManifestError(
            f"Platform record is missing required tool versions: {record_path}"
        )
    return record


def source_file_hashes(project_root: Path, paths: tuple[str, ...]) -> dict[str, str]:
    """Hash tracked packaging or license evidence from the immutable source tree."""

    records: dict[str, str] = {}
    for relative in paths:
        path = project_root / relative
        if not path.is_file():
            raise ReleaseManifestError(
                f"Required source evidence is missing: {relative}"
            )
        records[relative] = sha256_file(path)
    return records


def validate_source_provenance(
    provenance_path: Path,
    *,
    context: dict[str, str],
    source_asset: dict[str, int | str],
) -> dict[str, Any]:
    """Require source archive metadata to bind this exact file to validated tag context."""

    provenance = read_json_object(
        provenance_path, description="source archive provenance"
    )
    if provenance.get("schema_version") != 1:
        raise ReleaseManifestError(
            "Source archive provenance schema version is unsupported"
        )
    if (
        provenance.get("context") != context
        or provenance.get("archive") != source_asset
    ):
        raise ReleaseManifestError(
            "Source archive provenance does not match context and archive"
        )
    return provenance


def create_manifest(
    *,
    project_root: Path,
    context_path: Path,
    windows_installer: Path,
    flatpak_bundle: Path,
    source_archive: Path,
    source_provenance_path: Path,
    windows_record_path: Path,
    flatpak_record_path: Path,
    workflow_run_id: str,
    workflow_run_url: str,
) -> dict[str, Any]:
    """Create a manifest from independently downloaded platform artifacts and source inputs."""

    context = read_context(context_path)
    version = context["version"]
    windows_asset = require_expected_asset(
        windows_installer, f"MDLoggerSetup-{version}.exe"
    )
    flatpak_asset = require_expected_asset(
        flatpak_bundle, f"MDLogger-{version}.flatpak"
    )
    source_asset = require_expected_asset(
        source_archive, f"MDLogger-{version}-source.tar.gz"
    )
    source_provenance = validate_source_provenance(
        source_provenance_path, context=context, source_asset=source_asset
    )
    windows_record = validate_platform_record(
        windows_record_path, platform="windows-x64", asset=windows_asset
    )
    flatpak_record = validate_platform_record(
        flatpak_record_path, platform="linux-flatpak-x86_64", asset=flatpak_asset
    )
    if not workflow_run_id or not workflow_run_url.startswith("https://"):
        raise ReleaseManifestError("Workflow run ID and HTTPS URL are required")

    return {
        "assets": {
            "flatpak_bundle": flatpak_asset,
            "source_archive": source_asset,
            "windows_installer": windows_asset,
        },
        "license_evidence_sha256": source_file_hashes(project_root, LICENSE_EVIDENCE),
        "packaging_inputs_sha256": source_file_hashes(project_root, PACKAGING_INPUTS),
        "platform_verification": {
            "flatpak": flatpak_record,
            "windows": windows_record,
        },
        "release": {
            "commit_sha": context["commit_sha"],
            "tag": context["tag"],
            "tag_object_sha": context["tag_object_sha"],
            "version": version,
        },
        "schema_version": 1,
        "source_archive_provenance": source_provenance,
        "third_party_source_delivery": load_source_delivery(project_root),
        "workflow": {
            "run_id": workflow_run_id,
            "run_url": workflow_run_url,
        },
    }


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    """Parse platform-record or final-manifest command arguments."""

    parser = argparse.ArgumentParser(
        description="Create desktop release provenance JSON"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    record = commands.add_parser("platform-record")
    record.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    record.add_argument("--asset", type=Path, required=True)
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("--check", action="append", default=[])
    record.add_argument("--tool", action="append", default=[])

    manifest = commands.add_parser("manifest")
    manifest.add_argument("--project-root", type=Path, default=Path.cwd())
    manifest.add_argument("--context", type=Path, required=True)
    manifest.add_argument("--windows-installer", type=Path, required=True)
    manifest.add_argument("--flatpak-bundle", type=Path, required=True)
    manifest.add_argument("--source-archive", type=Path, required=True)
    manifest.add_argument("--source-provenance", type=Path, required=True)
    manifest.add_argument("--windows-record", type=Path, required=True)
    manifest.add_argument("--flatpak-record", type=Path, required=True)
    manifest.add_argument("--workflow-run-id", required=True)
    manifest.add_argument("--workflow-run-url", required=True)
    manifest.add_argument("--output", type=Path, required=True)

    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    """Run one manifest creation command."""

    args = parse_args(arguments)
    try:
        if args.command == "platform-record":
            write_json(
                args.output,
                create_platform_record(
                    platform=args.platform,
                    asset=args.asset,
                    checks=args.check,
                    tools=args.tool,
                ),
            )
        else:
            write_json(
                args.output,
                create_manifest(
                    project_root=args.project_root.resolve(),
                    context_path=args.context,
                    windows_installer=args.windows_installer,
                    flatpak_bundle=args.flatpak_bundle,
                    source_archive=args.source_archive,
                    source_provenance_path=args.source_provenance,
                    windows_record_path=args.windows_record,
                    flatpak_record_path=args.flatpak_record,
                    workflow_run_id=args.workflow_run_id,
                    workflow_run_url=args.workflow_run_url,
                ),
            )
    except ReleaseManifestError as error:
        print(f"ERROR: {error}")
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
