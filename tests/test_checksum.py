"""배포 파일 SHA-256 체크섬 생성 테스트."""

from __future__ import annotations

import hashlib

from mdlogger.checksum import sha256_file, write_checksum


def test_write_checksum(tmp_path):
    artifact = tmp_path / "MDLogger.exe"
    artifact.write_bytes(b"mdlogger release")

    output = write_checksum(artifact)
    expected = hashlib.sha256(b"mdlogger release").hexdigest()

    assert sha256_file(artifact) == expected
    assert output.name == "MDLogger.exe.sha256"
    assert output.read_text(encoding="ascii") == f"{expected}  MDLogger.exe\n"
