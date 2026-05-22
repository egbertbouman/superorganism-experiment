from __future__ import annotations

from PySide6.QtCore import Signal, Qt, QEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSpacerItem,
    QSizePolicy,
)

from ui.constants import ISSUE_TITLE_MAX_LENGTH, ISSUE_DESCRIPTION_MAX_LENGTH
from ui.models.issue_draft import IssueDraft
from ui.widgets.form import DialogActionBlock, TextAreaFieldBlock, TextFieldBlock


class CreateIssueOverlay(QWidget):
    created = Signal(object)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_errors: dict[str, str] = {}

        self.setObjectName("createIssueOverlay")
        self.hide()

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()

        if parent is not None:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())
            self.raise_()

        self._validate_form()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.overlay = QWidget(self)
        self.overlay.setObjectName("overlay")

        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(40, 40, 40, 40)
        overlay_layout.setSpacing(0)

        overlay_layout.addSpacerItem(
            QSpacerItem(
                20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
            )
        )

        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.setSpacing(0)

        center_row.addSpacerItem(
            QSpacerItem(
                20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
        )

        self.card = QWidget(self.overlay)
        self.card.setObjectName("dialogCard")
        self.card.setFixedWidth(560)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(30, 30, 30, 28)
        card_layout.setSpacing(16)

        self.title_label = QLabel("Create New Issue Proposal")
        self.title_label.setProperty("role", "dialog-title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_field = TextFieldBlock(
            title="Issue Title",
            placeholder_text="e.g., Improve vote review flow",
            max_length=ISSUE_TITLE_MAX_LENGTH,
            parent=self.card,
        )
        self.title_field.textChanged.connect(self._on_title_changed)

        self.description_field = TextAreaFieldBlock(
            title="Description",
            placeholder_text=(
                "Provide details about the issue, goals, and expected community impact..."
            ),
            max_length=ISSUE_DESCRIPTION_MAX_LENGTH,
            parent=self.card,
        )
        self.description_field.textChanged.connect(self._on_description_changed)

        self.action_block = DialogActionBlock(
            primary_text="Create Issue",
            secondary_text="Cancel",
            parent=self.card,
        )
        self.action_block.primaryClicked.connect(self._create)
        self.action_block.secondaryClicked.connect(self.close_overlay)

        card_layout.addWidget(self.title_label)
        card_layout.addWidget(self.title_field)
        card_layout.addWidget(self.description_field)
        card_layout.addWidget(self.action_block)

        center_row.addWidget(self.card)

        center_row.addSpacerItem(
            QSpacerItem(
                20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
        )

        overlay_layout.addLayout(center_row)

        overlay_layout.addSpacerItem(
            QSpacerItem(
                20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
            )
        )

        root.addWidget(self.overlay)

    def open_overlay(self) -> None:
        self._clear_fields()
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.activateWindow()
        self.title_field.focus_input()
        self._validate_form()

    def close_overlay(self) -> None:
        self.hide()
        self.closed.emit()

    def _clear_fields(self) -> None:
        self.title_field.clear()
        self.description_field.clear()
        self._clear_errors()

    def _clear_errors(self) -> None:
        self._current_errors.clear()
        self.title_field.clear_error()
        self.description_field.clear_error()
        self.action_block.set_primary_enabled(False)

    def _current_draft(self) -> IssueDraft:
        return IssueDraft(
            title=self.title_field.text(),
            description=self.description_field.text(),
        )

    def _validate_form(self) -> bool:
        draft = self._current_draft()
        self._apply_title_error(draft.validate_title())
        self._apply_description_error(draft.validate_description())
        return self._update_create_button_state()

    def _apply_title_error(self, error: str) -> None:
        self._set_error("title", error)
        self.title_field.set_error(error)

    def _apply_description_error(self, error: str) -> None:
        self._set_error("description", error)
        self.description_field.set_error(error)

    def _set_error(self, field_name: str, error: str) -> None:
        if error:
            self._current_errors[field_name] = error
        else:
            self._current_errors.pop(field_name, None)

    def _update_create_button_state(self) -> bool:
        is_valid = not self._current_errors
        self.action_block.set_primary_enabled(is_valid)
        return is_valid

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
        ):
            self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        if not self.card.geometry().contains(event.position().toPoint()):
            self.close_overlay()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_overlay()
            return
        super().keyPressEvent(event)

    def _create(self) -> None:
        if not self._validate_form():
            return

        draft = self._current_draft()
        self.created.emit(draft)
        self.close_overlay()

    def _on_title_changed(self, _text: str) -> None:
        draft = self._current_draft()
        self._apply_title_error(draft.validate_title())
        self._update_create_button_state()

    def _on_description_changed(self, _text: str) -> None:
        draft = self._current_draft()
        self._apply_description_error(draft.validate_description())
        self._update_create_button_state()
