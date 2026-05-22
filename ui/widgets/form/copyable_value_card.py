from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.common.icons import icon, icon_size


class CopyableValueCard(QFrame):
    def __init__(
        self,
        title: str,
        value: str = "",
        *,
        multiline: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self._multiline = multiline
        self.setProperty("role", "payment-address-card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)

        label = QLabel(title)
        label.setProperty("role", "payment-address-label")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        if multiline:
            self.value_widget = QTextEdit()
            self.value_widget.setReadOnly(True)
            self.value_widget.setProperty("variant", "default")
            self.value_widget.setProperty("field-type", "multi-line")
            self.value_widget.setFixedHeight(130)
        else:
            self.value_widget = QLabel()
            self.value_widget.setProperty("role", "payment-address-value")
            self.value_widget.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self.value_widget.setWordWrap(True)

        self.copy_btn = QPushButton()
        self.copy_btn.setProperty("variant", "icon-square")
        self.copy_btn.setFixedSize(40, 40)
        self.copy_btn.setIcon(icon("document-duplicate"))
        self.copy_btn.setIconSize(icon_size(18))
        self.copy_btn.clicked.connect(self.copy_value)

        row.addWidget(self.value_widget, 1)
        row.addWidget(self.copy_btn, 0, Qt.AlignmentFlag.AlignTop)

        layout.addWidget(label)
        layout.addLayout(row)

        self.set_text(value)

    def text(self) -> str:
        if self._multiline:
            return self.value_widget.toPlainText()
        return self.value_widget.text()

    def set_text(self, value: str) -> None:
        if self._multiline:
            self.value_widget.setPlainText(value)
        else:
            self.value_widget.setText(value)

    def copy_value(self) -> None:
        QGuiApplication.clipboard().setText(self.text())
