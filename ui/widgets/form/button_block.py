from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget


class DialogActionBlock(QWidget):
    primaryClicked = Signal()
    secondaryClicked = Signal()

    def __init__(
        self,
        primary_text: str,
        secondary_text: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.setProperty("role", "button-block")

        self._primary_button = QPushButton(primary_text)
        self._primary_button.setProperty("variant", "primary")
        self._primary_button.clicked.connect(self.primaryClicked.emit)

        self._secondary_button = QPushButton(secondary_text)
        self._secondary_button.setProperty("variant", "secondary")
        self._secondary_button.clicked.connect(self.secondaryClicked.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._primary_button)
        layout.addWidget(self._secondary_button)

    def set_primary_enabled(self, enabled: bool) -> None:
        self._primary_button.setEnabled(enabled)
