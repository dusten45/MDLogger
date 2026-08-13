"""배포 파일 SHA-256 체크섬 생성 테스트."""

from __future__ import annotations

import hashlib

from mdlogger.checksum import sha256_file, write_checksum, write_checksum_tree


def test_write_checksum(tmp_path):
    artifact = tmp_path / "MDLogger.exe"
    artifact.write_bytes(b"mdlogger release")

    output = write_checksum(artifact)
    expected = hashlib.sha256(b"mdlogger release").hexdigest()

    assert sha256_file(artifact) == expected
    assert output.name == "MDLogger.exe.sha256"
    assert output.read_text(encoding="ascii") == f"{expected}  MDLogger.exe\n"


def test_write_checksum_tree(tmp_path):
    bundle = tmp_path / "MDLogger"
    (bundle / "_internal").mkdir(parents=True)
    exe = bundle / "MDLogger.exe"
    exe.write_bytes(b"mdlogger release")
    nested = bundle / "_internal" / "base_library.zip"
    nested.write_bytes(b"zipdata")

    output = write_checksum_tree(bundle)

    assert output.name == "MDLogger.sha256"
    assert output.suffix == ".sha256"
    assert sha256_file(exe) in output.read_text(encoding="ascii")
    lines = output.read_text(encoding="ascii").strip().splitlines()
    rels = [line.split("  ", 1)[1] for line in lines]
    assert "MDLogger.exe" in rels
    assert "_internal/base_library.zip" in rels
