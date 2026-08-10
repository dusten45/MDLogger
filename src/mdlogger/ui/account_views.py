"""단계 6의 로그인·게스트 고지·계정 상태 UI."""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..auth.models import DeviceInfo
from ..game_sync.models import SyncConflict
from ..remote.games import PRIVATE_GAME_FIELDS
from .theme import METRICS, set_style_property


class AuthMode(StrEnum):
    LOGIN = "login"
    SIGNUP = "signup"


class GuestRecordChoice(StrEnum):
    IMPORT = "import"
    KEEP = "keep"
    LATER = "later"


class AuthWindow(QWidget):
    """로그인·회원가입과 이메일 확인 안내를 제공하는 시작 창."""

    sign_in_requested = Signal(str, str)
    sign_up_requested = Signal(str, str)
    guest_requested = Signal()
    resend_requested = Signal(str)
    password_reset_requested = Signal(str)
    flow_cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._mode = AuthMode.LOGIN
        self._verification_email = ""
        self.setWindowTitle("MD WCQ 로거 · 계정")
        self.resize(420, 560)
        self.setMinimumSize(360, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            METRICS.space_6, METRICS.space_6, METRICS.space_6, METRICS.space_6
        )
        root.setSpacing(METRICS.space_4)

        self._stack = QStackedWidget()
        self._form_page = self._build_form_page()
        self._verification_page = self._build_verification_page()
        self._stack.addWidget(self._form_page)
        self._stack.addWidget(self._verification_page)
        root.addWidget(self._stack)
        self.show_login()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.flow_cancelled.emit()
        super().closeEvent(event)

    def _build_form_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.space_2)

        self._title = QLabel()
        self._title.setProperty("role", "title")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)

        intro = QLabel("온라인 계정 또는 지속형 게스트로 시작할 수 있습니다.")
        intro.setProperty("tone", "muted")
        intro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addSpacing(METRICS.space_3)

        email_label = QLabel("이메일")
        self._email = QLineEdit()
        email_label.setBuddy(self._email)
        self._email.setObjectName("authEmail")
        self._email.setPlaceholderText("name@example.com")
        self._email.setAccessibleName("이메일")
        layout.addWidget(email_label)
        layout.addWidget(self._email)
        self._email_error = self._error_label()
        layout.addWidget(self._email_error)

        password_label = QLabel("비밀번호")
        self._password = QLineEdit()
        password_label.setBuddy(self._password)
        self._password.setObjectName("authPassword")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setAccessibleName("비밀번호")
        layout.addWidget(password_label)
        layout.addWidget(self._password)
        self._password_error = self._error_label()
        layout.addWidget(self._password_error)

        self._confirm_label = QLabel("비밀번호 확인")
        self._password_confirm = QLineEdit()
        self._confirm_label.setBuddy(self._password_confirm)
        self._password_confirm.setObjectName("authPasswordConfirm")
        self._password_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_confirm.setAccessibleName("비밀번호 확인")
        layout.addWidget(self._confirm_label)
        layout.addWidget(self._password_confirm)
        self._confirm_error = self._error_label()
        layout.addWidget(self._confirm_error)

        self._show_password = QCheckBox("비밀번호 표시")
        self._show_password.toggled.connect(self._set_password_visible)
        layout.addWidget(self._show_password)

        self._status = QLabel()
        self._status.setObjectName("authStatus")
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status)

        self._submit = QPushButton()
        self._submit.setObjectName("authSubmit")
        self._submit.setProperty("role", "primary")
        self._submit.clicked.connect(self._submit_form)
        layout.addWidget(self._submit)

        self._reset = QPushButton("비밀번호를 잊으셨나요?")
        self._reset.setProperty("role", "ghost")
        self._reset.clicked.connect(self._request_password_reset)
        layout.addWidget(self._reset)

        self._toggle_mode = QPushButton()
        self._toggle_mode.setProperty("role", "secondary")
        self._toggle_mode.clicked.connect(self._toggle_auth_mode)
        layout.addWidget(self._toggle_mode)

        divider = QLabel("또는")
        divider.setProperty("tone", "muted")
        divider.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(divider)

        self._guest = QPushButton("게스트로 계속")
        self._guest.setObjectName("guestContinue")
        self._guest.clicked.connect(self.guest_requested)
        layout.addWidget(self._guest)
        layout.addStretch(1)

        self._email.returnPressed.connect(self._submit_form)
        self._password.returnPressed.connect(self._submit_form)
        self._password_confirm.returnPressed.connect(self._submit_form)
        QWidget.setTabOrder(self._email, self._password)
        QWidget.setTabOrder(self._password, self._password_confirm)
        QWidget.setTabOrder(self._password_confirm, self._show_password)
        QWidget.setTabOrder(self._show_password, self._submit)
        QWidget.setTabOrder(self._submit, self._reset)
        QWidget.setTabOrder(self._reset, self._toggle_mode)
        QWidget.setTabOrder(self._toggle_mode, self._guest)
        return page

    def _build_verification_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.space_3)
        layout.addStretch(1)

        title = QLabel("이메일을 확인해 주세요")
        title.setProperty("role", "title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._verification_text = QLabel()
        self._verification_text.setWordWrap(True)
        self._verification_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._verification_text)

        self._verification_status = QLabel()
        self._verification_status.setWordWrap(True)
        self._verification_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._verification_status)

        self._verification_resend = QPushButton("인증 메일 다시 보내기")
        self._verification_resend.setObjectName("resendVerification")
        self._verification_resend.clicked.connect(
            lambda: self.resend_requested.emit(self._verification_email)
        )
        layout.addWidget(self._verification_resend)

        back = QPushButton("로그인으로 돌아가기")
        back.setProperty("role", "primary")
        back.clicked.connect(self.show_login)
        layout.addWidget(back)
        layout.addStretch(1)
        return page

    @staticmethod
    def _error_label() -> QLabel:
        label = QLabel()
        label.setProperty("tone", "danger")
        label.setWordWrap(True)
        label.hide()
        return label

    def show_login(self, message: str = "") -> None:
        self._mode = AuthMode.LOGIN
        self._stack.setCurrentWidget(self._form_page)
        self._title.setText("로그인")
        self._submit.setText("로그인")
        self._toggle_mode.setText("새 계정 만들기")
        self._reset.show()
        self._set_confirmation_visible(False)
        self.clear_errors()
        self.set_status(message)
        self._email.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_signup(self) -> None:
        self._mode = AuthMode.SIGNUP
        self._stack.setCurrentWidget(self._form_page)
        self._title.setText("회원가입")
        self._submit.setText("계정 만들기")
        self._toggle_mode.setText("이미 계정이 있습니다")
        self._reset.hide()
        self._set_confirmation_visible(True)
        self.clear_errors()
        self.set_status("")
        self._email.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_verification(self, email: str) -> None:
        self._verification_email = email
        self._verification_text.setText(
            f"{email} 주소로 보낸 인증 링크를 연 뒤 로그인해 주세요."
        )
        self._verification_status.clear()
        self._stack.setCurrentWidget(self._verification_page)

    def set_verification_busy(self, busy: bool) -> None:
        self._verification_resend.setEnabled(not busy)
        if busy:
            self.set_verification_status("인증 메일을 보내고 있습니다.")

    def set_verification_status(self, message: str, *, error: bool = False) -> None:
        self._verification_status.setText(message)
        set_style_property(
            self._verification_status, "tone", "danger" if error else "success"
        )

    def set_online_available(self, available: bool) -> None:
        for widget in (
            self._email,
            self._password,
            self._password_confirm,
            self._submit,
        ):
            widget.setEnabled(available)
        self._reset.setEnabled(available)
        self._toggle_mode.setEnabled(available)
        if not available:
            self.set_status(
                "온라인 계정 설정이 없습니다. 게스트로는 계속 사용할 수 있습니다.",
                error=True,
            )

    def set_busy(self, busy: bool) -> None:
        for widget in (
            self._email,
            self._password,
            self._password_confirm,
            self._show_password,
            self._submit,
            self._reset,
            self._toggle_mode,
            self._guest,
        ):
            widget.setEnabled(not busy)
        if busy:
            self.set_status("요청을 처리하고 있습니다…")

    def set_status(self, message: str, *, error: bool = False) -> None:
        self._status.setText(message)
        set_style_property(self._status, "tone", "danger" if error else "muted")

    def clear_errors(self) -> None:
        for field, label in (
            (self._email, self._email_error),
            (self._password, self._password_error),
            (self._password_confirm, self._confirm_error),
        ):
            label.clear()
            label.hide()
            set_style_property(field, "invalid", False)

    def show_auth_error(self, message: str, *, field: str | None = None) -> None:
        if field == "email":
            self._show_field_error(self._email, self._email_error, message)
        elif field == "password":
            self._show_field_error(self._password, self._password_error, message)
        else:
            self.set_status(message, error=True)

    def _show_field_error(self, field: QLineEdit, label: QLabel, message: str) -> None:
        label.setText(message)
        label.show()
        set_style_property(field, "invalid", True)
        field.setFocus(Qt.FocusReason.OtherFocusReason)

    def _toggle_auth_mode(self) -> None:
        if self._mode is AuthMode.LOGIN:
            self.show_signup()
        else:
            self.show_login()

    def _set_confirmation_visible(self, visible: bool) -> None:
        self._confirm_label.setVisible(visible)
        self._password_confirm.setVisible(visible)
        self._confirm_error.setVisible(visible and bool(self._confirm_error.text()))

    def _set_password_visible(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self._password.setEchoMode(mode)
        self._password_confirm.setEchoMode(mode)

    def _validate(self) -> bool:
        self.clear_errors()
        email = self._email.text().strip()
        password = self._password.text()
        valid = True
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            self._show_field_error(
                self._email, self._email_error, "올바른 이메일 주소를 입력해 주세요."
            )
            valid = False
        if len(password) < 6:
            self._show_field_error(
                self._password,
                self._password_error,
                "비밀번호는 6자 이상 입력해 주세요.",
            )
            valid = False
        if self._mode is AuthMode.SIGNUP and password != self._password_confirm.text():
            self._show_field_error(
                self._password_confirm,
                self._confirm_error,
                "비밀번호가 서로 다릅니다.",
            )
            valid = False
        return valid

    def _submit_form(self) -> None:
        if not self._validate():
            return
        email = self._email.text().strip()
        password = self._password.text()
        if self._mode is AuthMode.LOGIN:
            self.sign_in_requested.emit(email, password)
        else:
            self.sign_up_requested.emit(email, password)

    def _request_password_reset(self) -> None:
        self.clear_errors()
        email = self._email.text().strip()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            self._show_field_error(
                self._email,
                self._email_error,
                "재설정 메일을 받을 이메일 주소를 입력해 주세요.",
            )
            return
        self.password_reset_requested.emit(email)


class GuestNoticeDialog(QDialog):
    """첫 프로필 진입 전에 한 번 표시하는 필수 듀얼 데이터 고지."""

    def __init__(
        self, parent: QWidget | None = None, *, registered: bool = False
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("듀얼 데이터 사용 안내")
        self.setModal(True)
        self.resize(500, 430)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.space_6, METRICS.space_6, METRICS.space_6, METRICS.space_6
        )
        layout.setSpacing(METRICS.space_3)

        title = QLabel(
            "계정으로 계속하기 전에 확인해 주세요"
            if registered
            else "게스트로 계속하기 전에 확인해 주세요"
        )
        title.setProperty("role", "title")
        title.setWordWrap(True)
        layout.addWidget(title)

        profile_intro = (
            "계정 기록은 이 PC에 먼저 저장되고 서버의 개인 기록과 동기화됩니다. "
            if registered
            else "게스트 기록은 이 PC에 계속 보관됩니다. "
        )
        body = QLabel(
            profile_intro + "네트워크에 연결되면 "
            "듀얼 환경 분석을 위해 아래 게임 정보가 자동으로 전송됩니다.\n\n"
            "전송: 승패, 선·후공, 덱 분류, 턴 수, 종료 방식, 플레이 문맥과 점수, "
            "기록 시각, 앱·payload 버전\n\n"
            "전송하지 않음: 자유 입력 메모, 이메일, 표시 이름, 비밀번호·인증 토큰, "
            "로컬 파일 경로와 OS 사용자명\n\n"
            "오프라인에서도 기록할 수 있으며 전송은 연결이 복구된 뒤 진행됩니다."
        )
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body, 1)

        note = QLabel("이 필수 데이터 사용에 동의하지 않으면 앱을 사용할 수 없습니다.")
        note.setProperty("tone", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        cancel = QPushButton("돌아가기")
        cancel.clicked.connect(self.reject)
        accept = QPushButton(
            "동의하고 계정으로 계속" if registered else "동의하고 게스트로 계속"
        )
        accept.setObjectName("acceptGuestConsent")
        accept.setProperty("role", "primary")
        accept.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(accept)
        layout.addLayout(buttons)
        accept.setFocus()


class GuestRecordChoiceDialog(QDialog):
    """게스트에서 등록 계정으로 전환하기 전 원본 기록 처리를 확인한다."""

    def __init__(self, record_count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.choice = GuestRecordChoice.LATER
        self.setWindowTitle("게스트 기록 처리")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.space_6, METRICS.space_6, METRICS.space_6, METRICS.space_6
        )
        layout.setSpacing(METRICS.space_3)
        title = QLabel(f"게스트 기록 {record_count}건이 있습니다.")
        title.setProperty("role", "title")
        layout.addWidget(title)

        description = QLabel(
            "게스트 기록을 현재 계정으로 가져오거나, 게스트에 그대로 보관한 채 전환할 "
            "수 있습니다. 원본 게스트 기록은 어떤 경우에도 삭제되지 않습니다."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        import_button = QPushButton("현재 계정으로 가져오기")
        import_button.setProperty("role", "primary")
        import_button.clicked.connect(lambda: self._finish(GuestRecordChoice.IMPORT))
        layout.addWidget(import_button)

        keep = QPushButton("게스트에 보관하고 계정으로 전환")
        keep.clicked.connect(lambda: self._finish(GuestRecordChoice.KEEP))
        layout.addWidget(keep)

        later = QPushButton("나중에 결정")
        later.clicked.connect(lambda: self._finish(GuestRecordChoice.LATER))
        layout.addWidget(later)

    def _finish(self, choice: GuestRecordChoice) -> None:
        self.choice = choice
        self.accept()


class ConflictDialog(QDialog):
    """양쪽 값을 나란히 비교하고 충돌 해결 payload를 선택한다."""

    _FIELD_LABELS = {
        "played_at": "플레이 시각",
        "result": "결과",
        "turn_order": "선후공",
        "my_deck": "내 덱",
        "opp_deck": "상대 덱",
        "turns": "턴 수",
        "end_reason": "종료 방식",
        "score_after": "누적 점수",  # README: 2nd STAGE 누적 점수(절댓값)(N-7)
        "note": "개인 메모",
        "deleted_at": "삭제 상태",
    }

    def __init__(self, conflict: SyncConflict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("동기화 충돌 해결")
        self.setModal(True)
        self.resize(760, 520)
        self.setMinimumSize(620, 420)
        self.resolution: str | None = None
        self.merged_payload: dict | None = None
        self._conflict = conflict
        self._choices: dict[str, QComboBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.space_6, METRICS.space_6, METRICS.space_6, METRICS.space_6
        )
        layout.setSpacing(METRICS.space_3)
        title = QLabel("다른 장치와 이 장치에서 같은 기록을 변경했습니다.")
        title.setProperty("role", "title")
        title.setWordWrap(True)
        layout.addWidget(title)
        help_text = QLabel(
            "어느 값도 자동으로 버리지 않습니다. 전체 버전을 선택하거나, "
            "필드별 선택 내용을 확인한 뒤 적용하세요."
        )
        help_text.setProperty("tone", "muted")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        fields = [*PRIVATE_GAME_FIELDS, "deleted_at"]
        differing = [
            field
            for field in fields
            if conflict.local_payload.get(field) != conflict.remote_payload.get(field)
        ]
        table = QTableWidget(len(differing), 4)
        table.setHorizontalHeaderLabels(["필드", "이 장치", "서버", "적용할 값"])
        table.setAccessibleName("충돌 필드 비교")
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        for row, field in enumerate(differing):
            table.setItem(
                row, 0, QTableWidgetItem(self._FIELD_LABELS.get(field, field))
            )
            table.setItem(
                row,
                1,
                QTableWidgetItem(
                    self._display_value(conflict.local_payload.get(field))
                ),
            )
            table.setItem(
                row,
                2,
                QTableWidgetItem(
                    self._display_value(conflict.remote_payload.get(field))
                ),
            )
            choice = QComboBox()
            choice.addItem("이 장치", "local")
            choice.addItem("서버", "remote")
            choice.setAccessibleName(
                f"{self._FIELD_LABELS.get(field, field)}에 적용할 값"
            )
            table.setCellWidget(row, 3, choice)
            self._choices[field] = choice
        layout.addWidget(table, 1)

        buttons = QHBoxLayout()
        remote = QPushButton("서버 버전 사용")
        remote.clicked.connect(lambda: self._finish("remote"))
        buttons.addWidget(remote)
        local = QPushButton("이 장치 버전 사용")
        local.clicked.connect(lambda: self._finish("local"))
        buttons.addWidget(local)
        merged = QPushButton("선택 내용 적용")
        merged.setProperty("role", "primary")
        merged.clicked.connect(lambda: self._finish("merged"))
        buttons.addWidget(merged)
        layout.addLayout(buttons)

        cancel = QPushButton("나중에 해결")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    @staticmethod
    def _display_value(value: object) -> str:
        if value is None:
            return "없음"
        if value == "":
            return "빈 값"
        return str(value)

    def _finish(self, resolution: str) -> None:
        self.resolution = resolution
        if resolution == "merged":
            payload = dict(self._conflict.remote_payload)
            for field, choice in self._choices.items():
                if choice.currentData() == "local":
                    payload[field] = self._conflict.local_payload.get(field)
            self.merged_payload = payload
        self.accept()


class DeviceManagementDialog(QDialog):
    """등록된 장치 목록을 보여주고 특정 장치를 해제한다(로드맵 단계 11)."""

    def __init__(
        self,
        devices: list[DeviceInfo],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("장치 관리")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.revoke_requested: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.space_6, METRICS.space_6, METRICS.space_6, METRICS.space_6
        )
        layout.setSpacing(METRICS.space_3)
        title = QLabel("이 계정에 로그인한 장치")
        title.setProperty("role", "title")
        layout.addWidget(title)

        if not devices:
            empty = QLabel("등록된 장치가 없습니다.")
            empty.setProperty("tone", "muted")
            layout.addWidget(empty)
        else:
            for device in devices:
                row = self._device_row(device)
                layout.addLayout(row)

        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        layout.addWidget(close)

    def _device_row(self, device: DeviceInfo) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(METRICS.space_3)
        name = device.display_name or "이름 없는 장치"
        version = f" · v{device.client_version}" if device.client_version else ""
        label = QLabel(f"{name}{version}\n{device.installation_id}")
        label.setWordWrap(True)
        row.addWidget(label, 1)
        revoke = QPushButton("해제")
        revoke.setProperty("role", "danger")
        revoke.clicked.connect(
            lambda _checked=False, device_id=device.id: self._revoke(device.id)
        )
        row.addWidget(revoke)
        return row

    def _revoke(self, device_id: str) -> None:
        self.revoke_requested = device_id
        self.accept()


class AccountDialog(QDialog):
    """현재 프로필 상태와 로그인·로그아웃·계정 운영 동작을 제공한다."""

    login_requested = Signal()
    logout_requested = Signal()
    sync_requested = Signal()
    conflicts_requested = Signal()
    export_requested = Signal()
    sign_out_all_requested = Signal()
    delete_account_requested = Signal()
    manage_devices_requested = Signal()

    def __init__(
        self,
        profile_name: str,
        status_text: str,
        *,
        registered: bool,
        conflict_count: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("계정 및 동기화")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.space_6, METRICS.space_6, METRICS.space_6, METRICS.space_6
        )
        layout.setSpacing(METRICS.space_3)
        title = QLabel(profile_name)
        title.setProperty("role", "title")
        layout.addWidget(title)

        status = QLabel(status_text)
        status.setWordWrap(True)
        layout.addWidget(status)

        sync_note = QLabel(
            "게임 기록은 항상 현재 프로필의 로컬 DB에 먼저 저장되며, "
            "네트워크가 가능할 때 백그라운드에서 자동 업로드됩니다."
        )
        sync_note.setProperty("tone", "muted")
        sync_note.setWordWrap(True)
        layout.addWidget(sync_note)

        sync_now = QPushButton("지금 동기화")
        sync_now.setAccessibleName("실패한 항목을 포함해 지금 동기화")
        sync_now.clicked.connect(self.sync_requested)
        layout.addWidget(sync_now)

        if registered and conflict_count:
            conflicts = QPushButton(f"동기화 충돌 {conflict_count}건 해결")
            conflicts.setAccessibleName(
                f"보존된 동기화 충돌 {conflict_count}건 확인 및 해결"
            )
            conflicts.clicked.connect(self.conflicts_requested)
            layout.addWidget(conflicts)

        login = QPushButton(
            "다른 계정으로 전환" if registered else "로그인 또는 회원가입"
        )
        login.setProperty("role", "primary")
        login.clicked.connect(self.login_requested)
        layout.addWidget(login)

        if registered:
            logout = QPushButton("로그아웃하고 게스트로 전환")
            logout.clicked.connect(self.logout_requested)
            layout.addWidget(logout)

        if registered:
            layout.addSpacing(METRICS.space_2)
            manage_devices = QPushButton("장치 관리")
            manage_devices.clicked.connect(self.manage_devices_requested)
            layout.addWidget(manage_devices)

            sign_out_all = QPushButton("모든 기기에서 로그아웃")
            sign_out_all.setProperty("role", "danger")
            sign_out_all.clicked.connect(self.sign_out_all_requested)
            layout.addWidget(sign_out_all)

            export_data = QPushButton("내 데이터 내보내기")
            export_data.clicked.connect(self.export_requested)
            layout.addWidget(export_data)

            delete_account = QPushButton("계정 삭제")
            delete_account.setProperty("role", "danger")
            delete_account.clicked.connect(self.delete_account_requested)
            layout.addWidget(delete_account)

        close = QPushButton("닫기")
        close.clicked.connect(self.reject)
        layout.addWidget(close)

        preferred_width = 420
        self.setMinimumHeight(layout.heightForWidth(self.minimumWidth()))
        self.resize(preferred_width, layout.heightForWidth(preferred_width))
