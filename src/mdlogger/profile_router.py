"""시작 프로필 라우팅과 단계 6 계정 UI 흐름을 조정한다."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from threading import Thread
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from .app_controller import AppController
from .auth.credential_store import CredentialStoreError
from .auth.models import AuthError, AuthErrorKind, AuthSession, SignUpResult
from .auth.session_manager import SessionManager, SessionState
from .profiles import ProfileContext, ProfileError, ProfileKind, ProfileManager
from .ui.account_views import (
    AccountDialog,
    AuthWindow,
    GuestNoticeDialog,
    GuestRecordChoiceDialog,
)
from .ui.main_window import MainWindow

CONSENT_VERSION = "duel-data-v1"
ConsentPrompt = Callable[[bool, QWidget | None], bool]
GuestRecordsPrompt = Callable[[int, QWidget | None], bool]


def _default_consent_prompt(registered: bool, parent: QWidget | None) -> bool:
    dialog = GuestNoticeDialog(parent, registered=registered)
    return dialog.exec() == QDialog.DialogCode.Accepted


def _default_guest_records_prompt(record_count: int, parent: QWidget | None) -> bool:
    dialog = GuestRecordChoiceDialog(record_count, parent)
    return dialog.exec() == QDialog.DialogCode.Accepted


class ProfileRouter:
    """저장된 세션·동의·사용자 선택을 현재 로컬 프로필로 연결한다."""

    def __init__(
        self,
        profiles: ProfileManager,
        app_controller: AppController,
        sessions: SessionManager | None,
        *,
        auth_window: AuthWindow | None = None,
        consent_prompt: ConsentPrompt = _default_consent_prompt,
        guest_records_prompt: GuestRecordsPrompt = _default_guest_records_prompt,
    ) -> None:
        self._profiles = profiles
        self._app = app_controller
        self._sessions = sessions
        self._auth = auth_window if auth_window is not None else AuthWindow()
        self._consent_prompt = consent_prompt
        self._guest_records_prompt = guest_records_prompt
        self._pending: set[Future[Any]] = set()
        self._auth_generation = 0
        self._closing = False
        self._connect_auth_window()

    @property
    def auth_window(self) -> AuthWindow:
        return self._auth

    def start(self) -> None:
        """마지막 프로필을 복원하고 필요한 경우에만 시작 UI를 표시한다."""
        last_profile = self._profiles.last_profile()
        if last_profile is None:
            self.show_auth()
            return
        if not self._profiles.has_data_consent(CONSENT_VERSION):
            self.show_auth("계속하려면 듀얼 데이터 사용 안내를 확인해 주세요.")
            return
        if last_profile.kind is ProfileKind.GUEST:
            self._open_profile(last_profile)
            return
        self._restore_registered(last_profile)

    def show_auth(self, message: str = "") -> None:
        self._auth_generation += 1
        self._auth.show_login(message)
        self._auth.set_online_available(self._sessions is not None)
        self._auth.show()
        self._auth.raise_()
        self._auth.activateWindow()

    def request_guest(self) -> None:
        if not self._ensure_consent(registered=False):
            return
        self._auth.hide()
        self._open_profile(self._profiles.guest())

    def sign_in(self, email: str, password: str) -> None:
        sessions = self._sessions
        if sessions is None:
            self._auth.set_status(
                "온라인 계정 설정이 없습니다. 게스트로 계속해 주세요.", error=True
            )
            return
        self._auth.set_busy(True)
        QApplication.processEvents()
        try:
            session = sessions.authenticate(email, password)
        except CredentialStoreError as error:
            self._auth.set_busy(False)
            self._auth.show_auth_error(
                f"{error} OS 보안 저장소를 확인한 뒤 다시 시도해 주세요."
            )
            return
        except AuthError as error:
            self._auth.set_busy(False)
            self._show_auth_error(error, email)
            return
        self._auth.set_busy(False)
        self._finish_registered_sign_in(session)

    def sign_up(self, email: str, password: str) -> None:
        sessions = self._sessions
        if sessions is None:
            self._auth.set_status("온라인 계정 설정이 없습니다.", error=True)
            return
        self._auth.set_busy(True)
        QApplication.processEvents()
        try:
            result = sessions.register(email, password)
        except CredentialStoreError as error:
            self._auth.set_busy(False)
            self._auth.show_auth_error(
                f"{error} OS 보안 저장소를 확인한 뒤 다시 시도해 주세요."
            )
            return
        except AuthError as error:
            self._auth.set_busy(False)
            self._show_auth_error(error, email)
            return
        self._auth.set_busy(False)
        if result.needs_email_verification:
            self._auth.show_verification(email)
            return
        if result.session is None:
            self._auth.show_auth_error("회원가입 세션을 확인할 수 없습니다.")
            return
        self._finish_registered_sign_in(result.session)

    def resend_verification(self, email: str) -> None:
        sessions = self._sessions
        if sessions is None:
            return
        try:
            sessions.resend_verification_email(email)
        except AuthError as error:
            self._auth.set_verification_status(
                self._auth_error_message(error), error=True
            )
            return
        self._auth.set_verification_status("인증 메일을 다시 보냈습니다.")

    def request_password_reset(self, email: str) -> None:
        sessions = self._sessions
        if sessions is None:
            return
        self._auth.set_busy(True)
        QApplication.processEvents()
        try:
            sessions.request_password_reset(email)
        except AuthError as error:
            self._auth.set_busy(False)
            self._auth.show_auth_error(self._auth_error_message(error))
            return
        self._auth.set_busy(False)
        self._auth.set_status(
            "계정이 존재하면 비밀번호 재설정 메일을 보냈습니다. 메일함을 확인해 주세요."
        )

    def open_account_dialog(self) -> None:
        profile = self._app.current_profile
        if profile is None:
            return
        parent = self._main_window()
        registered = profile.kind is ProfileKind.REGISTERED
        status = self._profile_status(profile)
        dialog = AccountDialog(
            profile.display_name, status, registered=registered, parent=parent
        )
        dialog.login_requested.connect(lambda: self._open_auth_from_account(dialog))
        dialog.logout_requested.connect(lambda: self._logout_from_dialog(dialog))
        dialog.sync_requested.connect(lambda: self._app.request_sync(retry_failed=True))
        dialog.exec()

    def close(self) -> None:
        self._closing = True
        self._auth_generation += 1
        self._auth.close()

    def _connect_auth_window(self) -> None:
        self._auth.sign_in_requested.connect(self._start_sign_in)
        self._auth.sign_up_requested.connect(self._start_sign_up)
        self._auth.guest_requested.connect(self.request_guest)
        self._auth.resend_requested.connect(self._start_resend_verification)
        self._auth.password_reset_requested.connect(self._start_password_reset)
        self._auth.flow_cancelled.connect(self._cancel_auth_flow)

    def _start_sign_in(self, email: str, password: str) -> None:
        sessions = self._sessions
        if sessions is None:
            self.sign_in(email, password)
            return
        self._auth.set_busy(True)
        self._run_async(
            lambda: sessions.authenticate(email, password),
            lambda session: self._complete_async_sign_in(session),
            lambda error: self._complete_async_auth_error(error, email),
        )

    def _start_sign_up(self, email: str, password: str) -> None:
        sessions = self._sessions
        if sessions is None:
            self.sign_up(email, password)
            return
        self._auth.set_busy(True)
        self._run_async(
            lambda: sessions.register(email, password),
            lambda result: self._complete_async_sign_up(email, result),
            lambda error: self._complete_async_auth_error(error, email),
        )

    def _start_resend_verification(self, email: str) -> None:
        sessions = self._sessions
        if sessions is None:
            return
        self._auth.set_verification_busy(True)
        self._run_async(
            lambda: sessions.resend_verification_email(email),
            lambda _result: self._complete_async_resend(),
            lambda error: self._complete_async_verification_error(error),
        )

    def _start_password_reset(self, email: str) -> None:
        sessions = self._sessions
        if sessions is None:
            return
        self._auth.set_busy(True)
        self._run_async(
            lambda: sessions.request_password_reset(email),
            lambda _result: self._complete_async_password_reset(),
            lambda error: self._complete_async_auth_error(error, email),
        )

    def _run_async(
        self,
        operation: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        if self._closing:
            return
        generation = self._auth_generation
        future: Future[Any] = Future()

        def run() -> None:
            try:
                future.set_result(operation())
            except Exception as error:
                future.set_exception(error)

        Thread(target=run, name="mdlogger-auth", daemon=True).start()
        self._pending.add(future)

        def poll() -> None:
            if not future.done():
                if not self._closing:
                    QTimer.singleShot(25, poll)
                return
            self._pending.discard(future)
            if self._closing or generation != self._auth_generation:
                return
            try:
                result = future.result()
            except Exception as error:
                on_error(error)
            else:
                on_success(result)

        QTimer.singleShot(0, poll)

    def _cancel_auth_flow(self) -> None:
        self._auth_generation += 1

    def _complete_async_sign_in(self, session: AuthSession) -> None:
        self._auth.set_busy(False)
        self._finish_registered_sign_in(session)

    def _complete_async_sign_up(self, email: str, result: SignUpResult) -> None:
        self._auth.set_busy(False)
        if result.needs_email_verification:
            self._auth.show_verification(email)
        elif result.session is None:
            self._auth.show_auth_error("회원가입 세션을 확인할 수 없습니다.")
        else:
            self._finish_registered_sign_in(result.session)

    def _complete_async_resend(self) -> None:
        self._auth.set_verification_busy(False)
        self._auth.set_verification_status("인증 메일을 다시 보냈습니다.")

    def _complete_async_password_reset(self) -> None:
        self._auth.set_busy(False)
        self._auth.set_status(
            "계정이 존재하면 비밀번호 재설정 메일을 보냈습니다. 메일함을 확인해 주세요."
        )

    def _complete_async_auth_error(self, error: Exception, email: str) -> None:
        self._auth.set_busy(False)
        if isinstance(error, AuthError):
            self._show_auth_error(error, email)
        else:
            self._auth.show_auth_error(
                "인증 요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."
            )

    def _complete_async_verification_error(self, error: Exception) -> None:
        self._auth.set_verification_busy(False)
        message = (
            self._auth_error_message(error)
            if isinstance(error, AuthError)
            else "인증 메일을 보내지 못했습니다. 잠시 후 다시 시도해 주세요."
        )
        self._auth.set_verification_status(message, error=True)

    def _restore_registered(self, stored_profile: ProfileContext) -> None:
        sessions = self._sessions
        if stored_profile.remote_user_id is None:
            self.show_auth("저장된 등록 프로필 정보가 올바르지 않습니다.")
            return
        if sessions is None:
            self._open_profile(
                self._profiles.registered(
                    stored_profile.remote_user_id,
                    stored_profile.display_name,
                    session_state="offline",
                )
            )
            return
        try:
            snapshot = sessions.restore(stored_profile.remote_user_id)
        except CredentialStoreError:
            profile = self._profiles.registered(
                stored_profile.remote_user_id,
                stored_profile.display_name,
                session_state="credential_unavailable",
            )
            if self._open_profile(profile):
                self.show_auth(
                    "OS 보안 저장소를 사용할 수 없습니다. 설정을 확인한 뒤 다시 로그인해 주세요."
                )
            return

        if (
            snapshot.state is SessionState.AUTHENTICATED
            and snapshot.session is not None
        ):
            account = snapshot.session.account
            profile = self._profiles.registered(
                account.user_id, account.email, session_state="authenticated"
            )
        elif snapshot.state is SessionState.OFFLINE:
            profile = self._profiles.registered(
                stored_profile.remote_user_id,
                stored_profile.display_name,
                session_state="offline",
            )
        else:
            profile = self._profiles.registered(
                stored_profile.remote_user_id,
                stored_profile.display_name,
                session_state="reauth_required",
            )
        opened = self._open_profile(profile)
        if opened and snapshot.state in (
            SessionState.SIGNED_OUT,
            SessionState.REAUTH_REQUIRED,
        ):
            self.show_auth("세션이 만료되었습니다. 다시 로그인해 주세요.")

    def _finish_registered_sign_in(self, session: AuthSession) -> None:
        if not self._ensure_consent(registered=True):
            return
        current = self._app.current_profile
        if (
            current is not None
            and current.kind is ProfileKind.GUEST
            and self._app.current_game_count > 0
            and not self._guest_records_prompt(
                self._app.current_game_count, self._main_window()
            )
        ):
            return
        profile = self._profiles.registered(
            session.account.user_id,
            session.account.email,
            session_state="authenticated",
        )
        previous = self._app.current_profile
        if not self._open_profile(profile):
            return
        sessions = self._sessions
        if sessions is None:
            self._restore_after_activation_failure(previous)
            self.show_auth("온라인 계정 세션을 저장할 수 없습니다.")
            return
        try:
            sessions.activate(session)
            self._app.request_sync()
        except CredentialStoreError as error:
            self._restore_after_activation_failure(previous)
            self.show_auth(f"{error} OS 보안 저장소를 확인한 뒤 다시 시도해 주세요.")
            return
        self._auth.hide()

    def _ensure_consent(self, *, registered: bool) -> bool:
        if self._profiles.has_data_consent(CONSENT_VERSION):
            return True
        if not self._consent_prompt(registered, self._main_window()):
            return False
        try:
            self._profiles.accept_data_consent(CONSENT_VERSION)
        except (OSError, ProfileError) as error:
            self._auth.show_auth_error(
                f"동의 상태를 저장할 수 없습니다. {error}", field=None
            )
            return False
        return True

    def _open_profile(self, profile: ProfileContext) -> bool:
        previous = self._app.current_profile
        try:
            self._app.switch_profile(profile)
        except Exception as error:
            self._restore_after_activation_failure(previous)
            detail = (
                str(error)
                if isinstance(error, ProfileError)
                else "로컬 데이터 파일과 저장 공간을 확인해 주세요."
            )
            self.show_auth(f"프로필을 열 수 없습니다. {detail}")
            return False
        self._connect_current_main_window()
        return True

    def _restore_after_activation_failure(
        self, previous: ProfileContext | None
    ) -> None:
        if previous is None:
            self._app.close()
            return
        try:
            self._app.switch_profile(previous)
        except Exception:
            self._app.close()
        else:
            self._connect_current_main_window()

    def _connect_current_main_window(self) -> None:
        window = self._main_window()
        if window is not None:
            window.account_requested.connect(self.open_account_dialog)

    def _main_window(self) -> MainWindow | None:
        window = self._app.current_window
        return window if isinstance(window, MainWindow) else None

    def _open_auth_from_account(self, dialog: AccountDialog) -> None:
        dialog.accept()
        self.show_auth()

    def _logout_from_dialog(self, dialog: AccountDialog) -> None:
        profile = self._app.current_profile
        if profile is None or profile.remote_user_id is None:
            return
        sessions = self._sessions
        if sessions is not None:
            try:
                sessions.sign_out(profile.remote_user_id)
            except CredentialStoreError as error:
                QMessageBox.warning(
                    dialog,
                    "로그아웃 실패",
                    f"{error}\nOS 보안 저장소를 확인한 뒤 다시 시도해 주세요.",
                )
                return
        dialog.accept()
        self._open_profile(self._profiles.guest())

    def _show_auth_error(self, error: AuthError, email: str) -> None:
        if error.code in {"email_exists", "user_already_exists"}:
            self._auth.show_auth_error(
                "이미 가입된 이메일입니다. 로그인하거나 비밀번호를 재설정해 주세요.",
                field="email",
            )
        elif error.code == "email_address_invalid":
            self._auth.show_auth_error(
                "사용할 수 있는 올바른 이메일 주소를 입력해 주세요.", field="email"
            )
        elif error.code == "email_address_not_authorized":
            self._auth.show_auth_error(
                "이 이메일 주소는 현재 가입에 사용할 수 없습니다. 다른 주소를 입력해 주세요.",
                field="email",
            )
        elif error.code == "weak_password":
            self._auth.show_auth_error(
                "비밀번호가 서버의 보안 기준을 충족하지 않습니다. 더 길고 복잡하게 입력해 주세요.",
                field="password",
            )
        elif error.code == "signup_disabled":
            self._auth.show_auth_error(
                "현재 새 계정을 만들 수 없습니다. 잠시 후 다시 시도해 주세요."
            )
        elif error.code == "validation_failed":
            self._auth.show_auth_error(
                "입력 내용을 확인해 주세요. 문제가 계속되면 로그인 또는 비밀번호 재설정을 시도해 주세요."
            )
        elif error.kind is AuthErrorKind.CREDENTIALS:
            self._auth.show_auth_error(
                "이메일 또는 비밀번호가 올바르지 않습니다.", field="password"
            )
        elif error.kind is AuthErrorKind.EMAIL_UNVERIFIED:
            self._auth.show_verification(email)
            self._auth.set_verification_status(
                "이메일 인증 후 로그인해 주세요.", error=True
            )
        else:
            self._auth.show_auth_error(self._auth_error_message(error))

    @staticmethod
    def _auth_error_message(error: AuthError) -> str:
        if error.kind is AuthErrorKind.NETWORK:
            return "네트워크에 연결할 수 없습니다. 연결을 확인하거나 게스트로 계속해 주세요."
        if error.kind is AuthErrorKind.TOKEN_EXPIRED:
            return "세션이 만료되었습니다. 다시 로그인해 주세요."
        if error.kind is AuthErrorKind.EMAIL_UNVERIFIED:
            return "이메일 인증이 필요합니다. 메일함을 확인해 주세요."
        return "인증 서버가 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."

    def _profile_status(self, profile: ProfileContext) -> str:
        sync_status = self._app.sync_status
        sync_text = sync_status.display_text if sync_status is not None else "로컬 저장"
        if profile.kind is ProfileKind.GUEST:
            return f"게스트 · {sync_text}"
        detail = {
            "authenticated": "로그인됨",
            "offline": "오프라인 · 저장된 로컬 계정 사용 중",
            "reauth_required": "재로그인 필요 · 로컬 기록은 유지됨",
            "credential_unavailable": "OS 보안 저장소 확인 필요 · 로컬 기록은 유지됨",
        }.get(profile.session_state, "로컬 계정 사용 중")
        return f"{profile.display_name} · {detail} · {sync_text}"
