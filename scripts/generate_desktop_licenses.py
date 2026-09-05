#!/usr/bin/env python3
"""Generate and verify deterministic desktop third-party license artifacts.

The runtime closure comes from ``uv.lock`` through frozen ``uv tree`` and
``uv export`` commands. License approval is intentionally manual: the policy
records the exact metadata value reviewed, the selected expression, and the
exact tracked legal files. Package metadata is evidence, not an allow decision.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT_ROOT / "scripts" / "desktop_license_policy.json"
LOCK_PATH = PROJECT_ROOT / "uv.lock"

MD_BEGIN = "<!-- BEGIN GENERATED DESKTOP THIRD-PARTY NOTICES -->"
MD_END = "<!-- END GENERATED DESKTOP THIRD-PARTY NOTICES -->"
WEB_MD_BEGIN = "<!-- BEGIN GENERATED WEB THIRD-PARTY NOTICES -->"
WEB_MD_END = "<!-- END GENERATED WEB THIRD-PARTY NOTICES -->"
TXT_BEGIN = "===== BEGIN GENERATED DESKTOP THIRD-PARTY NOTICES ====="
TXT_END = "===== END GENERATED DESKTOP THIRD-PARTY NOTICES ====="

LEGAL_NAME_PARTS = (
    "LICENSE",
    "LICENCE",
    "COPYING",
    "NOTICE",
    "AUTHORS",
    "COPYRIGHT",
)
UV_TREE_PATTERN = re.compile(r"(?:├──|└──)\s+([A-Za-z0-9_.-]+)\s+v([^\s(]+)")
NORMALIZE_PATTERN = re.compile(r"[-_.]+")
REQUIREMENT_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)")

WEBENGINE_RUNTIME_FILES = (
    "QtWebEngineCore.abi3.so",
    "QtWebEngineQuick.abi3.so",
    "QtWebEngineWidgets.abi3.so",
    "Qt/lib/libQt6WebEngineCore.so.6",
    "Qt/libexec/QtWebEngineProcess",
    "Qt/resources/icudtl.dat",
    "Qt/resources/qtwebengine_devtools_resources.pak",
    "Qt/resources/qtwebengine_resources.pak",
    "Qt/resources/qtwebengine_resources_100p.pak",
    "Qt/resources/qtwebengine_resources_200p.pak",
    "Qt/resources/v8_context_snapshot.bin",
)
FFMPEG_RUNTIME_FILES = (
    "Qt/lib/libQt6FFmpegStub-crypto.so.3",
    "Qt/lib/libQt6FFmpegStub-ssl.so.3",
    "Qt/lib/libQt6FFmpegStub-va-drm.so.2",
    "Qt/lib/libQt6FFmpegStub-va-x11.so.2",
    "Qt/lib/libQt6FFmpegStub-va.so.2",
    "Qt/lib/libavcodec.so.61.19.101",
    "Qt/lib/libavformat.so.61.7.100",
    "Qt/lib/libavutil.so.59.39.100",
    "Qt/lib/libswresample.so.5.3.100",
    "Qt/lib/libswscale.so.8.3.100",
    "Qt/plugins/multimedia/libffmpegmediaplugin.so",
)


class ComplianceError(RuntimeError):
    """Raised when reviewed license policy and distribution evidence diverge."""


@dataclass(frozen=True)
class DistributionMetadata:
    """Relevant Core Metadata and legal-file evidence for one distribution."""

    name: str
    version: str
    license_source: str
    license_value: str
    legal_files: tuple[str, ...]


def normalize_name(value: str) -> str:
    """Return the PEP 503-style comparison key used by uv and metadata."""

    return NORMALIZE_PATTERN.sub("-", value).lower()


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA256 digest for a tracked file."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_generated_text(content: str) -> str:
    """Normalize generated text to the repository's Git whitespace policy."""

    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip(" \t") for line in normalized.split("\n"))
    return normalized.rstrip("\n") + "\n"


def is_legal_file(path: str | Path) -> bool:
    """Identify legal files using the reviewed conservative filename policy."""

    name = Path(path).name.upper()
    return any(part in name for part in LEGAL_NAME_PARTS) or "CC0 LEGAL" in name


def selected_metadata_license(message: Any) -> tuple[str, str]:
    """Select metadata evidence without treating it as an approval decision."""

    for source in ("License-Expression", "License"):
        value = message.get(source)
        if value and value.strip():
            return source, value.strip()

    classifiers = message.get_all("Classifier") or []
    license_classifiers = sorted(
        value.strip() for value in classifiers if value.startswith("License ::")
    )
    if license_classifiers:
        return "Classifier", " AND ".join(license_classifiers)
    return "", ""


def metadata_record_from_dist_info(dist_info: Path) -> DistributionMetadata:
    """Read a test or unpacked wheel ``*.dist-info`` fixture."""

    metadata_path = dist_info / "METADATA"
    if not metadata_path.is_file():
        raise ComplianceError(f"Missing metadata file: {metadata_path}")
    with metadata_path.open("rb") as stream:
        message = BytesParser(policy=compat32).parse(stream)

    name = (message.get("Name") or "").strip()
    version = (message.get("Version") or "").strip()
    source, value = selected_metadata_license(message)
    legal_files = tuple(
        sorted(
            (
                path.relative_to(dist_info.parent).as_posix()
                for path in dist_info.rglob("*")
                if path.is_file() and is_legal_file(path)
            ),
            key=str.lower,
        )
    )
    return DistributionMetadata(name, version, source, value, legal_files)


def installed_metadata_record(name: str) -> DistributionMetadata:
    """Read installed metadata and its exact distribution legal-file list."""

    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError as error:
        raise ComplianceError(
            f"Missing installed runtime distribution: {name}"
        ) from error

    source, value = selected_metadata_license(distribution.metadata)
    legal_files = tuple(
        sorted(
            (
                str(path)
                for path in distribution.files or []
                if is_legal_file(str(path))
            ),
            key=str.lower,
        )
    )
    return DistributionMetadata(
        (distribution.metadata.get("Name") or name).strip(),
        distribution.version,
        source,
        value,
        legal_files,
    )


def _require_non_unknown(value: str, description: str) -> None:
    if not value.strip() or "UNKNOWN" in value.upper():
        raise ComplianceError(f"{description} is missing or UNKNOWN")


def validate_metadata_record(
    package: Mapping[str, Any], record: DistributionMetadata
) -> None:
    """Compare installed or fixture metadata with one exact manual override."""

    expected_name = str(package["name"])
    if normalize_name(record.name) != normalize_name(expected_name):
        raise ComplianceError(
            f"Metadata name drift for {expected_name}: found {record.name!r}"
        )
    if record.version != package["version"]:
        raise ComplianceError(
            f"Version drift for {expected_name}: expected {package['version']}, "
            f"found {record.version}"
        )
    _require_non_unknown(record.license_value, f"Metadata license for {expected_name}")

    expected_license = package["metadata_license"]
    if (record.license_source, record.license_value) != (
        expected_license["source"],
        expected_license["value"],
    ):
        raise ComplianceError(
            f"Metadata license drift for {expected_name}: expected "
            f"{expected_license['source']}={expected_license['value']!r}, found "
            f"{record.license_source}={record.license_value!r}"
        )

    platform_files = package.get("metadata_license_files_by_platform", {})
    if not isinstance(platform_files, Mapping):
        raise ComplianceError(
            f"Platform metadata legal files must be a mapping for {expected_name}"
        )
    expected_files = tuple(
        platform_files.get(host_platform(), package["metadata_license_files"])
    )
    if record.legal_files != expected_files:
        raise ComplianceError(
            f"Metadata legal-file drift for {expected_name}: expected "
            f"{list(expected_files)!r}, found {list(record.legal_files)!r}"
        )


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    """Load the reviewed JSON policy."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComplianceError(f"Cannot load desktop license policy: {path}") from error
    if not isinstance(value, dict):
        raise ComplianceError("Desktop license policy must be a JSON object")
    return value


def validate_policy(
    policy: Mapping[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
    allow_known_blockers: bool = False,
) -> None:
    """Validate exact expressions, tracked originals, hashes, and uniqueness."""

    if policy.get("schema_version") != 1:
        raise ComplianceError("Unsupported desktop license policy schema")

    reviewed = set(policy.get("reviewed_expressions", []))
    blockers = {blocker["id"] for blocker in policy.get("known_blockers", [])}

    seen_names: set[str] = set()

    for package in policy.get("packages", []):
        name = str(package.get("name", ""))
        normalized = normalize_name(name)
        if not normalized or normalized in seen_names:
            raise ComplianceError(f"Duplicate or missing package policy: {name!r}")
        seen_names.add(normalized)

        version = str(package.get("version", ""))
        expression = str(package.get("selected_license_expression", ""))
        _require_non_unknown(version, f"Version for {name}")
        _require_non_unknown(expression, f"Selected license for {name}")

        blocker_id = package.get("blocker_id")
        if expression not in reviewed:
            if not (
                allow_known_blockers
                and blocker_id
                and blocker_id in blockers
                and "LicenseRef-" in expression
            ):
                raise ComplianceError(
                    f"Unreviewed license expression for {name}: {expression}"
                )

        metadata_license = package.get("metadata_license", {})
        _require_non_unknown(
            str(metadata_license.get("value", "")), f"Metadata license for {name}"
        )
        _validate_file_records(package.get("license_files", []), project_root, name)
        _validate_unique_sorted(
            package.get("metadata_license_files", []),
            f"metadata legal files for {name}",
        )
        platform_metadata_files = package.get("metadata_license_files_by_platform", {})
        if not isinstance(platform_metadata_files, Mapping):
            raise ComplianceError(
                f"Platform metadata legal files must be a mapping for {name}"
            )
        for platform, files in platform_metadata_files.items():
            if platform not in package.get("platforms", []):
                raise ComplianceError(
                    f"Unexpected metadata legal-file platform for {name}: {platform}"
                )
            _validate_unique_sorted(
                files, f"metadata legal files for {name} on {platform}"
            )

    for component in policy.get("components", []):
        name = str(component.get("name", ""))
        expression = str(component.get("selected_license_expression", ""))
        _require_non_unknown(expression, f"Selected license for {name}")
        if expression not in reviewed:
            raise ComplianceError(
                f"Unreviewed component license expression for {name}: {expression}"
            )
        _validate_file_records(component.get("license_files", []), project_root, name)

    if blockers and not allow_known_blockers:
        blocker_list = ", ".join(sorted(blockers))
        raise ComplianceError(f"Known release blockers remain: {blocker_list}")

    _validate_file_records(
        policy.get("source_documents", {}).get("files", []),
        project_root,
        "desktop source documents",
    )
    validate_qt_license_corpus(policy, project_root=project_root)
    validate_qt_source_attributions(policy, project_root=project_root)
    validate_flatpak_linux_native_payload(policy)
    validate_qt_runtime_attributions(policy, project_root=project_root)
    if host_platform() == "linux":
        validate_cryptography_wheel_sbom_evidence(policy, project_root=project_root)


def _validate_unique_sorted(values: Sequence[str], description: str) -> None:
    if list(values) != sorted(set(values), key=str.lower):
        raise ComplianceError(f"{description} must be sorted and contain no duplicates")


def _validate_file_records(
    records: Sequence[Mapping[str, Any]], project_root: Path, owner: str
) -> None:
    paths = [str(record.get("path", "")) for record in records]
    _validate_unique_sorted(paths, f"tracked legal files for {owner}")
    if not paths:
        raise ComplianceError(f"No tracked legal files for {owner}")

    for record in records:
        relative = Path(str(record["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ComplianceError(f"Unsafe legal-file path for {owner}: {relative}")
        path = project_root / relative
        if not path.is_file():
            raise ComplianceError(f"Missing tracked legal file for {owner}: {relative}")

        expected_hash = str(record.get("sha256", ""))
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise ComplianceError(
                f"Tracked legal-file hash drift for {owner}: {relative}; "
                f"expected {expected_hash}, found {actual_hash}"
            )


def validate_qt_license_corpus(
    policy: Mapping[str, Any], *, project_root: Path = PROJECT_ROOT
) -> None:
    """Validate Qt's exact-version license corpus extracted from the official source."""

    corpus = policy.get("qt_license_corpus", {})
    manifest_relative = Path(str(corpus.get("manifest", "")))
    if manifest_relative.is_absolute() or ".." in manifest_relative.parts:
        raise ComplianceError("Unsafe Qt license corpus manifest path")
    manifest_path = project_root / manifest_relative
    if not manifest_path.is_file():
        raise ComplianceError(
            f"Missing Qt license corpus manifest: {manifest_relative}"
        )
    expected_manifest_hash = str(corpus.get("manifest_sha256", ""))
    if sha256_file(manifest_path) != expected_manifest_hash:
        raise ComplianceError("Qt license corpus manifest hash drift")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source_sha256") != corpus.get("source_archive_sha256"):
        raise ComplianceError("Qt license corpus source archive hash drift")
    files = manifest.get("files", [])
    if len(files) != corpus.get("unique_license_file_count"):
        raise ComplianceError("Qt license corpus file count drift")
    _validate_file_records(files, project_root, "Qt 6.11.1 license corpus")

    listed = {Path(str(record["path"])).resolve() for record in files}
    actual = {
        path.resolve()
        for path in (manifest_path.parent / "LICENSES").rglob("*")
        if path.is_file()
    }
    if actual != listed:
        raise ComplianceError("Qt license corpus contains stale or missing files")


def validate_flatpak_linux_native_payload(policy: Mapping[str, Any]) -> None:
    """Validate Linux wheel-native payload pins against the active Linux wheels."""

    records = policy.get("flatpak_linux_native_payload", [])
    paths = [str(record.get("path", "")) for record in records]
    _validate_unique_sorted(paths, "Flatpak native-payload paths")
    expected_prefix = (
        Path("venv") / "lib" / f"python{policy['python_version']}" / "site-packages"
    )
    for record in records:
        path = Path(str(record.get("path", "")))
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.is_relative_to(expected_prefix)
        ):
            raise ComplianceError(f"Unsafe Flatpak native-payload path: {path}")
        for phase in ("wheel", "final_image"):
            phase_record = record.get(phase)
            if not isinstance(phase_record, Mapping):
                raise ComplianceError(
                    f"Missing Flatpak native-payload {phase} pin: {path}"
                )
            if (
                not isinstance(phase_record.get("size"), int)
                or phase_record["size"] <= 0
            ):
                raise ComplianceError(
                    f"Invalid Flatpak native-payload {phase} size: {path}"
                )
            digest = str(phase_record.get("sha256", ""))
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ComplianceError(
                    f"Invalid Flatpak native-payload {phase} hash: {path}"
                )

    if not sys.platform.startswith("linux"):
        return

    site_packages = Path(sys.prefix) / expected_prefix.relative_to("venv")
    for record in records:
        policy_path = Path(str(record["path"]))
        installed = site_packages / policy_path.relative_to(expected_prefix)
        wheel = record["wheel"]
        if not installed.is_file():
            raise ComplianceError(
                f"Installed Linux native payload is missing: {policy_path}"
            )
        if installed.stat().st_size != wheel["size"]:
            raise ComplianceError(
                f"Installed Linux native payload size drift: {policy_path}"
            )
        if sha256_file(installed) != wheel["sha256"]:
            raise ComplianceError(
                f"Installed Linux native payload hash drift: {policy_path}"
            )


def validate_qt_runtime_attributions(
    policy: Mapping[str, Any], *, project_root: Path = PROJECT_ROOT
) -> None:
    """Validate exact QtWebEngine and FFmpeg attribution evidence."""

    runtime = policy.get("qt_runtime_attributions", {})
    if runtime.get("exact_build_sbom_available") is not False:
        raise ComplianceError(
            "Qt wheel publisher exact-build SBOM availability must be explicit"
        )

    chromium = runtime.get("chromium", {})
    _validate_file_records(
        chromium.get("files", []), project_root, "QtWebEngine Chromium"
    )
    webengine_root = project_root / "licenses" / "desktop" / "qt-6.11.1" / "qtwebengine"
    source_version_text = (webengine_root / "CHROMIUM_VERSION").read_text(
        encoding="utf-8"
    )
    based_on = re.search(r"Based on Chromium version:\s+(\S+)", source_version_text)
    patched_to = re.search(
        r"Patched with security patches up to Chromium version:\s+(\S+)",
        source_version_text,
    )
    if based_on is None or based_on.group(1) != chromium.get("source_based_on_version"):
        raise ComplianceError("QtWebEngine Chromium source-base version drift")
    if patched_to is None or patched_to.group(1) != chromium.get(
        "security_patch_version"
    ):
        raise ComplianceError("QtWebEngine Chromium security-patch version drift")

    chrome_version = dict(
        line.split("=", 1)
        for line in (webengine_root / "chrome-VERSION")
        .read_text(encoding="utf-8")
        .splitlines()
        if "=" in line
    )
    runtime_version = ".".join(
        chrome_version[key] for key in ("MAJOR", "MINOR", "BUILD", "PATCH")
    )
    if runtime_version != chromium.get("runtime_version"):
        raise ComplianceError("QtWebEngine Chromium runtime version drift")

    credits = (webengine_root / "chromium-source-credits.html").read_text(
        encoding="utf-8"
    )
    if not credits.startswith("<!-- Generated by licenses.py; do not edit. -->"):
        raise ComplianceError("QtWebEngine Chromium credits generator marker missing")
    if credits.count('<div class="product">') != chromium.get(
        "source_credits_component_count"
    ):
        raise ComplianceError("QtWebEngine Chromium source credits count drift")

    ffmpeg = runtime.get("ffmpeg", {})
    _require_non_unknown(
        str(ffmpeg.get("selected_license_expression", "")),
        "Qt Multimedia FFmpeg selected license",
    )
    _validate_file_records(
        ffmpeg.get("files", []), project_root, "Qt Multimedia FFmpeg"
    )
    attribution_path = (
        project_root
        / "licenses"
        / "desktop"
        / "qt-6.11.1"
        / "qtmultimedia"
        / "ffmpeg"
        / "qt_attribution.json"
    )
    attributions = json.loads(attribution_path.read_text(encoding="utf-8"))
    by_id = {item["Id"]: item for item in attributions}
    expected_ids = {"ffmpeg", "ffmpeg-boost", "ffmpeg-libjpeg", "ffmpeg-zlib"}
    if set(by_id) != expected_ids:
        raise ComplianceError("Qt Multimedia FFmpeg attribution component drift")
    expected_components = {item["id"]: item for item in ffmpeg.get("components", [])}
    if set(expected_components) != expected_ids:
        raise ComplianceError("Qt Multimedia FFmpeg policy component drift")
    for component_id in sorted(expected_ids):
        actual = by_id[component_id]
        expected = expected_components[component_id]
        fields = {
            "Name": "name",
            "LicenseId": "license_id",
            "Copyright": "copyright",
            "DownloadLocation": "download_location",
        }
        for actual_key, expected_key in fields.items():
            if actual.get(actual_key) != expected.get(expected_key):
                raise ComplianceError(
                    "Qt Multimedia FFmpeg attribution drift: "
                    f"{component_id} {actual_key}"
                )
        if "version" in expected and actual.get("Version") != expected["version"]:
            raise ComplianceError(
                f"Qt Multimedia FFmpeg attribution drift: {component_id} Version"
            )

    main = by_id["ffmpeg"]
    if main.get("LicenseId") != ffmpeg.get("selected_license_expression"):
        raise ComplianceError("Qt Multimedia FFmpeg main license drift")
    if main.get("DownloadLocation") != ffmpeg.get("source_url"):
        raise ComplianceError("Qt Multimedia FFmpeg attribution source URL drift")
    aggregate = str(ffmpeg.get("aggregate_attribution_expression", ""))
    _require_non_unknown(aggregate, "Qt Multimedia FFmpeg aggregate attribution")
    for expression in ("IJG", "Zlib", "BSL-1.0"):
        if expression not in aggregate:
            raise ComplianceError(
                f"Qt Multimedia FFmpeg aggregate attribution misses {expression}"
            )
    _require_non_unknown(
        str(ffmpeg.get("source_sha256", "")), "Qt Multimedia FFmpeg source SHA256"
    )


def validate_qt_source_attributions(
    policy: Mapping[str, Any], *, project_root: Path = PROJECT_ROOT
) -> None:
    """Validate curated Qt source attributions and every referenced legal file."""

    expected = policy.get("qt_source_attributions", {})
    if expected.get("exact_build_sbom_available") is not False:
        raise ComplianceError(
            "Qt source attribution exact-build SBOM availability must be explicit"
        )

    file_record = expected.get("file", {})
    _validate_file_records([file_record], project_root, "Qt source attributions")
    attribution_path = project_root / str(file_record.get("path", ""))
    document = json.loads(attribution_path.read_text(encoding="utf-8"))

    for key in ("exact_build_sbom_available", "record_count", "scope"):
        if document.get(key) != expected.get(key):
            raise ComplianceError(f"Qt source attribution {key} drift")
    source_archive = document.get("source_archive", {})
    if source_archive.get("sha256") != expected.get("source_archive_sha256"):
        raise ComplianceError("Qt source attribution source_archive_sha256 drift")

    records = document.get("records", [])
    if not isinstance(records, list) or len(records) != expected.get("record_count"):
        raise ComplianceError("Qt source attribution record count drift")

    sort_keys = [
        (
            str(item.get("source_path", "")),
            str(item.get("attribution", {}).get("Id", "")),
            str(item.get("attribution", {}).get("Name", "")),
        )
        for item in records
    ]
    if sort_keys != sorted(sort_keys) or len(sort_keys) != len(set(sort_keys)):
        raise ComplianceError(
            "Qt source attribution records are unsorted or duplicated"
        )

    expressions: set[str] = set()
    legal_files: dict[str, str] = {}
    legal_reference_count = 0
    for item in records:
        attribution = item.get("attribution", {})
        expression = str(attribution.get("LicenseId", ""))
        _require_non_unknown(
            expression,
            f"Qt source attribution license for {item.get('source_path', '')}",
        )
        expressions.add(expression)

        item_legal_files = item.get("legal_files", [])
        if item_legal_files != sorted(
            item_legal_files,
            key=lambda value: (str(value.get("path", "")), str(value.get("kind", ""))),
        ):
            raise ComplianceError("Qt source attribution legal files are not sorted")
        legal_reference_count += len(item_legal_files)
        for legal_file in item_legal_files:
            path = str(legal_file.get("path", ""))
            digest = str(legal_file.get("sha256", ""))
            previous = legal_files.setdefault(path, digest)
            if previous != digest:
                raise ComplianceError(
                    f"Conflicting Qt source attribution legal-file hash: {path}"
                )

    if sorted(expressions) != expected.get("reviewed_license_expressions"):
        raise ComplianceError("Qt source attribution license-expression drift")
    if len(legal_files) != expected.get("legal_file_count"):
        raise ComplianceError("Qt source attribution legal-file count drift")
    if legal_reference_count < len(legal_files):
        raise ComplianceError("Qt source attribution legal-file references are invalid")
    _validate_file_records(
        [
            {"path": path, "sha256": digest}
            for path, digest in sorted(
                legal_files.items(), key=lambda item: item[0].lower()
            )
        ],
        project_root,
        "Qt source attribution legal files",
    )


def validate_cryptography_wheel_sbom_evidence(
    policy: Mapping[str, Any], *, project_root: Path = PROJECT_ROOT
) -> None:
    """Validate copied Linux cryptography wheel SBOM evidence byte-for-byte."""

    evidence = policy.get("cryptography_wheel_sbom_evidence", {})
    if not evidence:
        raise ComplianceError("Missing cryptography wheel SBOM evidence policy")
    if evidence.get("exact_build_sbom_available") is not True:
        raise ComplianceError("Cryptography wheel SBOM availability must be explicit")

    distribution = importlib.metadata.distribution(
        str(evidence.get("distribution", ""))
    )
    if distribution.version != evidence.get("version"):
        raise ComplianceError("Cryptography wheel SBOM distribution version drift")

    records = evidence.get("files", [])
    _validate_file_records(records, project_root, "cryptography wheel SBOM evidence")
    installed_documents: dict[str, dict[str, Any]] = {}
    for record in records:
        installed_path = Path(str(record.get("installed_path", "")))
        if installed_path.is_absolute() or ".." in installed_path.parts:
            raise ComplianceError("Unsafe cryptography wheel SBOM installed path")
        installed = Path(str(distribution.locate_file(installed_path)))
        if not installed.is_file():
            raise ComplianceError(
                f"Installed cryptography wheel SBOM missing: {installed_path}"
            )
        if sha256_file(installed) != record.get("sha256"):
            raise ComplianceError(
                f"Installed cryptography wheel SBOM hash drift: {installed_path}"
            )
        installed_documents[installed_path.name] = json.loads(
            installed.read_text(encoding="utf-8")
        )

    openssl_document = installed_documents.get("sbom.json", {})
    components = openssl_document.get("components", [])
    openssl = evidence.get("openssl", {})
    if len(components) != 1 or components[0].get("name") != "openssl":
        raise ComplianceError("Cryptography OpenSSL SBOM component drift")
    component = components[0]
    if component.get("version") != openssl.get("version"):
        raise ComplianceError("Cryptography OpenSSL SBOM version drift")
    references = component.get("externalReferences", [])
    urls = {reference.get("url") for reference in references}
    if openssl.get("source_url") not in urls:
        raise ComplianceError("Cryptography OpenSSL SBOM source URL drift")
    hashes = {
        item.get("content")
        for item in component.get("hashes", [])
        if item.get("alg") == "SHA-256"
    }
    if openssl.get("source_sha256") not in hashes:
        raise ComplianceError("Cryptography OpenSSL SBOM source hash drift")
    properties = {
        item.get("name"): item.get("value") for item in component.get("properties", [])
    }
    if properties.get("build:flags") != openssl.get("build_flags"):
        raise ComplianceError("Cryptography OpenSSL SBOM build-flag drift")

    rust_document = installed_documents.get("cryptography-rust.cyclonedx.json", {})
    rust = evidence.get("rust", {})
    rust_components = rust_document.get("components", [])
    if len(rust_components) != rust.get("component_count"):
        raise ComplianceError("Cryptography Rust SBOM component count drift")
    expressions = sorted(
        {
            str(license_record.get("expression", ""))
            for component_record in rust_components
            for license_record in component_record.get("licenses", [])
            if license_record.get("expression")
        }
    )
    if expressions != rust.get("license_expressions"):
        raise ComplianceError("Cryptography Rust SBOM license-expression drift")
    reviewed_expressions = policy.get("reviewed_evidence_expressions", [])
    if expressions != reviewed_expressions:
        raise ComplianceError(
            "Cryptography Rust SBOM evidence expressions are unreviewed"
        )


def load_lock_versions(lock_path: Path = LOCK_PATH) -> dict[str, str]:
    """Read all package versions from ``uv.lock`` using stdlib TOML support."""

    with lock_path.open("rb") as stream:
        lock = tomllib.load(stream)
    versions: dict[str, str] = {}
    for package in lock.get("package", []):
        if "version" not in package:
            continue
        name = normalize_name(str(package["name"]))
        version = str(package["version"])
        previous = versions.setdefault(name, version)
        if previous != version:
            raise ComplianceError(
                f"Multiple locked versions are not supported for {name}: "
                f"{previous}, {version}"
            )
    return versions


def validate_lock_versions(
    policy: Mapping[str, Any], lock_versions: Mapping[str, str]
) -> None:
    """Fail when a reviewed package or manual build component drifts."""

    for package in policy["packages"]:
        name = normalize_name(package["name"])
        actual = lock_versions.get(name)
        if actual != package["version"]:
            raise ComplianceError(
                f"Lock version drift for {package['name']}: expected "
                f"{package['version']}, found {actual}"
            )

    pyinstaller = lock_versions.get("pyinstaller")
    bootloader = next(
        (
            component
            for component in policy.get("components", [])
            if component["name"] == "PyInstaller bootloader"
        ),
        None,
    )
    if bootloader is None or pyinstaller != bootloader["version"]:
        raise ComplianceError(
            "PyInstaller bootloader component version does not match locked PyInstaller"
        )


def run_uv(arguments: Sequence[str], *, project_root: Path = PROJECT_ROOT) -> str:
    """Run a frozen uv inspection command and return normalized stdout."""

    result = subprocess.run(
        ["uv", *arguments],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ComplianceError(f"uv {' '.join(arguments)} failed: {detail}")
    return result.stdout.replace("\r\n", "\n")


def parse_uv_tree(output: str) -> dict[str, str]:
    """Parse distribution/version pairs from human-readable ``uv tree`` output."""

    closure: dict[str, str] = {}
    for match in UV_TREE_PATTERN.finditer(output):
        name = normalize_name(match.group(1))
        version = match.group(2)
        previous = closure.setdefault(name, version)
        if previous != version:
            raise ComplianceError(
                f"Conflicting versions in uv tree for {name}: {previous}, {version}"
            )
    return closure


def resolve_uv_tree(
    platform: str,
    policy: Mapping[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, str]:
    """Resolve one reviewed platform closure from the frozen lock."""

    uv_platform = policy["uv_platforms"][platform]
    output = run_uv(
        [
            "tree",
            "--no-dev",
            "--frozen",
            "--python-version",
            str(policy["python_version"]),
            "--python-platform",
            uv_platform,
        ],
        project_root=project_root,
    )
    return parse_uv_tree(output)


def validate_platform_closures(
    policy: Mapping[str, Any], *, project_root: Path = PROJECT_ROOT
) -> dict[str, dict[str, str]]:
    """Validate the reviewed closure shape used by generated inventories."""

    closures: dict[str, dict[str, str]] = {}
    for platform in sorted(policy["uv_platforms"]):
        expected = {
            normalize_name(package["name"]): package["version"]
            for package in policy["packages"]
            if platform in package["platforms"]
        }
        expected_count = policy["expected_distribution_counts"][platform]
        if len(expected) != expected_count:
            raise ComplianceError(
                f"{platform} runtime distribution count drift: expected "
                f"{expected_count}, policy has {len(expected)}"
            )
        closures[platform] = expected
    return closures


def host_platform() -> str | None:
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return None


def validate_installed_metadata(policy: Mapping[str, Any]) -> None:
    """Validate exact wheel metadata for the host platform's runtime closure."""

    platform = host_platform()
    if platform is None:
        return
    for package in policy["packages"]:
        if platform not in package["platforms"]:
            continue
        validate_metadata_record(
            package, installed_metadata_record(str(package["name"]))
        )


def export_runtime_requirements(*, project_root: Path = PROJECT_ROOT) -> str:
    """Export exact runtime pins and artifact hashes with platform markers."""

    output = run_uv(
        [
            "export",
            "--no-dev",
            "--no-emit-project",
            "--no-annotate",
            "--no-header",
            "--frozen",
        ],
        project_root=project_root,
    )
    blocks: list[tuple[str, list[str]]] = []
    current: list[str] = []
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        if raw_line[0].isspace():
            if not current:
                raise ComplianceError(f"Unexpected exported hash line: {raw_line}")
            current.append(raw_line.rstrip())
            continue
        if current:
            match = REQUIREMENT_PATTERN.match(current[0])
            if match is None:
                raise ComplianceError(f"Unexpected exported requirement: {current[0]}")
            blocks.append((normalize_name(match.group(1)), current))
        current = [raw_line.rstrip()]
    if current:
        match = REQUIREMENT_PATTERN.match(current[0])
        if match is None:
            raise ComplianceError(f"Unexpected exported requirement: {current[0]}")
        blocks.append((normalize_name(match.group(1)), current))

    names = [name for name, _ in blocks]
    if len(names) != len(set(names)):
        raise ComplianceError("Duplicate exported runtime requirement")
    blocks.sort(key=lambda pair: pair[0])
    return "\n".join("\n".join(lines) for _, lines in blocks) + "\n"


def _inventory_package(package: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "copyright": package["copyright"],
        "dependency": "direct" if package["direct"] else "indirect",
        "homepage": package["homepage"],
        "license_files": package["license_files"],
        "local_modifications": package["local_modifications"],
        "metadata_license": package["metadata_license"],
        "name": package["name"],
        "purpose": package["purpose"],
        "review_notes": package["review_notes"],
        "selected_license_expression": package["selected_license_expression"],
        "source_repository": package["source_repository"],
        "version": package["version"],
    }


def render_inventory(
    platform: str,
    policy: Mapping[str, Any],
    closure: Mapping[str, str],
    *,
    lock_path: Path = LOCK_PATH,
) -> str:
    """Render one stable platform inventory as sorted JSON."""

    packages = sorted(
        (
            _inventory_package(package)
            for package in policy["packages"]
            if platform in package["platforms"]
        ),
        key=lambda package: normalize_name(package["name"]),
    )
    components = sorted(
        (
            dict(component)
            for component in policy.get("components", [])
            if platform in component["platforms"]
        ),
        key=lambda component: normalize_name(component["name"]),
    )
    inventory = {
        "blocking_issues": policy.get("known_blockers", []),
        "components": components,
        "distribution_count": len(closure),
        "generated_by": "scripts/generate_desktop_licenses.py",
        "lockfile_sha256": sha256_file(lock_path),
        "packages": packages,
        "platform": platform,
        "scope": (
            "Reviewed uv resolver closure; final Flatpak image verification is "
            "performed separately."
            if platform == "linux"
            else "Reviewed uv resolver closure; this is not an exact PyInstaller payload inventory."
        ),
        "python_version": policy["python_version"],
        "schema_version": 1,
        "uv_command": (
            "uv tree --no-dev --frozen "
            f"--python-version {policy['python_version']} "
            f"--python-platform {policy['uv_platforms'][platform]}"
        ),
    }
    return json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_flatpak_qt_inventory(*, project_root: Path = PROJECT_ROOT) -> str:
    """Render the Qt/PySide files installed by the locked Linux Flatpak wheels."""

    if not sys.platform.startswith("linux"):
        tracked = (
            project_root / "licenses" / "inventory" / "qt-modules-linux-flatpak.json"
        )
        if not tracked.is_file():
            raise ComplianceError(
                "Linux Qt module inventory must be generated on a Linux host"
            )
        return tracked.read_text(encoding="utf-8")

    distributions: list[dict[str, Any]] = []
    files: set[str] = set()
    for distribution_name in ("PySide6-Essentials", "PySide6-Addons"):
        distribution = importlib.metadata.distribution(distribution_name)
        distribution_files = sorted(
            file.as_posix()
            for file in (distribution.files or ())
            if file.as_posix().startswith("PySide6/")
        )
        distributions.append(
            {
                "name": distribution.metadata["Name"],
                "version": distribution.version,
                "installed_file_count": len(distribution_files),
            }
        )
        files.update(distribution_files)

    source_imports: set[str] = set()
    import_pattern = re.compile(r"PySide6\.(Qt[A-Za-z0-9_]+)")
    for source_path in sorted((project_root / "src").rglob("*.py")):
        source_imports.update(
            import_pattern.findall(source_path.read_text(encoding="utf-8"))
        )

    binding_modules = sorted(
        Path(file).name.split(".abi3", 1)[0].split(".", 1)[0]
        for file in files
        if file.startswith("PySide6/Qt") and file.endswith((".abi3.so", ".pyd"))
    )
    qt_libraries = sorted(
        Path(file).name
        for file in files
        if file.startswith("PySide6/Qt/lib/") and "Qt6" in Path(file).name
    )
    plugins = sorted(
        file.removeprefix("PySide6/Qt/plugins/")
        for file in files
        if file.startswith("PySide6/Qt/plugins/")
    )
    qml_modules = sorted(
        {
            file.removeprefix("PySide6/Qt/qml/").split("/", 1)[0]
            for file in files
            if file.startswith("PySide6/Qt/qml/")
        }
    )
    inventory = {
        "schema_version": 1,
        "platform": "linux-flatpak-x86_64",
        "scope": (
            "Files installed by the complete locked PySide6-Essentials and "
            "PySide6-Addons wheels; this is broader than modules imported by MDLogger."
        ),
        "distributions": distributions,
        "direct_source_imports": sorted(source_imports),
        "binding_modules": binding_modules,
        "qt_libraries": qt_libraries,
        "plugins": plugins,
        "qml_module_roots": qml_modules,
        "translation_file_count": sum(
            file.startswith("PySide6/Qt/translations/") for file in files
        ),
        "resource_file_count": sum(
            file.startswith("PySide6/Qt/resources/") for file in files
        ),
        "excluded_files": [
            "pyqtgraph/colors/maps/PAL-relaxed.hex",
            "pyqtgraph/colors/maps/PAL-relaxed_bright.hex",
        ],
        "license_path": "GPL-3.0-only",
        "corresponding_source": "licenses/sources/desktop-source-offer.md",
    }
    return json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _runtime_binary_record(package_root: Path, relative: str) -> dict[str, object]:
    path = package_root / relative
    if not path.is_file():
        raise ComplianceError(
            f"Missing locked PySide6 runtime file: PySide6/{relative}"
        )
    return {
        "path": f"PySide6/{relative}",
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _required_c_string(value: object, label: str) -> str:
    if not isinstance(value, bytes):
        raise ComplianceError(f"Unable to inspect {label}")
    return value.decode("utf-8")


def render_qt_third_party_runtime_inventory(
    policy: Mapping[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
    inspect_runtime: bool = True,
) -> str:
    """Render binary evidence for QtWebEngine/Chromium and FFmpeg on Linux."""

    tracked = (
        project_root
        / "licenses"
        / "inventory"
        / "qt-third-party-runtime-linux-flatpak.json"
    )
    if not inspect_runtime or not sys.platform.startswith("linux"):
        if not tracked.is_file():
            raise ComplianceError(
                "Linux Qt third-party runtime inventory must be generated on Linux"
            )
        return tracked.read_text(encoding="utf-8")

    runtime = policy["qt_runtime_attributions"]
    chromium_policy = runtime["chromium"]
    ffmpeg_policy = runtime["ffmpeg"]
    distribution = importlib.metadata.distribution("PySide6-Addons")
    package_root = Path(str(distribution.locate_file("PySide6"))).resolve()

    from PySide6.QtWebEngineCore import qWebEngineChromiumVersion, qWebEngineVersion

    qt_webengine_version = qWebEngineVersion()
    chromium_version = qWebEngineChromiumVersion()
    if qt_webengine_version != "6.11.1":
        raise ComplianceError(
            f"QtWebEngine runtime version drift: {qt_webengine_version}"
        )
    if chromium_version != chromium_policy["runtime_version"]:
        raise ComplianceError(f"Chromium runtime version drift: {chromium_version}")

    avcodec = ctypes.CDLL(str(package_root / "Qt/lib/libavcodec.so.61"))
    avutil = ctypes.CDLL(str(package_root / "Qt/lib/libavutil.so.59"))
    avcodec.avcodec_configuration.restype = ctypes.c_char_p
    avcodec.avcodec_license.restype = ctypes.c_char_p
    avutil.av_version_info.restype = ctypes.c_char_p
    ffmpeg_version = _required_c_string(
        avutil.av_version_info(), "FFmpeg runtime version"
    )
    ffmpeg_license = _required_c_string(
        avcodec.avcodec_license(), "FFmpeg runtime license"
    )
    ffmpeg_configure = _required_c_string(
        avcodec.avcodec_configuration(), "FFmpeg configure flags"
    )
    for value, expected, label in (
        (ffmpeg_version, ffmpeg_policy["version"], "version"),
        (ffmpeg_license, ffmpeg_policy["runtime_license"], "license"),
        (ffmpeg_configure, ffmpeg_policy["configure"], "configure flags"),
    ):
        if value != expected:
            raise ComplianceError(
                f"Qt Multimedia FFmpeg runtime {label} drift: {value}"
            )

    inventory = {
        "schema_version": 1,
        "platform": "linux-flatpak-x86_64",
        "scope": (
            "Binary inspection of the complete locked PySide6-Addons wheel "
            "installed by Flatpak."
        ),
        "distribution": {
            "name": distribution.metadata["Name"],
            "version": distribution.version,
        },
        "exact_build_sbom_available": runtime["exact_build_sbom_available"],
        "qt_source_attributions": {
            "path": policy["qt_source_attributions"]["file"]["path"],
            "record_count": policy["qt_source_attributions"]["record_count"],
            "legal_file_count": policy["qt_source_attributions"]["legal_file_count"],
            "reviewed_license_expressions": policy["qt_source_attributions"][
                "reviewed_license_expressions"
            ],
            "scope": policy["qt_source_attributions"]["scope"],
        },
        "chromium": {
            "qt_webengine_version": qt_webengine_version,
            "runtime_version": chromium_version,
            "source_based_on_version": chromium_policy["source_based_on_version"],
            "security_patch_version": chromium_policy["security_patch_version"],
            "payload_files": [
                _runtime_binary_record(package_root, relative)
                for relative in WEBENGINE_RUNTIME_FILES
            ],
            "source_credits": {
                "component_count": chromium_policy["source_credits_component_count"],
                "path": (
                    "licenses/desktop/qt-6.11.1/qtwebengine/"
                    "chromium-source-credits.html"
                ),
                "scope": chromium_policy["source_credits_scope"],
            },
            "legal_files": [record["path"] for record in chromium_policy["files"]],
        },
        "ffmpeg": {
            "version": ffmpeg_version,
            "runtime_license": ffmpeg_license,
            "selected_license_expression": ffmpeg_policy["selected_license_expression"],
            "aggregate_attribution_expression": ffmpeg_policy[
                "aggregate_attribution_expression"
            ],
            "components": ffmpeg_policy["components"],
            "configure": ffmpeg_configure,
            "source_url": ffmpeg_policy["source_url"],
            "source_sha256": ffmpeg_policy["source_sha256"],
            "payload_files": [
                _runtime_binary_record(package_root, relative)
                for relative in FFMPEG_RUNTIME_FILES
            ],
            "dynamic_system_dependencies": [
                "libbz2.so.1",
                "libm.so.6",
                "libz.so.1",
            ],
            "legal_files": [record["path"] for record in ffmpeg_policy["files"]],
        },
        "provenance_note": (
            "The PySide wheel publisher did not include an exact-build SBOM. "
            "This inventory therefore combines exact binary inspection with "
            "attribution metadata from the verified Qt 6.11.1 source archive."
        ),
    }
    return json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _markdown_desktop_section(policy: Mapping[str, Any]) -> str:
    lines = [
        "## Desktop distributions",
        "",
        "This section is generated from `uv.lock` and the manually reviewed ",
        "`scripts/desktop_license_policy.json`. It covers the supported Linux ",
        "Flatpak and Windows PyInstaller/Inno Setup distributions.",
        "",
        "- Review status: lockfile closures, tracked legal files, and selected ",
        "  license expressions are reviewed. Final Windows payload inspection ",
        "  remains a Windows release-host check.",
        "- Linux Flatpak resolver closure: 19 third-party distributions.",
        "- Windows resolver closure: 15 third-party distributions. This is not ",
        "  represented as an exact PyInstaller payload inventory.",
        "- Windows also embeds the PyInstaller bootloader 6.21.0 as a manually ",
        "  inventoried build component.",
        "- Qt/PySide6 is distributed under the selected `GPL-3.0-only` path.",
        "- Exact Qt/PySide6 corresponding-source instructions: ",
        "  `licenses/sources/desktop-source-offer.md`.",
        "- The 83 unique license texts from all 402 Qt 6.11.1 source archive ",
        "  `LICENSES` entries are preserved under `licenses/desktop/qt-6.11.1/`.",
        "- Qt package-specific source attribution: 123 records and 88 referenced ",
        "  legal files under `licenses/desktop/qt-6.11.1/`. This is a conservative ",
        "  Linux source-attribution superset, not an exact wheel-build SBOM.",
        "- The full Linux wheel also ships QtWebEngine with Chromium ",
        "  `140.0.7339.225` and Qt Multimedia with FFmpeg `7.1.3`; exact binary ",
        "  evidence is in `licenses/inventory/qt-third-party-runtime-linux-flatpak.json`.",
        "- Chromium's 262-component credits are a conservative Linux source-tree ",
        "  superset generated without the unavailable wheel publisher GN ",
        "  dependency graph: `licenses/desktop/qt-6.11.1/qtwebengine/",
        "  chromium-source-credits.html`.",
        "- FFmpeg 7.1.3 attribution covers FFmpeg, libjpeg, zlib, and Boost; its ",
        "  aggregate expression and all texts are under ",
        "  `licenses/desktop/qt-6.11.1/qtmultimedia/ffmpeg/`.",
        "- The PySide wheel publisher did not include an exact-build SBOM; the ",
        "  tracked evidence does not claim otherwise. Cryptography is separate: its ",
        "  Linux wheel ships exact OpenSSL and Rust build-provenance SBOM files under ",
        "  `licenses/desktop/cryptography-50.0.0/sboms/`; the Rust document is not ",
        "  an object-level linker map. Codec patent obligations ",
        "  can vary by format and distribution country and are not granted by Qt.",
        "- `PAL-relaxed.hex` and `PAL-relaxed_bright.hex` from pyqtgraph are ",
        "  excluded from both supported desktop distributions because their ",
        "  license and provenance could not be confirmed.",
    ]

    lines.extend(
        [
            "",
            "### Runtime distributions",
        ]
    )
    for package in sorted(
        policy["packages"], key=lambda value: normalize_name(value["name"])
    ):
        platforms = ", ".join(platform.title() for platform in package["platforms"])
        files = ", ".join(f"`{item['path']}`" for item in package["license_files"])
        lines.extend(
            [
                f"#### {package['name']} {package['version']}",
                "",
                f"- Platforms: {platforms}",
                f"- Dependency: {'direct' if package['direct'] else 'indirect'}",
                f"- Purpose: {package['purpose']}",
                f"- Selected license: `{package['selected_license_expression']}`",
                f"- Copyright/attribution: {package['copyright']}",
                f"- Homepage: {package['homepage']}",
                f"- Source: {package['source_repository']}",
                f"- Local modifications: {package['local_modifications']}",
                f"- Legal files: {files}",
                f"- Review note: {package['review_notes'] or 'No additional note.'}",
                "",
            ]
        )

    lines.extend(["### Additional distributed components", ""])
    for component in policy["components"]:
        files = ", ".join(f"`{item['path']}`" for item in component["license_files"])
        lines.extend(
            [
                f"#### {component['name']} {component['version']}",
                "",
                f"- Platforms: {', '.join(platform.title() for platform in component['platforms'])}",
                f"- Purpose: {component['purpose']}",
                f"- License: `{component['selected_license_expression']}`",
                f"- Copyright: {component['copyright']}",
                f"- Source: {component['source_repository']}",
                f"- Legal files: {files}",
                f"- Review note: {component['review_notes']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _text_desktop_section(policy: Mapping[str, Any]) -> str:
    lines = [
        "DESKTOP DISTRIBUTIONS",
        "=====================",
        "",
        "Review status: lockfile closures, tracked legal files, and selected license expressions are reviewed; final Windows payload inspection remains a Windows release-host check.",
        "Linux Flatpak resolver closure: 19 third-party distributions.",
        "Windows resolver closure: 15 third-party distributions plus PyInstaller bootloader 6.21.0; this is not an exact PyInstaller payload inventory.",
        "Qt/PySide6 selected license: GPL-3.0-only.",
        "Source instructions: licenses/sources/desktop-source-offer.md",
        "Qt license corpus: licenses/desktop/qt-6.11.1/LICENSES-MANIFEST.json (83 unique texts from 402 source entries).",
        "Qt package-specific attribution: 123-record conservative Linux source-attribution superset plus 88 referenced legal files; not an exact wheel-build SBOM.",
        "QtWebEngine Chromium runtime: 140.0.7339.225; 262-component conservative Linux source-tree superset generated without the unavailable wheel publisher GN dependency graph: licenses/desktop/qt-6.11.1/qtwebengine/chromium-source-credits.html.",
        "Qt Multimedia FFmpeg runtime: 7.1.3; attribution covers FFmpeg, libjpeg, zlib, and Boost: licenses/desktop/qt-6.11.1/qtmultimedia/ffmpeg/.",
        "Binary evidence: licenses/inventory/qt-third-party-runtime-linux-flatpak.json.",
        "The PySide wheel publisher did not include an exact-build SBOM; no exact-build SBOM is claimed for PySide.",
        "Cryptography Linux wheel SBOM evidence for OpenSSL and 39 Rust build components: licenses/desktop/cryptography-50.0.0/sboms/; the Rust document is not an object-level linker map.",
        "Codec patent obligations vary by format and country and are not granted by Qt.",
        "Excluded unverified assets: pyqtgraph/colors/maps/PAL-relaxed.hex and PAL-relaxed_bright.hex.",
        "",
        "RUNTIME DISTRIBUTIONS",
        "---------------------",
        "",
    ]
    for package in sorted(
        policy["packages"], key=lambda value: normalize_name(value["name"])
    ):
        files = ", ".join(item["path"] for item in package["license_files"])
        lines.extend(
            [
                f"{package['name']} {package['version']}",
                f"  Platforms: {', '.join(package['platforms'])}",
                f"  Dependency: {'direct' if package['direct'] else 'indirect'}",
                f"  Purpose: {package['purpose']}",
                f"  Selected license: {package['selected_license_expression']}",
                f"  Copyright/attribution: {package['copyright']}",
                f"  Homepage: {package['homepage']}",
                f"  Source: {package['source_repository']}",
                f"  Local modifications: {package['local_modifications']}",
                f"  Legal files: {files}",
                f"  Review note: {package['review_notes'] or 'No additional note.'}",
                "",
            ]
        )

    lines.extend(
        ["ADDITIONAL DISTRIBUTED COMPONENTS", "---------------------------------", ""]
    )
    for component in policy["components"]:
        files = ", ".join(item["path"] for item in component["license_files"])
        lines.extend(
            [
                f"{component['name']} {component['version']}",
                f"  Platforms: {', '.join(component['platforms'])}",
                f"  Purpose: {component['purpose']}",
                f"  License: {component['selected_license_expression']}",
                f"  Copyright: {component['copyright']}",
                f"  Source: {component['source_repository']}",
                f"  Legal files: {files}",
                f"  Review note: {component['review_notes']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _markdown_web_section(project_root: Path = PROJECT_ROOT) -> str:
    """Render the repository-level web summary from the reviewed web inventory."""

    inventory_path = project_root / "web" / "licenses" / "inventory.json"
    if not inventory_path.is_file():
        raise ComplianceError(f"Missing reviewed web inventory: {inventory_path}")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    packages = inventory.get("packages", [])
    expected_count = inventory.get("runtimePackageCount")
    if expected_count != len(packages):
        raise ComplianceError("Web runtime package count does not match its inventory")

    lines = [
        "## Web production distribution",
        "",
        "This section summarizes the reviewed Vite browser bundle, PWA registration ",
        "helper, and generated Workbox service worker inventory. The complete plain-text ",
        "notice is published as `web/public/third-party-notices.txt` and deployed at ",
        "`/third-party-notices.txt`.",
        "",
        f"- Runtime package count: {expected_count}.",
        "- Reviewed runtime license expressions: `MIT`, `0BSD`.",
        "- Package-specific originals: `web/public/licenses/`.",
        "- Actual bundle evidence is checked from temporary Vite production sourcemaps.",
        "- Sharp/libvips and other icon-generation, build, test, lint, and deploy tools ",
        "  are excluded because they are not present in the production browser or ",
        "  service-worker runtime.",
        "",
        "### Web runtime packages",
        "",
    ]
    for package in packages:
        files = ", ".join(
            f"`web/public/{item['path']}`" for item in package["licenseFiles"]
        )
        lines.extend(
            [
                f"- **{package['name']} {package['version']}** — "
                f"`{package['license']}`; evidence: `{package['bundleEvidence']}`; "
                f"legal files: {files}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def update_generated_section(
    current: str,
    *,
    begin: str,
    end: str,
    generated: str,
    preamble: str,
) -> str:
    """Replace only the desktop block so independently generated web text survives."""

    block = f"{begin}\n{generated.rstrip()}\n{end}"
    if not current:
        return f"{preamble.rstrip()}\n\n{block}\n"
    if begin in current or end in current:
        if current.count(begin) != 1 or current.count(end) != 1:
            raise ComplianceError("Generated notice markers are missing or duplicated")
        start = current.index(begin)
        finish = current.index(end, start) + len(end)
        return f"{current[:start]}{block}{current[finish:]}"
    return f"{current.rstrip()}\n\n{block}\n"


def build_outputs(
    policy: Mapping[str, Any],
    closures: Mapping[str, Mapping[str, str]],
    requirements: str,
    *,
    project_root: Path = PROJECT_ROOT,
    inspect_qt_runtime: bool = True,
) -> dict[Path, str]:
    """Build every generated file without writing it."""

    markdown_path = project_root / "THIRD_PARTY_NOTICES.md"
    text_path = project_root / "THIRD_PARTY_NOTICES.txt"
    markdown_current = (
        markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
    )
    text_current = text_path.read_text(encoding="utf-8") if text_path.exists() else ""

    markdown = update_generated_section(
        markdown_current,
        begin=MD_BEGIN,
        end=MD_END,
        generated=_markdown_desktop_section(policy),
        preamble=(
            "# Third-Party Notices\n\n"
            "Generated platform sections are delimited so desktop and web inventories "
            "can be maintained independently."
        ),
    )
    markdown = update_generated_section(
        markdown,
        begin=WEB_MD_BEGIN,
        end=WEB_MD_END,
        generated=_markdown_web_section(project_root),
        preamble=(
            "# Third-Party Notices\n\n"
            "Generated platform sections are delimited so desktop and web inventories "
            "can be maintained independently."
        ),
    )
    text = update_generated_section(
        text_current,
        begin=TXT_BEGIN,
        end=TXT_END,
        generated=_text_desktop_section(policy),
        preamble=(
            "MDLOGGER THIRD-PARTY NOTICES\n"
            "============================\n\n"
            "Generated platform sections are maintained independently."
        ),
    )

    return {
        project_root / "flatpak" / "requirements-runtime.txt": requirements,
        project_root / "licenses" / "inventory" / "desktop-linux.json": (
            render_inventory(
                "linux",
                policy,
                closures["linux"],
                lock_path=project_root / "uv.lock",
            )
        ),
        project_root / "licenses" / "inventory" / "desktop-windows.json": (
            render_inventory(
                "windows",
                policy,
                closures["windows"],
                lock_path=project_root / "uv.lock",
            )
        ),
        project_root / "licenses" / "inventory" / "qt-modules-linux-flatpak.json": (
            render_flatpak_qt_inventory(project_root=project_root)
        ),
        (
            project_root
            / "licenses"
            / "inventory"
            / "qt-third-party-runtime-linux-flatpak.json"
        ): render_qt_third_party_runtime_inventory(
            policy,
            project_root=project_root,
            inspect_runtime=inspect_qt_runtime,
        ),
        markdown_path: markdown,
        text_path: text,
    }


def write_or_check_outputs(outputs: Mapping[Path, str], *, check: bool) -> None:
    """Write generated text or fail if checked files differ byte-for-byte."""

    stale: list[str] = []
    normalized_outputs = {
        path: normalize_generated_text(expected) for path, expected in outputs.items()
    }
    for path, expected in sorted(
        normalized_outputs.items(), key=lambda item: str(item[0])
    ):
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if check:
            if current != expected:
                stale.append(path.relative_to(PROJECT_ROOT).as_posix())
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8", newline="\n")

    if stale:
        raise ComplianceError(
            "Generated desktop license artifacts are stale: " + ", ".join(stale)
        )


def generate(*, check: bool) -> None:
    """Validate all evidence, then generate or check committed artifacts."""

    policy = load_policy()
    validate_policy(policy)
    validate_lock_versions(policy, load_lock_versions())
    closures = validate_platform_closures(policy)
    validate_installed_metadata(policy)
    requirements = export_runtime_requirements()
    write_or_check_outputs(
        build_outputs(
            policy,
            closures,
            requirements,
            inspect_qt_runtime=not check,
        ),
        check=check,
    )


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if committed generated artifacts differ",
    )

    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = parse_args(arguments)
    try:
        generate(check=args.check)
    except ComplianceError as error:
        print(f"desktop license compliance failed: {error}", file=sys.stderr)
        return 1
    action = "checked" if args.check else "generated"
    print(f"desktop license artifacts {action} successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
