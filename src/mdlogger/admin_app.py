"""별도 관리자 데스크톱 앱 진입점."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .admin_modes import AdminConfigurationError, admin_client_from_environment
from .app_settings import SettingsRepository
from .ui.admin_window import AdminWindow
from .ui.focus import install_pointer_focus_only
from .ui.icons import application_icon
from .ui.theme import ThemeMode, apply_theme


def main() -> None:
    """service-role 환경 변수로 서버 모드 관리 창을 연다."""
    app = QApplication(sys.argv)
    install_pointer_focus_only(app)
    app.setApplicationName("MDLogger 관리자")
    icon = application_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    apply_theme(app, ThemeMode.SYSTEM, ui_scale=SettingsRepository().load().ui_scale)

    try:
        client = admin_client_from_environment()
    except AdminConfigurationError as error:
        QMessageBox.critical(
            None,
            "관리자 앱 설정 필요",
            f"{error}\n\n환경 변수를 설정한 뒤 다시 실행하세요.",
        )
        sys.exit(1)

    window = AdminWindow(client)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
