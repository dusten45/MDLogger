"""데스크톱 제3자 라이선스 inventory·배포 포함 회귀 테스트."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from shutil import copy2, copytree

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "generate_desktop_licenses.py"
MODULE_NAME = "mdlogger_desktop_license_generator"
SPEC = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
LICENSES = importlib.util.module_from_spec(SPEC)
sys.modules[MODULE_NAME] = LICENSES
SPEC.loader.exec_module(LICENSES)

VERIFIER_PATH = PROJECT_ROOT / "scripts" / "verify_flatpak_license_payload.py"
VERIFIER_MODULE_NAME = "mdlogger_flatpak_license_verifier"
VERIFIER_SPEC = importlib.util.spec_from_file_location(
    VERIFIER_MODULE_NAME, VERIFIER_PATH
)
assert VERIFIER_SPEC is not None and VERIFIER_SPEC.loader is not None
FLATPAK_VERIFIER = importlib.util.module_from_spec(VERIFIER_SPEC)
sys.modules[VERIFIER_MODULE_NAME] = FLATPAK_VERIFIER
VERIFIER_SPEC.loader.exec_module(FLATPAK_VERIFIER)


def _fixture_dist_info(
    tmp_path: Path,
    *,
    license_header: str | None,
    license_value: str | None,
) -> Path:
    dist_info = tmp_path / "fixture_package-1.2.3.dist-info"
    (dist_info / "licenses").mkdir(parents=True)
    metadata_lines = [
        "Metadata-Version: 2.4",
        "Name: fixture-package",
        "Version: 1.2.3",
    ]
    if license_header is not None and license_value is not None:
        metadata_lines.append(f"{license_header}: {license_value}")
    (dist_info / "METADATA").write_text(
        "\n".join(metadata_lines) + "\n",
        encoding="utf-8",
    )
    (dist_info / "licenses" / "LICENSE.txt").write_text(
        "fixture license\n",
        encoding="utf-8",
    )
    return dist_info


def _fixture_policy() -> dict[str, object]:
    return {
        "name": "fixture-package",
        "version": "1.2.3",
        "metadata_license": {
            "source": "License-Expression",
            "value": "MIT",
        },
        "metadata_license_files": [
            "fixture_package-1.2.3.dist-info/licenses/LICENSE.txt"
        ],
    }


def test_metadata_fixture_reads_exact_name_version_license_and_files(tmp_path):
    dist_info = _fixture_dist_info(
        tmp_path,
        license_header="License-Expression",
        license_value="MIT",
    )

    record = LICENSES.metadata_record_from_dist_info(dist_info)

    assert record.name == "fixture-package"
    assert record.version == "1.2.3"
    assert record.license_source == "License-Expression"
    assert record.license_value == "MIT"
    assert record.legal_files == (
        "fixture_package-1.2.3.dist-info/licenses/LICENSE.txt",
    )
    LICENSES.validate_metadata_record(_fixture_policy(), record)


@pytest.mark.parametrize("license_value", [None, "", "UNKNOWN"])
def test_metadata_fixture_rejects_missing_or_unknown_license(tmp_path, license_value):
    dist_info = _fixture_dist_info(
        tmp_path,
        license_header="License-Expression" if license_value is not None else None,
        license_value=license_value,
    )
    record = LICENSES.metadata_record_from_dist_info(dist_info)

    with pytest.raises(LICENSES.ComplianceError, match="missing or UNKNOWN"):
        LICENSES.validate_metadata_record(_fixture_policy(), record)


def test_metadata_fixture_rejects_missing_exact_legal_file(tmp_path):
    dist_info = _fixture_dist_info(
        tmp_path,
        license_header="License-Expression",
        license_value="MIT",
    )
    (dist_info / "licenses" / "LICENSE.txt").unlink()
    record = LICENSES.metadata_record_from_dist_info(dist_info)

    with pytest.raises(LICENSES.ComplianceError, match="legal-file drift"):
        LICENSES.validate_metadata_record(_fixture_policy(), record)


def test_policy_rejects_unreviewed_expression():
    policy = copy.deepcopy(LICENSES.load_policy())
    policy["packages"][0]["selected_license_expression"] = "LicenseRef-Unreviewed"

    with pytest.raises(LICENSES.ComplianceError, match="Unreviewed license"):
        LICENSES.validate_policy(policy)


def test_policy_rejects_missing_tracked_original():
    policy = copy.deepcopy(LICENSES.load_policy())
    policy["packages"][0]["license_files"][0]["path"] = (
        "licenses/desktop/cffi-2.1.1/licenses/DOES-NOT-EXIST"
    )

    with pytest.raises(LICENSES.ComplianceError, match="Missing tracked legal file"):
        LICENSES.validate_policy(policy)


def test_default_policy_records_numpy_native_known_limitation():
    policy = LICENSES.load_policy()

    expected_components = {
        "NumPy Linux OpenBLAS and LAPACK",
        "GNU libgfortran runtime from NumPy Linux wheel",
        "GNU libquadmath runtime from NumPy Linux wheel",
    }
    notes = {
        component["name"]: component["review_notes"]
        for component in policy["components"]
        if component["name"] in expected_components
    }

    assert policy["known_blockers"] == []
    assert "release_blockers" not in policy
    assert set(notes) == expected_components
    assert all(note.startswith("Known limitation:") for note in notes.values())
    LICENSES.validate_policy(policy)


def test_qt_license_corpus_preserves_all_unique_source_texts():
    policy = LICENSES.load_policy()
    manifest = json.loads(
        (
            PROJECT_ROOT
            / "licenses"
            / "desktop"
            / "qt-6.11.1"
            / "LICENSES-MANIFEST.json"
        ).read_text(encoding="utf-8")
    )

    assert manifest["source_sha256"] == (
        "252acef8c5ae68074d91cadba2ee4a83465051bbb970dd26e8f0daa0f3904e03"
    )
    assert manifest["archive_license_member_count"] == 402
    assert manifest["unique_license_file_count"] == 83
    LICENSES.validate_qt_license_corpus(policy)


def test_qt_source_attributions_preserve_linux_scope_and_legal_files():
    policy = LICENSES.load_policy()
    document = json.loads(
        (
            PROJECT_ROOT
            / "licenses"
            / "desktop"
            / "qt-6.11.1"
            / "QT-THIRD-PARTY-ATTRIBUTIONS.json"
        ).read_text(encoding="utf-8")
    )

    assert document["exact_build_sbom_available"] is False
    assert document["record_count"] == 123
    assert (
        document["source_archive"]["sha256"]
        == policy["qt_source_attributions"]["source_archive_sha256"]
    )
    expressions = {record["attribution"]["LicenseId"] for record in document["records"]}
    assert "AFL-2.1 OR GPL-2.0-or-later" in expressions
    assert "MPL-2.0" in expressions
    assert any("Bison-exception-2.2" in expression for expression in expressions)
    legal_files = {
        legal_file["path"]
        for record in document["records"]
        for legal_file in record["legal_files"]
    }
    assert len(legal_files) == 88
    LICENSES.validate_qt_source_attributions(policy)


def test_source_document_hash_drift_is_rejected():
    policy = copy.deepcopy(LICENSES.load_policy())
    policy["source_documents"]["files"][0]["sha256"] = "0" * 64

    with pytest.raises(LICENSES.ComplianceError, match="desktop source documents"):
        LICENSES.validate_policy(policy)


def test_cryptography_wheel_sbom_evidence_is_exact_and_limited():
    policy = LICENSES.load_policy()
    evidence = policy["cryptography_wheel_sbom_evidence"]

    assert evidence["exact_build_sbom_available"] is True
    assert evidence["openssl"]["version"] == "4.0.1"
    assert evidence["rust"]["component_count"] == 39
    assert "Apache-2.0 WITH LLVM-exception" in evidence["rust"]["license_expressions"]
    assert "Apache-2.0 OR GPL-2.0-only" in evidence["rust"]["license_expressions"]
    LICENSES.validate_cryptography_wheel_sbom_evidence(policy)


def test_windows_policy_validation_skips_linux_wheel_evidence(monkeypatch):
    policy = LICENSES.load_policy()
    monkeypatch.setattr(LICENSES, "host_platform", lambda: "windows")
    monkeypatch.setattr(
        LICENSES,
        "validate_cryptography_wheel_sbom_evidence",
        lambda *_args, **_kwargs: pytest.fail(
            "Windows policy validation must not load Linux wheel evidence"
        ),
    )

    LICENSES.validate_policy(policy)


def test_qt_runtime_attributions_preserve_chromium_and_ffmpeg_evidence():
    policy = LICENSES.load_policy()
    runtime = policy["qt_runtime_attributions"]

    assert runtime["exact_build_sbom_available"] is False
    assert runtime["chromium"]["runtime_version"] == "140.0.7339.225"
    assert runtime["chromium"]["source_credits_component_count"] == 262
    assert "Linux source-tree superset" in runtime["chromium"]["source_credits_scope"]
    assert runtime["ffmpeg"]["version"] == "7.1.3"
    assert runtime["ffmpeg"]["runtime_license"] == "LGPL version 2.1 or later"
    ffmpeg = runtime["ffmpeg"]
    assert {component["id"] for component in ffmpeg["components"]} == {
        "ffmpeg",
        "ffmpeg-boost",
        "ffmpeg-libjpeg",
        "ffmpeg-zlib",
    }
    for expression in ("IJG", "Zlib", "BSL-1.0"):
        assert expression in ffmpeg["aggregate_attribution_expression"]
    LICENSES.validate_qt_runtime_attributions(policy)


def test_qt_runtime_inventory_tracks_binary_payload_and_no_exact_build_sbom():
    inventory = json.loads(
        (
            PROJECT_ROOT
            / "licenses"
            / "inventory"
            / "qt-third-party-runtime-linux-flatpak.json"
        ).read_text(encoding="utf-8")
    )

    assert inventory["exact_build_sbom_available"] is False
    assert inventory["chromium"]["runtime_version"] == "140.0.7339.225"
    assert inventory["chromium"]["source_credits"]["component_count"] == 262
    chromium_paths = {item["path"] for item in inventory["chromium"]["payload_files"]}
    assert "PySide6/Qt/lib/libQt6WebEngineCore.so.6" in chromium_paths
    assert "PySide6/Qt/libexec/QtWebEngineProcess" in chromium_paths

    assert inventory["ffmpeg"]["version"] == "7.1.3"
    ffmpeg_paths = {item["path"] for item in inventory["ffmpeg"]["payload_files"]}
    assert "PySide6/Qt/lib/libavcodec.so.61.19.101" in ffmpeg_paths
    assert "PySide6/Qt/plugins/multimedia/libffmpegmediaplugin.so" in ffmpeg_paths


def test_uv_tree_parser_deduplicates_and_rejects_version_conflicts():
    output = """mdlogger
├── alpha v1.0
│   └── shared-package v2.0
└── shared_package v2.0 (*)
"""
    assert LICENSES.parse_uv_tree(output) == {
        "alpha": "1.0",
        "shared-package": "2.0",
    }

    with pytest.raises(LICENSES.ComplianceError, match="Conflicting versions"):
        LICENSES.parse_uv_tree(output.replace("v2.0 (*)", "v3.0"))


def test_current_uv_closures_match_reviewed_counts_and_versions():
    policy = LICENSES.load_policy()
    closures = LICENSES.validate_platform_closures(policy)

    assert len(closures["linux"]) == 19
    assert len(closures["windows"]) == 15
    assert closures["linux"]["cryptography"] == "50.0.0"
    assert "cryptography" not in closures["windows"]
    assert closures["windows"]["pywin32-ctypes"] == "0.2.3"


def test_lock_version_drift_is_rejected():
    policy = LICENSES.load_policy()
    versions = LICENSES.load_lock_versions()
    versions["numpy"] = "0"

    with pytest.raises(LICENSES.ComplianceError, match="Lock version drift"):
        LICENSES.validate_lock_versions(policy, versions)


def test_generated_inventories_are_stably_sorted_without_duplicates():
    for filename, expected_count in (
        ("desktop-linux.json", 19),
        ("desktop-windows.json", 15),
    ):
        inventory = json.loads(
            (PROJECT_ROOT / "licenses" / "inventory" / filename).read_text(
                encoding="utf-8"
            )
        )
        names = [package["name"] for package in inventory["packages"]]
        assert len(names) == expected_count
        assert names == sorted(names, key=LICENSES.normalize_name)
        assert len(names) == len({LICENSES.normalize_name(name) for name in names})

    windows = json.loads(
        (PROJECT_ROOT / "licenses" / "inventory" / "desktop-windows.json").read_text(
            encoding="utf-8"
        )
    )
    assert windows["components"][0]["name"] == "PyInstaller bootloader"
    assert windows["components"][0]["version"] == "6.21.0"


def test_flatpak_qt_inventory_tracks_full_wheels_and_direct_imports():
    inventory = json.loads(
        (
            PROJECT_ROOT / "licenses" / "inventory" / "qt-modules-linux-flatpak.json"
        ).read_text(encoding="utf-8")
    )

    assert inventory["direct_source_imports"] == [
        "QtCore",
        "QtGui",
        "QtSvg",
        "QtWidgets",
    ]
    assert "QtCore" in inventory["binding_modules"]
    assert "libQt6Core.so.6" in inventory["qt_libraries"]
    assert inventory["translation_file_count"] > 0
    assert "QtWebEngineCore" in inventory["binding_modules"]
    assert "libQt6WebEngineCore.so.6" in inventory["qt_libraries"]
    assert "multimedia/libffmpegmediaplugin.so" in inventory["plugins"]
    assert inventory["excluded_files"] == [
        "pyqtgraph/colors/maps/PAL-relaxed.hex",
        "pyqtgraph/colors/maps/PAL-relaxed_bright.hex",
    ]


def test_flatpak_runtime_requirements_preserve_platform_markers():
    requirements = (PROJECT_ROOT / "flatpak" / "requirements-runtime.txt").read_text(
        encoding="utf-8"
    )
    assert "cryptography==50.0.0 ; sys_platform == 'linux'" in requirements
    assert "pywin32-ctypes==0.2.3 ; sys_platform == 'win32'" in requirements
    names = [
        LICENSES.normalize_name(line.split("==", 1)[0])
        for line in requirements.splitlines()
        if line and not line[0].isspace()
    ]
    assert "--hash=sha256:" in requirements
    assert names == sorted(names)
    assert len(names) == len(set(names))


def test_pyinstaller_spec_exposes_legal_files_and_excludes_unverified_palettes():
    spec = (PROJECT_ROOT / "MDLogger.spec").read_text(encoding="utf-8")
    assert 'copy2("LICENSE", distribution_root / "LICENSE")' in spec
    assert 'copy2("THIRD_PARTY_NOTICES.txt"' in spec
    assert 'copytree("licenses/desktop", distribution_licenses / "desktop")' in spec
    assert 'copytree("licenses/sources", distribution_licenses / "sources")' in spec
    assert '"licenses/inventory/desktop-windows.json"' in spec
    assert 'contents_directory="."' not in spec
    assert '"pyqtgraph/colors/maps/PAL-relaxed.hex"' in spec
    assert '"pyqtgraph/colors/maps/PAL-relaxed_bright.hex"' in spec
    assert "entry[0]" in spec


def test_inno_installs_and_checks_complete_onedir_legal_structure():
    installer = (PROJECT_ROOT / "scripts" / "installer_windows.iss").read_text(
        encoding="utf-8"
    )
    assert '#ifnexist "..\\dist\\MDLogger\\LICENSE"' in installer
    assert "THIRD_PARTY_NOTICES.txt is required" in installer
    assert "desktop-windows.json" in installer
    assert "desktop-source-offer.md" in installer
    assert "ArchitecturesAllowed=x64compatible" in installer
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in installer
    assert 'Source: "..\\dist\\MDLogger\\*"' in installer
    assert "recursesubdirs createallsubdirs" in installer


def test_flatpak_uses_pins_no_deps_and_installs_legal_documents():
    manifest = (
        PROJECT_ROOT / "flatpak" / "io.github.dusten45.MDLogger.yaml"
    ).read_text(encoding="utf-8")
    assert (
        "pip install --no-deps --require-hashes -r flatpak/requirements-runtime.txt"
        in manifest
    )
    assert "pip install --no-deps ." in manifest
    assert "site-packages/pip" in manifest
    assert (
        "verify_flatpak_license_payload.py --app-root /app --payload-phase wheel"
        in manifest
    )
    assert "/app/share/licenses/mdlogger/LICENSE" in manifest
    assert "/app/share/licenses/mdlogger/desktop" in manifest
    assert "desktop-linux.json" in manifest
    assert "desktop-windows.json" not in manifest
    assert "/app/share/doc/mdlogger/THIRD_PARTY_NOTICES.txt" in manifest
    assert "/app/share/doc/mdlogger/sources" in manifest
    assert (
        "rm -f /app/venv/lib/python3.13/site-packages/pyqtgraph/colors/maps/PAL-relaxed.hex"
        in manifest
    )
    assert (
        "test ! -e /app/venv/lib/python3.13/site-packages/pyqtgraph/colors/maps/PAL-relaxed_bright.hex"
        in manifest
    )


def test_flatpak_native_payload_policy_is_pinned_to_the_linux_wheel():
    policy = LICENSES.load_policy()
    payload = policy["flatpak_linux_native_payload"]

    assert [record["path"] for record in payload] == sorted(
        record["path"] for record in payload
    )
    assert {Path(record["path"]).name for record in payload} == {
        "_rust.abi3.so",
        "libgfortran-040039e1-0352e75f.so.5.0.0",
        "libquadmath-96973f99-934c22de.so.0.0.0",
        "libscipy_openblas64_-32a4b2a6.so",
    }
    openblas = next(
        record
        for record in payload
        if record["path"].endswith("libscipy_openblas64_-32a4b2a6.so")
    )
    assert openblas["wheel"] == {
        "size": 25409073,
        "sha256": "05c9f9eb89ee68a4b9d673184fa91c99587e736392c0c2d49180a8aa5303d080",
    }
    assert openblas["final_image"] == {
        "size": 25411168,
        "sha256": "bb3fa92ddcb248780063434a9f46701ecc2a949a15198af19e95078db765f7a4",
    }
    LICENSES.validate_flatpak_linux_native_payload(policy)


def _write_flatpak_license_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Create a synthetic final image whose evidence matches a copied policy."""

    policy = copy.deepcopy(LICENSES.load_policy())
    app_root = tmp_path / "app"
    site_packages = app_root / FLATPAK_VERIFIER.SITE_PACKAGES
    site_packages.mkdir(parents=True)

    for package in policy["packages"]:
        if "linux" not in package["platforms"]:
            continue
        dist_info = site_packages / f"{package['name']}-{package['version']}.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text(
            "Metadata-Version: 2.4\n"
            f"Name: {package['name']}\n"
            f"Version: {package['version']}\n",
            encoding="utf-8",
        )

    (app_root / "share/licenses/mdlogger").mkdir(parents=True)
    (app_root / "share/doc/mdlogger").mkdir(parents=True)
    copy2(PROJECT_ROOT / "LICENSE", app_root / "share/licenses/mdlogger/LICENSE")
    copy2(
        PROJECT_ROOT / "THIRD_PARTY_NOTICES.txt",
        app_root / "share/doc/mdlogger/THIRD_PARTY_NOTICES.txt",
    )
    copy2(
        PROJECT_ROOT / "THIRD_PARTY_NOTICES.md",
        app_root / "share/doc/mdlogger/THIRD_PARTY_NOTICES.md",
    )
    copytree(
        PROJECT_ROOT / "licenses/desktop",
        app_root / "share/licenses/mdlogger/desktop",
    )
    copytree(
        PROJECT_ROOT / "licenses/sources",
        app_root / "share/doc/mdlogger/sources",
    )

    inventory_directory = app_root / FLATPAK_VERIFIER.INVENTORY_DIRECTORY
    inventory_directory.mkdir(parents=True)
    copy2(
        PROJECT_ROOT / "licenses/inventory/desktop-linux.json",
        inventory_directory / "desktop-linux.json",
    )

    qt_distributions = [
        {
            "name": package["name"],
            "version": package["version"],
        }
        for package in policy["packages"]
        if package["name"] in {"PySide6-Essentials", "PySide6-Addons"}
    ]
    (inventory_directory / "qt-modules-linux-flatpak.json").write_text(
        json.dumps(
            {
                "platform": "linux-flatpak-x86_64",
                "distributions": qt_distributions,
                "binding_modules": [],
                "qt_libraries": [],
                "plugins": [],
                "qml_module_roots": [],
                "translation_file_count": 0,
                "resource_file_count": 0,
            }
        ),
        encoding="utf-8",
    )

    runtime = json.loads(
        (
            PROJECT_ROOT
            / "licenses/inventory/qt-third-party-runtime-linux-flatpak.json"
        ).read_text(encoding="utf-8")
    )
    for section, filename in (("chromium", "chromium.bin"), ("ffmpeg", "ffmpeg.bin")):
        contents = f"fixture {section}".encode()
        payload_path = site_packages / "PySide6/runtime" / filename
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_bytes(contents)
        runtime[section]["payload_files"] = [
            {
                "path": f"PySide6/runtime/{filename}",
                "size": len(contents),
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
        ]
    (inventory_directory / "qt-third-party-runtime-linux-flatpak.json").write_text(
        json.dumps(runtime), encoding="utf-8"
    )

    native_contents = b"fixture native payload"
    native_path = site_packages / "fixture-native.so"
    native_path.write_bytes(native_contents)
    native_pin = {
        "size": len(native_contents),
        "sha256": hashlib.sha256(native_contents).hexdigest(),
    }
    policy["flatpak_linux_native_payload"] = [
        {
            "path": "venv/lib/python3.13/site-packages/fixture-native.so",
            "wheel": native_pin,
            "final_image": native_pin,
        }
    ]

    for record in policy["cryptography_wheel_sbom_evidence"]["files"]:
        copied = PROJECT_ROOT / record["path"]
        installed = site_packages / record["installed_path"]
        installed.parent.mkdir(parents=True, exist_ok=True)
        copy2(copied, installed)

    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return app_root, policy_path


def test_flatpak_final_image_verifier_accepts_a_complete_matching_fixture(tmp_path):
    app_root, policy_path = _write_flatpak_license_fixture(tmp_path)

    FLATPAK_VERIFIER.verify(app_root, policy_path)
    FLATPAK_VERIFIER.verify(app_root, policy_path, payload_phase="wheel")


def test_windows_ci_does_not_treat_linux_runtime_evidence_as_payload_evidence():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    windows_job = workflow.split("    windows-package:", 1)[1]

    assert "Analysis-00.toc" in windows_job
    assert "COLLECT-00.toc" in windows_job
    assert (
        "Linux Qt runtime evidence must not be treated as Windows payload evidence"
        in windows_job
    )
    assert "ISCC.exe" in windows_job
    assert "Install and verify Inno Setup payload" in windows_job
    assert "/VERYSILENT" in windows_job
    assert "Installed Windows inventory missing" in windows_job


def test_generator_check_mode_is_deterministic():
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--check",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "checked successfully" in result.stdout
