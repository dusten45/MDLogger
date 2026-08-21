"""하드닝 H1 — 배포 빌드 설정 주입 테스트.

설정 우선순위(환경변수 > 번들 빌드 설정 > `.env` > 없음)와, 번들 생성 모듈의
커밋 금지·비밀 미포함 강제를 검증한다.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import mdlogger.remote.config as config_module
from mdlogger.remote.config import (
    RemoteConfig,
    bundled_config,
    env_file_config,
    get_remote_config,
)
from mdlogger.secret_scan import (
    assert_not_secret,
    is_publishable_key,
    is_service_role_key,
    scan_file,
    scan_path,
)

URL = "https://xyzproject.supabase.co"
ANON_PREFIX_KEY = "sb_publishable_AAAbb00"
SERVICE_ROLE_PREFIX_KEY = "sb_secret_abc123"
SERVICE_ROLE_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJyb2xlIjoic2VydmljZV9yb2xlIn0.abcdefghijklmnopqrst"
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("MDLOGGER_SUPABASE_URL", raising=False)
    monkeypatch.delenv("MDLOGGER_SUPABASE_ANON_KEY", raising=False)


# ----- 설정 우선순위 -----


def test_config_from_environment_returns_none_when_missing():
    assert config_module.config_from_environment() is None


def test_bundled_config_injected_module():
    fake = SimpleNamespace(SUPABASE_URL=URL, SUPABASE_ANON_KEY=ANON_PREFIX_KEY)
    cfg = bundled_config(fake)
    assert cfg is not None
    assert cfg.base_url == URL
    assert cfg.anon_key == ANON_PREFIX_KEY


def test_bundled_config_ignores_incomplete_module():
    fake_empty = SimpleNamespace(SUPABASE_URL="", SUPABASE_ANON_KEY="")
    assert bundled_config(fake_empty) is None
    fake_partial = SimpleNamespace(SUPABASE_URL=URL, SUPABASE_ANON_KEY="")
    assert bundled_config(fake_partial) is None


def test_bundled_config_default_absorbs_missing_module():
    # 개발 저장소에는 _bundled_config가 없다(별도 테스트로 강제). ImportError 흡수 → None.
    importlib.invalidate_caches()
    assert bundled_config() is None


def test_environment_overrides_bundled(monkeypatch):
    bundle_cfg = RemoteConfig(
        base_url="https://bundle.example.com", anon_key=ANON_PREFIX_KEY
    )
    monkeypatch.setattr(config_module, "bundled_config", lambda: bundle_cfg)
    monkeypatch.setenv("MDLOGGER_SUPABASE_URL", "https://env.example.com")
    monkeypatch.setenv("MDLOGGER_SUPABASE_ANON_KEY", ANON_PREFIX_KEY)
    cfg = get_remote_config()
    assert cfg is not None
    assert cfg.base_url == "https://env.example.com"


def test_environment_overrides_env_file(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"{config_module._URL_ENV}=https://env-file.example.com\n"
        f"{config_module._ANON_KEY_ENV}={ANON_PREFIX_KEY}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "bundled_config", lambda: None)
    monkeypatch.setattr(
        config_module, "env_file_config", lambda: env_file_config(env_path)
    )
    monkeypatch.setenv("MDLOGGER_SUPABASE_URL", "https://env.example.com")
    monkeypatch.setenv("MDLOGGER_SUPABASE_ANON_KEY", ANON_PREFIX_KEY)
    cfg = get_remote_config()
    assert cfg is not None and cfg.base_url == "https://env.example.com"


def test_bundled_used_when_no_environment(monkeypatch):
    bundle_cfg = RemoteConfig(
        base_url="https://bundle.example.com", anon_key=ANON_PREFIX_KEY
    )
    monkeypatch.setattr(config_module, "bundled_config", lambda: bundle_cfg)
    cfg = get_remote_config()
    assert cfg is not None and cfg.base_url == bundle_cfg.base_url


def test_none_when_no_environment_and_no_bundle(monkeypatch):
    monkeypatch.setattr(config_module, "bundled_config", lambda: None)
    monkeypatch.setattr(config_module, "env_file_config", lambda: None)
    assert get_remote_config() is None


def test_env_file_used_when_no_environment_or_bundle(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"{config_module._URL_ENV}=https://env-file.example.com\n"
        f"{config_module._ANON_KEY_ENV}={ANON_PREFIX_KEY}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "bundled_config", lambda: None)
    monkeypatch.setattr(
        config_module, "env_file_config", lambda: env_file_config(env_path)
    )
    cfg = get_remote_config()
    assert cfg is not None and cfg.base_url == "https://env-file.example.com"


def test_env_file_config_reads_values(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# comment\n"
        f"{config_module._URL_ENV}=https://env-file.example.com\n"
        f'{config_module._ANON_KEY_ENV}="{ANON_PREFIX_KEY}"\n',
        encoding="utf-8",
    )
    cfg = env_file_config(env_path)
    assert cfg is not None
    assert cfg.base_url == "https://env-file.example.com"
    assert cfg.anon_key == ANON_PREFIX_KEY


def test_env_file_config_ignores_missing_or_incomplete(tmp_path):
    assert env_file_config(tmp_path / ".env") is None
    bad = tmp_path / ".env"
    bad.write_text(f"{config_module._URL_ENV}=\n", encoding="utf-8")
    assert env_file_config(bad) is None


def test_env_file_config_ignores_bad_url(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"{config_module._URL_ENV}=not-a-url\n"
        f"{config_module._ANON_KEY_ENV}={ANON_PREFIX_KEY}\n",
        encoding="utf-8",
    )
    assert env_file_config(env_path) is None


# ----- 비밀 미포함 검사 -----


def test_service_role_detection_prefix_and_jwt():
    assert is_service_role_key(SERVICE_ROLE_PREFIX_KEY)
    assert is_service_role_key(SERVICE_ROLE_JWT)
    assert not is_service_role_key(ANON_PREFIX_KEY)
    assert not is_service_role_key(f"{URL}/rest/v1")


def test_publishable_detection():
    assert is_publishable_key(ANON_PREFIX_KEY)
    assert not is_publishable_key(SERVICE_ROLE_JWT)


def test_assert_not_secret_rejects_service_role():
    with pytest.raises(ValueError):
        assert_not_secret(URL, SERVICE_ROLE_PREFIX_KEY)
    with pytest.raises(ValueError):
        assert_not_secret(URL, SERVICE_ROLE_JWT)
    with pytest.raises(ValueError):
        assert_not_secret("https://user:pass@host.example.com", ANON_PREFIX_KEY)


def test_assert_not_secret_allows_anon():
    assert_not_secret(URL, ANON_PREFIX_KEY)


def test_scan_file(tmp_path):
    bad = tmp_path / "bad.exe"
    bad.write_bytes(b"release " + SERVICE_ROLE_PREFIX_KEY.encode())
    assert scan_file(bad)
    good = tmp_path / "good.exe"
    good.write_bytes(b"release " + ANON_PREFIX_KEY.encode())
    assert not scan_file(good)


def test_scan_file_handles_binary_invalid_utf8(tmp_path):
    # 실제 PyInstaller 산출물처럼 유효하지 않은 UTF-8 바이트가 섞인 파일도
    # LookupError 없이 스캔해야 한다(오류 핸들러 `ignore`). 회귀 방지(단계 5).
    bad = tmp_path / "bad-bin"
    bad.write_bytes(
        b"\xff\xfe\x00release " + SERVICE_ROLE_PREFIX_KEY.encode() + b"\xff"
    )
    assert scan_file(bad)
    good = tmp_path / "good-bin"
    good.write_bytes(b"\xff\xfe\x00release " + ANON_PREFIX_KEY.encode() + b"\xff")
    assert not scan_file(good)


def test_scan_path_scans_directory_recursively(tmp_path):
    # onedir 산출물 폴더처럼 중첩 구조에서도 비밀을 찾고 경로를 붙여 보고한다.
    bundle = tmp_path / "MDLogger"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "MDLogger.exe").write_bytes(b"bootloader")
    (bundle / "_internal" / "base_library.zip").write_bytes(
        b"release " + SERVICE_ROLE_PREFIX_KEY.encode()
    )

    issues = scan_path(bundle)

    assert any("base_library.zip" in i and "sb_secret_" in i for i in issues)
    assert any(i.startswith("_internal/") for i in issues)


def test_scan_path_accepts_single_file(tmp_path):
    good = tmp_path / "good.exe"
    good.write_bytes(b"release " + ANON_PREFIX_KEY.encode())
    assert not scan_path(good)


def test_scan_path_passes_clean_directory(tmp_path):
    bundle = tmp_path / "MDLogger"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "MDLogger.exe").write_bytes(b"bootloader")
    (bundle / "_internal" / "data.json").write_bytes(
        b"release " + ANON_PREFIX_KEY.encode()
    )
    assert not scan_path(bundle)


# ----- 생성 모듈 gitignore 강제 + 생성 스크립트 -----


def test_generated_module_is_gitignored():
    gitignore = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(
        encoding="utf-8"
    )
    assert "src/mdlogger/remote/_bundled_config.py" in gitignore


def test_generated_module_not_present_in_source():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "mdlogger"
        / "remote"
        / "_bundled_config.py"
    )
    assert not module_path.exists(), "번들 모듈은 저장소에 커밋되지 않아야 한다"


def _run_generator(
    tmp_path,
    dest,
    *,
    env_text: str | None,
    extra_env: dict[str, str] | None = None,
):
    project_root = tmp_path / "project"
    script = project_root / "scripts" / "generate_build_config.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "scripts" / "generate_build_config.py",
        script,
    )
    if env_text is not None:
        (project_root / ".env").write_text(env_text, encoding="utf-8")

    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    if extra_env:
        child_env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(script), "--dest", str(dest)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=child_env,
    )


def _env_text(url: str, anon_key: str) -> str:
    return f"MDLOGGER_SUPABASE_URL={url}\nMDLOGGER_SUPABASE_ANON_KEY={anon_key}\n"


def test_generate_script_fails_when_root_env_is_missing(tmp_path):
    dest = tmp_path / "out" / "_bundled_config.py"
    proc = _run_generator(tmp_path, dest, env_text=None)
    assert proc.returncode != 0
    assert ".env 파일이 없습니다" in proc.stderr
    assert not dest.exists()


def test_generate_script_rejects_service_role_before_writing(tmp_path):
    dest = tmp_path / "out" / "_bundled_config.py"
    proc = _run_generator(
        tmp_path,
        dest,
        env_text=_env_text(URL, SERVICE_ROLE_PREFIX_KEY),
    )
    assert proc.returncode != 0
    assert not dest.exists(), "service-role key로는 파일을 쓰면 안 된다"


def test_generate_script_writes_anon_bundle(tmp_path):
    dest = tmp_path / "out" / "_bundled_config.py"
    proc = _run_generator(tmp_path, dest, env_text=_env_text(URL, ANON_PREFIX_KEY))
    assert proc.returncode == 0, proc.stderr
    assert dest.exists()
    text = dest.read_text(encoding="utf-8")
    assert URL in text
    assert ANON_PREFIX_KEY in text
    assert not scan_file(dest), "생성 모듈에 비밀이 없어야 한다"


def test_generate_script_writes_bundle_from_environment_variables(tmp_path):
    dest = tmp_path / "out" / "_bundled_config.py"
    proc = _run_generator(
        tmp_path,
        dest,
        env_text=None,
        extra_env={
            "MDLOGGER_SUPABASE_URL": URL,
            "MDLOGGER_SUPABASE_ANON_KEY": ANON_PREFIX_KEY,
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert dest.exists()
    text = dest.read_text(encoding="utf-8")
    assert URL in text
    assert ANON_PREFIX_KEY in text
    assert not scan_file(dest)


def test_generate_script_fails_on_invalid_url_in_environment(tmp_path):
    dest = tmp_path / "out" / "_bundled_config.py"
    proc = _run_generator(
        tmp_path,
        dest,
        env_text=None,
        extra_env={
            "MDLOGGER_SUPABASE_URL": "invalid-url-scheme",
            "MDLOGGER_SUPABASE_ANON_KEY": ANON_PREFIX_KEY,
        },
    )
    assert proc.returncode != 0
    assert "올바르지 않습니다" in proc.stderr
    assert not dest.exists()


def test_generate_script_fails_on_empty_values(tmp_path):
    dest = tmp_path / "out" / "_bundled_config.py"
    proc = _run_generator(tmp_path, dest, env_text=_env_text("", ANON_PREFIX_KEY))
    assert proc.returncode != 0
    assert not dest.exists()
