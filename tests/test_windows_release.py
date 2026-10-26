"""Windows release signing and protected workflow regression tests."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from mdlogger._version import __version__
from mdlogger.updater import verify_manifest

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
with patch.object(sys, "path", [str(ROOT), *sys.path]):
    provenance = import_module("scripts.release.create_release_manifest")
    release = import_module("scripts.release.windows_release")


def test_installer_default_version_matches_application():
    script = (ROOT / "scripts" / "installer_windows.iss").read_text(encoding="utf-8")
    assert f'#define MyAppVersion "{__version__}"' in script


@pytest.fixture(scope="module")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def _public_record(key: rsa.RSAPrivateKey, key_id: str = "test-only") -> dict[str, str]:
    numbers = key.public_key().public_numbers()
    return {
        "key_id": key_id,
        "modulus": base64.b64encode(
            numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
        ).decode("ascii"),
        "exponent": base64.b64encode(b"\x01\x00\x01").decode("ascii"),
    }


def _pem(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def _checksum(path: Path) -> None:
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{provenance.sha256_file(path)}  {path.name}\n", encoding="ascii"
    )


@pytest.fixture
def signing_inputs(tmp_path, private_key):
    keys = tmp_path / "keys.json"
    provenance.write_json(keys, {"schema": 1, "keys": [_public_record(private_key)]})
    installer = tmp_path / "MDLoggerSetup-2.1.0.exe"
    installer.write_bytes(b"MZ offline installer fixture")
    _checksum(installer)
    return {
        "version": "2.1.0",
        "installer": installer,
        "keys_path": keys,
        "private_key_pem": _pem(private_key),
        "now": NOW,
    }


def _verify(manifest, signature, inputs, *, now=NOW):
    return release.verify_update(
        manifest,
        signature,
        keys_path=inputs["keys_path"],
        installer=inputs["installer"],
        now=now,
    )


def _resign(manifest, private_key):
    raw = provenance.canonical_json(manifest).encode("utf-8")
    return raw, provenance.canonical_json(
        {
            "schema": 1,
            "key_id": "test-only",
            "signature": base64.b64encode(
                private_key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
            ).decode("ascii"),
        }
    ).encode("utf-8")


def test_release_signer_interoperates_with_bundled_updater(signing_inputs):
    manifest, signature = release.sign_update(**signing_inputs)
    value = _verify(manifest, signature, signing_inputs)
    plan = verify_manifest(
        manifest,
        signature,
        current_version="2.0.0",
        expected_version="2.1.0",
        trusted_keys=json.loads(signing_inputs["keys_path"].read_bytes()),
        now=NOW,
    )
    assert value["key_id"] == "test-only"
    assert value["expires_at"] == "2027-01-22T12:00:00Z"
    assert plan.version == "2.1.0"
    assert plan.sha256 == provenance.sha256_file(signing_inputs["installer"])
    assert plan.manifest == manifest
    assert manifest.endswith(b"\n") and b"\r" not in manifest
    assert release.sign_update(**signing_inputs) == (manifest, signature)


@pytest.mark.parametrize(
    "private_key_pem", ["", "secret-invalid-key", "not-ascii-한글"]
)
def test_signing_errors_do_not_disclose_private_material(
    signing_inputs, private_key_pem
):
    signing_inputs["private_key_pem"] = private_key_pem
    with pytest.raises(release.WindowsReleaseError) as result:
        release.sign_update(**signing_inputs)
    assert not private_key_pem or private_key_pem not in str(result.value)


def test_signing_requires_an_exact_pinned_key_match(signing_inputs):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    provenance.write_json(
        signing_inputs["keys_path"], {"schema": 1, "keys": [_public_record(other_key)]}
    )
    with pytest.raises(release.WindowsReleaseError, match="does not uniquely match"):
        release.sign_update(**signing_inputs)


@pytest.mark.parametrize("records", [[], [{"key_id": "bad"}]])
def test_missing_or_malformed_public_keys_fail_closed(signing_inputs, records):
    provenance.write_json(signing_inputs["keys_path"], {"schema": 1, "keys": records})
    with pytest.raises(release.WindowsReleaseError):
        release.sign_update(**signing_inputs)


def test_duplicate_trust_ids_are_rejected(signing_inputs, private_key):
    provenance.write_json(
        signing_inputs["keys_path"],
        {
            "schema": 1,
            "keys": [_public_record(private_key), _public_record(private_key)],
        },
    )
    with pytest.raises(release.WindowsReleaseError, match="duplicate"):
        release.sign_update(**signing_inputs)


def test_signer_rejects_weak_rsa_key(signing_inputs):
    signing_inputs["private_key_pem"] = _pem(
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )
    with pytest.raises(release.WindowsReleaseError, match="3072"):
        release.sign_update(**signing_inputs)


def test_metadata_requires_exact_bytes_not_equivalent_json(signing_inputs):
    manifest, signature = release.sign_update(**signing_inputs)
    for changed in (manifest + b" ", manifest.replace(b"\n", b"\r\n")):
        with pytest.raises(release.WindowsReleaseError, match="signature verification"):
            _verify(changed, signature, signing_inputs)


def test_installer_mutation_is_rejected(signing_inputs):
    manifest, signature = release.sign_update(**signing_inputs)
    original = signing_inputs["installer"].read_bytes()
    signing_inputs["installer"].write_bytes(b"X" + original[1:])
    with pytest.raises(release.WindowsReleaseError, match="does not match"):
        _verify(manifest, signature, signing_inputs)


@pytest.mark.parametrize(
    "offset", [timedelta(days=90), -timedelta(minutes=5, seconds=1)]
)
def test_expired_or_future_metadata_is_rejected(signing_inputs, offset):
    manifest, signature = release.sign_update(**signing_inputs)
    with pytest.raises(release.WindowsReleaseError, match="expired or not yet valid"):
        _verify(manifest, signature, signing_inputs, now=NOW + offset)


@pytest.mark.parametrize("days", [0, 367, True])
def test_signer_bounds_validity_period(signing_inputs, days):
    with pytest.raises(release.WindowsReleaseError, match="1 to 366"):
        release.sign_update(**signing_inputs, validity_days=days)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "url",
            "https://github.com/attacker/MDLogger/releases/download/v2.1.0/MDLoggerSetup-2.1.0.exe",
        ),
        (
            "url",
            "https://github.com/dusten45/MDLogger/releases/download/v2.1.0/MDLoggerSetup-2.1.0.exe?redirect=1",
        ),
        ("name", "../MDLoggerSetup-2.1.0.exe"),
        ("size", True),
        ("size", 0),
        ("size", 1024 * 1024 * 1024 + 1),
        ("sha256", "A" * 64),
    ],
)
def test_even_signed_invalid_installer_metadata_is_rejected(
    signing_inputs, private_key, field, value
):
    raw, _ = release.sign_update(**signing_inputs)
    manifest = json.loads(raw)
    manifest["installer"][field] = value
    raw, signature = _resign(manifest, private_key)
    with pytest.raises(release.WindowsReleaseError, match="installer identity"):
        _verify(raw, signature, signing_inputs)


@pytest.mark.parametrize(
    ("field", "value"),
    [("key_id", "unknown"), ("platform", "linux-x64"), ("schema", True)],
)
def test_signed_identity_cannot_be_confused(signing_inputs, private_key, field, value):
    raw, _ = release.sign_update(**signing_inputs)
    manifest = json.loads(raw)
    manifest[field] = value
    raw, signature = _resign(manifest, private_key)
    with pytest.raises(release.WindowsReleaseError):
        _verify(raw, signature, signing_inputs)


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(release.WindowsReleaseError, match="Duplicate"):
        release.json_object(b'{"schema":1,"schema":1}')


def test_production_trust_bundle_contains_only_valid_public_material():
    path = ROOT / release.TRUSTED_KEYS_PATH
    assert b"PRIVATE KEY" not in path.read_bytes()
    keys = release.trusted_keys(path)
    assert keys and "test-only" not in keys


def test_release_requires_existing_checksum(signing_inputs):
    signing_inputs["installer"].with_suffix(".exe.sha256").unlink()
    with pytest.raises(provenance.ReleaseManifestError, match="sidecar"):
        release.sign_update(**signing_inputs)


@pytest.fixture
def assembly_inputs(tmp_path, signing_inputs, monkeypatch):
    project = tmp_path / "source"
    for relative in (
        "src/mdlogger/_version.py",
        "uv.lock",
        "pyproject.toml",
        "MDLogger.spec",
        "scripts/installer_windows.iss",
        "scripts/update/build_helper.ps1",
        "scripts/desktop_license_policy.json",
    ):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('__version__ = "2.1.0"\n', encoding="utf-8")
    provenance.write_json(
        project / release.TRUSTED_KEYS_PATH,
        json.loads(signing_inputs["keys_path"].read_bytes()),
    )
    context = {
        "tag": "v2.1.0",
        "version": "2.1.0",
        "tag_object_sha": "a" * 40,
        "commit_sha": "b" * 40,
    }
    inputs = tmp_path / "inputs"
    provenance.write_json(inputs / "release-context.json", context)
    archive = inputs / "MDLogger-2.1.0-source.tar.gz"
    archive.write_bytes(b"immutable archive fixture")
    _checksum(archive)
    provenance.write_json(
        inputs / "source-provenance.json",
        {
            "schema_version": 1,
            "context": context,
            "archive": provenance.file_record(archive),
        },
    )
    artifacts = signing_inputs["installer"].parent
    helper = artifacts / "MDLoggerUpdate.exe"
    helper.write_bytes(b"MZ independent helper fixture")
    provenance.write_json(
        artifacts / "windows-verification.json",
        provenance.create_platform_record(
            platform="windows-x64",
            asset=signing_inputs["installer"],
            checks=sorted(provenance.REQUIRED_PLATFORM_CHECKS["windows-x64"]),
            tools=[
                f"{tool}=fixture"
                for tool in provenance.REQUIRED_PLATFORM_TOOLS["windows-x64"]
            ],
        ),
    )
    provenance.write_json(
        artifacts / "windows-update-verification.json",
        release.update_record(
            signing_inputs["installer"],
            helper,
            signing_inputs["keys_path"],
        ),
    )
    monkeypatch.setenv("MDLOGGER_UPDATE_SIGNING_KEY", signing_inputs["private_key_pem"])
    return argparse.Namespace(
        project_root=project,
        inputs=inputs,
        artifacts=artifacts,
        output=tmp_path / "assets",
    )


def test_assembly_signs_only_verified_artifacts(assembly_inputs):
    release.assemble(assembly_inputs)
    assert {path.name for path in assembly_inputs.output.iterdir()} == {
        "MDLoggerSetup-2.1.0.exe",
        "MDLoggerSetup-2.1.0.exe.sha256",
        "MDLogger-2.1.0-update.json",
        "MDLogger-2.1.0-update.json.sig",
        "windows-release-provenance.json",
    }
    for path in assembly_inputs.output.iterdir():
        assert b"PRIVATE KEY" not in path.read_bytes()


@pytest.mark.parametrize(
    "filename", ["windows-verification.json", "windows-update-verification.json"]
)
def test_assembly_rejects_incomplete_build_evidence(assembly_inputs, filename):
    path = assembly_inputs.artifacts / filename
    record = json.loads(path.read_bytes())
    record["verification"].pop(next(iter(record["verification"])))
    provenance.write_json(path, record)
    with pytest.raises((release.WindowsReleaseError, provenance.ReleaseManifestError)):
        release.assemble(assembly_inputs)
    assert not assembly_inputs.output.exists()


def test_assembly_rejects_source_archive_mismatch_before_signing(assembly_inputs):
    (assembly_inputs.inputs / "MDLogger-2.1.0-source.tar.gz").write_bytes(b"changed")
    with pytest.raises(provenance.ReleaseManifestError, match="sidecar"):
        release.assemble(assembly_inputs)
    assert not assembly_inputs.output.exists()


def test_assembly_missing_secret_does_not_create_partial_release(
    assembly_inputs, monkeypatch
):
    monkeypatch.delenv("MDLOGGER_UPDATE_SIGNING_KEY")
    with pytest.raises(release.WindowsReleaseError, match="missing"):
        release.assemble(assembly_inputs)
    assert not assembly_inputs.output.exists()


def test_windows_workflow_preserves_immutable_protected_draft_boundary():
    workflow = (ROOT / ".github/workflows/windows-release.yml").read_text(
        encoding="utf-8"
    )
    prepare, windows, signing = (
        workflow.split("    windows:")[0],
        workflow.split("    windows:")[1].split("    sign-and-draft:")[0],
        workflow.split("    sign-and-draft:")[1],
    )
    assert "workflow_dispatch:" in prepare and "ref: ${{ inputs.tag }}" in prepare
    assert "create_source_archive.py" in prepare
    assert "uv sync --locked --group dev" in windows
    for command in (
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run ty check",
        "uv run pytest --ignore=tests/integration",
        "generate_desktop_licenses.py --check",
        "pip-audit==2.10.1",
        "-VerifyUpdater",
    ):
        assert command in windows
    specification = (ROOT / "MDLogger.spec").read_text(encoding="utf-8")
    assert "subprocess.run(" in specification
    assert "scripts/update/UpdateHelper.cs" in specification
    assert "check=True" in specification
    assert (
        'copy2(update_helper, distribution_root / "MDLoggerUpdate.exe")'
        in specification
    )
    assert windows.index("uv run pyinstaller") < windows.index("-VerifyUpdater")
    assert "MDLOGGER_UPDATE_SIGNING_KEY" not in prepare + windows
    assert "environment: desktop-release\n" in signing
    assert workflow.count("contents: write") == 1
    assert "needs.windows.outputs.artifact_id" in signing
    assert (
        signing.index("windows_release assemble")
        < signing.index("verify_windows_update_signature.ps1")
        < signing.index("gh release create")
    )
    assert "--verify-tag --draft" in signing
    assert "RELEASE_TAG: ${{ needs.prepare.outputs.tag }}" in signing
    assert '--title "$env:RELEASE_TAG"' in signing
    assert signing.count("--title ") == 1
    assert "--clobber" not in workflow and "release edit" not in workflow
    assert "flatpak-builder" not in workflow and "web-deploy" not in workflow
    assert "-update.json.sig" in signing and '-update.json"' in signing


def test_native_release_verification_checks_negative_cases_without_installing():
    script = (ROOT / "scripts/release/verify_windows_update_signature.ps1").read_text(
        encoding="utf-8"
    )
    assert "--verify-payload" in script
    assert "Test-NativeVerification -Expected 0" in script
    assert script.count("Test-NativeVerification -Expected 2") == 3
    assert "-WorkingDirectory $scratch -Wait -PassThru" in script
    assert "PRIVATE KEY" not in script
