"""신규 기록에 부여할 현재 환경(environment) version을 관리한다(하드닝 H4).

로드맵 §7.6/결정 H-2: 서로 다른 월 환경의 기록이 집계에서 섞이지 않도록,
클라이언트는 현재 유효한 ``environment_versions.id``를 조회·캐시하고 **신규
기록에만** 부여한다. 환경을 알 수 없는 오프라인에서는 NULL로 두고 소급 부여하지
않는다(추측 금지). 이미 사용된 환경 version의 의미는 나중에 덮어쓰지 않는다.
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Any

from .paths import DATA_DIR
from .remote.client import JsonHttpClient
from .remote.config import RemoteConfig
from .remote.errors import NetworkError, ResponseFormatError

ENVIRONMENT_VERSION_CACHE_PATH = DATA_DIR / "environment_version_cache.json"


def load_env_id(path: Path) -> str | None:
    """캐시 파일에서 현재 환경 version id를 읽는다. 없으면 None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("environment_version_id") if isinstance(data, dict) else None
    return str(value).strip() if isinstance(value, str) and value.strip() else None


def save_env_id(path: Path, env_id: str | None) -> None:
    """현재 환경 version id를 원자적으로 캐시 기록한다. None이면 제거."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    if env_id is None:
        tmp.write_text("{}", encoding="utf-8")
    else:
        payload = json.dumps(
            {"environment_version_id": env_id}, ensure_ascii=False, indent=2
        )
        tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(path)


class EnvironmentVersionClient:
    """``environment_versions`` 기준정보에서 현재 유효한 행 id를 읽는다."""

    def __init__(
        self,
        config: RemoteConfig,
        *,
        client: JsonHttpClient | None = None,
        timeout: float = 3.0,
    ) -> None:
        self._config = config
        self._client = client or JsonHttpClient(timeout=timeout)

    def fetch_current(self) -> str | None:
        """지금 유효한 환경 version id를 반환한다. 조회 실패는 None(비차단)."""
        url = self._fetch_url()
        headers = {
            "apikey": self._config.anon_key,
            "Authorization": f"Bearer {self._config.anon_key}",
        }
        try:
            response = self._client.request_json("GET", url, None, headers)
        except (NetworkError, ResponseFormatError):
            return None
        if response.status != 200:
            return None
        body = response.json()
        if isinstance(body, list) and body:
            item = body[0]
            env_id = item.get("id") if isinstance(item, dict) else None
            return (
                str(env_id).strip()
                if isinstance(env_id, str) and env_id.strip()
                else None
            )
        return None

    def _fetch_url(self) -> str:
        query = urllib.parse.urlencode(
            {
                "select": "id",
                "effective_from": "lte.now",
                "effective_to": "gte.now",
                "order": "effective_from.desc",
                "limit": "1",
            }
        )
        return f"{self._config.rest_url}/environment_versions?{query}"


def _load_current(cache_path: Path) -> str | None:
    return load_env_id(cache_path)


class EnvironmentVersionProvider:
    """현재 환경 version id를 캐시로 관리한다(주입 가능)."""

    def __init__(
        self,
        cache_path: Path = ENVIRONMENT_VERSION_CACHE_PATH,
        *,
        load: Any | None = None,
        save: Any | None = None,
    ) -> None:
        self._cache_path = cache_path
        self._load = load or _load_current
        self._save = save or save_env_id
        self._current = self._load(self._cache_path)

    def current(self) -> str | None:
        return self._current

    def set_current(self, env_id: str | None) -> None:
        self._current = None if not env_id else str(env_id).strip()
        self._save(self._cache_path, self._current)

    def reset(self) -> None:
        """데이터 파일을 다시 만들지 않고 메모리의 캐시 값을 비운다."""
        self._current = None


_PROVIDER = EnvironmentVersionProvider()


def current_environment_id() -> str | None:
    """신규 기록에 부여할 현재 환경 version id(없으면 None)."""
    return _PROVIDER.current()


def reset_current_environment() -> None:
    """앱 초기화 후 이전 실행의 환경 캐시를 새 기록에 쓰지 않게 한다."""
    _PROVIDER.reset()


def refresh_from_server(remote_config: RemoteConfig | None) -> str | None:
    """온라인일 때 현재 환경 id를 조회해 캐시에 반영한다."""
    if remote_config is not None:
        env_id = EnvironmentVersionClient(remote_config).fetch_current()
        if env_id is not None:
            _PROVIDER.set_current(env_id)
    return _PROVIDER.current()
