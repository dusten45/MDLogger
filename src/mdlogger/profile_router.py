"""시작 프로필 라우팅과 단계 6 계정 UI 흐름을 조정한다."""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QWidget

from .app_controller import AppController
from .auth.credential_store import CredentialStoreError
from .auth.models import AuthError, AuthErrorKind, AuthSession, SignUpResult
from .auth.session_manager import SessionManager, SessionState
from .guest_import import (
    GuestImportError,
    GuestImportResult,
    import_guest_records,
)
from .profiles import ProfileContext, ProfileError, ProfileKind, ProfileManager
from .ui.account_views import (
    AccountDialog,
    AuthWindow,
    ConflictDialog,
    GuestNoticeDialog,
    GuestRecordChoice,
    GuestRecordChoiceDialog,
)
from .ui.main_window import MainWindow

CONSENT_VERSION = "duel-data-v1"
ConsentPrompt = Callable[[bool, QWidget | None], bool]
GuestRecordsPrompt = Callable[[int, QWidget | None], GuestRecordChoice]
ImportResultPrompt = Callable[
    [GuestImportResult | None, BaseException | None, QWidget | None], bool
]


def _default_consent_prompt(registered: bool, parent: QWidget | None) -> bool:
    dialog = GuestNoticeDialog(parent, registered=registered)
    return dialog.exec() == QDialog.DialogCode.Accepted


def _default_guest_records_prompt(
    record_count: int, parent: QWidget | None
) -> GuestRecordChoice:
    dialog = GuestRecordChoiceDialog(record_count, parent)
    dialog.exec()
    return dialog.choice


def _default_import_result_prompt(
    result: GuestImportResult | None,
    error: BaseException | None,
    parent: QWidget | None,
) -> bool:
    if error is not None:
        QMessageBox.critical(
            parent,
            "게스트 기록 가져오기 실패",
            f"게스트 기록을 가져오지 못했습니다. 게스트 데이터는 그대로 보존됩니다.\n{error}",
        )
        return False
    if result is None:
        return False
    message = f"게스트 기록 {result.imported_count}건을 계정으로 가져왔습니다."
    if result.skipped_count:
        message += f"\n{result.skipped_count}건은 이미 계정에 있어 건너뛰었습니다."
    QMessageBox.information(parent, "게스트 기록 가져오기 완료", message)
    return True


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
        import_result_prompt: ImportResultPrompt = _default_import_result_prompt,
    ) -> None:
        self._profiles = profiles
        self._app = app_controller
        self._sessions = sessions
        self._auth = auth_window if auth_window is not None else AuthWindow()
        self._consent_prompt = consent_prompt
        self._guest_records_prompt = guest_records_prompt
        self._import_result_prompt = import_result_prompt
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
        # 이전 진행 중(요청 중) 창을 닫았다 다시 열면 set_busy(True)가 비활성화한
        # 게스트/비밀번호 표시를 재활성화한다. 이후 set_online_available이 온라인 전용
        # 필드를 다시 적절히 조정한다(P0-6).
        self._auth.set_busy(False)
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
        sync_status = self._app.sync_status
        conflict_count = (
            int(getattr(sync_status, "conflict_count", 0))
            if sync_status is not None
            else 0
        )
        dialog = AccountDialog(
            profile.display_name,
            status,
            registered=registered,
            conflict_count=conflict_count,
            parent=parent,
        )
        dialog.login_requested.connect(lambda: self._open_auth_from_account(dialog))
        dialog.logout_requested.connect(lambda: self._logout_from_dialog(dialog))
        dialog.sync_requested.connect(self._request_sync)
        dialog.conflicts_requested.connect(lambda: self._open_conflicts(dialog))
        dialog.export_requested.connect(lambda: self._export_account_data(dialog))
        dialog.sign_out_all_requested.connect(
            lambda: self._sign_out_all_devices(dialog)
        )
        dialog.delete_account_requested.connect(lambda: self._delete_account(dialog))
        dialog.exec()

    def _open_conflicts(self, account_dialog: QDialog) -> None:
        account_dialog.hide()
        parent = self._main_window()
        try:
            for conflict in self._app.list_conflicts():
                dialog = ConflictDialog(conflict, parent)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    break
                if dialog.resolution is not None:
                    try:
                        self._app.resolve_conflict(
                            conflict.id,
                            dialog.resolution,
                            dialog.merged_payload,
                            expected_remote_version=int(
                                conflict.remote_payload["change_version"]
                            ),
                        )
                    except (KeyError, TypeError, ValueError) as error:
                        QMessageBox.information(
                            parent,
                            "충돌 정보 갱신 필요",
                            f"{error}\n최신 충돌 내용을 다시 확인해 주세요.",
                        )
                        break
        finally:
            account_dialog.accept()

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
        if stored_profile.session_state == "signed_out":
            # 사용자가 명시적으로 로그아웃했으므로 등록 프로필을 자동으로 열지 않고
            # 깨끗한 로그인 창으로 시작한다. 로그인 창에서 다시 로그인하거나
            # 게스트로 계속할 수 있다. 저장된 refresh token이 잔존해도 항상
            # 로그인을 요구한다(로그아웃 상태가 우선).
            self.show_auth("로그아웃되었습니다. 다시 로그인해 주세요.")
            return
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
        guest_choice = GuestRecordChoice.KEEP
        if (
            current is not None
            and current.kind is ProfileKind.GUEST
            and self._app.current_game_count > 0
        ):
            guest_choice = self._guest_records_prompt(
                self._app.current_game_count, self._main_window()
            )
            if guest_choice is GuestRecordChoice.LATER:
                return
        profile = self._profiles.registered(
            session.account.user_id,
            session.account.email,
            session_state="authenticated",
        )
        previous = self._app.current_profile
        if guest_choice is GuestRecordChoice.IMPORT and current is not None:
            if not self._import_guest_records(current, profile):
                return
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

    def _import_guest_records(
        self, guest: ProfileContext, registered: ProfileContext
    ) -> bool:
        """게스트 기록을 등록 계정 DB로 비파괴 import하고 결과를 알린다."""
        try:
            self._profiles.prepare_database(registered)
            result = import_guest_records(guest.database_path, registered.database_path)
        except (GuestImportError, ProfileError, OSError) as error:
            return self._import_result_prompt(None, error, self._main_window())
        return self._import_result_prompt(result, None, self._main_window())

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
        self._return_to_login()

    def _return_to_login(self) -> None:
        """현재 등록 계정을 로그아웃하고 로그인 창으로 돌아간다(게스트 선택 가능).

        마지막 등록 세션 상태를 '로그아웃됨'으로 기록하고, 현재 등록 창을 닫은 뒤
        로그인/회원가입 창을 보여준다. 사용자는 로그인 창에서 다시 로그인하거나
        게스트로 계속할 수 있다.
        """
        try:
            self._profiles.set_session_state("signed_out")
        except ProfileError:
            # 세션 상태 기록은 로그아웃의 필수 조건이 아니다. 토큰 제거는
            # SessionManager.sign_out 계열이 이미 수행했으므로, 기록 실패가
            # 로그아웃·로그인 창 전환을 막지 않게 한다.
            pass
        try:
            self._app.close()
        finally:
            # 현재 등록 창 정리 중 예외가 나도 사용자가 화면 없이 남지 않도록
            # 로그인 창은 반드시 보여준다(B-2).
            self.show_auth()

    def _request_sync(self) -> None:
        """동기화 버튼: outbox 재시도 후 즉시 동기화를 시도한다(A-2)."""
        try:
            self._app.request_sync(retry_failed=True)
        except Exception as error:  # noqa: BLE001
            parent = self._main_window()
            if parent is not None:
                QMessageBox.information(
                    parent,
                    "재시도",
                    f"재시도 항목을 다시 처리하지 못했습니다.\n{error}\n"
                    "자동으로 다시 시도됩니다.",
                )

    def _export_account_data(self, dialog: AccountDialog) -> None:
        """본인 개인 데이터를 파일로 내보낸다(로드맵 12.4)."""
        sessions = self._sessions
        if sessions is None:
            QMessageBox.information(
                dialog, "데이터 내보내기", "온라인 계정 설정이 없습니다."
            )
            return
        try:
            data = sessions.export_account_data()
        except AuthError as error:
            QMessageBox.warning(
                dialog, "데이터 내보내기 실패", self._auth_error_message(error)
            )
            return

        default_name = (
            f"mdlogger-account-data-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        )
        path, _ = QFileDialog.getSaveFileName(
            dialog, "내 데이터 저장", default_name, "JSON 문서 (*.json)"
        )
        if not path:
            return
        try:
            payload = {
                "format": "mdlogger-account-data",
                "exported_at": datetime.now().astimezone().isoformat(),
                "profile": data.profile,
                "games": list(data.games),
                "devices": [
                    {
                        "id": device.id,
                        "installation_id": device.installation_id,
                        "display_name": device.display_name,
                        "client_version": device.client_version,
                        "created_at": device.created_at,
                        "last_seen_at": device.last_seen_at,
                        "last_acknowledged_version": device.last_acknowledged_version,
                    }
                    for device in data.devices
                ],
            }
            Path(path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as error:
            QMessageBox.critical(
                dialog, "데이터 내보내기 실패", f"파일을 저장하지 못했습니다.\n{error}"
            )
            return
        QMessageBox.information(
            dialog,
            "데이터 내보내기 완료",
            f"계정 개인 데이터를 저장했습니다.\n{path}",
        )

    def _sign_out_all_devices(self, dialog: AccountDialog) -> None:
        """모든 장치에서 로그아웃한다(로드맵 단계 11)."""
        sessions = self._sessions
        if sessions is None:
            QMessageBox.information(
                dialog, "모든 기기에서 로그아웃", "온라인 계정 설정이 없습니다."
            )
            return
        answer = QMessageBox.question(
            dialog,
            "모든 기기에서 로그아웃",
            "모든 기기에서 이 계정을 로그아웃합니다. 이 기기의 로컬 기록은 유지됩니다.\n"
            "계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            count = sessions.sign_out_all_devices()
        except CredentialStoreError as error:
            # 서버측 세션 폐기·장치 행 정리는 이미 성공했지만, 로컬 refresh token
            # 제거에 실패했다. 세션이 서버에서 폐기됐으므로 다음 갱신 시 재로그인된다.
            QMessageBox.warning(
                dialog,
                "모든 기기 로그아웃 실패",
                f"{error}\nOS 보안 저장소를 확인한 뒤 다시 시도해 주세요.",
            )
            return
        except AuthError as error:
            QMessageBox.warning(
                dialog, "모든 기기 로그아웃 실패", self._auth_error_message(error)
            )
            return
        dialog.accept()
        self._return_to_login()
        self._notify_sign_out_all(count)

    def _notify_sign_out_all(self, count: int) -> None:
        """로그인 창 위에 모든 기기 로그아웃 완료 알림을 띄운다.

        작고 단순한 확인용 알림으로, 한 번 확인하면 바로 닫힌다.
        """
        QMessageBox.information(
            self._auth,
            "모든 기기 로그아웃",
            f"{count}대의 기기에서 로그아웃하였습니다.",
        )

    def _delete_account(self, dialog: AccountDialog) -> None:
        """계정 삭제를 서버에 요청한다(로드맵 단계 11, 결정 4)."""
        sessions = self._sessions
        if sessions is None:
            QMessageBox.information(dialog, "계정 삭제", "온라인 계정 설정이 없습니다.")
            return
        answer = QMessageBox.warning(
            dialog,
            "계정 삭제",
            "계정을 삭제하면 서버의 개인 기록(게임, 메모, 장치 정보)이 영구 삭제됩니다.\n"
            "이 기기의 로컬 데이터는 서버와 별개로 남아 있습니다.\n"
            "분석용 비식별 기록은 유지될 수 있습니다(로드맵 9.3).\n\n정말 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            sessions.delete_account()
        except AuthError as error:
            QMessageBox.critical(
                dialog, "계정 삭제 실패", self._auth_error_message(error)
            )
            return
        dialog.accept()
        QMessageBox.information(
            dialog,
            "계정 삭제 완료",
            "서버 계정이 삭제되었습니다. 로컬 데이터는 그대로 유지됩니다.",
        )
        self._return_to_login()

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
        if error.kind is AuthErrorKind.RATE_LIMITED:
            return "요청이 너무 잦아 잠시 제한됐습니다. 잠시 후 다시 시도해 주세요."
        # 분류하지 못한 서버 오류는 원인 코드를 함께 보여줘 진단할 수 있게 한다.
        hint = f" (코드: {error.code})" if error.code else ""
        return (
            f"인증 서버가 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.{hint}"
        )

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
