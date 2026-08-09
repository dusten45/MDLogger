"""원격 서버 접속 설정.

publishable(anon) key는 앱에 포함할 수 있는 공개 값이다(로드맵 8.1).
service-role/secret key는 어떤 경로로도 이 설정에 두지 않는다.

설정 우선순위: 환경변수 > 번들 빌드 설정 > 없음(오프라인).
- 개발·테스트에서는 환경변수로 번들 값을 덮어쓸 수 있어야 한다.
- 빌드 산출물에는 `scripts/generate_build_config.py`가 만든
  ``mdlogger.remote._bundled_config`` 모듈만 번들된다.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass

_URL_ENV = "MDLOGGER_SUPABASE_URL"
_ANON_KEY_ENV = "MDLOGGER_SUPABASE_ANON_KEY"

# 빌드 시 생성되는 번들 설정 모듈. 저장소에는 커밋하지 않으며(.gitignore),
# PYTHONPATH/PyInstaller 上 존재하지 않으면 ImportError를 흡수해 오프라인 동작으로 돌아간다.
_BUILD_CONFIG_MODULE = "mdlogger.remote._bundled_config"


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


def _load_build_module() -> object | None:
    """``_bundled_config`` 모듈을 반환한다. 없으면 None(ImportError 흡수)."""
    try:
        return importlib.import_module(_BUILD_CONFIG_MODULE)
    except ImportError:
        return None


def bundled_config(module: object | None = None) -> RemoteConfig | None:
    """빌드 시 번들된 publishable 설정을 읽는다.

    ``module``을 주입할 수 있다(테스트용). 주입하지 않으면 실제 모듈을 import하되,
    없으면(개발 저장소, 소스 실행) None을 반환해 오프라인 동작으로 폴백한다.
    """
    source = module if module is not None else _load_build_module()
    if source is None:
        return None
    base_url = str(getattr(source, "SUPABASE_URL", "") or "").strip()
    anon_key = str(getattr(source, "SUPABASE_ANON_KEY", "") or "").strip()
    if not base_url or not anon_key:
        return None
    return RemoteConfig(base_url=base_url, anon_key=anon_key)


def get_remote_config() -> RemoteConfig | None:
    """환경변수 > 번들 빌드 설정 > 없음(오프라인) 순서로 설정을 해석한다."""
    return config_from_environment() or bundled_config()
