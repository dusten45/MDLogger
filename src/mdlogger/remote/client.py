"""표준 라이브러리 기반 JSON HTTP client.

로드맵 16장에 따라 새 HTTP 의존성 대신 ``urllib``을 사용한다.
모든 요청에 timeout을 적용하고 TLS 검증은 기본값(검증 활성)을 유지하며,
transport를 주입할 수 있어 테스트에서 실제 네트워크 없이 대체할 수 있다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from .errors import NetworkError, ResponseFormatError

DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """상태 코드와 본문만 담는 최소 HTTP 응답."""

    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        if not self.body:
            return None
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ResponseFormatError(
                f"서버 응답(JSON) 해석 실패 (HTTP {self.status})"
            ) from error


class HttpTransport(Protocol):
    """단일 HTTP 요청을 수행하는 주입 가능한 transport."""

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse: ...


class UrllibTransport:
    """``urllib.request`` 기반 기본 transport. TLS 검증은 기본값을 따른다."""

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        if not url.startswith("https://") and not url.startswith("http://"):
            raise NetworkError("지원하지 않는 URL 스킴입니다.")
        request = urllib.request.Request(url, data=body, method=method)
        for name, value in headers.items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status=int(response.status),
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as error:
            # 4xx/5xx는 서버가 응답한 것이므로 응답으로 반환해 분류한다.
            with error:
                return HttpResponse(
                    status=int(error.code),
                    body=error.read(),
                    headers=dict(error.headers.items()),
                )
        except OSError as error:
            # urllib.error.URLError와 timeout 모두 OSError 계열이다.
            raise NetworkError("서버에 연결할 수 없습니다.") from error


class JsonHttpClient:
    """JSON 요청/응답 전용의 얇은 client."""

    def __init__(
        self,
        transport: HttpTransport | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._transport = transport or UrllibTransport()
        self._timeout = timeout

    def request_json(
        self,
        method: str,
        url: str,
        payload: Any,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        body = None
        request_headers = dict(headers or {})
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        return self._transport.request(
            method, url, request_headers, body, self._timeout
        )

    def post_json(
        self,
        url: str,
        payload: Any,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        return self.request_json("POST", url, payload, headers)
