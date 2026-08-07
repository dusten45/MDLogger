"""원격 통신 오류의 공통 분류.

네트워크 오류(재시도 가능)와 서버가 응답한 거부(재시도 무의미)를
구분한다(로드맵 9.5). 오류 메시지에는 토큰이나 자격 증명을 포함하지 않는다.
"""

from __future__ import annotations


class RemoteError(Exception):
    """원격 통신 실패의 공통 기반."""


class NetworkError(RemoteError):
    """연결 실패, timeout, DNS 실패 등 응답을 받지 못한 오류."""


class ResponseFormatError(RemoteError):
    """서버 응답 본문이 기대한 JSON 형식이 아닐 때."""
