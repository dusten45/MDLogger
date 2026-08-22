"""통합 설정 창 (계획 2, spec §6.1~§6.3).

네 범주(화면 및 접근성/성능/기록/계정 및 데이터)를 왼쪽 목록 + 오른쪽 옵션의
2열 구조로 제공한다. 설정 변경은 즉시 적용하고, 계정·동기화 작업은 기존
``ProfileRouter``/``SessionManager``가 처리하도록 시그널로 위임한다. 이 창은
인증 토큰이나 raw DB connection을 직접 소유하지 않는다(spec §6.3).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..app_settings import (
    AccentPreset,
    AppSettings,
    ReduceMotion,
    ScoreInputMode,
    SettingsStore,
    effective_reduce_motion,
)
from ..game_service import GameService
from ..paths import PRIVACY_POLICY_URL, TERMS_OF_SERVICE_URL
from ..remote.settings_sync import SettingsSyncClient, SettingsSyncError
from ..settings import DEFAULT_MODE_LAST_USED, ModeSettings
from .focus import restrict_focus_to_pointer
from .result_view import set_result_motion_enabled
from .theme import (
    METRICS,
    FontRole,
    ThemeController,
    ThemeMode,
    font_for_role,
    scaled,
    set_style_property,
)
from .widgets import SingleSelect

THEME_OPTIONS = [("system", "시스템"), ("light", "밝게"), ("dark", "어둡게")]
ACCENT_OPTIONS = [
    ("blue", "파랑"),
    ("indigo", "남색"),
    ("teal", "청록"),
    ("magenta", "자홍"),
    ("amber", "주황"),
]
UI_SCALE_OPTIONS = [
    ("0.75", "75%"),
    ("0.8", "80%"),
    ("0.9", "90%"),
    ("1.0", "100%"),
    ("1.1", "110%"),
    ("1.25", "125%"),
    ("1.5", "150%"),
]
REDUCE_MOTION_OPTIONS = [("system", "시스템"), ("off", "끔"), ("on", "켬")]
SCORE_INPUT_MODE_OPTIONS = [
    ("delta", "변동폭만 입력"),
    ("direct", "변화한 점수 직접 입력"),
]
DEFAULT_MODE_LAST_USED_LABEL = "이전 모드 기억"


def _default_mode_options(modes: list[Any]) -> list[tuple[str, str]]:
    """예약된 이전 모드 항목과 중복되는 캐시 모드는 선택지에서 제외한다."""
    options = [(DEFAULT_MODE_LAST_USED, DEFAULT_MODE_LAST_USED_LABEL)]
    for mode in modes:
        mode_id = str(mode["id"])
        label = str(mode["display_name"])
        if mode_id == DEFAULT_MODE_LAST_USED or label == DEFAULT_MODE_LAST_USED_LABEL:
            continue
        options.append((mode_id, label))
    return options


class SettingsWindow(QDialog):
    """통합 설정 창. 설정 적용은 즉시, 계정·동기화는 시그널로 위임한다."""

    # 계정 및 데이터 범주 (기존 AccountDialog 시그널 흡수, spec §6.3)
    login_requested = Signal()
    logout_requested = Signal()
    sync_requested = Signal()
    conflicts_requested = Signal()
    export_requested = Signal()
    sign_out_all_requested = Signal()
    delete_account_requested = Signal()
    app_reset_requested = Signal()
    # 메모 표시 여부를 메인 창(상세 폼/통계 표)에 전달한다.
    memo_enabled_changed = Signal(bool)
    # 점수/레이팅 입력 방식을 메인 창(상세 폼)에 전달한다.
    score_input_mode_changed = Signal(str)

    def __init__(
        self,
        store: SettingsStore,
        theme: ThemeController | None,
        games: GameService | None,
        *,
        sync_client: SettingsSyncClient | None = None,
        access_token: Callable[[], str | None] | None = None,
        profile_name: str,
        status_text: str,
        registered: bool,
        conflict_count: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._theme = theme
        self._games = games
        self._sync_client = sync_client
        self._access_token = access_token
        self._registered = registered
        self._conflict_count = conflict_count
        self._settings = store.load()
        self._mode_settings = ModeSettings(games) if games is not None else None

        self.setWindowTitle("설정")
        self.setMinimumSize(scaled(620), scaled(520))
        self.resize(scaled(680), scaled(620))

        root = QVBoxLayout(self)
        root.setContentsMargins(
            METRICS.space_4, METRICS.space_4, METRICS.space_4, METRICS.space_4
        )
        root.setSpacing(METRICS.space_3)

        body = QHBoxLayout()
        body.setSpacing(METRICS.space_4)

        self._nav = QListWidget()
        self._nav.setFixedWidth(scaled(160))
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        body.addWidget(self._nav)

        self._page_scroll = QScrollArea()
        self._page_scroll.setWidgetResizable(True)
        self._page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._stack = QStackedWidget()
        self._page_scroll.setWidget(self._stack)
        body.addWidget(self._page_scroll, 1)
        root.addLayout(body, 1)

        self._pages: list[tuple[str, QWidget]] = [
            ("화면 및 접근성", self._build_appearance_page()),
            ("성능", self._build_performance_page()),
            ("기록", self._build_recording_page()),
            ("계정 및 데이터", self._build_account_page(profile_name, status_text)),
        ]
        for title, page in self._pages:
            item = QListWidgetItem(title)
            self._nav.addItem(item)
            self._stack.addWidget(page)

        footer = QHBoxLayout()
        reset_btn = QPushButton("설정 초기화")
        reset_btn.setAccessibleName("앱 설정을 기본값으로 되돌리기")
        reset_btn.clicked.connect(self._reset_settings)
        footer.addWidget(reset_btn)

        app_reset_btn = QPushButton("앱 초기화")
        app_reset_btn.setProperty("role", "danger")
        app_reset_btn.setAccessibleName(
            "설정과 이 기기에 저장된 모든 앱 데이터 삭제하기"
        )
        app_reset_btn.clicked.connect(self._request_application_reset)
        footer.addWidget(app_reset_btn)
        footer.addStretch(1)
        close_btn = QPushButton("닫기")
        close_btn.setProperty("role", "primary")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        self._nav.setCurrentRow(0)
        restrict_focus_to_pointer(self)

    # ----- 페이지 구성 -----
    def _build_appearance_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(METRICS.space_3)

        self._theme_select = SingleSelect(THEME_OPTIONS)
        self._theme_select.setValue(self._settings.theme_mode.value)
        self._theme_select.changed.connect(self._on_theme_changed)
        layout.addLayout(
            self._option(
                "테마", "밝게/어둡게 또는 시스템 설정을 따릅니다.", self._theme_select
            )
        )

        self._accent_select = SingleSelect(ACCENT_OPTIONS)
        self._accent_select.setValue(self._settings.accent_color)
        self._accent_select.changed.connect(self._on_accent_changed)
        layout.addLayout(
            self._option(
                "강조색", "버튼·선택 등에 쓰이는 강조 색상입니다.", self._accent_select
            )
        )

        self._ui_scale_select = SingleSelect(UI_SCALE_OPTIONS)
        self._ui_scale_select.setValue(_ui_scale_key(self._settings.ui_scale))
        self._ui_scale_select.changed.connect(self._on_ui_scale_changed)
        layout.addLayout(
            self._option(
                "UI 크기",
                "버튼·글자·아이콘·간격 등 모든 UI 요소를 같은 비율로 조정합니다. 다음 앱 실행부터 적용됩니다.",
                self._ui_scale_select,
            )
        )

        self._motion_select = SingleSelect(REDUCE_MOTION_OPTIONS)
        self._motion_select.setValue(self._settings.reduce_motion.value)
        self._motion_select.changed.connect(self._on_motion_changed)
        layout.addLayout(
            self._option(
                "애니메이션 감소",
                "전적 입력 버튼의 확대 애니메이션을 줄입니다.",
                self._motion_select,
            )
        )

        layout.addStretch(1)
        return page

    def _build_performance_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(METRICS.space_3)

        self._low_spec = QCheckBox("저사양 모드")
        self._low_spec.setChecked(self._settings.low_spec_mode)
        self._low_spec.toggled.connect(self._on_low_spec_changed)
        layout.addWidget(self._low_spec)
        hint = QLabel(
            "애니메이션과 일부 시각 효과를 줄여 CPU·GPU 사용량을 낮춥니다. "
            "기록과 동기화 기능은 그대로 유지됩니다."
        )
        set_style_property(hint, "tone", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch(1)
        return page

    def _build_recording_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(METRICS.space_3)

        self._memo_check = QCheckBox("메모 사용")
        self._memo_check.setChecked(self._settings.memo_enabled)
        self._memo_check.toggled.connect(self._on_memo_changed)
        layout.addWidget(self._memo_check)
        memo_hint = QLabel(
            "끄면 입력·기록 표의 메모가 숨겨집니다. 기존 메모는 삭제되지 않습니다."
        )
        set_style_property(memo_hint, "tone", "muted")
        memo_hint.setWordWrap(True)
        layout.addWidget(memo_hint)

        if self._mode_settings is not None and self._games is not None:
            modes = self._games.get_active_play_modes()
            self._default_mode = SingleSelect(_default_mode_options(modes))
            current = self._mode_settings.default_mode
            if current is None or current == DEFAULT_MODE_LAST_USED:
                self._default_mode.setValue(DEFAULT_MODE_LAST_USED)
            else:
                self._default_mode.setValue(current)
            self._default_mode.changed.connect(self._on_default_mode_changed)
            layout.addLayout(
                self._option(
                    "기본 모드",
                    "앱 시작 시 기록할 모드를 선택합니다.",
                    self._default_mode,
                )
            )

        self._score_input_mode_select = SingleSelect(SCORE_INPUT_MODE_OPTIONS)
        self._score_input_mode_select.setValue(self._settings.score_input_mode.value)
        self._score_input_mode_select.changed.connect(self._on_score_input_mode_changed)
        layout.addLayout(
            self._option(
                "점수 입력 방식",
                "변동폭만 입력: 점수 변화의 절댓값만 입력하면 승/패에 따라 자동으로 "
                "더하거나 뺍니다. 변화한 점수 직접 입력: 경기 후 점수를 직접 입력합니다.",
                self._score_input_mode_select,
            )
        )

        layout.addStretch(1)
        return page

    def _build_account_page(self, profile_name: str, status_text: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(METRICS.space_3)

        title = QLabel(profile_name)
        set_style_property(title, "role", "title")
        layout.addWidget(title)

        status = QLabel(status_text)
        status.setWordWrap(True)
        layout.addWidget(status)

        sync_btn = QPushButton("지금 동기화")
        sync_btn.clicked.connect(self.sync_requested)
        layout.addWidget(sync_btn)

        if self._registered and self._conflict_count:
            conflicts_btn = QPushButton(f"동기화 충돌 {self._conflict_count}건 해결")
            conflicts_btn.clicked.connect(self.conflicts_requested)
            layout.addWidget(conflicts_btn)

        # 설정 동기화 (취향 설정만, 등록 프로필 + 온라인 전용)
        self._settings_upload_btn = QPushButton("설정 업로드")
        self._settings_upload_btn.clicked.connect(self._upload_settings)
        self._settings_download_btn = QPushButton("설정 다운로드")
        self._settings_download_btn.clicked.connect(self._download_settings)
        sync_available = self._registered and self._sync_client is not None
        if not sync_available:
            self._settings_upload_btn.setEnabled(False)
            self._settings_download_btn.setEnabled(False)
            note = QLabel(
                "설정 동기화는 로그인 후 사용할 수 있습니다."
                if not self._registered
                else "온라인 연결이 필요합니다."
            )
            set_style_property(note, "tone", "muted")
            layout.addWidget(note)
        layout.addWidget(self._settings_upload_btn)
        layout.addWidget(self._settings_download_btn)

        login_btn = QPushButton(
            "다른 계정으로 전환" if self._registered else "로그인 또는 회원가입"
        )
        login_btn.setProperty("role", "primary")
        login_btn.clicked.connect(self.login_requested)
        layout.addWidget(login_btn)

        if self._registered:
            logout_btn = QPushButton("로그아웃")
            logout_btn.clicked.connect(self.logout_requested)
            layout.addWidget(logout_btn)

            layout.addSpacing(METRICS.space_2)
            danger_header = QHBoxLayout()
            danger_header.setSpacing(METRICS.space_2)

            left_divider = QFrame()
            left_divider.setFixedHeight(METRICS.focus_width)
            set_style_property(left_divider, "role", "danger-divider")
            danger_header.addWidget(left_divider, 1)

            danger_title = QLabel("위험 구역")
            danger_title.setFont(font_for_role(danger_title.font(), FontRole.TITLE))
            set_style_property(danger_title, "role", "title")
            set_style_property(danger_title, "tone", "danger")
            danger_header.addWidget(danger_title)

            right_divider = QFrame()
            right_divider.setFixedHeight(METRICS.focus_width)
            set_style_property(right_divider, "role", "danger-divider")
            danger_header.addWidget(right_divider, 1)
            layout.addLayout(danger_header)

            sign_out_all_btn = QPushButton("모든 기기에서 로그아웃")
            sign_out_all_btn.setProperty("role", "danger")
            sign_out_all_btn.clicked.connect(self.sign_out_all_requested)
            layout.addWidget(sign_out_all_btn)

            export_btn = QPushButton("내 데이터 내보내기")
            export_btn.clicked.connect(self.export_requested)
            layout.addWidget(export_btn)

            delete_btn = QPushButton("계정 삭제")
            delete_btn.setProperty("role", "danger")
            delete_btn.clicked.connect(self.delete_account_requested)
            layout.addWidget(delete_btn)

        layout.addSpacing(METRICS.space_2)
        legal_header = QLabel("서비스 및 법률 정책")
        set_style_property(legal_header, "tone", "muted")
        layout.addWidget(legal_header)

        legal_buttons = QHBoxLayout()
        legal_buttons.setSpacing(METRICS.space_2)
        privacy_btn = QPushButton("개인정보 처리방침")
        privacy_btn.setObjectName("settingsPrivacyLink")
        privacy_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(PRIVACY_POLICY_URL))
        )
        legal_buttons.addWidget(privacy_btn)

        terms_btn = QPushButton("서비스 이용약관")
        terms_btn.setObjectName("settingsTermsLink")
        terms_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(TERMS_OF_SERVICE_URL))
        )
        legal_buttons.addWidget(terms_btn)
        layout.addLayout(legal_buttons)

        layout.addStretch(1)
        return page

    # ----- 내비게이션 -----
    def _on_nav_changed(self, row: int) -> None:
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)

    # ----- 설정 변경 처리 (즉시 적용) -----
    def _on_theme_changed(self, value: str) -> None:
        self._settings = _replace(self._settings, theme_mode=ThemeMode(value))
        self._commit()

    def _on_accent_changed(self, value: str) -> None:
        self._settings = _replace(self._settings, accent_color=value)
        self._commit()

    def _on_ui_scale_changed(self, value: str) -> None:
        self._settings = _replace(self._settings, ui_scale=float(value))
        self._commit()

    def _on_motion_changed(self, value: str) -> None:
        self._settings = _replace(self._settings, reduce_motion=ReduceMotion(value))
        self._commit()

    def _on_low_spec_changed(self, checked: bool) -> None:
        self._settings = _replace(self._settings, low_spec_mode=checked)
        self._commit()

    def _on_memo_changed(self, checked: bool) -> None:
        self._settings = _replace(self._settings, memo_enabled=checked)
        self._commit()

    def _on_default_mode_changed(self, value: str) -> None:
        if self._mode_settings is not None:
            self._mode_settings.set_default_mode(value)

    def _on_score_input_mode_changed(self, value: str) -> None:
        self._settings = _replace(
            self._settings, score_input_mode=ScoreInputMode(value)
        )
        self._commit()

    def _commit(self) -> None:
        self._store.save(self._settings)
        self._apply_theme()
        self._apply_motion()
        self.memo_enabled_changed.emit(self._settings.memo_enabled)
        self.score_input_mode_changed.emit(self._settings.score_input_mode.value)

    def _apply_theme(self) -> None:
        if self._theme is not None:
            self._theme.set_mode(self._settings.theme_mode)
            self._theme.set_accent(self._settings.accent_color)

    def _apply_motion(self) -> None:
        set_result_motion_enabled(not effective_reduce_motion(self._settings))

    # ----- 설정 초기화 -----
    def reset_to_defaults(self) -> None:
        """설정을 기본값으로 저장하고 현재 UI에 즉시 적용한다."""
        self._settings = AppSettings()
        self._store.save(self._settings)
        self._sync_widgets()
        self._commit()

    def _reset_settings(self) -> None:
        self.reset_to_defaults()

    def _request_application_reset(self) -> None:
        confirmed = QMessageBox.warning(
            self,
            "앱 초기화",
            "이 앱이 관리하는 설정, 경기 기록, 프로필, 동기화 및 덱 캐시를 모두 삭제합니다.\n\n"
            "현재 및 앱이 기억하는 로그인 정보도 제거되며 시작 화면으로 돌아갑니다.\n"
            "서버에 저장된 계정과 데이터, 현재 데이터 폴더 외부 파일은 삭제되지 않습니다.\n\n"
            "계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmed == QMessageBox.StandardButton.Yes:
            self.app_reset_requested.emit()

    def _sync_widgets(self) -> None:
        self._theme_select.setValue(self._settings.theme_mode.value)
        self._accent_select.setValue(self._settings.accent_color)
        self._ui_scale_select.setValue(_ui_scale_key(self._settings.ui_scale))
        self._motion_select.setValue(self._settings.reduce_motion.value)
        self._low_spec.setChecked(self._settings.low_spec_mode)
        self._memo_check.setChecked(self._settings.memo_enabled)
        self._score_input_mode_select.setValue(self._settings.score_input_mode.value)

    # ----- 설정 동기화 -----
    def _upload_settings(self) -> None:
        client = self._sync_client
        token = self._token()
        if client is None or token is None:
            return
        preferences = self._preferences()
        try:
            client.upload(preferences, token)
        except SettingsSyncError as error:
            self._show_sync_error("설정 업로드 실패", error)
            return
        self._show_sync_info("설정 업로드 완료", "취향 설정을 업로드했습니다.")

    def _download_settings(self) -> None:
        client = self._sync_client
        token = self._token()
        if client is None or token is None:
            return
        try:
            preferences = client.download(token)
        except SettingsSyncError as error:
            self._show_sync_error("설정 다운로드 실패", error)
            return
        if preferences is None:
            self._show_sync_info("설정 다운로드", "서버에 저장된 설정이 없습니다.")
            return
        self._apply_downloaded_preferences(preferences)
        self._show_sync_info("설정 다운로드 완료", "취향 설정을 적용했습니다.")

    def _preferences(self) -> dict[str, Any]:
        return {
            "theme_mode": self._settings.theme_mode.value,
            "accent_color": self._settings.accent_color,
            "memo_enabled": self._settings.memo_enabled,
            "default_mode": (
                self._mode_settings.default_mode or DEFAULT_MODE_LAST_USED
                if self._mode_settings is not None
                else DEFAULT_MODE_LAST_USED
            ),
            "score_input_mode": self._settings.score_input_mode.value,
        }

    def _apply_downloaded_preferences(self, preferences: dict[str, Any]) -> None:
        theme_mode = preferences.get("theme_mode")
        accent = preferences.get("accent_color")
        memo_enabled = preferences.get("memo_enabled")
        default_mode = preferences.get("default_mode")
        score_input_mode = preferences.get("score_input_mode")

        updates: dict[str, Any] = {}
        if isinstance(theme_mode, str):
            try:
                updates["theme_mode"] = ThemeMode(theme_mode)
            except ValueError:
                pass
        if isinstance(accent, str) and accent in {p.value for p in AccentPreset}:
            updates["accent_color"] = accent
        if isinstance(memo_enabled, bool):
            updates["memo_enabled"] = memo_enabled
        if isinstance(score_input_mode, str) and score_input_mode in {
            m.value for m in ScoreInputMode
        }:
            updates["score_input_mode"] = ScoreInputMode(score_input_mode)
        if updates:
            self._settings = _replace(self._settings, **updates)
            self._store.save(self._settings)
            self._sync_widgets()
            self._commit()
        if default_mode is not None and self._mode_settings is not None:
            self._mode_settings.set_default_mode(str(default_mode))
            if hasattr(self, "_default_mode"):
                self._default_mode.setValue(str(default_mode))

    def _token(self) -> str | None:
        if self._access_token is None:
            return None
        return self._access_token()

    def _show_sync_error(self, title: str, error: Exception) -> None:
        QMessageBox.warning(self, title, str(error))

    def _show_sync_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)

    # ----- 헬퍼 -----
    @staticmethod
    def _option(name: str, description: str, widget: QWidget) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(METRICS.space_1)
        label = QLabel(name)
        label.setFont(font_for_role(label.font(), FontRole.LABEL))
        layout.addWidget(label)
        layout.addWidget(widget)
        hint = QLabel(description)
        set_style_property(hint, "tone", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return layout


def _replace(settings: AppSettings, **updates: Any) -> AppSettings:
    """불변 ``AppSettings``의 일부 필드만 바꾼 새 값을 만든다."""
    values = {
        "theme_mode": settings.theme_mode,
        "accent_color": settings.accent_color,
        "ui_scale": settings.ui_scale,
        "low_spec_mode": settings.low_spec_mode,
        "reduce_motion": settings.reduce_motion,
        "memo_enabled": settings.memo_enabled,
        "score_input_mode": settings.score_input_mode,
    }
    values.update(updates)
    return AppSettings(**values)


def _ui_scale_key(scale: float) -> str:
    """float UI 배율을 선택 옵션의 문자열 키로 매핑한다."""
    for key, _label in UI_SCALE_OPTIONS:
        if abs(float(key) - scale) < 0.001:
            return key
    return "1.0"
