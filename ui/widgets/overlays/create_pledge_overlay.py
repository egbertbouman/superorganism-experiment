from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from PySide6.QtCore import Signal, Qt, QEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSpacerItem,
    QSizePolicy,
    QStackedLayout, QFrame,
)

from democracy.funding.service import PledgeRequest
from ui.models.pledge_draft import PledgeDraft
from ui.models.signed_pledge_draft import SignedPledgeDraft
from ui.widgets.form import DialogActionBlock, TextAreaFieldBlock, TextFieldBlock
from ui.widgets.form.copyable_value_card import CopyableValueCard


@dataclass(frozen=True)
class PledgeOverlayContext:
    campaign_id: UUID
    solution_title: str
    asking_price_sats: int
    raised_sats: int
    deadline_height: int
    payout_address: str
    status_text: str


@dataclass(frozen=True)
class PendingPledgeRequest:
    txid: str
    vout: int
    pledge_request: PledgeRequest

class CreatePledgeOverlay(QWidget):
    pledge_request_requested = Signal(object)
    signed_pledge_submitted = Signal(object)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._context: PledgeOverlayContext | None = None
        self._pending_request: PendingPledgeRequest | None = None
        self._request_errors: dict[str, str] = {}
        self._signed_pledge_errors: dict[str, str] = {}

        self.setObjectName("createPledgeOverlay")
        self.hide()

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()

        if parent is not None:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())
            self.raise_()

        self._show_request_step()
        self._validate_request_form()
        self._validate_signed_pledge_form()

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
            QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.setSpacing(0)

        center_row.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        self.card = QWidget(self.overlay)
        self.card.setObjectName("dialogCard")
        self.card.setFixedWidth(700)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(30, 30, 30, 28)
        card_layout.setSpacing(16)

        self.title_label = QLabel("Create Funding Pledge")
        self.title_label.setProperty("role", "dialog-title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.step_copy_label = QLabel("")
        self.step_copy_label.setProperty("role", "dialog-copy")
        self.step_copy_label.setWordWrap(True)
        self.step_copy_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.pages_wrap = QWidget(self.card)
        self.pages_layout = QStackedLayout(self.pages_wrap)
        self.pages_layout.setContentsMargins(0, 0, 0, 0)

        self._build_request_page()
        self._build_signing_page()

        card_layout.addWidget(self.title_label)
        card_layout.addWidget(self.step_copy_label)
        card_layout.addWidget(self.pages_wrap)

        center_row.addWidget(self.card)

        center_row.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

        overlay_layout.addLayout(center_row)

        overlay_layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        root.addWidget(self.overlay)

    def _build_request_page(self) -> None:
        self.request_page = QWidget()
        layout = QVBoxLayout(self.request_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.warning_label = QLabel(
            "Only create a pledge for funds you intend to commit to this campaign. The "
            "request binds one UTXO to the campaign payout terms, target amount, and deadline."
        )
        self.warning_label.setProperty("role", "dialog-note")
        self.warning_label.setWordWrap(True)

        self.summary_card = QFrame()
        self.summary_card.setProperty("variant", "card")

        summary_layout = QVBoxLayout(self.summary_card)
        summary_layout.setContentsMargins(18, 18, 18, 18)
        summary_layout.setSpacing(10)

        self.summary_kicker = QLabel("PLEDGE TARGET")
        self.summary_kicker.setProperty("role", "solution-meta-kicker")

        self.solution_title_label = QLabel("--")
        self.solution_title_label.setProperty("role", "field-label")
        self.solution_title_label.setWordWrap(True)

        self.summary_details_label = QLabel("--")
        self.summary_details_label.setProperty("role", "dialog-copy")
        self.summary_details_label.setWordWrap(True)

        summary_layout.addWidget(self.summary_kicker)
        summary_layout.addWidget(self.solution_title_label)
        summary_layout.addWidget(self.summary_details_label)

        self.txid_field = TextFieldBlock(
            title="txid",
            placeholder_text="64-character transaction id",
            parent=self.card,
        )
        self.txid_field.textChanged.connect(self._on_request_fields_changed)

        self.vout_field = TextFieldBlock(
            title="vout",
            placeholder_text="e.g., 0",
            parent=self.card,
        )
        self.vout_field.textChanged.connect(self._on_request_fields_changed)

        self.request_action_block = DialogActionBlock(
            primary_text="Create pledge request",
            secondary_text="Cancel",
            parent=self.card,
        )
        self.request_action_block.primaryClicked.connect(self._request_pledge_template)
        self.request_action_block.secondaryClicked.connect(self.close_overlay)

        layout.addWidget(self.warning_label)
        layout.addWidget(self.summary_card)
        layout.addWidget(self.txid_field)
        layout.addWidget(self.vout_field)
        layout.addWidget(self.request_action_block)

        self.pages_layout.addWidget(self.request_page)

    def _build_signing_page(self) -> None:
        self.signing_page = QWidget()
        layout = QVBoxLayout(self.signing_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.human_summary_card = QFrame()
        self.human_summary_card.setProperty("variant", "card")

        human_layout = QVBoxLayout(self.human_summary_card)
        human_layout.setContentsMargins(18, 18, 18, 18)
        human_layout.setSpacing(10)

        self.human_summary_kicker = QLabel("PLEDGE SUMMARY")
        self.human_summary_kicker.setProperty("role", "solution-meta-kicker")

        self.human_summary_label = QLabel("--")
        self.human_summary_label.setProperty("role", "dialog-copy")
        self.human_summary_label.setWordWrap(True)

        human_layout.addWidget(self.human_summary_kicker)
        human_layout.addWidget(self.human_summary_label)

        self.psbt_card = CopyableValueCard(
            title="PSBT TO SIGN",
            multiline=True,
            parent=self.card,
        )

        self.signed_psbt_field = TextAreaFieldBlock(
            title="Signed pledge PSBT",
            placeholder_text="Paste the signed pledge PSBT here",
            parent=self.card,
        )
        self.signed_psbt_field.textChanged.connect(self._on_signed_pledge_changed)

        self.submit_action_block = DialogActionBlock(
            primary_text="Submit signed pledge",
            secondary_text="Back",
            parent=self.card,
        )
        self.submit_action_block.primaryClicked.connect(self._submit_signed_pledge)
        self.submit_action_block.secondaryClicked.connect(self._show_request_step)

        layout.addWidget(self.human_summary_card)
        layout.addWidget(self.psbt_card)
        layout.addWidget(self.signed_psbt_field)
        layout.addWidget(self.submit_action_block)

        self.pages_layout.addWidget(self.signing_page)

    def open_overlay(self, context: PledgeOverlayContext) -> None:
        self._context = context
        self._pending_request = None
        self._clear_request_fields()
        self._clear_signed_pledge_fields()
        self._populate_context()
        self._show_request_step()
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.activateWindow()
        self.txid_field.focus_input()

    def show_signing_step(
        self,
        pending_request: PendingPledgeRequest,
    ) -> None:
        self._pending_request = pending_request
        self._clear_signed_pledge_fields()
        self._populate_signing_step()
        self.title_label.setText("Sign Funding Pledge")
        self.step_copy_label.setText(
            "Review the pledge template below, copy the PSBT into your wallet for signing, "
            "then paste the signed PSBT back here to submit the pledge."
        )
        self.pages_layout.setCurrentWidget(self.signing_page)
        self.signed_psbt_field.focus_input()
        self._validate_signed_pledge_form()

    def close_overlay(self) -> None:
        self.hide()
        self.closed.emit()

    def _show_request_step(self) -> None:
        self.title_label.setText("Create Funding Pledge")
        self.step_copy_label.setText(
            "Choose the specific UTXO you want to pledge. The app will build a pledge request "
            "template for that outpoint and the current campaign terms."
        )
        self.pages_layout.setCurrentWidget(self.request_page)
        self._validate_request_form()

    def _populate_context(self) -> None:
        if self._context is None:
            self.solution_title_label.setText("--")
            self.summary_details_label.setText("--")
            return

        context = self._context
        self.solution_title_label.setText(context.solution_title)
        self.summary_details_label.setText(
            "\n".join(
                [
                    f"Status: {context.status_text}",
                    f"Target: {context.asking_price_sats:,} sats",
                    f"Raised: {context.raised_sats:,} sats",
                    f"Deadline block: {context.deadline_height}",
                    f"Payout address: {context.payout_address}",
                ]
            )
        )

    def _populate_signing_step(self) -> None:
        if self._pending_request is None or self._context is None:
            self.human_summary_label.setText("--")
            self.psbt_card.set_text("")
            return

        pledge_request = self._pending_request.pledge_request
        self.human_summary_label.setText(
            "\n".join(
                [
                    f"You are preparing a pledge for '{self._context.solution_title}'.",
                    (
                        f"This pledge spends outpoint {self._pending_request.txid}:"
                        f"{self._pending_request.vout} with value "
                        f"{pledge_request.value_sats:,} sats."
                    ),
                    (
                        f"The transaction preserves the campaign payout to "
                        f"{pledge_request.developer_payout_address} for "
                        f"{pledge_request.asking_price_sats:,} sats."
                    ),
                    (
                        f"The campaign deadline is block {pledge_request.deadline_height} "
                        f"and the wallet must sign using {pledge_request.sighash_type}."
                    ),
                    f"Commitment: {pledge_request.campaign_commitment_hex}",
                ]
            )
        )
        self.psbt_card.set_text(pledge_request.psbt_base64)

    def _clear_request_fields(self) -> None:
        self.txid_field.clear()
        self.vout_field.clear()
        self._clear_request_errors()

    def _clear_request_errors(self) -> None:
        self._request_errors.clear()
        self.txid_field.clear_error()
        self.vout_field.clear_error()
        self.request_action_block.set_primary_enabled(False)

    def _clear_signed_pledge_fields(self) -> None:
        self.signed_psbt_field.clear()
        self._signed_pledge_errors.clear()
        self.signed_psbt_field.clear_error()
        self.submit_action_block.set_primary_enabled(False)

    def _current_request_draft(self) -> PledgeDraft:
        return PledgeDraft(
            txid=self.txid_field.text(),
            vout=self.vout_field.text(),
        )

    def _current_signed_pledge_draft(self) -> SignedPledgeDraft:
        return SignedPledgeDraft(
            signed_pledge_psbt=self.signed_psbt_field.text(),
        )

    def _validate_request_form(self) -> bool:
        draft = self._current_request_draft()
        self._apply_txid_error(draft.validate_txid())
        self._apply_vout_error(draft.validate_vout())
        return self._update_request_button_state()

    def _validate_signed_pledge_form(self) -> bool:
        draft = self._current_signed_pledge_draft()
        self._apply_signed_psbt_error(draft.validate_signed_pledge_psbt())
        return self._update_signed_pledge_button_state()

    def _apply_txid_error(self, error: str) -> None:
        self._set_request_error("txid", error)
        self.txid_field.set_error(error)

    def _apply_vout_error(self, error: str) -> None:
        self._set_request_error("vout", error)
        self.vout_field.set_error(error)

    def _apply_signed_psbt_error(self, error: str) -> None:
        self._set_signed_pledge_error("signed_pledge_psbt", error)
        self.signed_psbt_field.set_error(error)

    def _set_request_error(self, field_name: str, error: str) -> None:
        if error:
            self._request_errors[field_name] = error
        else:
            self._request_errors.pop(field_name, None)

    def _set_signed_pledge_error(self, field_name: str, error: str) -> None:
        if error:
            self._signed_pledge_errors[field_name] = error
        else:
            self._signed_pledge_errors.pop(field_name, None)

    def _update_request_button_state(self) -> bool:
        is_valid = not self._request_errors and self._context is not None
        self.request_action_block.set_primary_enabled(is_valid)
        return is_valid

    def _update_signed_pledge_button_state(self) -> bool:
        is_valid = not self._signed_pledge_errors and self._pending_request is not None
        self.submit_action_block.set_primary_enabled(is_valid)
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

    def _request_pledge_template(self) -> None:
        if not self._validate_request_form():
            return

        self.pledge_request_requested.emit(self._current_request_draft())

    def _submit_signed_pledge(self) -> None:
        if not self._validate_signed_pledge_form():
            return

        self.signed_pledge_submitted.emit(self._current_signed_pledge_draft())

    def _on_request_fields_changed(self, _text: str) -> None:
        draft = self._current_request_draft()
        self._apply_txid_error(draft.validate_txid())
        self._apply_vout_error(draft.validate_vout())
        self._update_request_button_state()

    def _on_signed_pledge_changed(self, _text: str) -> None:
        draft = self._current_signed_pledge_draft()
        self._apply_signed_psbt_error(draft.validate_signed_pledge_psbt())
        self._update_signed_pledge_button_state()
