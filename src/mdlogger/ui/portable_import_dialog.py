"""휴대용 아카이브(.mdlogger-export) 가져오기 대화상자.

통계/기록 창의 "휴대용 아카이브 가져오기"로 열린다. 사용자가 내보낸
``.mdlogger-export`` 디렉터리를 선택해 현재 프로필 DB에 원자적으로 가져온다
(``portable.import_portable_archive``). 성공 시 결과(가져온/건너뛴/실패 개수,
재가져오기 여부)를 안내하고 대화상자를 닫으며, 손상·변조·과대·버전 불일치
(``PortableArchiveError``)는 원인을 안내하고 대상 DB를 바꾸지 않은 채
대화상자를 유지한다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..portable import PortableArchiveError, import_portable_archive
from .theme import scaled


class PortableImportDialog(QDialog):
    """가져올 휴대용 아카이브를 선택·가져오는 모달 대화상자."""

    def __init__(
        self,
        target_db_path: str | Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("휴대용 아카이브 가져오기")
        self.setModal(True)
        self.setMinimumWidth(scaled(440))
        self._target_db_path = Path(target_db_path)
        self.already_imported = False
        self.imported_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled(24), scaled(24), scaled(24), scaled(24))
        layout.setSpacing(scaled(12))

        title = QLabel("가져올 휴대용 아카이브 선택")
        title.setProperty("role", "title")
        layout.addWidget(title)

        hint = QLabel(
            "휴대용 아카이브(.mdlogger-export) 폴더를 선택하면 "
            "현재 프로필 DB로 가져옵니다."
        )
        hint.setWordWrap(True)
        hint.setProperty("tone", "muted")
        layout.addWidget(hint)

        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("아카이브 폴더 경로")
        browse = QPushButton("찾아보기")
        browse.setProperty("role", "secondary")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.setSpacing(scaled(8))
        row.addWidget(self._path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        buttons = QHBoxLayout()
        buttons.setSpacing(scaled(8))
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        import_btn = QPushButton("가져오기")
        import_btn.setProperty("role", "primary")
        import_btn.clicked.connect(self._import)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(import_btn)
        layout.addLayout(buttons)
        import_btn.setFocus()

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "아카이브 폴더 선택")
        if path:
            self._path_edit.setText(path)

    def _import(self) -> None:
        raw = self._path_edit.text().strip()
        if not raw:
            QMessageBox.warning(
                self,
                "경로 필요",
                "휴대용 아카이브 폴더를 선택하세요.",
                QMessageBox.StandardButton.Ok,
            )
            return
        archive_path = Path(raw)
        try:
            result = import_portable_archive(archive_path, self._target_db_path)
        except PortableArchiveError as exc:
            QMessageBox.critical(
                self,
                "가져오기 실패",
                f"아카이브를 가져올 수 없습니다.\n\n{exc}",
                QMessageBox.StandardButton.Ok,
            )
            return
        except Exception as exc:  # noqa: BLE001 - 가져오기 실패를 사용자에게 안내
            QMessageBox.critical(
                self,
                "가져오기 실패",
                f"아카이브를 가져올 수 없습니다.\n\n{exc}",
                QMessageBox.StandardButton.Ok,
            )
            return

        self.already_imported = result.already_imported
        self.imported_count = result.imported_count
        if result.already_imported:
            message = "이미 가져온 아카이브입니다."
        else:
            message = (
                f"가져온 기록: {result.imported_count}개\n"
                f"건너뛴 기록: {result.skipped_count}개\n"
                f"실패한 기록: {result.failed_count}개"
            )
        QMessageBox.information(
            self, "가져오기 완료", message, QMessageBox.StandardButton.Ok
        )
        self.accept()
