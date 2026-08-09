"""계정 서비스 추상 인터페이스.

로드맵 2.1에 따라 인증 계층을 추상화해 이후 소셜 로그인 등 다른 제공자를
추가할 수 있게 한다. UI와 동기화 계층은 이 인터페이스에만 의존한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import (
    AccountDeletionResult,
    AccountExportData,
    AuthSession,
    DeviceInfo,
    SignUpResult,
)


class AccountService(ABC):
    """이메일 기반 등록 계정 인증 동작의 경계."""

    @abstractmethod
    def sign_up(self, email: str, password: str) -> SignUpResult:
        """이메일 회원가입. 이메일 인증 대기 상태일 수 있다."""

    @abstractmethod
    def sign_in(self, email: str, password: str) -> AuthSession:
        """이메일·비밀번호 로그인."""

    @abstractmethod
    def refresh_session(self, refresh_token: str) -> AuthSession:
        """refresh token으로 세션을 갱신한다. 토큰은 회전될 수 있다."""

    @abstractmethod
    def sign_out(self, access_token: str) -> None:
        """서버 세션(refresh token)을 폐기한다."""

    @abstractmethod
    def resend_verification_email(self, email: str) -> None:
        """가입 확인(이메일 인증) 메일을 다시 보낸다."""

    @abstractmethod
    def request_password_reset(self, email: str) -> None:
        """비밀번호 재설정 메일 전송을 요청한다."""

    @abstractmethod
    def export_account_data(self, access_token: str) -> AccountExportData:
        """본인 개인 데이터를 내려받는다(로드맵 12.4)."""

    @abstractmethod
    def list_devices(self, access_token: str) -> list[DeviceInfo]:
        """등록된 장치 목록을 조회한다."""

    @abstractmethod
    def revoke_device(self, access_token: str, installation_id: str) -> None:
        """특정 장치를 해제한다(모든 장치 로그아웃의 일부)."""

    @abstractmethod
    def sign_out_all_devices(self, access_token: str) -> int:
        """모든 장치에서 로그아웃하고 해제된 장치 수를 돌려준다."""

    @abstractmethod
    def delete_account(
        self, access_token: str, user_id: str | None = None
    ) -> AccountDeletionResult:
        """계정 삭제를 요청한다. 클라이언트 secret 없이 서버에서 수행된다."""
