from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from cashu.core.helpers import sum_proofs
from cashu.wallet.helpers import deserialize_token_from_string
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QWidget):
    action_requested = pyqtSignal(str, object)
    mint_requested = pyqtSignal(int)
    debug_changed = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("py_cashu | Cashu Qt Demo")
        self.resize(1260, 780)
        self.setMinimumSize(980, 620)
        self._tokens: list[dict[str, Any]] = []
        self._current_qr_path = ""
        self._selected_token_id: int | None = None
        self._selected_token_text = ""
        self._build_ui()
        self._apply_theme()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([560, 700])
        root.addWidget(splitter, stretch=1)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        title = QLabel("Cashu actions")
        title.setObjectName("Title")
        layout.addWidget(title)

        mint_box = QGroupBox("Mint")
        mint_layout = QVBoxLayout(mint_box)
        self.mint_combo = QComboBox()
        self.mint_combo.currentIndexChanged.connect(self.mint_requested.emit)
        mint_layout.addWidget(self.mint_combo)
        self.mint_info_label = QLabel("")
        self.mint_info_label.setWordWrap(True)
        mint_layout.addWidget(self.mint_info_label)
        layout.addWidget(mint_box)

        actions = QGroupBox("Keys")
        actions_layout = QGridLayout(actions)
        actions_layout.setSpacing(6)
        self._add_action(actions_layout, 0, 0, "Show", "show_keys")
        self._add_confirmed_action(
            actions_layout,
            0,
            1,
            "Load",
            "load_seed_from_env",
            "This overwrites the SQLite wallet seed from CASHU_MNEMO.",
        )
        self._add_action(actions_layout, 0, 2, "Save", "save_seed_to_env")
        actions_layout.setColumnStretch(0, 1)
        actions_layout.setColumnStretch(1, 1)
        actions_layout.setColumnStretch(2, 1)
        layout.addWidget(actions)

        invoice_box = QGroupBox("Invoice and token")
        invoice_layout = QGridLayout(invoice_box)
        invoice_layout.setSpacing(6)
        self.amount_input = QLineEdit("21")
        self.amount_input.setPlaceholderText("Amount in sats")
        self.amount_input.setMaximumWidth(70)
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("Token label")
        self.label_input.setMaximumWidth(440)
        invoice_layout.addWidget(QLabel("Amount"), 0, 0)
        invoice_layout.addWidget(self.amount_input, 0, 1)
        invoice_layout.addWidget(QLabel("Label"), 0, 2)
        invoice_layout.addWidget(self.label_input, 0, 3)
        self._add_action(invoice_layout, 1, 0, "Create invoice", "request_invoice")
        self._add_action(invoice_layout, 1, 1, "Mint token after payment", "mint_token")
        self._add_action(invoice_layout, 1, 2, "Create mock token", "mock_token")
        invoice_layout.setColumnStretch(0, 1)
        invoice_layout.setColumnStretch(1, 0)
        invoice_layout.setColumnStretch(2, 1)
        invoice_layout.setColumnStretch(3, 2)
        layout.addWidget(invoice_box)

        token_box = QGroupBox("Last saved tokens")
        token_layout = QVBoxLayout(token_box)
        self.tokens_table = QTableWidget(0, 5)
        self.tokens_table.setHorizontalHeaderLabels(["Time", "Label", "Amount", "$", "Del"])
        self.tokens_table.verticalHeader().setVisible(False)
        self.tokens_table.setColumnWidth(0, 145)
        self.tokens_table.setColumnWidth(1, 180)
        self.tokens_table.setColumnWidth(2, 70)
        self.tokens_table.setColumnWidth(3, 52)
        self.tokens_table.setColumnWidth(4, 58)
        self.tokens_table.cellClicked.connect(self._token_cell_clicked)
        token_layout.addWidget(self.tokens_table)

        token_actions = QHBoxLayout()
        unspent_btn = QPushButton("unspent")
        unspent_btn.clicked.connect(lambda: self.action_requested.emit("set_token_filter", {"filter": "unspent"}))
        token_actions.addWidget(unspent_btn)
        all_btn = QPushButton("all")
        all_btn.clicked.connect(lambda: self.action_requested.emit("set_token_filter", {"filter": "all"}))
        token_actions.addWidget(all_btn)
        info_btn = QPushButton("info")
        info_btn.clicked.connect(self._open_token_info_dialog)
        token_actions.addWidget(info_btn)
        redeem_btn = QPushButton("redeem")
        redeem_btn.clicked.connect(self._open_redeem_dialog)
        token_actions.addWidget(redeem_btn)
        token_layout.addLayout(token_actions)

        layout.addWidget(token_box, stretch=1)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("Verbose logs")
        title.setObjectName("Title")
        top.addWidget(title)
        top.addStretch()
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("Status")
        top.addWidget(self.status_label)
        self.debug_checkbox = QCheckBox("Verbose")
        self.debug_checkbox.setChecked(True)
        self.debug_checkbox.toggled.connect(self.debug_changed.emit)
        top.addWidget(self.debug_checkbox)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_debug)
        top.addWidget(clear_btn)
        layout.addLayout(top)

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.setHandleWidth(8)
        self.debug_box = QTextBrowser()
        vertical.addWidget(self.debug_box)

        qr_panel = QFrame()
        qr_panel.setObjectName("QrPanel")
        qr_layout = QVBoxLayout(qr_panel)
        qr_header = QHBoxLayout()
        qr_title = QLabel("QR preview")
        qr_title.setObjectName("Title")
        qr_header.addWidget(qr_title)
        qr_header.addStretch()
        self.qr_path_label = QLabel("")
        self.qr_path_label.setObjectName("Muted")
        qr_header.addWidget(self.qr_path_label)
        qr_layout.addLayout(qr_header)
        self.qr_label = QLabel("No QR yet")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumHeight(260)
        self.qr_label.setObjectName("QrLabel")
        qr_layout.addWidget(self.qr_label, stretch=1)
        vertical.addWidget(qr_panel)

        vertical.setSizes([360, 330])
        layout.addWidget(vertical, stretch=1)

        return panel

    def _add_action(self, layout: QGridLayout, row: int, column: int, label: str, action: str) -> None:
        button = QPushButton(label)
        button.clicked.connect(lambda _checked=False, name=action: self._emit_action(name))
        layout.addWidget(button, row, column)

    def _add_confirmed_action(
        self,
        layout: QGridLayout,
        row: int,
        column: int,
        label: str,
        action: str,
        message: str,
    ) -> None:
        button = QPushButton(label)
        button.clicked.connect(lambda _checked=False, name=action, text=message: self._confirm_action(name, text))
        layout.addWidget(button, row, column)

    def _emit_action(self, action: str) -> None:
        payload: dict[str, Any] = {
            "amount": self.amount_input.text().strip(),
            "label": self.label_input.text().strip(),
        }
        self.action_requested.emit(action, payload)

    def _confirm_action(self, action: str, message: str) -> None:
        result = QMessageBox.question(
            self,
            "Confirm",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            self._emit_action(action)

    def _open_redeem_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Redeem token")
        dialog.resize(720, 420)

        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Paste a Cashu token. The selected mint is the target. If the token belongs "
            "to another mint, the app redeems it at its source mint, pays a Lightning "
            "invoice to the selected mint, exports the received proofs as a new local "
            "token, shows its QR, and adds it to the token database."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        token_edit = QTextEdit()
        token_edit.setPlaceholderText("cashuA... or cashuB...")
        if self._selected_token_text:
            token_edit.setPlainText(self._selected_token_text)
            token_edit.selectAll()
        layout.addWidget(token_edit, stretch=1)

        action = {"kind": ""}
        buttons = QHBoxLayout()
        buttons.addStretch()
        save_btn = QPushButton("Save")
        redeem_btn = QPushButton("Redeem")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(lambda: self._accept_redeem_dialog(dialog, action, "save"))
        redeem_btn.clicked.connect(lambda: self._accept_redeem_dialog(dialog, action, "redeem"))
        cancel_btn.clicked.connect(dialog.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(redeem_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        token_text = token_edit.toPlainText().strip()
        if not token_text:
            QMessageBox.information(self, "Redeem token", "Paste a token first.")
            return

        if action["kind"] == "save":
            self.action_requested.emit(
                "save_pasted_token",
                {
                    "token": token_text,
                    "label": self.label_input.text().strip(),
                },
            )
            return

        self.action_requested.emit(
            "redeem_pasted_token",
            {
                "token": token_text,
                "label": self.label_input.text().strip(),
            },
        )

    def _accept_redeem_dialog(self, dialog: QDialog, action: dict[str, str], kind: str) -> None:
        action["kind"] = kind
        dialog.accept()

    def _open_token_info_dialog(self) -> None:
        if not self._selected_token_text:
            QMessageBox.information(self, "Token info", "Select a saved token first.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Token info")
        dialog.resize(760, 520)

        layout = QVBoxLayout(dialog)
        parsed = QTextEdit()
        parsed.setReadOnly(True)
        parsed.setPlainText(self._token_preview_text(self._selected_token_text))
        layout.addWidget(parsed, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _token_preview_text(self, token_text: str) -> str:
        if not token_text:
            return ""
        try:
            token = deserialize_token_from_string(token_text)
            proofs = list(getattr(token, "proofs", []))
            proof_amounts = [int(getattr(proof, "amount", 0) or 0) for proof in proofs]
            keyset_ids = sorted({str(getattr(proof, "id", "") or "") for proof in proofs if getattr(proof, "id", "")})
            secret_conditions = [
                condition
                for proof in proofs
                for condition in self._secret_conditions(str(getattr(proof, "secret", "") or ""))
            ]
            data = {
                "token_prefix": token_text[:6],
                "token_type": type(token).__name__,
                "mint": str(getattr(token, "mint", "") or ""),
                "unit": str(getattr(token, "unit", "") or ""),
                "memo": getattr(token, "memo", None),
                "amount": int(sum_proofs(proofs)) if proofs else 0,
                "proof_count": len(proofs),
                "proof_amounts": proof_amounts,
                "proof_amount_breakdown": self._amount_breakdown(proof_amounts),
                "keyset_ids": keyset_ids,
                "has_dleq": any(bool(getattr(proof, "dleq", None)) for proof in proofs),
                "has_witness": any(bool(getattr(proof, "witness", None)) for proof in proofs),
                "spending_conditions": secret_conditions,
                "expiry": self._expiry_from_conditions(secret_conditions),
                "secret_previews": [
                    self._short_text(str(getattr(proof, "secret", "") or ""))
                    for proof in proofs[:8]
                ],
            }
            if len(proofs) > 8:
                data["secret_previews"].append(f"... {len(proofs) - 8} more")
            return json.dumps(data, indent=2, ensure_ascii=False)
        except Exception as exc:
            return f"Could not parse token:\n{type(exc).__name__}: {exc}"

    def _secret_conditions(self, secret: str) -> list[dict[str, Any]]:
        try:
            value = json.loads(secret)
        except Exception:
            return []
        if not isinstance(value, list) or len(value) < 2 or not isinstance(value[1], dict):
            return []
        tags = value[1].get("tags") or []
        parsed_tags: dict[str, list[str]] = {}
        for tag in tags:
            if isinstance(tag, list) and tag:
                parsed_tags.setdefault(str(tag[0]), []).extend(str(part) for part in tag[1:])
        return [
            {
                "kind": str(value[0]),
                "data": value[1].get("data"),
                "nonce": value[1].get("nonce"),
                "tags": parsed_tags,
            }
        ]

    def _expiry_from_conditions(self, conditions: list[dict[str, Any]]) -> str | None:
        for condition in conditions:
            tags = condition.get("tags") or {}
            locktimes = tags.get("locktime") or tags.get("expiry") or tags.get("expiration")
            if locktimes:
                return str(locktimes[0])
        return None

    def _amount_breakdown(self, amounts: list[int]) -> dict[str, int]:
        out: dict[str, int] = {}
        for amount in amounts:
            key = str(amount)
            out[key] = out.get(key, 0) + 1
        return out

    def _short_text(self, value: str, limit: int = 24) -> str:
        if len(value) <= limit * 2 + 3:
            return value
        return f"{value[:limit]}...{value[-limit:]}"

    def set_mints(self, mints: list[dict[str, str]]) -> None:
        self.mint_combo.blockSignals(True)
        self.mint_combo.clear()
        for mint in mints:
            self.mint_combo.addItem(mint["label"])
        self.mint_combo.blockSignals(False)

    def set_mint_index(self, index: int) -> None:
        self.mint_combo.blockSignals(True)
        self.mint_combo.setCurrentIndex(index)
        self.mint_combo.blockSignals(False)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def append_debug(self, text: str) -> None:
        self.debug_box.append(f"<pre>{html.escape(text)}</pre>")

    def clear_debug(self) -> None:
        self.debug_box.clear()

    def update_view(self, state: dict[str, Any]) -> None:
        mint = state.get("mint", {})
        self.mint_info_label.setText(f"Active: {mint.get('url', '')} | DB: {mint.get('db', '')}")
        self._tokens = list(state.get("tokens") or [])
        self._render_tokens()
        qr_path = state.get("qr_path")
        if qr_path:
            self.show_qr(str(qr_path))
        if "selected_token_text" in state:
            self._selected_token_text = str(state.get("selected_token_text") or "")

    def show_qr(self, path: str) -> None:
        self._current_qr_path = path
        pixmap = QPixmap(path)
        self.qr_path_label.setText(Path(path).name)
        if pixmap.isNull():
            self.qr_label.setText(f"Could not load QR:\n{path}")
            return
        scaled = pixmap.scaled(
            max(120, self.qr_label.width() - 20),
            max(120, self.qr_label.height() - 20),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.qr_label.setPixmap(scaled)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        if self._current_qr_path:
            self.show_qr(self._current_qr_path)

    def _render_tokens(self) -> None:
        self.tokens_table.setRowCount(len(self._tokens))
        for row, token in enumerate(self._tokens):
            for column, value in enumerate(
                [
                    str(token.get("created_at", "")),
                    str(token.get("label", "")),
                    str(token.get("amount", "")),
                ]
            ):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, token.get("id"))
                self.tokens_table.setItem(row, column, item)

            spent_button = QPushButton("$" if not token.get("used") else "spent")
            spent_button.setProperty("tokenButton", True)
            spent_button.clicked.connect(
                lambda _checked=False, token_id=token.get("id"): self.action_requested.emit(
                    "toggle_token",
                    {"id": token_id},
                )
            )
            self.tokens_table.setCellWidget(row, 3, spent_button)

            delete_button = QPushButton("Trash")
            delete_button.setProperty("dangerButton", True)
            delete_button.clicked.connect(
                lambda _checked=False, token_id=token.get("id"): self.action_requested.emit(
                    "delete_token",
                    {"id": token_id},
                )
            )
            self.tokens_table.setCellWidget(row, 4, delete_button)

    def _token_cell_clicked(self, row: int, column: int) -> None:
        if column >= 3:
            return
        item = self.tokens_table.item(row, column)
        if item is None:
            return
        token_id = item.data(Qt.ItemDataRole.UserRole)
        if token_id is not None:
            self._selected_token_id = int(token_id)
            self.action_requested.emit("show_token", {"id": token_id})

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #121417;
                color: #e8e8e8;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 11pt;
            }
            QLabel#Title {
                font-size: 15pt;
                font-weight: 600;
                color: #ffffff;
            }
            QLabel#Status {
                color: #9ad1ff;
                padding: 4px 0;
            }
            QLabel#Muted {
                color: #8b96a3;
            }
            QLabel#QrLabel {
                background: #0c0e11;
                border: 1px solid #333941;
                border-radius: 5px;
                color: #8b96a3;
            }
            QFrame#QrPanel {
                background: #121417;
            }
            QGroupBox {
                border: 1px solid #333941;
                border-radius: 6px;
                margin-top: 10px;
                padding: 10px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                background: #26313d;
                border: 1px solid #3d4a57;
                border-radius: 5px;
                padding: 8px 10px;
                text-align: left;
            }
            QPushButton:hover {
                background: #314153;
            }
            QPushButton:pressed {
                background: #1d2732;
            }
            QPushButton[dangerButton="true"] {
                background: #3a2428;
                border-color: #6b343d;
            }
            QPushButton[tokenButton="true"] {
                text-align: center;
            }
            QLineEdit, QComboBox, QTextBrowser, QTextEdit, QTableWidget {
                background: #0f1114;
                border: 1px solid #333941;
                border-radius: 5px;
                padding: 6px;
                color: #e8e8e8;
            }
            QHeaderView::section {
                background: #1b2026;
                color: #e8e8e8;
                border: 1px solid #333941;
                padding: 5px;
            }
            QSplitter::handle {
                background: #262b31;
            }
            """
        )
