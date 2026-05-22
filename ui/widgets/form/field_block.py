from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class _BaseFieldBlock(QWidget):
    def __init__(
        self,
        title: str,
        input_widget: QWidget,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        self.setProperty("role", "field-block")
        self._input_widget = input_widget

        self.label = QLabel(title)
        self.label.setProperty("role", "field-label")

        self.error_label = QLabel("")
        self.error_label.setProperty("role", "error-label")
        error_size_policy = self.error_label.sizePolicy()
        error_size_policy.setRetainSizeWhenHidden(True)
        self.error_label.setSizePolicy(error_size_policy)
        self.error_label.hide()

        self.counter_label = QLabel("")
        self.counter_label.setProperty("role", "counter-label")
        self.counter_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.counter_label.hide()

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)
        meta_row.addWidget(self.error_label, 1)
        meta_row.addWidget(self.counter_label, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.label)
        layout.addWidget(self._input_widget)
        layout.addLayout(meta_row)

    def set_error(self, error: str) -> None:
        self.error_label.setText(error)
        self.error_label.setVisible(bool(error))
        self.set_invalid(bool(error))

    def clear_error(self) -> None:
        self.set_error("")

    def set_counter(self, text: str, *, over_limit: bool = False) -> None:
        self.counter_label.setText(text)
        self.counter_label.setVisible(bool(text))
        self.counter_label.setProperty("over-limit", over_limit)
        self._refresh_style(self.counter_label)

    def clear_counter(self) -> None:
        self.counter_label.clear()
        self.counter_label.hide()
        self.counter_label.setProperty("over-limit", False)
        self._refresh_style(self.counter_label)

    def _update_length_counter(self, text: str, max_length: int | None) -> None:
        if max_length is None:
            self.clear_counter()
            return
        current_length = len(text)
        self.set_counter(
            f"{current_length}/{max_length}",
            over_limit=current_length > max_length,
        )

    def set_invalid(self, invalid: bool) -> None:
        self._input_widget.setProperty("invalid", invalid)
        self._refresh_style(self._input_widget)

    def focus_input(self) -> None:
        self._input_widget.setFocus()

    def _refresh_style(self, widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


class TextFieldBlock(_BaseFieldBlock):
    textChanged = Signal(str)

    def __init__(
        self,
        title: str,
        placeholder_text: str | None = None,
        max_length: int | None = None,
        parent: QWidget | None = None,
    ):
        line_edit = QLineEdit()
        line_edit.setProperty("variant", "default")
        line_edit.setProperty("field-type", "single-line")
        if placeholder_text is not None:
            line_edit.setPlaceholderText(placeholder_text)

        super().__init__(
            title=title,
            input_widget=line_edit,
            parent=parent,
        )

        self.line_edit = line_edit
        self._max_length = max_length
        self.line_edit.textChanged.connect(self._on_text_changed)
        self._update_length_counter(self.text(), self._max_length)

    def text(self) -> str:
        return self.line_edit.text()

    def clear(self) -> None:
        self.line_edit.clear()

    def _on_text_changed(self) -> None:
        text = self.text()
        self._update_length_counter(text, self._max_length)
        self.textChanged.emit(text)


class TextAreaFieldBlock(_BaseFieldBlock):
    textChanged = Signal(str)

    def __init__(
        self,
        title: str,
        placeholder_text: str | None = None,
        *,
        max_length: int | None = None,
        input_height: int = 140,
        parent: QWidget | None = None,
    ):
        text_edit = QTextEdit()
        text_edit.setProperty("variant", "default")
        text_edit.setProperty("field-type", "multi-line")
        text_edit.setFixedHeight(input_height)
        if placeholder_text is not None:
            text_edit.setPlaceholderText(placeholder_text)

        super().__init__(
            title=title,
            input_widget=text_edit,
            parent=parent,
        )

        self.text_edit = text_edit
        self._max_length = max_length
        self.text_edit.textChanged.connect(self._on_text_changed)
        self._update_length_counter(self.text(), self._max_length)

    def text(self) -> str:
        return self.text_edit.toPlainText()

    def clear(self) -> None:
        self.text_edit.clear()

    def _on_text_changed(self) -> None:
        text = self.text()
        self._update_length_counter(text, self._max_length)
        self.textChanged.emit(text)
