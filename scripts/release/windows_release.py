#!/usr/bin/env python3
"""Sign Windows update metadata only after validating immutable release evidence."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from scripts.release import create_release_manifest as provenance
from scripts.release.validate_release_version import read_project_version

REPOSITORY = "dusten45/MDLogger"
TRUSTED_KEYS_PATH = Path("src/mdlogger/data/update-trusted-keys.json")
KEY_ID_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")
VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
UPDATE_CHECKS = frozenset(
    {
        "administrator-installation",
        "standalone-helper",
        "installed-helper",
        "reinstall-preserves-user-data",
    }
)
MAX_INSTALLER_BYTES = 1024 * 1024 * 1024


class WindowsReleaseError(RuntimeError):
    """A signed Windows release cannot be produced or verified safely."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise WindowsReleaseError("Duplicate JSON field")
        result[name] = value
    return result


def json_object(raw: bytes, *, limit: int = 64 * 1024) -> dict[str, Any]:
    if not raw or len(raw) > limit:
        raise WindowsReleaseError("JSON metadata exceeds its size limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError) as error:
        raise WindowsReleaseError("Invalid UTF-8 JSON metadata") from error
    if not isinstance(value, dict):
        raise WindowsReleaseError("JSON metadata must be an object")
    return value


def trusted_keys(path: Path) -> dict[str, rsa.RSAPublicKey]:
    value = json_object(path.read_bytes())
    if type(value.get("schema")) is not int or value["schema"] != 1:
        raise WindowsReleaseError("Unsupported trusted-key schema")
    records = value.get("keys")
    if not isinstance(records, list) or not records:
        raise WindowsReleaseError("Pinned update signing keys are missing")
    keys: dict[str, rsa.RSAPublicKey] = {}
    for record in records:
        if not isinstance(record, dict):
            raise WindowsReleaseError("Invalid pinned key record")
        key_id = record.get("key_id")
        if (
            not isinstance(key_id, str)
            or not KEY_ID_PATTERN.fullmatch(key_id)
            or key_id in keys
        ):
            raise WindowsReleaseError("Invalid or duplicate pinned key ID")
        try:
            modulus = base64.b64decode(record["modulus"], validate=True)
            exponent = base64.b64decode(record["exponent"], validate=True)
            if not modulus or modulus[0] == 0 or exponent != b"\x01\x00\x01":
                raise ValueError("Invalid RSA public numbers")
            key = rsa.RSAPublicNumbers(
                65537, int.from_bytes(modulus, "big")
            ).public_key()
        except (KeyError, TypeError, ValueError, binascii.Error) as error:
            raise WindowsReleaseError("Invalid pinned RSA public key") from error
        if not 3072 <= key.key_size <= 4096:
            raise WindowsReleaseError("Pinned RSA key must have 3072 to 4096 bits")
        keys[key_id] = key
    return keys


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise WindowsReleaseError("Missing signed timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise WindowsReleaseError("Signed timestamps must use UTC seconds") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise WindowsReleaseError("Signed timestamp is not canonical")
    return parsed


def verify_update(
    manifest_bytes: bytes,
    signature_bytes: bytes,
    *,
    keys_path: Path,
    installer: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify exact bytes, trust, freshness, fixed origin, and installer contents."""
    manifest = json_object(manifest_bytes, limit=16 * 1024)
    signature = json_object(signature_bytes, limit=4096)
    key_id = signature.get("key_id")
    keys = trusted_keys(keys_path)
    if (
        type(signature.get("schema")) is not int
        or signature["schema"] != 1
        or not isinstance(key_id, str)
        or key_id not in keys
        or manifest.get("key_id") != key_id
    ):
        raise WindowsReleaseError("Unknown or mismatched signing key")
    try:
        detached = base64.b64decode(signature["signature"], validate=True)
        keys[key_id].verify(
            detached, manifest_bytes, padding.PKCS1v15(), hashes.SHA256()
        )
    except (KeyError, ValueError, TypeError, binascii.Error, InvalidSignature) as error:
        raise WindowsReleaseError("Update signature verification failed") from error
    version = manifest.get("version")
    if (
        type(manifest.get("schema")) is not int
        or manifest["schema"] != 1
        or manifest.get("platform") != "windows-x64"
        or not isinstance(version, str)
        or not VERSION_PATTERN.fullmatch(version)
    ):
        raise WindowsReleaseError("Invalid Windows update version or platform")
    issued_at = _timestamp(manifest.get("issued_at"))
    expires_at = _timestamp(manifest.get("expires_at"))
    now = now or datetime.now(UTC)
    if not timedelta(0) < expires_at - issued_at <= timedelta(days=366):
        raise WindowsReleaseError("Invalid update validity interval")
    if issued_at > now + timedelta(minutes=5) or expires_at <= now:
        raise WindowsReleaseError("Update metadata is expired or not yet valid")
    asset = manifest.get("installer")
    expected_name = f"MDLoggerSetup-{version}.exe"
    expected_url = (
        f"https://github.com/{REPOSITORY}/releases/download/v{version}/{expected_name}"
    )
    if (
        not isinstance(asset, dict)
        or asset.get("name") != expected_name
        or asset.get("url") != expected_url
        or type(asset.get("size")) is not int
        or not 0 < asset["size"] <= MAX_INSTALLER_BYTES
        or not isinstance(asset.get("sha256"), str)
        or not provenance.SHA256_PATTERN.fullmatch(asset["sha256"])
    ):
        raise WindowsReleaseError("Invalid installer identity or download origin")
    if (
        installer.name != expected_name
        or not installer.is_file()
        or installer.stat().st_size != asset["size"]
        or provenance.sha256_file(installer) != asset["sha256"]
    ):
        raise WindowsReleaseError("Installer does not match signed metadata")
    return manifest


def sign_update(
    *,
    version: str,
    installer: Path,
    keys_path: Path,
    private_key_pem: str,
    now: datetime | None = None,
    validity_days: int = 90,
) -> tuple[bytes, bytes]:
    """Use a protected environment secret, never a CLI argument or private-key file."""
    if not private_key_pem.strip():
        raise WindowsReleaseError("MDLOGGER_UPDATE_SIGNING_KEY is missing")
    try:
        private = serialization.load_pem_private_key(
            private_key_pem.encode("ascii"), password=None
        )
    except (ValueError, TypeError, UnsupportedAlgorithm):
        # Do not expose parser diagnostics or any part of the private material.
        raise WindowsReleaseError("Update signing key cannot be loaded") from None
    if (
        not isinstance(private, rsa.RSAPrivateKey)
        or not 3072 <= private.key_size <= 4096
    ):
        raise WindowsReleaseError("Update signing key must be RSA 3072 to 4096 bits")
    matching_ids = [
        key_id
        for key_id, key in trusted_keys(keys_path).items()
        if key.public_numbers() == private.public_key().public_numbers()
    ]
    if len(matching_ids) != 1:
        raise WindowsReleaseError(
            "Signing key does not uniquely match a pinned public key"
        )
    if type(validity_days) is not int or not 1 <= validity_days <= 366:
        raise WindowsReleaseError("Update validity must be 1 to 366 days")
    if not VERSION_PATTERN.fullmatch(version):
        raise WindowsReleaseError("Invalid release version")
    asset = provenance.require_expected_asset(installer, f"MDLoggerSetup-{version}.exe")
    issued_at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    manifest_bytes = provenance.canonical_json(
        {
            "schema": 1,
            "key_id": matching_ids[0],
            "version": version,
            "platform": "windows-x64",
            "issued_at": issued_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (issued_at + timedelta(days=validity_days)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "installer": {
                "name": installer.name,
                "url": f"https://github.com/{REPOSITORY}/releases/download/v{version}/{installer.name}",
                "size": asset["size_bytes"],
                "sha256": asset["sha256"],
            },
        }
    ).encode("utf-8")
    signature_bytes = provenance.canonical_json(
        {
            "schema": 1,
            "key_id": matching_ids[0],
            "signature": base64.b64encode(
                private.sign(manifest_bytes, padding.PKCS1v15(), hashes.SHA256())
            ).decode("ascii"),
        }
    ).encode("utf-8")
    verify_update(
        manifest_bytes,
        signature_bytes,
        keys_path=keys_path,
        installer=installer,
        now=issued_at,
    )
    return manifest_bytes, signature_bytes


def update_record(installer: Path, helper: Path, keys_path: Path) -> dict[str, Any]:
    return {
        "schema": 1,
        "installer": provenance.file_record(installer),
        "helper": provenance.file_record(helper),
        "trusted_keys_sha256": provenance.sha256_file(keys_path),
        "verification": {name: "passed" for name in sorted(UPDATE_CHECKS)},
    }


def assemble(args: argparse.Namespace) -> None:
    """Recheck downloaded build evidence before exposing the signing key to use."""
    context = provenance.read_context(args.inputs / "release-context.json")
    version = context["version"]
    if read_project_version(args.project_root) != version:
        raise WindowsReleaseError(
            "Extracted source version does not match release context"
        )
    archive = args.inputs / f"MDLogger-{version}-source.tar.gz"
    source = provenance.require_expected_asset(archive, archive.name)
    source_provenance = provenance.validate_source_provenance(
        args.inputs / "source-provenance.json", context=context, source_asset=source
    )
    installer = args.artifacts / f"MDLoggerSetup-{version}.exe"
    asset = provenance.require_expected_asset(installer, installer.name)
    record = provenance.validate_platform_record(
        args.artifacts / "windows-verification.json",
        platform="windows-x64",
        asset=asset,
    )
    keys_path = args.project_root / TRUSTED_KEYS_PATH
    helper = args.artifacts / "MDLoggerUpdate.exe"
    updater_record = json_object(
        (args.artifacts / "windows-update-verification.json").read_bytes()
    )
    if updater_record != update_record(installer, helper, keys_path):
        raise WindowsReleaseError(
            "Updater verification record does not match release inputs"
        )
    packaging_inputs = provenance.source_file_hashes(
        args.project_root,
        (
            "uv.lock",
            "pyproject.toml",
            "MDLogger.spec",
            "scripts/installer_windows.iss",
            "scripts/update/build_helper.ps1",
            TRUSTED_KEYS_PATH.as_posix(),
            "scripts/desktop_license_policy.json",
        ),
    )
    manifest, signature = sign_update(
        version=version,
        installer=installer,
        keys_path=keys_path,
        private_key_pem=os.environ.pop("MDLOGGER_UPDATE_SIGNING_KEY", ""),
    )
    args.output.mkdir(parents=True, exist_ok=False)
    for path in (installer, installer.with_suffix(".exe.sha256")):
        shutil.copyfile(path, args.output / path.name)
    (args.output / f"MDLogger-{version}-update.json").write_bytes(manifest)
    (args.output / f"MDLogger-{version}-update.json.sig").write_bytes(signature)
    provenance.write_json(
        args.output / "windows-release-provenance.json",
        {
            "schema": 1,
            "release": context,
            "source_archive_provenance": source_provenance,
            "windows_verification": record,
            "updater_verification": updater_record,
            "signed_manifest_sha256": provenance.sha256_file(
                args.output / f"MDLogger-{version}-update.json"
            ),
            "packaging_inputs_sha256": packaging_inputs,
        },
    )


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("assemble")
    build.add_argument("--project-root", type=Path, default=Path.cwd())
    build.add_argument("--inputs", type=Path, required=True)
    build.add_argument("--artifacts", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    record = commands.add_parser("record")
    record.add_argument("--installer", type=Path, required=True)
    record.add_argument("--helper", type=Path, required=True)
    record.add_argument("--keys", type=Path, default=TRUSTED_KEYS_PATH)
    record.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--signature", type=Path, required=True)
    verify.add_argument("--installer", type=Path, required=True)
    verify.add_argument("--keys", type=Path, default=TRUSTED_KEYS_PATH)
    args = parser.parse_args(arguments)
    try:
        if args.command == "assemble":
            assemble(args)
        elif args.command == "record":
            trusted_keys(args.keys)
            provenance.write_json(
                args.output, update_record(args.installer, args.helper, args.keys)
            )
        else:
            verify_update(
                args.manifest.read_bytes(),
                args.signature.read_bytes(),
                keys_path=args.keys,
                installer=args.installer,
            )
    except (WindowsReleaseError, provenance.ReleaseManifestError, OSError) as error:
        print(f"ERROR: {error}")
        return 1
    print("Windows release verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
