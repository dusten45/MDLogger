"""원격 서버 접속 설정.

publishable(anon) key는 앱에 포함할 수 있는 공개 값이다(로드맵 8.1).
service-role/secret key는 어떤 경로로도 이 설정에 두지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_URL_ENV = "MDLOGGER_SUPABASE_URL"
_ANON_KEY_ENV = "MDLOGGER_SUPABASE_ANON_KEY"


@dataclass(frozen=True, slots=True)
class RemoteConfig:
    """Supabase 프로젝트의 base URL과 publishable key."""

    base_url: str
    anon_key: str

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("https://", "http://")):
            raise ValueError("base_url은 http(s) URL이어야 합니다.")
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    @property
    def auth_url(self) -> str:
        return f"{self.base_url}/auth/v1"

    @property
    def functions_url(self) -> str:
        return f"{self.base_url}/functions/v1"

    @property
    def rest_url(self) -> str:
        return f"{self.base_url}/rest/v1"


def config_from_environment() -> RemoteConfig | None:
    """환경 변수에서 설정을 읽는다. 없으면 None(오프라인 전용 동작)."""
    base_url = os.environ.get(_URL_ENV, "").strip()
    anon_key = os.environ.get(_ANON_KEY_ENV, "").strip()
    if not base_url or not anon_key:
        return None
    return RemoteConfig(base_url=base_url, anon_key=anon_key)
