"""실제 다운로드나 설치 없이 업데이트 신뢰 경계와 인계를 검증한다."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from mdlogger import updater


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def signed_payload(key, *, data=b"MZ-test-installer", changes=None):
    now = datetime.now(UTC).replace(microsecond=0)
    body = {
        "schema": 1,
        "key_id": "test-only",
        "version": "2.1.0",
        "platform": "windows-x64",
        "issued_at": (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "installer": {
            "name": "MDLoggerSetup-2.1.0.exe",
            "url": "https://github.com/dusten45/MDLogger/releases/download/v2.1.0/MDLoggerSetup-2.1.0.exe",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    }
    body.update(changes or {})
    manifest = json.dumps(body, separators=(",", ":")).encode()
    signature = json.dumps(
        {
            "schema": 1,
            "key_id": "test-only",
            "signature": base64.b64encode(
                key.sign(manifest, padding.PKCS1v15(), hashes.SHA256())
            ).decode(),
        }
    ).encode()
    public = key.public_key().public_numbers()
    keys = {
        "schema": 1,
        "keys": [
            {
                "key_id": "test-only",
                "modulus": base64.b64encode(public.n.to_bytes(384)).decode(),
                "exponent": base64.b64encode(public.e.to_bytes(3)).decode(),
            }
        ],
    }
    return manifest, signature, keys, data


def plan_for(key, **kwargs):
    manifest, signature, keys, data = signed_payload(key, **kwargs)
    return updater.verify_manifest(
        manifest,
        signature,
        current_version="2.0.0",
        expected_version="2.1.0",
        trusted_keys=keys,
    ), data


class Response(io.BytesIO):
    def __init__(self, data, url, headers=None, status=200):
        super().__init__(data)
        self.url = url
        self.headers = headers or {}
        self.status = status

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

    def read(self, size=-1):
        assert 0 < size <= updater._CHUNK_SIZE, "항상 제한된 크기로 읽어야 합니다."
        return super().read(size)


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request, *, timeout):
        assert timeout == 15.0
        self.requests.append(request)
        value = self.routes[request.full_url]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            return Response(*value)
        return Response(value, request.full_url)


def release_http(key):
    manifest, signature, keys, data = signed_payload(key)
    assets = [
        {
            "name": name,
            "browser_download_url": updater._asset_url("2.1.0", name),
            "size": len(content),
            "state": "uploaded",
        }
        for name, content in [
            ("MDLogger-2.1.0-update.json", manifest),
            ("MDLogger-2.1.0-update.json.sig", signature),
            ("MDLoggerSetup-2.1.0.exe", data),
        ]
    ]
    release = {
        "tag_name": "v2.1.0",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-01-01T00:00:00Z",
        "assets": assets,
    }
    routes = {updater.RELEASE_API: json.dumps(release).encode()}
    routes.update(
        {
            asset["browser_download_url"]: content
            for asset, content in zip(assets, (manifest, signature, data), strict=True)
        }
    )
    return FakeHttp(routes), release, keys


def test_only_windows_checks_updates_without_auth_tokens(signing_key):
    http, _, keys = release_http(signing_key)
    assert updater.check_update("2.0.0", platform="linux", opener=http) is None
    assert not http.requests
    plan = updater.check_update(
        "2.0.0", platform="win32", opener=http, trusted_keys=keys
    )
    assert plan is not None and plan.version == "2.1.0"
    assert len(http.requests) == 3
    assert all(not request.has_header("Authorization") for request in http.requests)


@pytest.mark.parametrize(
    "change",
    [
        {"draft": True},
        {"prerelease": True},
        {"published_at": None},
        {"tag_name": "v2.1.0-rc1"},
        {"tag_name": "v02.1.0"},
    ],
)
def test_rejects_nonpublished_or_nonstable_release(signing_key, change):
    http, release, keys = release_http(signing_key)
    release.update(change)
    http.routes[updater.RELEASE_API] = json.dumps(release).encode()
    with pytest.raises(updater.UpdateError):
        updater.check_update("2.0.0", platform="win32", opener=http, trusted_keys=keys)
    assert len(http.requests) == 1


def test_current_version_never_downloads_metadata(signing_key):
    http, _, _ = release_http(signing_key)
    assert updater.check_update("2.1.0", platform="win32", opener=http) is None
    assert len(http.requests) == 1


@pytest.mark.parametrize("mutation", ["url", "duplicate", "size", "missing-signature"])
def test_release_asset_contract_is_strict(signing_key, mutation):
    http, release, keys = release_http(signing_key)
    if mutation == "url":
        release["assets"][0]["browser_download_url"] = (
            "https://github.com/other/repo/asset"
        )
    elif mutation == "duplicate":
        release["assets"].append(release["assets"][0])
    elif mutation == "size":
        release["assets"][2]["size"] += 1
    else:
        del release["assets"][1]
    http.routes[updater.RELEASE_API] = json.dumps(release).encode()
    with pytest.raises(updater.UpdateError):
        updater.check_update("2.0.0", platform="win32", opener=http, trusted_keys=keys)


def test_signature_is_over_exact_bytes_and_never_checksum_fallback(signing_key):
    manifest, signature, keys, _ = signed_payload(signing_key)
    with pytest.raises(updater.UpdateError, match="서명"):
        updater.verify_manifest(
            manifest + b" ",
            signature,
            current_version="2.0.0",
            expected_version="2.1.0",
            trusted_keys=keys,
        )
    with pytest.raises(updater.UpdateError):
        updater.verify_manifest(
            manifest,
            b"",
            current_version="2.0.0",
            expected_version="2.1.0",
            trusted_keys=keys,
        )
    with pytest.raises(updater.UpdateError, match="신뢰"):
        updater.verify_manifest(
            manifest,
            signature,
            current_version="2.0.0",
            expected_version="2.1.0",
            trusted_keys={"schema": 1, "keys": []},
        )


@pytest.mark.parametrize(
    "change",
    [
        {"platform": "linux"},
        {"version": "2.2.0"},
        {"schema": True},
        {"key_id": "different"},
        {"issued_at": "2999-01-01T00:00:00Z", "expires_at": "2999-02-01T00:00:00Z"},
        {"issued_at": "2000-01-01T00:00:00Z", "expires_at": "2000-02-01T00:00:00Z"},
        {"issued_at": "2000-01-01T00:00:00Z", "expires_at": "2999-02-01T00:00:00Z"},
        {"issued_at": "2026-1-1T00:00:00Z"},
        {"expires_at": None},
    ],
)
def test_signed_but_invalid_manifest_is_rejected(signing_key, change):
    with pytest.raises(updater.UpdateError):
        plan_for(signing_key, changes=change)


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "../setup.exe"),
        ("url", "https://evil.example/setup.exe"),
        ("size", True),
        ("size", 0),
        ("size", updater.MAX_INSTALLER_BYTES + 1),
        ("sha256", "x" * 64),
    ],
)
def test_signed_installer_fields_are_not_arbitrary_commands(signing_key, field, value):
    raw, _, _, _ = signed_payload(signing_key)
    asset = json.loads(raw)["installer"]
    asset[field] = value
    with pytest.raises(updater.UpdateError):
        plan_for(signing_key, changes={"installer": asset})


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/dusten45/MDLogger/releases/download/a",
        "https://localhost/a",
        "https://github.com/other/repo/a",
        "https://github.com@evil.example/a",
        "https://release-assets.githubusercontent.com:444/a",
        "https://release-assets.githubusercontent.com/a#fragment",
    ],
)
def test_redirect_is_rejected_before_following(url):
    handler = updater._SafeRedirect()
    with pytest.raises(updater.UpdateError):
        handler.redirect_request(Request(updater.RELEASE_API), None, 302, "", {}, url)


def test_metadata_size_bound_without_content_length():
    http = FakeHttp({updater.RELEASE_API: b"x" * 100})
    with pytest.raises(updater.UpdateError, match="크기"):
        updater._fetch_bytes(updater.RELEASE_API, 20, http)


def test_download_verifies_stream_and_publishes_only_complete_payload(
    signing_key, tmp_path
):
    plan, data = plan_for(signing_key)
    progress = []
    http = FakeHttp(
        {
            plan.installer_url: (
                data,
                "https://release-assets.githubusercontent.com/assets/file?signature=test",
            )
        }
    )
    downloaded = updater.download_update(
        plan,
        cache_dir=tmp_path,
        opener=http,
        progress=lambda done, total: progress.append((done, total)),
    )
    assert downloaded.installer.read_bytes() == data
    assert (downloaded.directory / "update.json").read_bytes() == plan.manifest
    assert (downloaded.directory / "update.json.sig").read_bytes() == plan.signature
    assert not (downloaded.directory / "installer.part").exists()
    assert progress[-1] == (len(data), len(data))


@pytest.mark.parametrize(
    "mutation", ["truncated", "oversized", "tampered", "header", "redirect", "encoding"]
)
def test_bad_download_leaves_no_executable(signing_key, tmp_path, mutation):
    plan, data = plan_for(signing_key)
    url = plan.installer_url
    headers = {}
    if mutation == "truncated":
        data = data[:-1]
    elif mutation == "oversized":
        data += b"x"
    elif mutation == "tampered":
        data = b"X" + data[1:]
    elif mutation == "header":
        headers["Content-Length"] = str(plan.size + 1)
    elif mutation == "redirect":
        url = "https://evil.example/installer"
    else:
        headers["Content-Encoding"] = "gzip"
    with pytest.raises(updater.UpdateError):
        updater.download_update(
            plan,
            cache_dir=tmp_path,
            opener=FakeHttp({plan.installer_url: (data, url, headers)}),
        )
    assert not list(tmp_path.iterdir()), (
        "검증에 실패한 설치 파일은 남기지 않아야 합니다."
    )


def test_cancel_during_download_cleans_partial_file(signing_key, tmp_path):
    plan, data = plan_for(signing_key, data=b"MZ" + b"x" * 100000)
    cancelled = False

    def on_progress(done, total):
        nonlocal cancelled
        cancelled = True

    with pytest.raises(updater.UpdateCancelled):
        updater.download_update(
            plan,
            cache_dir=tmp_path,
            opener=FakeHttp({plan.installer_url: data}),
            progress=on_progress,
            cancelled=lambda: cancelled,
        )
    assert not list(tmp_path.iterdir())


def test_cancel_before_request_never_downloads(signing_key, tmp_path):
    plan, _ = plan_for(signing_key)
    http = FakeHttp({})
    with pytest.raises(updater.UpdateCancelled):
        updater.download_update(
            plan, cache_dir=tmp_path, opener=http, cancelled=lambda: True
        )
    assert not http.requests and not list(tmp_path.iterdir())


@pytest.fixture
def job_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = tmp_path / "MDLogger" / "updates" / ("a" * 32)
    root.mkdir(parents=True)
    return root


def test_cancel_is_only_allowed_before_installation(job_directory):
    job = updater.UpdateJob(job_directory, "b" * 64, 123)
    updater._write_json(
        job_directory / "state.json", {"token": job.token, "phase": "ready"}
    )
    updater.cancel_update(job)
    assert json.loads((job_directory / "cancel.json").read_text())["token"] == job.token
    updater._write_json(
        job_directory / "state.json", {"token": job.token, "phase": "installing"}
    )
    with pytest.raises(updater.UpdateError, match="중간"):
        updater.cancel_update(job)


@pytest.mark.parametrize("matching", [True, False])
def test_startup_receipt_requires_job_token_and_version(
    job_directory, monkeypatch, matching
):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setenv("MDLOGGER_UPDATE_JOB", str(job_directory))
    monkeypatch.setenv("MDLOGGER_UPDATE_TOKEN", "b" * 64)
    updater._write_json(
        job_directory / "state.json",
        {"token": "b" * 64, "phase": "starting", "version": "2.1.0"},
    )
    assert (
        updater.acknowledge_update_startup("2.1.0" if matching else "2.0.0") is matching
    )
    assert (job_directory / "started.json").exists() is matching
    assert "MDLOGGER_UPDATE_TOKEN" not in os.environ


@pytest.mark.parametrize("data_source", ["argument", "relative-environment"])
def test_helper_is_copied_outside_install_tree_before_handoff(
    signing_key, tmp_path, monkeypatch, data_source
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    plan, data = plan_for(signing_key)
    download = updater.download_update(
        plan, opener=FakeHttp({plan.installer_url: data})
    )
    install = tmp_path / "ProgramFiles" / "MDLogger"
    install.mkdir(parents=True)
    executable = install / "MDLogger.exe"
    executable.write_bytes(b"test application")
    executable.with_name("MDLoggerUpdate.exe").write_bytes(b"test helper")
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater, "_clean_dll_directory", nullcontext)
    seen = []

    def spawn(arguments, **kwargs):
        seen.append((arguments, kwargs))
        job = json.loads(Path(arguments[2]).read_text())
        updater._write_json(
            download.directory / "state.json", {"token": job["token"], "phase": "ready"}
        )
        return SimpleNamespace(pid=456, poll=lambda: None)

    monkeypatch.setattr(updater.subprocess, "Popen", spawn)
    if data_source == "relative-environment":
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MDLOGGER_DATA_DIR", "custom-data")
    job = updater.launch_update(
        download,
        os.getpid(),
        executable=executable,
        data_dir=tmp_path / "custom-data" if data_source == "argument" else None,
    )
    assert job.helper_pid == 456
    authorized = json.loads(
        (download.directory / "install-authorized.json").read_text()
    )
    assert authorized == {"token": job.token, "version": "2.1.0"}
    assert Path(seen[0][0][0]).parent == download.directory
    assert seen[0][0][1] == "--job"
    body = json.loads((download.directory / "job.json").read_text())
    assert body["data_dir"] == str(tmp_path / "custom-data")
    assert seen[0][1]["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert not Path(seen[0][0][0]).is_relative_to(install)


def test_failed_ready_receipt_never_authorizes_later_install(
    signing_key, tmp_path, monkeypatch
):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    plan, data = plan_for(signing_key)
    download = updater.download_update(
        plan, opener=FakeHttp({plan.installer_url: data})
    )
    install = tmp_path / "installed"
    install.mkdir()
    executable = install / "MDLogger.exe"
    executable.write_bytes(b"test application")
    executable.with_name("MDLoggerUpdate.exe").write_bytes(b"test helper")
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater, "_clean_dll_directory", nullcontext)

    def spawn(*args, **kwargs):
        (download.directory / "state.json").write_bytes(b"invalid state")
        return SimpleNamespace(pid=456, poll=lambda: None)

    monkeypatch.setattr(updater.subprocess, "Popen", spawn)
    with pytest.raises(updater.UpdateError):
        updater.launch_update(download, os.getpid(), executable=executable)
    assert not (download.directory / "install-authorized.json").exists()
    assert (download.directory / "cancel.json").exists()


def test_non_windows_launch_is_rejected_without_processes(
    signing_key, tmp_path, monkeypatch
):
    plan, data = plan_for(signing_key)
    downloaded = updater.download_update(
        plan, cache_dir=tmp_path, opener=FakeHttp({plan.installer_url: data})
    )
    monkeypatch.setattr(updater.sys, "platform", "linux")
    with pytest.raises(updater.UpdateError, match="Windows"):
        updater.launch_update(downloaded, os.getpid())


def test_installer_preserves_admin_scope_and_silent_launch_contract():
    source = (
        Path(__file__).resolve().parents[1] / "scripts/installer_windows.iss"
    ).read_text()
    assert "PrivilegesRequired=admin" in source
    assert "DefaultDirName={autopf}" in source
    assert f"AppMutex={updater.APPLICATION_MUTEX}" in source
    assert "Flags: nowait postinstall skipifsilent" in source


@pytest.mark.parametrize("case", ["running", "updating", "denied", "new", "authorized"])
def test_windows_mutex_blocks_other_instances_and_allows_only_authorized_restart(
    job_directory, monkeypatch, case
):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater, "_application_handle", None)
    error = 0
    closed = []

    class Function:
        def __init__(self, function):
            self.function = function

        def __call__(self, *args):
            return self.function(*args)

    def open_mutex(*args):
        nonlocal error
        error = 5 if case == "denied" else 2
        return 42 if case in {"updating", "authorized"} else 0

    def create_mutex(*args):
        nonlocal error
        error = 183 if case == "running" else 0
        return 2**40 + 3

    kernel = SimpleNamespace(
        OpenMutexW=Function(open_mutex),
        CreateMutexW=Function(create_mutex),
        CloseHandle=Function(lambda handle: closed.append(handle) or 1),
    )
    monkeypatch.setattr(
        updater.ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False
    )
    monkeypatch.setattr(updater.ctypes, "get_last_error", lambda: error, raising=False)
    if case == "authorized":
        monkeypatch.setenv("MDLOGGER_UPDATE_JOB", str(job_directory))
        monkeypatch.setenv("MDLOGGER_UPDATE_TOKEN", "c" * 64)
        updater._write_json(
            job_directory / "state.json",
            {"token": "c" * 64, "phase": "starting", "version": "2.1.0"},
        )
    allowed = case in {"new", "authorized"}
    assert updater.acquire_application_mutex() is allowed
    assert (updater._application_handle is not None) is allowed
    if case == "running":
        assert 2**40 + 3 in closed
