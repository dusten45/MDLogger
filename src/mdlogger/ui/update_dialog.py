"""사용자 승인을 받는 Windows 업데이트 진행 창."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import METRICS, scaled


class UpdateDialog(QDialog):
    install_requested = Signal()
    cancellation_requested = Signal()

    def __init__(
        self, current_version: str, version: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MDLogger 업데이트")
        self.setModal(True)
        self.setMinimumWidth(scaled(440))
        self._installing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.space_4, METRICS.space_4, METRICS.space_4, METRICS.space_4
        )
        layout.setSpacing(METRICS.space_3)
        title = QLabel(f"새 버전 {version}을 사용할 수 있습니다.")
        title.setProperty("role", "title")
        title.setWordWrap(True)
        layout.addWidget(title)
        description = QLabel(
            f"현재 버전: {current_version}\n"
            "설치 파일을 확인한 뒤 앱을 종료하고 업데이트합니다. "
            "Windows 관리자 권한 확인이 나타날 수 있습니다. "
            "설치가 끝나면 앱이 다시 실행되며 기록은 보존됩니다."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self._status = QLabel("진행하려면 업데이트를 선택하세요.")
        self._status.setWordWrap(True)
        self._status.setAccessibleName("업데이트 상태")
        layout.addWidget(self._status)
        self._progress = QProgressBar()
        self._progress.setAccessibleName("업데이트 다운로드 진행률")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._later = QPushButton("나중에")
        self._later.clicked.connect(self.reject)
        buttons.addWidget(self._later)
        self._install = QPushButton("업데이트")
        self._install.setProperty("role", "primary")
        self._install.clicked.connect(self.install_requested)
        buttons.addWidget(self._install)
        layout.addLayout(buttons)

    def set_downloading(self) -> None:
        self._install.setEnabled(False)
        self._later.setText("취소")
        self._status.setText("설치 파일을 내려받고 서명을 확인하고 있습니다.")

    def set_progress(self, received: int, total: int) -> None:
        self._progress.setValue(min(100, received * 100 // max(total, 1)))

    def set_installing(self) -> None:
        self._installing = True
        self._install.setEnabled(False)
        self._later.setEnabled(False)
        self._status.setText("안전하게 앱을 종료할 준비를 하고 있습니다.")
        self._progress.setRange(0, 0)

    def set_error(self, message: str) -> None:
        self._installing = False
        self._status.setText(message)
        self._progress.setRange(0, 100)
        self._install.setText("다시 시도")
        self._install.setEnabled(True)
        self._later.setText("나중에")
        self._later.setEnabled(True)

    def finish_handoff(self) -> None:
        """실행기가 준비된 뒤의 승인된 종료는 사용자 취소와 구분한다."""
        self._installing = False
        super().accept()

    def reject(self) -> None:
        if self._installing:
            return
        self.cancellation_requested.emit()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._installing:
            event.ignore()
            return
        super().closeEvent(event)
