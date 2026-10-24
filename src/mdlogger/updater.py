"""서명된 Windows 업데이트의 조회, 다운로드, 독립 helper 인계.

네트워크와 helper 준비 대기는 호출자를 블로킹하므로 UI worker에서 호출한다.
앱 종료와 새 창이 준비된 시점의 확인은 앱 수명 주기를 소유한 호출자의 책임이다.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

REPOSITORY = "dusten45/MDLogger"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
APP_ID = "F0987F41-0A8B-4B2E-9C61-9CDD4F8E7C00"
APPLICATION_MUTEX = rf"Global\MDLogger.Application.{APP_ID}"
UPDATE_MUTEX = rf"Global\MDLogger.Update.{APP_ID}"
MAX_INSTALLER_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_SIGNATURE_BYTES = 8192
_CHUNK_SIZE = 64 * 1024
_TIMEOUT = 15.0
_VERSION = re.compile(
    r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\Z"
)
_HEX_TOKEN = re.compile(r"[0-9a-f]{64}\Z")
_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_application_handle: int | None = None


class UpdateError(Exception):
    """검증이나 업데이트 인계가 안전하게 완료되지 않았다."""


class UpdateCancelled(UpdateError):
    """사용자가 설치 시작 전 다운로드를 취소했다."""


class HttpResponse(Protocol):
    headers: Mapping[str, str]

    def geturl(self) -> str: ...

    def getcode(self) -> int: ...

    def read(self, size: int = -1) -> bytes: ...


class HttpOpener(Protocol):
    def __call__(
        self, request: urllib.request.Request, *, timeout: float
    ) -> AbstractContextManager[HttpResponse]: ...


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    current_version: str
    version: str
    installer_name: str
    installer_url: str
    size: int
    sha256: str
    manifest: bytes
    signature: bytes
    trusted_keys: bytes


@dataclass(frozen=True, slots=True)
class DownloadedUpdate:
    plan: UpdatePlan
    directory: Path
    installer: Path


@dataclass(frozen=True, slots=True)
class UpdateJob:
    directory: Path
    token: str
    helper_pid: int


def _version(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise UpdateError("업데이트 버전 형식이 올바르지 않습니다.")
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise UpdateError("업데이트 정보에 중복 필드가 있습니다.")
        result[name] = value
    return result


def _json_object(data: bytes, maximum: int) -> dict[str, Any]:
    if not data or len(data) > maximum:
        raise UpdateError("업데이트 정보의 크기가 허용 범위를 벗어났습니다.")
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise UpdateError("업데이트 정보를 읽을 수 없습니다.") from error
    if not isinstance(result, dict):
        raise UpdateError("업데이트 정보 형식이 올바르지 않습니다.")
    return result


def _decode_base64(value: object) -> bytes:
    if not isinstance(value, str) or len(value) > MAX_SIGNATURE_BYTES:
        raise UpdateError("업데이트 서명 형식이 올바르지 않습니다.")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as error:
        raise UpdateError("업데이트 서명 형식이 올바르지 않습니다.") from error


def load_trusted_keys() -> dict[str, Any]:
    """배포본에 고정한 공개 키만 읽는다. 네트워크 키 교체는 허용하지 않는다."""
    try:
        path = Path(__file__).with_name("data") / "update-trusted-keys.json"
        with path.open("rb") as stream:
            return _json_object(stream.read(MAX_MANIFEST_BYTES + 1), MAX_MANIFEST_BYTES)
    except OSError as error:
        raise UpdateError(
            "신뢰할 업데이트 공개 키가 설치되어 있지 않습니다."
        ) from error


def verify_manifest(
    manifest: bytes,
    signature: bytes,
    *,
    current_version: str,
    expected_version: str,
    trusted_keys: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> UpdatePlan:
    """정확한 원문 바이트의 서명과 플랫폼, 버전, 설치 파일 계약을 검증한다."""
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise UpdateError("업데이트 정보가 너무 큽니다.")
    envelope = _json_object(signature, MAX_SIGNATURE_BYTES)
    keys = dict(trusted_keys) if trusted_keys is not None else load_trusted_keys()
    key_id = envelope.get("key_id")
    if (
        type(envelope.get("schema")) is not int
        or envelope["schema"] != 1
        or not isinstance(key_id, str)
        or not _KEY_ID.fullmatch(key_id)
        or type(keys.get("schema")) is not int
        or keys["schema"] != 1
        or not isinstance(keys.get("keys"), list)
    ):
        raise UpdateError("업데이트 서명 또는 신뢰 키 형식이 올바르지 않습니다.")
    matches = [
        key
        for key in keys["keys"]
        if isinstance(key, dict) and key.get("key_id") == key_id
    ]
    if len(matches) != 1:
        raise UpdateError("신뢰할 수 없는 업데이트 서명 키입니다.")
    modulus = int.from_bytes(_decode_base64(matches[0].get("modulus")))
    exponent = int.from_bytes(_decode_base64(matches[0].get("exponent")))
    if not 3072 <= modulus.bit_length() <= 4096 or exponent != 65537:
        raise UpdateError("업데이트 공개 키가 보안 조건을 충족하지 않습니다.")
    try:
        rsa.RSAPublicNumbers(exponent, modulus).public_key().verify(
            _decode_base64(envelope.get("signature")),
            manifest,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (InvalidSignature, ValueError) as error:
        raise UpdateError(
            "업데이트 서명이 유효하지 않습니다. 설치하지 않았습니다."
        ) from error
    value = _json_object(manifest, MAX_MANIFEST_BYTES)
    try:
        issued = datetime.strptime(value["issued_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        expires = datetime.strptime(value["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        if (
            issued.strftime("%Y-%m-%dT%H:%M:%SZ") != value["issued_at"]
            or expires.strftime("%Y-%m-%dT%H:%M:%SZ") != value["expires_at"]
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise UpdateError("업데이트 서명의 유효 기간이 올바르지 않습니다.") from error
    moment = now if now is not None else datetime.now(UTC)
    if (
        value.get("key_id") != key_id
        or expires <= moment
        or issued > moment + timedelta(minutes=5)
        or not timedelta(0) < expires - issued <= timedelta(days=366)
    ):
        raise UpdateError("업데이트 서명이 만료되었거나 아직 유효하지 않습니다.")
    version = value.get("version")
    if (
        type(value.get("schema")) is not int
        or value["schema"] != 1
        or value.get("platform") != "windows-x64"
        or version != expected_version
        or _version(version) <= _version(current_version)
    ):
        raise UpdateError("현재 앱에 적용할 수 없는 업데이트입니다.")
    installer = value.get("installer")
    if not isinstance(installer, dict):
        raise UpdateError("업데이트 설치 파일 정보가 없습니다.")
    name = f"MDLoggerSetup-{version}.exe"
    url = _asset_url(str(version), name)
    size = installer.get("size")
    digest = installer.get("sha256")
    if (
        installer.get("name") != name
        or installer.get("url") != url
        or type(size) is not int
        or not 0 < size <= MAX_INSTALLER_BYTES
        or not isinstance(digest, str)
        or not _HEX_TOKEN.fullmatch(digest)
    ):
        raise UpdateError(
            "업데이트 설치 파일의 주소, 크기 또는 해시가 올바르지 않습니다."
        )
    return UpdatePlan(
        current_version,
        str(version),
        name,
        url,
        size,
        digest,
        manifest,
        signature,
        json.dumps(keys, separators=(",", ":")).encode("utf-8"),
    )


def _asset_url(version: str, name: str) -> str:
    return f"https://github.com/{REPOSITORY}/releases/download/v{version}/{name}"


def _check_transport_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and not parsed.fragment
        )
    except ValueError as error:
        raise UpdateError("허용되지 않은 업데이트 주소입니다.") from error
    if not valid:
        raise UpdateError("업데이트는 승인된 HTTPS 주소에서만 받을 수 있습니다.")
    if parsed.hostname == "api.github.com" and url == RELEASE_API:
        return
    if parsed.hostname == "github.com" and not parsed.query:
        prefix = f"/{REPOSITORY}/releases/download/"
        if (
            parsed.path.startswith(prefix)
            and "%" not in parsed.path
            and ".." not in parsed.path
        ):
            return
    if parsed.hostname in {
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }:
        return
    raise UpdateError("허용되지 않은 업데이트 다운로드 서버입니다.")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_transport_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(opener: HttpOpener | None) -> HttpOpener:
    return opener or cast(HttpOpener, urllib.request.build_opener(_SafeRedirect()).open)


def _request(url: str, opener: HttpOpener) -> AbstractContextManager[HttpResponse]:
    _check_transport_url(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MDLogger-Updater",
            "Accept": "application/octet-stream",
            "Accept-Encoding": "identity",
        },
    )
    if url == RELEASE_API:
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
    return opener(request, timeout=_TIMEOUT)


def _validate_response(response: HttpResponse, maximum: int) -> None:
    _check_transport_url(response.geturl())
    if response.getcode() != 200:
        raise UpdateError("업데이트 서버가 파일을 제공하지 않았습니다.")
    if response.headers.get("Content-Encoding", "identity") != "identity":
        raise UpdateError("압축된 업데이트 응답은 허용하지 않습니다.")
    length = response.headers.get("Content-Length")
    if length is not None:
        try:
            size = int(length)
        except ValueError as error:
            raise UpdateError("업데이트 응답 크기가 올바르지 않습니다.") from error
        if not 0 <= size <= maximum:
            raise UpdateError("업데이트 응답이 허용된 크기를 초과했습니다.")


def _fetch_bytes(url: str, maximum: int, opener: HttpOpener) -> bytes:
    deadline = time.monotonic() + 60.0
    with _request(url, opener) as response:
        _validate_response(response, maximum)
        data = bytearray()
        while chunk := response.read(min(_CHUNK_SIZE, maximum + 1 - len(data))):
            if time.monotonic() > deadline:
                raise UpdateError("업데이트 정보 다운로드 시간이 초과되었습니다.")
            data.extend(chunk)
            if len(data) > maximum:
                raise UpdateError("업데이트 응답이 허용된 크기를 초과했습니다.")
        return bytes(data)


def check_update(
    current_version: str,
    *,
    trusted_keys: Mapping[str, Any] | None = None,
    opener: HttpOpener | None = None,
    platform: str | None = None,
) -> UpdatePlan | None:
    """공개된 stable 릴리스만 확인한다. 다른 OS에서는 네트워크를 호출하지 않는다."""
    if (platform if platform is not None else sys.platform) != "win32":
        return None
    _version(current_version)
    client = _opener(opener)
    try:
        release = _json_object(
            _fetch_bytes(RELEASE_API, 2 * 1024 * 1024, client), 2 * 1024 * 1024
        )
        tag = release.get("tag_name")
        if (
            release.get("draft") is not False
            or release.get("prerelease") is not False
            or not isinstance(release.get("published_at"), str)
            or not release["published_at"]
            or not isinstance(tag, str)
            or not tag.startswith("v")
        ):
            raise UpdateError("공개된 정식 업데이트 릴리스가 아닙니다.")
        version = tag[1:]
        if _version(version) <= _version(current_version):
            return None
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise UpdateError("릴리스에 업데이트 파일이 없습니다.")
        names = [
            f"MDLogger-{version}-update.json",
            f"MDLogger-{version}-update.json.sig",
            f"MDLoggerSetup-{version}.exe",
        ]
        selected: dict[str, dict[str, Any]] = {}
        for name, maximum in zip(
            names,
            (MAX_MANIFEST_BYTES, MAX_SIGNATURE_BYTES, MAX_INSTALLER_BYTES),
            strict=True,
        ):
            matches = [
                asset
                for asset in assets
                if isinstance(asset, dict) and asset.get("name") == name
            ]
            if len(matches) != 1:
                raise UpdateError("릴리스의 업데이트 파일이 없거나 중복되었습니다.")
            asset = matches[0]
            if (
                asset.get("browser_download_url") != _asset_url(version, name)
                or asset.get("state") != "uploaded"
                or type(asset.get("size")) is not int
                or not 0 < asset["size"] <= maximum
            ):
                raise UpdateError("릴리스의 업데이트 파일 정보가 올바르지 않습니다.")
            selected[name] = asset
        plan = verify_manifest(
            _fetch_bytes(_asset_url(version, names[0]), MAX_MANIFEST_BYTES, client),
            _fetch_bytes(_asset_url(version, names[1]), MAX_SIGNATURE_BYTES, client),
            current_version=current_version,
            expected_version=version,
            trusted_keys=trusted_keys,
        )
        if selected[names[2]]["size"] != plan.size:
            raise UpdateError("서명된 설치 파일과 릴리스 파일의 크기가 다릅니다.")
        return plan
    except (OSError, urllib.error.URLError) as error:
        raise UpdateError(
            "업데이트 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."
        ) from error


def _update_cache() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise UpdateError("Windows 사용자 업데이트 폴더를 찾을 수 없습니다.")
    return Path(local) / "MDLogger" / "updates"


def _reject_reparse(path: Path) -> None:
    for candidate in (path, *path.parents):
        if not candidate.exists():
            continue
        info = candidate.lstat()
        if (
            candidate.is_symlink()
            or getattr(info, "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise UpdateError("연결된 폴더에서는 업데이트를 실행할 수 없습니다.")


def download_update(
    plan: UpdatePlan,
    *,
    cache_dir: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    opener: HttpOpener | None = None,
) -> DownloadedUpdate:
    """설치 전까지 취소 가능한 제한 크기 다운로드. 해시 일치 후에만 파일을 공개한다."""
    verified = verify_manifest(
        plan.manifest,
        plan.signature,
        current_version=plan.current_version,
        expected_version=plan.version,
        trusted_keys=_json_object(plan.trusted_keys, MAX_MANIFEST_BYTES),
    )
    if verified != plan:
        raise UpdateError("업데이트 계획이 서명된 정보와 다릅니다.")
    root = cache_dir if cache_dir is not None else _update_cache()
    _reject_reparse(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = root / uuid.uuid4().hex
    directory.mkdir(mode=0o700)
    partial = directory / "installer.part"
    installer = directory / plan.installer_name
    try:
        if cancelled is not None and cancelled():
            raise UpdateCancelled("업데이트 다운로드를 취소했습니다.")
        digest = hashlib.sha256()
        count = 0
        deadline = time.monotonic() + 600.0
        with (
            _request(plan.installer_url, _opener(opener)) as response,
            partial.open("xb") as output,
        ):
            _validate_response(response, plan.size)
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateCancelled("업데이트 다운로드를 취소했습니다.")
                if time.monotonic() > deadline:
                    raise UpdateError("업데이트 다운로드 시간이 초과되었습니다.")
                chunk = response.read(min(_CHUNK_SIZE, plan.size + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                if count > plan.size:
                    raise UpdateError("설치 파일이 서명된 크기를 초과했습니다.")
                output.write(chunk)
                digest.update(chunk)
                if progress is not None:
                    progress(count, plan.size)
            output.flush()
            os.fsync(output.fileno())
        if count != plan.size or not hmac.compare_digest(
            digest.hexdigest(), plan.sha256
        ):
            raise UpdateError("설치 파일 검증에 실패했습니다. 설치하지 않았습니다.")
        (directory / "update.json").write_bytes(plan.manifest)
        (directory / "update.json.sig").write_bytes(plan.signature)
        partial.replace(installer)
        return DownloadedUpdate(plan, directory, installer)
    except BaseException as error:
        for path in (
            partial,
            installer,
            directory / "update.json",
            directory / "update.json.sig",
        ):
            path.unlink(missing_ok=True)
        directory.rmdir()
        if isinstance(error, (OSError, urllib.error.URLError)):
            raise UpdateError("업데이트 파일을 받거나 저장하지 못했습니다.") from error
        raise


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _read_state(path: Path) -> dict[str, Any]:
    _reject_reparse(path)
    with path.open("rb") as stream:
        return _json_object(stream.read(MAX_MANIFEST_BYTES + 1), MAX_MANIFEST_BYTES)


def _job_directory(path: Path) -> Path:
    _reject_reparse(path)
    resolved = path.resolve(strict=True)
    if resolved.parent != _update_cache().resolve(strict=True) or not re.fullmatch(
        r"[0-9a-f]{32}", resolved.name
    ):
        raise UpdateError("허용되지 않은 업데이트 작업 폴더입니다.")
    return resolved


def _external_environment(executable: Path) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("_PYI_")
    }
    for name in (
        "QT_PLUGIN_PATH",
        "QML2_IMPORT_PATH",
        "MDLOGGER_UPDATE_JOB",
        "MDLOGGER_UPDATE_TOKEN",
    ):
        env.pop(name, None)
    roots = [executable.parent.resolve()]
    if hasattr(sys, "_MEIPASS"):
        roots.append(Path(sys._MEIPASS).resolve())
    env["PATH"] = os.pathsep.join(
        part
        for part in env.get("PATH", "").split(os.pathsep)
        if part and not any(Path(part).resolve().is_relative_to(root) for root in roots)
    )
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


@contextmanager
def _clean_dll_directory():
    if sys.platform != "win32":
        raise UpdateError("Windows에서만 업데이트 실행 환경을 준비할 수 있습니다.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    kernel.GetDllDirectoryW.restype = ctypes.c_uint32
    kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    kernel.SetDllDirectoryW.restype = ctypes.c_int
    buffer = ctypes.create_unicode_buffer(32768)
    size = kernel.GetDllDirectoryW(len(buffer), buffer)
    if size >= len(buffer) or not kernel.SetDllDirectoryW(None):
        raise UpdateError("업데이트 실행 환경을 안전하게 준비하지 못했습니다.")
    try:
        yield
    finally:
        kernel.SetDllDirectoryW(buffer.value if size else None)


def launch_update(
    download: DownloadedUpdate,
    parent_pid: int,
    *,
    executable: Path | None = None,
    data_dir: Path | None = None,
) -> UpdateJob:
    """helper의 검증 완료를 기다려 인계한다. 반환 후에만 앱을 정상 종료해야 한다."""
    if sys.platform != "win32" or parent_pid != os.getpid():
        raise UpdateError("현재 Windows 앱에서만 업데이트를 시작할 수 있습니다.")
    directory = _job_directory(download.directory)
    target = (executable if executable is not None else Path(sys.executable)).resolve(
        strict=True
    )
    if target.name != "MDLogger.exe" or directory.is_relative_to(target.parent):
        raise UpdateError("설치된 MDLogger 실행 파일을 확인할 수 없습니다.")
    _reject_reparse(target)
    helper_source = target.with_name("MDLoggerUpdate.exe")
    _reject_reparse(helper_source)
    if not helper_source.is_file():
        raise UpdateError("업데이트 실행 도우미가 설치되어 있지 않습니다.")
    token = secrets.token_hex(32)
    helper = directory / "MDLoggerUpdate.exe"
    if helper.exists() or (directory / "job.json").exists():
        raise UpdateError("이미 사용한 업데이트 작업입니다. 다시 다운로드해 주세요.")
    shutil.copyfile(helper_source, helper)
    selected_data_dir = data_dir
    if selected_data_dir is None and os.environ.get("MDLOGGER_DATA_DIR"):
        selected_data_dir = Path(os.environ["MDLOGGER_DATA_DIR"]).expanduser()
    _write_json(
        directory / "job.json",
        {
            "schema": 1,
            "parent_pid": parent_pid,
            "executable": str(target),
            "version": download.plan.version,
            "token": token,
            "data_dir": str(selected_data_dir.resolve())
            if selected_data_dir is not None
            else None,
        },
    )
    with _clean_dll_directory():
        process = subprocess.Popen(
            [str(helper), "--job", str(directory / "job.json")],
            cwd=directory,
            env=_external_environment(target),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=0x00000008 | 0x00000200,
        )
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                state = _read_state(directory / "state.json")
            except FileNotFoundError:
                state = {}
            if state.get("token") == token:
                if state.get("phase") == "ready":
                    # 준비 결과를 읽지 못한 앱이 나중에 닫혀도 설치가 시작되면 안 된다.
                    _write_json(
                        directory / "install-authorized.json",
                        {"token": token, "version": download.plan.version},
                    )
                    return UpdateJob(directory, token, process.pid)
                if state.get("phase") == "failed":
                    raise UpdateError(
                        str(state.get("message") or "업데이트를 준비하지 못했습니다.")
                    )
            if process.poll() is not None:
                raise UpdateError("업데이트 도우미가 설치를 준비하지 못했습니다.")
            time.sleep(0.05)
        raise UpdateError("업데이트 준비 시간이 초과되었습니다. 현재 앱을 유지합니다.")
    except BaseException:
        try:
            _write_json(directory / "cancel.json", {"token": token})
        except OSError:
            pass
        raise


def cancel_update(job: UpdateJob) -> None:
    """앱 종료가 거부된 경우 대기 중인 helper만 취소한다. 설치 프로세스는 죽이지 않는다."""
    directory = _job_directory(job.directory)
    state = _read_state(directory / "state.json")
    if state.get("token") != job.token or state.get("phase") != "ready":
        raise UpdateError("이미 설치를 시작한 업데이트는 중간에 취소할 수 없습니다.")
    _write_json(directory / "cancel.json", {"token": job.token})


def _startup_job() -> tuple[Path, str, dict[str, Any]] | None:
    path = os.environ.get("MDLOGGER_UPDATE_JOB")
    token = os.environ.get("MDLOGGER_UPDATE_TOKEN", "")
    if not path or not _HEX_TOKEN.fullmatch(token):
        return None
    try:
        directory = _job_directory(Path(path))
        state = _read_state(directory / "state.json")
        if state.get("token") != token or state.get("phase") not in {
            "starting",
            "recovering",
        }:
            return None
        return directory, token, state
    except (OSError, UpdateError):
        return None


def acquire_application_mutex() -> bool:
    """앱 프로세스가 끝날 때까지 mutex를 유지한다. 업데이트 중 새 인스턴스도 막는다."""
    global _application_handle
    if sys.platform != "win32" or _application_handle is not None:
        return True
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    update = kernel.OpenMutexW(0x00100000, False, UPDATE_MUTEX)
    if update:
        kernel.CloseHandle(update)
        if _startup_job() is None:
            return False
    elif ctypes.get_last_error() == 5:
        return False
    elif ctypes.get_last_error() not in (0, 2):
        raise UpdateError("업데이트 잠금 상태를 확인할 수 없습니다.")
    handle = kernel.CreateMutexW(None, False, APPLICATION_MUTEX)
    error = ctypes.get_last_error()
    if not handle:
        if error == 5:
            return False
        raise UpdateError("앱 실행 잠금을 만들 수 없습니다.")
    if error == 183:
        kernel.CloseHandle(handle)
        return False
    _application_handle = handle
    return True


def acknowledge_update_startup(current_version: str) -> bool:
    """새 앱의 초기화와 창 표시가 성공한 뒤 helper에 기동 완료를 알린다."""
    if sys.platform != "win32":
        return False
    context = _startup_job()
    os.environ.pop("MDLOGGER_UPDATE_JOB", None)
    os.environ.pop("MDLOGGER_UPDATE_TOKEN", None)
    if context is None:
        return False
    directory, token, state = context
    if state.get("version") != current_version:
        return False
    try:
        _write_json(
            directory / "started.json",
            {
                "schema": 1,
                "token": token,
                "version": current_version,
                "pid": os.getpid(),
            },
        )
    except OSError:
        return False
    return True
