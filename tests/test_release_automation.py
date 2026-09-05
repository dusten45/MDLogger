"""Desktop release automation contract tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIRECTORY = PROJECT_ROOT / "scripts" / "release"


def _load_release_module(filename: str, module_name: str):
    path = RELEASE_DIRECTORY / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


VALIDATE = _load_release_module(
    "validate_release_version.py", "mdlogger_release_version_validator"
)
ARCHIVE = _load_release_module("create_source_archive.py", "mdlogger_source_archive")
MANIFEST = _load_release_module(
    "create_release_manifest.py", "mdlogger_release_manifest"
)
VALIDATION = _load_release_module(
    "release_validation.py", "mdlogger_release_validation"
)


def _run_git(project_root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(project_root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_release_contract(root: Path, *, version: str = "1.2.3") -> None:
    version_path = root / "src/mdlogger/_version.py"
    version_path.parent.mkdir(parents=True)
    version_path.write_text(f'__version__ = "{version}"\n', encoding="utf-8")

    installer = root / "scripts/installer_windows.iss"
    installer.parent.mkdir(parents=True)
    installer.write_text(
        "\n".join(
            (
                "#ifndef MyAppVersion",
                "OutputBaseFilename=MDLoggerSetup-{#MyAppVersion}",
                "VersionInfoVersion={#MyAppVersion}",
                "ArchitecturesAllowed=x64compatible",
            )
        ),
        encoding="utf-8",
    )
    for relative in VALIDATE.REQUIRED_RELEASE_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def _init_release_repository(tmp_path: Path, *, version: str = "1.2.3") -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    _write_release_contract(root, version=version)
    _run_git(root, "init")
    _run_git(root, "config", "user.name", "Release test")
    _run_git(root, "config", "user.email", "release@example.test")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "release contract")
    return root


def _tag_annotated(root: Path, tag: str) -> None:
    _run_git(root, "tag", "-a", tag, "-m", tag)


def _write_checksum(path: Path) -> None:
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{MANIFEST.sha256_file(path)}  {path.name}\n", encoding="ascii", newline="\n"
    )


def _platform_tools(platform: str) -> list[str]:
    return [
        f"{name}=test-value"
        for name in sorted(MANIFEST.REQUIRED_PLATFORM_TOOLS[platform])
    ]


def _write_manifest_source_tree(root: Path) -> None:
    for relative in (*MANIFEST.PACKAGING_INPUTS, *MANIFEST.LICENSE_EVIDENCE):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"evidence: {relative}\n", encoding="utf-8")
    source_delivery = RELEASE_DIRECTORY / "third_party_source_delivery.json"
    (root / "scripts/release/third_party_source_delivery.json").write_text(
        source_delivery.read_text(encoding="utf-8"), encoding="utf-8"
    )


def test_validate_release_requires_an_annotated_clean_matching_tag(tmp_path):
    root = _init_release_repository(tmp_path)
    _tag_annotated(root, "v1.2.3")

    context = VALIDATE.validate_release(root, "v1.2.3")

    assert context.tag == "v1.2.3"
    assert context.version == "1.2.3"
    assert context.commit_sha == _run_git(root, "rev-parse", "HEAD")
    assert context.tag_object_sha == _run_git(root, "rev-parse", "refs/tags/v1.2.3")


def test_validate_release_rejects_lightweight_tag(tmp_path):
    root = _init_release_repository(tmp_path)
    _run_git(root, "tag", "v1.2.3")

    with pytest.raises(VALIDATE.ReleaseVersionError, match="annotated"):
        VALIDATE.validate_release(root, "v1.2.3")


@pytest.mark.parametrize("tag", ["1.2.3", "v1.2", "v1.2.3-rc1", "v1.2.3;echo bad"])
def test_validate_tag_format_rejects_unsafe_or_unsupported_release_tags(tag):
    with pytest.raises(VALIDATE.ReleaseVersionError):
        VALIDATE.validate_tag_format(tag)


def test_validate_release_rejects_tag_version_mismatch(tmp_path):
    root = _init_release_repository(tmp_path, version="1.2.4")
    _tag_annotated(root, "v1.2.3")

    with pytest.raises(VALIDATE.ReleaseVersionError, match="does not match"):
        VALIDATE.validate_release(root, "v1.2.3")


def test_source_archive_context_rechecks_tagged_source_version(tmp_path):
    root = _init_release_repository(tmp_path, version="1.2.4")
    _tag_annotated(root, "v1.2.3")
    context = {
        "tag": "v1.2.3",
        "version": "1.2.3",
        "tag_object_sha": _run_git(root, "rev-parse", "refs/tags/v1.2.3"),
        "commit_sha": _run_git(root, "rev-parse", "v1.2.3^{commit}"),
    }

    with pytest.raises(ARCHIVE.SourceArchiveError, match="version does not match"):
        ARCHIVE.verify_context_matches_repository(root, context)


def test_source_archive_context_rejects_unvalidated_tag_metadata(tmp_path):
    context_path = tmp_path / "release-context.json"
    context_path.write_text(
        json.dumps(
            {
                "tag": "v1.2.3",
                "version": "1.2.3",
                "commit_sha": "a" * 40,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ARCHIVE.SourceArchiveError, match="invalid tag"):
        ARCHIVE.load_context(context_path)


def test_create_source_archive_contains_only_committed_tag_source(tmp_path):
    root = _init_release_repository(tmp_path)
    _tag_annotated(root, "v1.2.3")
    commit = _run_git(root, "rev-parse", "v1.2.3^{commit}")
    (root / "untracked-secret.txt").write_text("must not be archived", encoding="utf-8")

    archive, checksum = ARCHIVE.create_source_archive(
        root,
        commit_sha=commit,
        version="1.2.3",
        output_directory=tmp_path / "release-inputs",
    )

    assert checksum.read_text(encoding="ascii") == (
        f"{ARCHIVE.sha256_file(archive)}  MDLogger-1.2.3-source.tar.gz\n"
    )
    with tarfile.open(archive, "r:gz") as source:
        names = source.getnames()
    assert "MDLogger-1.2.3/src/mdlogger/_version.py" in names
    assert "MDLogger-1.2.3/untracked-secret.txt" not in names


def test_verify_windows_payload_rejects_missing_files_and_excluded_content(tmp_path):
    payload = tmp_path / "MDLogger"
    payload.mkdir()

    with pytest.raises(VALIDATION.ReleaseValidationError, match="missing required"):
        VALIDATION.verify_windows_payload(payload)

    for relative in VALIDATION.WINDOWS_REQUIRED_FILES:
        path = payload / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("required", encoding="utf-8")
    (payload / "_internal").mkdir()
    (payload / "_internal" / "PAL-relaxed.hex").write_text(
        "forbidden", encoding="utf-8"
    )

    with pytest.raises(
        VALIDATION.ReleaseValidationError, match="excluded pyqtgraph palettes"
    ):
        VALIDATION.verify_windows_payload(payload)


def test_verify_checksum_file_rejects_a_mismatched_sidecar(tmp_path):
    artifact = tmp_path / "MDLogger-1.2.3.flatpak"
    artifact.write_bytes(b"bundle")
    _write_checksum(artifact)
    VALIDATION.verify_checksum_file(artifact, artifact.with_suffix(".flatpak.sha256"))

    artifact.with_suffix(".flatpak.sha256").write_text(
        f"{'0' * 64}  {artifact.name}\n", encoding="ascii"
    )
    with pytest.raises(VALIDATION.ReleaseValidationError, match="does not match"):
        VALIDATION.verify_checksum_file(
            artifact, artifact.with_suffix(".flatpak.sha256")
        )


def test_manifest_is_canonical_and_rejects_artifact_record_mismatch(tmp_path):
    source_root = tmp_path / "source"
    _write_manifest_source_tree(source_root)
    context_path = tmp_path / "release-context.json"
    context_path.write_text(
        json.dumps(
            {
                "tag": "v1.2.3",
                "version": "1.2.3",
                "tag_object_sha": "a" * 40,
                "commit_sha": "b" * 40,
            }
        ),
        encoding="utf-8",
    )

    installer = tmp_path / "MDLoggerSetup-1.2.3.exe"
    bundle = tmp_path / "MDLogger-1.2.3.flatpak"
    source = tmp_path / "MDLogger-1.2.3-source.tar.gz"
    for path, content in (
        (installer, b"windows"),
        (bundle, b"flatpak"),
        (source, b"source"),
    ):
        path.write_bytes(content)
        _write_checksum(path)
    source_provenance_path = tmp_path / "source-provenance.json"
    MANIFEST.write_json(
        source_provenance_path,
        {
            "archive": MANIFEST.file_record(source),
            "context": json.loads(context_path.read_text(encoding="utf-8")),
            "schema_version": 1,
        },
    )

    windows_record = MANIFEST.create_platform_record(
        platform="windows-x64",
        asset=installer,
        checks=sorted(MANIFEST.REQUIRED_PLATFORM_CHECKS["windows-x64"]),
        tools=_platform_tools("windows-x64"),
    )
    flatpak_record = MANIFEST.create_platform_record(
        platform="linux-flatpak-x86_64",
        asset=bundle,
        checks=sorted(MANIFEST.REQUIRED_PLATFORM_CHECKS["linux-flatpak-x86_64"]),
        tools=_platform_tools("linux-flatpak-x86_64"),
    )
    windows_record_path = tmp_path / "windows.json"
    flatpak_record_path = tmp_path / "flatpak.json"
    MANIFEST.write_json(windows_record_path, windows_record)
    MANIFEST.write_json(flatpak_record_path, flatpak_record)

    manifest = MANIFEST.create_manifest(
        project_root=source_root,
        context_path=context_path,
        windows_installer=installer,
        flatpak_bundle=bundle,
        source_archive=source,
        source_provenance_path=source_provenance_path,
        windows_record_path=windows_record_path,
        flatpak_record_path=flatpak_record_path,
        workflow_run_id="123",
        workflow_run_url="https://github.example.test/owner/repo/actions/runs/123",
    )

    assert manifest["assets"]["windows_installer"]["filename"] == installer.name
    assert manifest["third_party_source_delivery"]["delivery"]["automation_status"] == (
        "pending_manual_attachment"
    )
    first_output = tmp_path / "first-manifest.json"
    second_output = tmp_path / "second-manifest.json"
    MANIFEST.write_json(first_output, manifest)
    MANIFEST.write_json(second_output, manifest)
    assert first_output.read_bytes() == second_output.read_bytes()

    windows_record["asset"]["sha256"] = "0" * 64
    MANIFEST.write_json(windows_record_path, windows_record)
    with pytest.raises(MANIFEST.ReleaseManifestError, match="does not match"):
        MANIFEST.create_manifest(
            project_root=source_root,
            context_path=context_path,
            windows_installer=installer,
            flatpak_bundle=bundle,
            source_archive=source,
            source_provenance_path=source_provenance_path,
            windows_record_path=windows_record_path,
            flatpak_record_path=flatpak_record_path,
            workflow_run_id="123",
            workflow_run_url="https://github.example.test/owner/repo/actions/runs/123",
        )


def test_platform_record_rejects_missing_required_verification(tmp_path):
    asset = tmp_path / "MDLoggerSetup-1.2.3.exe"
    asset.write_bytes(b"windows")
    _write_checksum(asset)

    with pytest.raises(MANIFEST.ReleaseManifestError, match="checks are incomplete"):
        MANIFEST.create_platform_record(
            platform="windows-x64",
            asset=asset,
            checks=["installer-checksum"],
            tools=_platform_tools("windows-x64"),
        )


def test_platform_record_rejects_missing_required_tool_version(tmp_path):
    asset = tmp_path / "MDLogger-1.2.3.flatpak"
    asset.write_bytes(b"flatpak")
    _write_checksum(asset)
    tools = _platform_tools("linux-flatpak-x86_64")
    tools.remove("sdk-commit=test-value")

    with pytest.raises(
        MANIFEST.ReleaseManifestError, match="tool versions are incomplete"
    ):
        MANIFEST.create_platform_record(
            platform="linux-flatpak-x86_64",
            asset=asset,
            checks=sorted(MANIFEST.REQUIRED_PLATFORM_CHECKS["linux-flatpak-x86_64"]),
            tools=tools,
        )


def test_manual_source_delivery_inventory_is_grounded_in_the_source_offer():
    policy = json.loads(
        (RELEASE_DIRECTORY / "third_party_source_delivery.json").read_text(
            encoding="utf-8"
        )
    )
    source_offer = (
        PROJECT_ROOT / "licenses/sources/desktop-source-offer.md"
    ).read_text(encoding="utf-8")

    assert policy["delivery"]["delivery_location"] == "same_github_release"
    assert policy["delivery"]["automation_status"] == "pending_manual_attachment"
    assert policy["delivery"]["workflow_downloads_or_attaches_archives"] is False
    for archive in policy["archives"]:
        assert archive["filename"] in source_offer
        assert archive["url"] in source_offer
        assert archive["sha256"] in source_offer


def test_platform_scripts_keep_the_required_release_verification_boundaries():
    windows = (RELEASE_DIRECTORY / "verify_windows_release.ps1").read_text(
        encoding="utf-8"
    )
    flatpak = (RELEASE_DIRECTORY / "verify_flatpak_release.sh").read_text(
        encoding="utf-8"
    )

    assert "mdlogger.secret_scan" in windows
    assert "mdlogger.checksum" in windows
    assert "installer-silent-installation" in windows
    assert "verify_flatpak_license_payload.py" in flatpak
    assert "mdlogger.secret_scan" in flatpak
    assert "flatpak build-bundle" in flatpak
    assert "flatpak install --user" in flatpak


def test_workflow_keeps_release_writes_and_notes_in_the_final_draft_job():
    workflow = (PROJECT_ROOT / ".github/workflows/desktop-release.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "contents: read" in workflow
    assert workflow.count("contents: write") == 1
    assert "if: ${{ inputs.create_draft }}" in workflow
    assert "needs.windows.outputs.artifact_id" in workflow
    assert "needs.flatpak.outputs.artifact_id" in workflow
    assert "--draft" in workflow
    assert "--generate-notes" not in workflow
    assert "Source commit:" in workflow
    assert "Source archive SHA-256:" in workflow
    assert "web-deploy.yml" not in workflow
