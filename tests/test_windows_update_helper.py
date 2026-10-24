"""Windows에서 독립 helper를 컴파일하고 서명 검증만 실행한다. 설치는 하지 않는다."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows 기본 .NET 컴파일러가 필요합니다."
)


@pytest.fixture(scope="module")
def native_helper(tmp_path_factory):
    root = tmp_path_factory.mktemp("native-updater")
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    public = key.public_key().public_numbers()
    keys = {
        "schema": 1,
        "keys": [
            {
                "key_id": "test-only",
                "modulus": base64.b64encode(public.n.to_bytes(384)).decode(),
                "exponent": "AQAB",
            }
        ],
    }
    trust = root / "keys.json"
    trust.write_text(json.dumps(keys), encoding="utf-8")
    helper = root / "MDLoggerUpdate.exe"
    source = Path(__file__).resolve().parents[1] / "scripts/update"
    compiler = (
        Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    )
    subprocess.run(
        [
            str(compiler),
            "/nologo",
            "/target:winexe",
            "/platform:anycpu",
            "/codepage:65001",
            f"/out:{helper}",
            "/reference:System.Web.Extensions.dll",
            "/reference:System.Windows.Forms.dll",
            f"/resource:{trust},MDLogger.UpdateTrustedKeys.json",
            f"/win32manifest:{source / 'update-helper.manifest'}",
            str(source / "UpdateHelper.cs"),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return helper, key


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "manifest-tamper",
        "installer-tamper",
        "signature-missing",
        "expired",
        "wrong-key-id",
    ],
)
def test_standalone_native_signature_verification(native_helper, tmp_path, case):
    helper, key = native_helper
    content = b"MZ fake installer - verification must never execute this"
    now = datetime.now(UTC).replace(microsecond=0)
    manifest = {
        "schema": 1,
        "version": "2.1.0",
        "platform": "windows-x64",
        "key_id": "test-only",
        "issued_at": (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (
            now + timedelta(days=30) if case != "expired" else now - timedelta(days=1)
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "installer": {
            "name": "MDLoggerSetup-2.1.0.exe",
            "url": "https://github.com/dusten45/MDLogger/releases/download/v2.1.0/MDLoggerSetup-2.1.0.exe",
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    }
    if case == "wrong-key-id":
        manifest["key_id"] = "wrong"
    raw = json.dumps(manifest).encode()
    envelope = {
        "schema": 1,
        "key_id": "test-only",
        "signature": base64.b64encode(
            key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
        ).decode(),
    }
    (tmp_path / "update.json").write_bytes(
        raw + b" " if case == "manifest-tamper" else raw
    )
    if case != "signature-missing":
        (tmp_path / "update.json.sig").write_text(
            json.dumps(envelope), encoding="utf-8"
        )
    (tmp_path / "MDLoggerSetup-2.1.0.exe").write_bytes(
        b"X" + content[1:] if case == "installer-tamper" else content
    )
    result = subprocess.run(
        [str(helper), "--verify-payload", str(tmp_path)], check=False, timeout=30
    )
    assert result.returncode == (0 if case == "valid" else 2)
    assert not (tmp_path / "state.json").exists(), (
        "검증 전용 호출은 설치 상태를 생성하지 않아야 합니다."
    )
