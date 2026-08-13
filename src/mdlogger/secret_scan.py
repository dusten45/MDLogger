"""배포 산출물·생성 모듈의 비밀(secret) 미포함을 검사한다.

Supabase 키 형식:
- 신형: publishable(anon)은 ``sb_publishable_...``, service-role(secret)은
  ``sb_secret_...`` 접두사.
- 구형: 둘 다 JWT(JWT 헤더. JWT payload) 형식이며, payload의 ``role`` claim으로
  구분한다(``anon`` / ``service_role``).

검사 목표: service-role key·secret JWT·임베드된 자격 증명이 산출물에
들어가지 못하게 한다. anon(publishable) key는 로드맵 8.1에 따라 **허용**된다.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path

_SERVICE_ROLE_PREFIX = "sb_secret_"
_PUBLISHABLE_PREFIX = "sb_publishable_"

# JWT처럼 보이는 토큰: 헤더.payload.서명(세 부분, base64url).
_JWT_RE = re.compile(r"[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}")


def _b64url_decode(segment: str) -> bytes | None:
    try:
        padded = segment + "=" * (-len(segment) % 4)
        return base64.urlsafe_b64decode(padded)
    except Exception:
        return None


def jwt_role(token: str) -> str | None:
    """JWT payload의 ``role`` claim을 반환한다. 복호화 불가/아니면 None."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = _b64url_decode(parts[1])
    if payload is None:
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    role = data.get("role")
    return str(role) if isinstance(role, str) else None


def is_service_role_key(key: str) -> bool:
    """값이 service-role(secret) key인지 판별한다. anon key는 False."""
    key = key.strip()
    if key.lower().startswith(_SERVICE_ROLE_PREFIX):
        return True
    for token in _JWT_RE.findall(key):
        if jwt_role(token) == "service_role":
            return True
    return False


def is_publishable_key(key: str) -> bool:
    """값이 publishable(anon) key로 보이는지 판별한다(허용 대상)."""
    key = key.strip()
    if key.lower().startswith(_PUBLISHABLE_PREFIX):
        return True
    for token in _JWT_RE.findall(key):
        if jwt_role(token) == "anon":
            return True
    return False


def assert_not_secret(base_url: str, anon_key: str) -> None:
    """번들 설정 값이 비밀이면 ValueError를 던진다(빌드를 중단시킨다)."""
    if "://" in base_url and "@" in base_url.split("://", 1)[1].split("/", 1)[0]:
        raise ValueError("base_url에 user:pass 자격 증명이 포함되어서는 안 됩니다.")
    if is_service_role_key(anon_key):
        raise ValueError(
            "anon_key 자리에 service-role/secret key가 들어왔습니다. "
            "publishable(anon) key만 번들할 수 있습니다."
        )


def scan_build_config(path: Path) -> list[str]:
    """생성된 번들 모듈 파일의 비밀 요소를 찾아 설명 목록을 반환한다."""
    return scan_bytes(path.read_bytes())


def scan_bytes(data: bytes) -> list[str]:
    """바이트 데이터에서 service-role key·비밀 자격 증명을 찾아 반환한다."""
    issues: list[str] = []
    text = data.decode("utf-8", errors="ignore")
    lower = text.lower()
    if _SERVICE_ROLE_PREFIX in lower:
        issues.append(f"'{_SERVICE_ROLE_PREFIX}' service-role key 접두사 발견")
    for token in _JWT_RE.findall(text):
        if jwt_role(token) == "service_role":
            issues.append("role='service_role' JWT(service-role key) 발견")
    # URL authority부의 user:pass 자격 증명(웹 주소 형태의 토큰 회피용).
    for match in re.findall(r"https?://[^\s\"']+", text):
        rest = match.split("://", 1)[1].split("/", 1)[0]
        if "@" in rest:
            issues.append("URL에 임베드된 자격 증명 발견")
    return issues


def scan_file(path: Path) -> list[str]:
    """파일의 비밀 요소를 찾아 설명 목록을 반환한다."""
    return scan_bytes(path.read_bytes())


def scan_path(path: Path) -> list[str]:
    """파일 또는 폴더에서 비밀 요소를 찾아 설명 목록을 반환한다.

    PyInstaller onedir 산출물은 폴더 형태이므로, 폴더가 주어지면 내부의 일반
    파일을 재귀적으로 모두 검사한다. 발견한 문제에는 어느 파일에서 나왔는지
    경로를 접두로 붙인다(``path.relpath``).
    """
    if not path.is_dir():
        return scan_file(path)
    issues: list[str] = []
    for file in sorted(p for p in path.rglob("*") if p.is_file()):
        for issue in scan_file(file):
            issues.append(f"{file.relative_to(path)}: {issue}")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(
        description="배포 산출물의 service-role key·비밀 자격 증명 미포함 검사"
    )
    parser.add_argument("path", type=Path, help="검사할 파일 또는 폴더")
    args = parser.parse_args()
    issues = scan_path(args.path)
    if not issues:
        print(f"OK: {args.path}")
        return
    for issue in issues:
        print(f"FAIL: {issue}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
