from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import sqlite3
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import qrcode
from cashu.core.helpers import sum_proofs
from cashu.core.split import amount_split
from cashu.wallet.wallet import Wallet
from cashu.wallet.helpers import deserialize_token_from_string

from .token_pdf import TokenPdfRenderer
from .tokenstore import TokenStore
from dotenv import load_dotenv, set_key
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
ENV_FILE = ROOT / ".env"
ENV_MNEMONIC_KEY = "CASHU_MNEMO"
APP_DB = DATA_DIR / "cashu_app.sqlite3"

INVOICE_TXT = DATA_DIR / "temp_invoice.txt"
INVOICE_QR = DATA_DIR / "temp_invoice.png"
TOKEN_TXT = DATA_DIR / "temp_token.txt"
TOKEN_QR = DATA_DIR / "temp_token.png"
TOKENS_PDF_DIR = DATA_DIR / "tokens_pdf"
SEED_BACKUP = DATA_DIR / "temp_seed_backup.txt"

DEBUG = True


@dataclass(frozen=True)
class MintProfile:
    label: str
    url: str
    db: str
    wallet_name: str


MINTS = [
    MintProfile(
        label="cashu.cz",
        url="https://cashu.cz",
        db="cashu_cz_demo.sqlite",
        wallet_name="cashu-cz-demo",
    ),
    MintProfile(
        label="kashu.me",
        url="https://kashu.me",
        db="kashu_me_demo.sqlite",
        wallet_name="kashu-me-demo",
    ),
    MintProfile(
        label="cashu.21m.lol",
        url="https://cashu.21m.lol",
        db="cashu_21m_lol_demo.sqlite",
        wallet_name="cashu-21m-lol-demo",
    ),
]


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def short_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%y%m%d|%H:%M")


def file_stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%y%m%d_%H_%M")


def compact_ws(value: str) -> str:
    return " ".join(value.strip().split())


def obj_to_dict(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool, list, dict)):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def get_any_attr(obj: Any, names: list[str], default: Any = None) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


async def maybe_call(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


def bip39_seed_hex_from_mnemonic(mnemonic: str, passphrase: str = "") -> str:
    salt = ("mnemonic" + passphrase).encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha512",
        compact_ws(mnemonic).encode("utf-8"),
        salt,
        2048,
    ).hex()


def read_env_mnemonic() -> str | None:
    load_dotenv(ENV_FILE, override=True)
    value = os.getenv(ENV_MNEMONIC_KEY)
    return compact_ws(value) if value else None


def save_env_mnemonic(mnemonic: str) -> None:
    if not ENV_FILE.exists():
        ENV_FILE.write_text("", encoding="utf-8")
    set_key(
        dotenv_path=str(ENV_FILE),
        key_to_set=ENV_MNEMONIC_KEY,
        value_to_set=compact_ws(mnemonic),
        quote_mode="always",
    )
    load_dotenv(ENV_FILE, override=True)


def save_text_and_qr(text: str, txt_file: Path, png_file: Path) -> None:
    txt_file.parent.mkdir(parents=True, exist_ok=True)
    png_file.parent.mkdir(parents=True, exist_ok=True)
    txt_file.write_text(text, encoding="utf-8")
    image = qrcode.make(text)
    image.save(png_file)


class CashuWorker(QObject):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    data_signal = pyqtSignal(dict)
    mints_signal = pyqtSignal(list)
    mint_index_signal = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._mint_index = 0
        self._debug = DEBUG
        self._store = TokenStore(APP_DB, TOKEN_TXT, TOKEN_QR, now_fn=now)
        self._pending_quote_id: str | None = None
        self._pending_amount: int | None = None
        self._pending_label: str | None = None
        self._pending_multi_count: int | None = None
        self._pending_multi_amount: int | None = None
        self._pending_multi_splits: list[list[int]] = []
        self._pending_multi_pdf = False
        self._pending_multi_common_label = ""
        self._pending_mint_ready = False
        self._auto_mint_in_progress = False
        self._show_used_tokens = False
        self._cleanup_old_temp_previews()

    @pyqtSlot()
    def initialize(self) -> None:
        self.mints_signal.emit(
            [{"label": mint.label, "url": mint.url, "db": mint.db} for mint in MINTS]
        )
        self.mint_index_signal.emit(self._mint_index)
        self._emit_state()
        self._log("Cashu Qt demo initialized.")
        self._load_mint_info_safely()

    @pyqtSlot(bool)
    def set_debug(self, enabled: bool) -> None:
        self._debug = enabled
        self._out(f"Verbose output {'enabled' if enabled else 'disabled'}; concise results stay visible.")

    @pyqtSlot(int)
    def set_mint(self, index: int) -> None:
        if not 0 <= index < len(MINTS):
            return
        self._mint_index = index
        self._pending_quote_id = None
        self._pending_amount = None
        self._pending_label = None
        self._clear_pending_multi()
        self._pending_mint_ready = False
        self._auto_mint_in_progress = False
        self._out(f"Mint switched to {self._mint().label} ({self._mint().url}).")
        self._emit_state()
        self._load_mint_info_safely()

    @pyqtSlot(str, object)
    def run_action(self, action: str, payload: object) -> None:
        payload = payload if isinstance(payload, dict) else {}
        self._out(f"Running: {self._action_label(action)}")
        try:
            if action == "mint_info":
                self._run_async(self._mint_info())
            elif action == "show_keys":
                self._show_keys()
            elif action == "load_seed_from_env":
                self._load_seed_from_env()
            elif action == "save_seed_to_env":
                self._save_seed_to_env()
            elif action == "request_invoice":
                amount = self._payload_amount(payload)
                label = self._payload_label(payload)
                self._run_async(self._request_invoice(amount, label))
            elif action == "request_multi_invoice":
                amount = self._payload_amount(payload)
                count = self._payload_multi_count(payload)
                label = self._payload_label(payload, default_prefix="multi-token")
                create_pdf = bool(payload.get("create_pdf"))
                common_label = str(payload.get("common_label") or "").strip()
                self._run_async(
                    self._request_multi_invoice(amount, count, label, create_pdf, common_label)
                )
            elif action == "mint_token":
                label = self._payload_label(payload)
                self._run_async(self._mint_token(label))
            elif action == "check_invoice_payment":
                self._run_async(self._check_invoice_payment())
            elif action == "mock_token":
                amount = self._payload_amount(payload)
                label = self._payload_label(payload, default_prefix="mock-token")
                self._create_mock_token(amount, label)
            elif action == "show_token":
                self._show_token(int(payload.get("id")))
            elif action == "check_token_state":
                self._run_async(self._check_saved_token_state(int(payload.get("id"))))
            elif action == "set_token_filter":
                self._set_token_filter(str(payload.get("filter") or "unspent"))
            elif action == "redeem_pasted_token":
                token_text = str(payload.get("token") or "").strip()
                label = self._payload_label(payload, default_prefix="received-token")
                self._run_async(self._redeem_pasted_token(token_text, label))
            elif action == "save_pasted_token":
                token_text = str(payload.get("token") or "").strip()
                label = self._payload_label(payload, default_prefix="saved-token")
                self._save_pasted_token(token_text, label)
            elif action == "toggle_token":
                self._store.toggle(int(payload.get("id")))
                self._out(f"Token #{payload.get('id')} used flag toggled.")
                self._emit_state()
            elif action == "delete_token":
                self._store.delete(int(payload.get("id")))
                self._out(f"Token #{payload.get('id')} deleted.")
                self._emit_state()
            else:
                self._out(f"Unknown action: {action}")
        except Exception as exc:
            if action == "mint_info":
                self.status_signal.emit("Mint unavailable")
                self._out(self._concise_mint_unavailable(exc))
            else:
                self.status_signal.emit("Error")
                self._out(f"ERROR: {type(exc).__name__}: {exc}")

    def _action_label(self, action: str) -> str:
        labels = {
            "mint_info": "checking mint info",
            "show_keys": "showing local seed keys",
            "load_seed_from_env": "loading seed from .env into SQLite",
            "save_seed_to_env": "saving SQLite seed into .env",
            "request_invoice": "requesting Lightning invoice",
            "request_multi_invoice": "requesting multi-token invoice",
            "mint_token": "minting paid invoice into token",
            "check_invoice_payment": "checking invoice payment",
            "mock_token": "creating mock token",
            "show_token": "showing saved token",
            "check_token_state": "checking token proof state",
            "set_token_filter": "changing token list filter",
            "redeem_pasted_token": "redeeming pasted token",
            "save_pasted_token": "saving pasted token",
            "toggle_token": "toggling token used flag",
            "delete_token": "deleting token",
        }
        return labels.get(action, action)

    def _mint(self) -> MintProfile:
        return MINTS[self._mint_index]

    async def _wallet(self) -> Wallet:
        mint = self._mint()
        return await self._wallet_for_mint(mint)

    async def _wallet_for_mint(self, mint: MintProfile) -> Wallet:
        wallet = await Wallet.with_db(
            url=mint.url,
            db=str(DATA_DIR / mint.db),
            name=mint.wallet_name,
        )
        try:
            await wallet.load_mint()
        except Exception as exc:
            raise RuntimeError(
                f"Mint is not available or returned invalid metadata: {mint.url}"
            ) from exc
        if not getattr(wallet, "keysets", None):
            raise RuntimeError(f"Mint keysets are not available: {mint.url}")
        return wallet

    def _mint_for_url(self, url: str | None) -> MintProfile:
        if not url:
            return self._mint()
        for mint in MINTS:
            if mint.url.rstrip("/") == url.rstrip("/"):
                return mint
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in url.lower()).strip("_")
        return MintProfile(
            label=url,
            url=url,
            db=f"received_{safe_name}.sqlite",
            wallet_name=f"received-{safe_name}",
        )

    def _run_async(self, coro: Any) -> None:
        asyncio.run(coro)

    def _load_mint_info_safely(self) -> None:
        try:
            self._run_async(self._mint_info())
        except Exception as exc:
            self.status_signal.emit("Mint unavailable")
            self._out(self._concise_mint_unavailable(exc))

    def _cleanup_old_temp_previews(self) -> None:
        for directory in [ROOT, DATA_DIR]:
            for path in directory.glob("temp_token_preview_*.png"):
                try:
                    path.unlink()
                except Exception as exc:
                    self._log(f"Could not delete old temp preview {path}: {exc}")

    def _payload_amount(self, payload: dict[str, Any]) -> int:
        raw = str(payload.get("amount") or "").strip()
        if not raw.isdigit():
            raise ValueError("Amount must be a positive integer.")
        amount = int(raw)
        if amount <= 0:
            raise ValueError("Amount must be greater than zero.")
        return amount

    def _payload_label(self, payload: dict[str, Any], default_prefix: str = "token") -> str:
        label = str(payload.get("label") or "").strip()
        return label if label else f"{default_prefix}-{short_stamp()}"

    def _payload_multi_count(self, payload: dict[str, Any]) -> int:
        raw = str(payload.get("count") or "").strip()
        if not raw.isdigit():
            raise ValueError("Token count must be 1, 3, or 5.")
        count = int(raw)
        if count not in {1, 3, 5}:
            raise ValueError("Token count must be 1, 3, or 5.")
        return count

    def _clear_pending_multi(self) -> None:
        self._pending_multi_count = None
        self._pending_multi_amount = None
        self._pending_multi_splits = []
        self._pending_multi_pdf = False
        self._pending_multi_common_label = ""

    async def _mint_info(self) -> None:
        self.status_signal.emit("Loading mint info...")
        self._log_section("Mint info")
        wallet = await self._wallet()
        if not self._debug:
            self._out(self._concise_mint_info(wallet))
        self._log(f"Mint URL:\n{wallet.url}")
        self._log(f"Number of keysets:\n{len(wallet.keysets)}")
        self._log_json("wallet.keysets", wallet.keysets)
        for attr in ["mint_info", "info", "keysets", "url", "unit", "balance"]:
            if hasattr(wallet, attr):
                try:
                    self._log_json(f"wallet.{attr}", getattr(wallet, attr))
                except Exception as exc:
                    self._log(f"Could not print wallet.{attr}: {exc}")
        self._log(self._sqlite_dump(include_seed=False))
        self.status_signal.emit("Ready")
        self._emit_state()

    def _concise_mint_info(self, wallet: Wallet) -> str:
        mint = self._mint()
        unit = get_any_attr(wallet, ["unit"], None)
        balance = get_any_attr(wallet, ["balance"], None)
        info = get_any_attr(wallet, ["mint_info", "info"], None)
        name = get_any_attr(info, ["name"], None) if info else None
        pubkey = get_any_attr(info, ["pubkey"], None) if info else None
        lines = [
            "Mint info: available",
            f"Mint: {mint.label}",
            f"URL: {wallet.url}",
            f"Name: {name or '-'}",
            f"Keysets: {len(getattr(wallet, 'keysets', []) or [])}",
            f"Unit: {unit or '-'}",
            f"Wallet balance: {balance if balance is not None else '-'}",
            f"Wallet DB: {DATA_DIR / mint.db}",
        ]
        if pubkey:
            lines.append(f"Pubkey: {str(pubkey)[:32]}...")
        return "\n".join(lines)

    def _concise_mint_unavailable(self, exc: Exception) -> str:
        mint = self._mint()
        return "\n".join(
            [
                "Mint info: unavailable",
                f"Mint: {mint.label}",
                f"URL: {mint.url}",
                f"Error: {type(exc).__name__}: {exc}",
                f"Wallet DB: {DATA_DIR / mint.db}",
            ]
        )

    def _show_keys(self) -> None:
        self.status_signal.emit("Loading keys...")
        self._log_section("Keys / mnemonic")
        record = self._sqlite_seed_record()
        self._log("SQLite seed / mnemonic:")
        if record:
            self._log_json("sqlite seed", record)
        else:
            self._log("<not found>")
        self._log(".env mnemonic:")
        env_mnemonic = read_env_mnemonic()
        self._log(f"{ENV_MNEMONIC_KEY}:")
        self._log(env_mnemonic if env_mnemonic else "<not found>")
        self._out(
            "\n".join(
                [
                    "Key check complete",
                    f"SQLite seed: {'found' if record else 'not found'}",
                    f".env mnemonic: {'found' if env_mnemonic else 'not found'}",
                    f"Data dir: {DATA_DIR}",
                ]
            )
        )
        self.status_signal.emit("Ready")
        self._emit_state()

    def _load_seed_from_env(self) -> None:
        self.status_signal.emit("Updating SQLite seed...")
        env_mnemonic = read_env_mnemonic()
        if not env_mnemonic:
            raise RuntimeError(f"No {ENV_MNEMONIC_KEY} found in .env.")
        record = self._sqlite_seed_record()
        if not record:
            raise RuntimeError("No SQLite seed record found.")
        backup_text = (
            "Cashu seed backup\n"
            "=================\n\n"
            f"DB: {record['db']}\n\n"
            "OLD SEED:\n"
            f"{record['seed']}\n\n"
            "OLD MNEMONIC:\n"
            f"{record['mnemonic']}\n"
        )
        SEED_BACKUP.write_text(backup_text, encoding="utf-8")
        new_seed = bip39_seed_hex_from_mnemonic(env_mnemonic)
        with sqlite3.connect(record["db"]) as conn:
            conn.execute("DELETE FROM seed")
            conn.execute(
                "INSERT INTO seed(seed, mnemonic) VALUES (?, ?)",
                (new_seed, env_mnemonic),
            )
        self._log_section("Seed updated from .env")
        self._log(f"Backup saved to:\n{SEED_BACKUP}")
        self._log(f"NEW SEED:\n{new_seed}")
        self._log(f"NEW MNEMONIC:\n{env_mnemonic}")
        self._out(
            "\n".join(
                [
                    "SQLite seed updated from .env",
                    f"DB: {record['db']}",
                    f"Backup: {SEED_BACKUP}",
                ]
            )
        )
        self.status_signal.emit("Ready")
        self._emit_state()

    def _save_seed_to_env(self) -> None:
        self.status_signal.emit("Saving seed to .env...")
        record = self._sqlite_seed_record()
        if not record:
            raise RuntimeError("No SQLite mnemonic found.")
        save_env_mnemonic(record["mnemonic"])
        self._log(f"Saved {ENV_MNEMONIC_KEY} to:\n{ENV_FILE}")
        self._out(f"Saved SQLite mnemonic to {ENV_FILE}.")
        self.status_signal.emit("Ready")
        self._emit_state()

    async def _request_invoice(self, amount: int, label: str) -> None:
        self.status_signal.emit("Requesting invoice...")
        self._log_section("Request invoice")
        self._clear_pending_multi()
        wallet = await self._wallet()
        quote = await self._request_mint_compat(wallet, amount)
        self._log_json("Quote object", quote)
        quote_id = get_any_attr(quote, ["quote", "quote_id", "id"])
        invoice = get_any_attr(quote, ["request", "invoice", "pr", "payment_request"])
        if not quote_id:
            raise RuntimeError("Could not obtain quote_id.")
        if not invoice:
            raise RuntimeError("Could not obtain Lightning invoice.")
        self._pending_quote_id = str(quote_id)
        self._pending_amount = amount
        self._pending_label = label
        self._pending_mint_ready = self._quote_is_paid(quote)
        self._auto_mint_in_progress = False
        save_text_and_qr(str(invoice), INVOICE_TXT, INVOICE_QR)
        self._log(f"QUOTE ID:\n{quote_id}")
        self._log(f"LIGHTNING INVOICE:\n{invoice}")
        self._log(f"Invoice saved to:\n{INVOICE_TXT}\n{INVOICE_QR}")
        self._out(
            "\n".join(
                [
                    "Invoice requested",
                    f"Mint: {self._mint().label}",
                    f"Amount: {amount} sats",
                    f"Quote: {quote_id}",
                    f"TXT: {INVOICE_TXT}",
                    f"QR: {INVOICE_QR}",
                ]
            )
        )
        self.status_signal.emit("Waiting for payment")
        self._emit_state(qr_path=INVOICE_QR)

    async def _request_multi_invoice(
        self,
        amount_per_token: int,
        count: int,
        label: str,
        create_pdf: bool,
        common_label: str,
    ) -> None:
        self.status_signal.emit("Requesting multi-token invoice...")
        self._log_section("Request multi-token invoice")
        token_split = sorted(amount_split(amount_per_token), reverse=True)
        if not token_split:
            raise ValueError("Amount per token must be greater than zero.")
        splits = [token_split[:] for _ in range(count)]
        total_amount = amount_per_token * count

        wallet = await self._wallet()
        quote = await self._request_mint_compat(wallet, total_amount)
        self._log_json("Quote object", quote)
        quote_id = get_any_attr(quote, ["quote", "quote_id", "id"])
        invoice = get_any_attr(quote, ["request", "invoice", "pr", "payment_request"])
        if not quote_id:
            raise RuntimeError("Could not obtain quote_id.")
        if not invoice:
            raise RuntimeError("Could not obtain Lightning invoice.")

        self._pending_quote_id = str(quote_id)
        self._pending_amount = total_amount
        self._pending_label = label
        self._pending_multi_count = count
        self._pending_multi_amount = amount_per_token
        self._pending_multi_splits = splits
        self._pending_multi_pdf = create_pdf
        self._pending_multi_common_label = common_label
        self._pending_mint_ready = self._quote_is_paid(quote)
        self._auto_mint_in_progress = False

        save_text_and_qr(str(invoice), INVOICE_TXT, INVOICE_QR)
        self._log(
            "\n".join(
                [
                    f"Multi-token plan: {count} x {amount_per_token} sats",
                    f"Invoice total: {total_amount} sats",
                    f"Per-token split: {token_split}",
                    f"Total proof count: {sum(len(split) for split in splits)}",
                    f"Create PDF: {'yes' if create_pdf else 'no'}",
                    f"Common label: {common_label or '<empty>'}",
                ]
            )
        )
        self._log(f"QUOTE ID:\n{quote_id}")
        self._log(f"LIGHTNING INVOICE:\n{invoice}")
        self._log(f"Invoice saved to:\n{INVOICE_TXT}\n{INVOICE_QR}")
        self._out(
            "\n".join(
                [
                    "Multi-token invoice requested",
                    f"Mint: {self._mint().label}",
                    f"Tokens: {count} x {amount_per_token} sats",
                    f"Total: {total_amount} sats",
                    f"Quote: {quote_id}",
                    f"QR: {INVOICE_QR}",
                ]
            )
        )
        self.status_signal.emit("Waiting for multi-token payment")
        self._emit_state(qr_path=INVOICE_QR)

    async def _check_invoice_payment(self) -> None:
        if (
            not self._pending_quote_id
            or not self._pending_amount
            or self._auto_mint_in_progress
        ):
            return

        wallet = await self._wallet()
        quote = await self._get_mint_quote_compat(wallet, self._pending_quote_id)
        state = str(get_any_attr(quote, ["state"], "") or "")
        self._log(f"Payment check for quote {self._pending_quote_id}: {state or '<unknown>'}")
        if not self._quote_is_paid(quote):
            self._pending_mint_ready = False
            self.status_signal.emit("Waiting for payment")
            self._out(f"Invoice is not paid yet: {state or 'unknown state'}.")
            self._emit_state()
            return

        self._pending_mint_ready = True
        self._emit_state()
        self._auto_mint_in_progress = True
        self.status_signal.emit("Payment found, minting...")
        self._out("Invoice payment found; minting token now.")
        try:
            if self._pending_multi_count:
                await self._mint_multi_tokens(self._pending_label or f"multi-token-{now()}")
            else:
                await self._mint_token(self._pending_label or f"token-{now()}")
        except Exception as exc:
            self._auto_mint_in_progress = False
            self._pending_mint_ready = True
            self.status_signal.emit("Payment found, manual mint available")
            self._log(f"Automatic mint failed, manual mint is available: {type(exc).__name__}: {exc}")
            self._out(f"Automatic mint failed; manual mint is available: {type(exc).__name__}: {exc}")
            self._emit_state()

    async def _mint_token(self, label: str) -> None:
        if not self._pending_quote_id or not self._pending_amount:
            raise RuntimeError("Create an invoice first, pay it, then mint the token.")
        if self._pending_multi_count:
            await self._mint_multi_tokens(label)
            return
        self.status_signal.emit("Minting token...")
        self._log_section("Mint token after payment")
        wallet = await self._wallet()
        proofs = await self._mint_compat(wallet, self._pending_amount, self._pending_quote_id)
        self._log_json("Proofs", proofs)
        token = await self._serialize_token_compat(wallet, proofs)
        if not token:
            raise RuntimeError("Token is empty.")
        token = str(token)
        save_text_and_qr(token, TOKEN_TXT, TOKEN_QR)
        row_id = self._store.insert(
            mint=self._mint(),
            amount=self._pending_amount,
            label=label,
            token=token,
            is_mock=False,
        )
        self._log(f"CASHU TOKEN:\n{token}")
        self._log(f"Token saved as row {row_id}:\n{TOKEN_TXT}\n{TOKEN_QR}")
        self._out(
            "\n".join(
                [
                    "Token minted",
                    f"Row: {row_id}",
                    f"Mint: {self._mint().label}",
                    f"Amount: {self._pending_amount} sats",
                    f"TXT: {TOKEN_TXT}",
                    f"QR: {TOKEN_QR}",
                ]
            )
        )
        self._pending_quote_id = None
        self._pending_amount = None
        self._pending_label = None
        self._clear_pending_multi()
        self._pending_mint_ready = False
        self._auto_mint_in_progress = False
        self.status_signal.emit("Token ready")
        self._emit_state(qr_path=TOKEN_QR)

    async def _mint_multi_tokens(self, label: str) -> None:
        if not self._pending_quote_id or not self._pending_amount:
            raise RuntimeError("Create an invoice first, pay it, then mint the tokens.")
        if not self._pending_multi_count or not self._pending_multi_amount or not self._pending_multi_splits:
            raise RuntimeError("No multi-token plan is pending.")

        self.status_signal.emit("Minting multi-token batch...")
        self._log_section("Mint multi-token batch after payment")
        wallet = await self._wallet()
        flat_split = [amount for split in self._pending_multi_splits for amount in split]
        if sum(flat_split) != self._pending_amount:
            raise RuntimeError("Multi-token split does not match the pending invoice amount.")

        proofs = await self._mint_compat(
            wallet,
            self._pending_amount,
            self._pending_quote_id,
            split=flat_split,
        )
        self._log_json("Proofs", proofs)

        groups = self._group_proofs_by_splits(list(proofs), self._pending_multi_splits)
        row_ids: list[int] = []
        tokens: list[str] = []
        group_splits: list[list[int]] = []
        last_token = ""
        stamp = short_stamp()
        for index, group in enumerate(groups, start=1):
            token = await self._serialize_token_compat(wallet, group)
            if not token:
                raise RuntimeError(f"Token {index} is empty.")
            last_token = str(token)
            tokens.append(last_token)
            save_text_and_qr(last_token, TOKEN_TXT, TOKEN_QR)
            proof_split = [int(getattr(proof, "amount", 0) or 0) for proof in group]
            group_splits.append(proof_split)
            token_label = f"multi#{index}_{stamp}"
            row_id = self._store.insert(
                mint=self._mint(),
                amount=self._pending_multi_amount,
                label=token_label,
                token=last_token,
                is_mock=False,
            )
            row_ids.append(row_id)
            self._log(
                "\n".join(
                    [
                        f"MULTI TOKEN {index}/{self._pending_multi_count}",
                        f"Amount: {self._pending_multi_amount}",
                        f"Proof split: {proof_split}",
                        f"Saved row: {row_id}",
                        last_token,
                    ]
                )
            )

        if self._pending_multi_pdf:
            pdf_path = TokenPdfRenderer(
                TOKENS_PDF_DIR,
                file_stamp_fn=file_stamp,
                log_fn=self._log,
            ).create_multi_token_pdf(
                tokens=tokens,
                amount_per_token=self._pending_multi_amount,
                splits=group_splits,
                created_stamp=stamp,
                common_label=self._pending_multi_common_label,
                mint_url=self._mint().url,
            )
            self._log(f"Multi-token PDF saved:\n{pdf_path}")

        amount_each = self._pending_multi_amount
        self._pending_quote_id = None
        self._pending_amount = None
        self._pending_label = None
        self._clear_pending_multi()
        self._pending_mint_ready = False
        self._auto_mint_in_progress = False
        self.status_signal.emit(f"Multi-token batch ready ({len(row_ids)} tokens)")
        self._log(f"Multi-token batch saved rows: {row_ids}")
        self._out(
            "\n".join(
                [
                    "Multi-token batch minted",
                    f"Rows: {row_ids}",
                    f"Mint: {self._mint().label}",
                    f"Token count: {len(row_ids)}",
                    f"Amount each: {amount_each} sats",
                    f"QR preview: {TOKEN_QR}",
                ]
            )
        )
        self._emit_state(qr_path=TOKEN_QR if last_token else None)

    def _group_proofs_by_splits(self, proofs: list[Any], splits: list[list[int]]) -> list[list[Any]]:
        pool = list(proofs)
        groups: list[list[Any]] = []
        for split in splits:
            group: list[Any] = []
            for amount in split:
                match_index = next(
                    (
                        index
                        for index, proof in enumerate(pool)
                        if int(getattr(proof, "amount", 0) or 0) == amount
                    ),
                    None,
                )
                if match_index is None:
                    raise RuntimeError(f"Mint returned no proof for amount {amount}.")
                group.append(pool.pop(match_index))
            if sum_proofs(group) != sum(split):
                raise RuntimeError("Grouped proofs do not match the planned token amount.")
            groups.append(group)
        if pool:
            raise RuntimeError(f"Mint returned {len(pool)} unexpected extra proofs.")
        return groups

    def _create_mock_token(self, amount: int, label: str) -> None:
        self.status_signal.emit("Creating mock token...")
        self._log_section("Mock token")
        seed = f"{now()}|{self._mint().label}|{amount}|{label}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        token = f"cashuB_mock_{self._mint().label}_{amount}_{digest}"
        save_text_and_qr(token, TOKEN_TXT, TOKEN_QR)
        row_id = self._store.insert(
            mint=self._mint(),
            amount=amount,
            label=label,
            token=token,
            is_mock=True,
        )
        self._log(f"Mock token saved as row {row_id}.")
        self._log(f"TOKEN:\n{token}")
        self._out(
            "\n".join(
                [
                    "Mock token created",
                    f"Row: {row_id}",
                    f"Mint: {self._mint().label}",
                    f"Amount: {amount} sats",
                    f"QR: {TOKEN_QR}",
                ]
            )
        )
        self.status_signal.emit("Mock token ready")
        self._emit_state(qr_path=TOKEN_QR)

    def _show_token(self, token_id: int) -> None:
        token = self._store.get(token_id)
        if not token:
            raise RuntimeError(f"Token row {token_id} not found.")

        txt_path = TOKEN_TXT
        png_path = TOKEN_QR
        token_text = str(token.get("token_text") or "")

        if token_text:
            txt_path.write_text(token_text, encoding="utf-8")
            save_text_and_qr(token_text, txt_path, png_path)

        self._log_section(f"Saved token #{token_id}")
        self._log_json(
            "token metadata",
            {
                "id": token.get("id"),
                "created_at": token.get("created_at"),
                "mint": token.get("mint_label"),
                "amount": token.get("amount"),
                "label": token.get("label"),
                "used": bool(token.get("used")),
                "is_mock": bool(token.get("is_mock")),
                "txt": str(txt_path),
                "png": str(png_path),
            },
        )
        self._log(f"TOKEN TXT:\n{token_text}")
        self._out(
            "\n".join(
                [
                    f"Showing token #{token_id}",
                    f"Mint: {token.get('mint_label')}",
                    f"Amount: {token.get('amount')} sats",
                    f"Used: {bool(token.get('used'))}",
                    f"QR: {png_path}",
                ]
            )
        )
        self.status_signal.emit(f"Showing token #{token_id}")
        self._emit_state(
            qr_path=png_path,
            selected_token_text=token_text,
            selected_token_state={},
        )

    async def _check_saved_token_state(self, token_id: int) -> None:
        token = self._store.get(token_id)
        if not token:
            raise RuntimeError(f"Token row {token_id} not found.")
        token_text = str(token.get("token_text") or "")
        self.status_signal.emit("Checking token state...")
        mint_state = await self._check_token_mint_state(token)
        self._log_json("token mint state", mint_state)
        self._out(
            "\n".join(
                [
                    f"Token state checked #{token_id}",
                    f"Mint: {mint_state.get('mint') or token.get('mint_label')}",
                    f"Summary: {mint_state.get('summary') or mint_state.get('error') or '-'}",
                ]
            )
        )
        self.status_signal.emit(f"Token state checked #{token_id}")
        self._emit_state(selected_token_text=token_text, selected_token_state=mint_state)

    async def _check_token_mint_state(self, token: dict[str, Any]) -> dict[str, Any]:
        if token.get("is_mock"):
            return {"error": "mock token has no mint proof state"}
        token_text = str(token.get("token_text") or "").strip()
        if not token_text:
            return {"error": "empty token"}
        try:
            token_obj = deserialize_token_from_string(token_text)
            proofs = list(getattr(token_obj, "proofs", []))
            if not proofs:
                return {"error": "token has no proofs"}
            mint_url = str(getattr(token_obj, "mint", "") or token.get("mint_url") or self._mint().url)
            mint = self._mint_for_url(mint_url)
            wallet = await self._wallet_for_mint(mint)
            if hasattr(wallet, "_expand_short_keyset_ids"):
                await wallet._expand_short_keyset_ids(proofs)
            response = await wallet.check_proof_state(proofs)
            states = list(getattr(response, "states", []) or [])
            values = [
                str(get_any_attr(get_any_attr(state, ["state"], ""), ["value"], get_any_attr(state, ["state"], ""))).lower()
                for state in states
            ]
            summary: dict[str, int] = {}
            for value in values:
                key = value.split(".")[-1] if value else "unknown"
                summary[key] = summary.get(key, 0) + 1
            return {
                "mint": mint.url,
                "summary": summary,
                "states": values,
            }
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    async def _redeem_pasted_token(self, token_text: str, label: str) -> None:
        if not token_text:
            raise RuntimeError("Paste a token first.")

        self.status_signal.emit("Redeeming token...")
        self._log_section("Redeem pasted token")
        self._log("Parsing token text...")

        token_obj = deserialize_token_from_string(token_text)
        mint_url = str(getattr(token_obj, "mint", "") or self._mint().url)
        source_mint = self._mint_for_url(mint_url)
        target_mint = self._mint()
        amount_in = int(sum_proofs(getattr(token_obj, "proofs", [])))

        self._log_json(
            "incoming token",
            {
                "token_mint": mint_url,
                "active_target_mint": target_mint.url,
                "unit": str(getattr(token_obj, "unit", "")),
                "amount": amount_in,
            },
        )

        if self._same_mint(source_mint.url, target_mint.url):
            new_token, amount_out, row_id = await self._redeem_same_mint(
                token_obj,
                source_mint,
                label,
            )
            self._log(
                "\n".join(
                    [
                        "Mint accepted the pasted token and returned fresh proofs for this wallet.",
                        f"Received amount: {amount_out}",
                        f"Saved new local token row: {row_id}",
                        f"TXT: {TOKEN_TXT}",
                        f"PNG: {TOKEN_QR}",
                        "",
                        "NEW LOCAL TOKEN TXT:",
                        new_token,
                    ]
                )
            )
        else:
            new_token, amount_out, row_id = await self._redeem_cross_mint(
                token_obj,
                source_mint,
                target_mint,
                amount_in,
                label,
            )
            self._log(
                "\n".join(
                    [
                        "Token was redeemed at its source mint, then moved to the active mint via Lightning.",
                        f"Source mint: {source_mint.url}",
                        f"Target mint: {target_mint.url}",
                        f"Input amount: {amount_in}",
                        f"Received amount: {amount_out}",
                        f"Saved new local token row: {row_id}",
                        f"TXT: {TOKEN_TXT}",
                        f"PNG: {TOKEN_QR}",
                        "",
                        "NEW TARGET-MINT TOKEN TXT:",
                        new_token,
                    ]
                )
            )

        marked = self._store.mark_used_by_token(token_text)
        if marked:
            self._log(f"Marked {marked} pasted-token row as used in local history.")
        self._out(
            "\n".join(
                [
                    "Pasted token redeemed",
                    f"Saved row: {row_id}",
                    f"Amount: {amount_out} sats",
                    f"QR: {TOKEN_QR}",
                ]
            )
        )
        self.status_signal.emit("Token redeemed")
        self._emit_state(qr_path=TOKEN_QR)

    def _save_pasted_token(self, token_text: str, label: str) -> None:
        if not token_text:
            raise RuntimeError("Paste a token first.")

        self.status_signal.emit("Saving token...")
        self._log_section("Save pasted token")
        token_obj = deserialize_token_from_string(token_text)
        mint_url = str(getattr(token_obj, "mint", "") or self._mint().url)
        mint = self._mint_for_url(mint_url)
        amount = int(sum_proofs(getattr(token_obj, "proofs", [])))

        save_text_and_qr(token_text, TOKEN_TXT, TOKEN_QR)
        row_id = self._store.insert(
            mint=mint,
            amount=amount,
            label=label,
            token=token_text,
            is_mock=False,
        )
        self._log_json(
            "saved pasted token",
            {
                "row": row_id,
                "mint": mint.url,
                "amount": amount,
                "label": label,
                "txt": str(TOKEN_TXT),
                "png": str(TOKEN_QR),
            },
        )
        self._out(
            "\n".join(
                [
                    "Pasted token saved",
                    f"Row: {row_id}",
                    f"Mint: {mint.label}",
                    f"Amount: {amount} sats",
                    f"QR: {TOKEN_QR}",
                ]
            )
        )
        self.status_signal.emit("Token saved")
        self._emit_state(qr_path=TOKEN_QR, selected_token_text=token_text)

    async def _redeem_same_mint(
        self,
        token_obj: Any,
        mint: MintProfile,
        label: str,
    ) -> tuple[str, int, int]:
        wallet = await self._wallet_for_mint(mint)
        self._log("Asking the token mint to swap incoming proofs into fresh wallet proofs...")
        new_proofs = await self._redeem_token_proofs(wallet, token_obj)
        amount = int(sum_proofs(new_proofs))
        new_token = await self._serialize_token_compat(wallet, new_proofs)
        if not new_token:
            raise RuntimeError("Could not export received proofs as a token.")
        new_token = str(new_token)

        save_text_and_qr(new_token, TOKEN_TXT, TOKEN_QR)
        row_id = self._store.insert(
            mint=mint,
            amount=amount,
            label=label,
            token=new_token,
            is_mock=False,
        )
        return new_token, amount, row_id

    async def _redeem_cross_mint(
        self,
        token_obj: Any,
        source_mint: MintProfile,
        target_mint: MintProfile,
        amount_in: int,
        label: str,
    ) -> tuple[str, int, int]:
        source_wallet = await self._wallet_for_mint(source_mint)
        target_wallet = await self._wallet_for_mint(target_mint)

        self._log("Redeeming pasted token at its source mint first...")
        source_proofs = await self._redeem_token_proofs(source_wallet, token_obj)
        source_amount = int(sum_proofs(source_proofs))
        if source_amount <= 0:
            raise RuntimeError("Source mint returned no spendable proofs.")

        mint_quote, melt_quote, target_amount, total_amount = await self._cross_mint_quotes(
            target_wallet,
            source_wallet,
            min(amount_in, source_amount),
        )
        mint_quote_id = str(get_any_attr(mint_quote, ["quote", "quote_id", "id"]) or "")
        invoice = str(get_any_attr(mint_quote, ["request", "invoice", "pr", "payment_request"]) or "")
        melt_quote_id = str(get_any_attr(melt_quote, ["quote", "quote_id", "id"]) or "")
        fee_reserve = int(get_any_attr(melt_quote, ["fee_reserve"], 0) or 0)
        if not mint_quote_id or not invoice or not melt_quote_id:
            raise RuntimeError("Could not obtain complete cross-mint quote data.")

        self._log(
            "Paying target mint invoice from source mint: "
            f"target={target_amount}, total_with_fee_reserve={total_amount}, fee_reserve={fee_reserve}"
        )
        send_proofs, _ = await source_wallet.select_to_send(
            source_proofs,
            total_amount,
            set_reserved=True,
        )
        melt_response = await source_wallet.melt(
            send_proofs,
            invoice,
            fee_reserve,
            melt_quote_id,
        )
        self._log_json("Melt response", melt_response)

        target_proofs = await self._mint_compat(target_wallet, target_amount, mint_quote_id)
        amount_out = int(sum_proofs(target_proofs))
        new_token = await self._serialize_token_compat(target_wallet, target_proofs)
        if not new_token:
            raise RuntimeError("Could not export target-mint proofs as a token.")
        new_token = str(new_token)

        save_text_and_qr(new_token, TOKEN_TXT, TOKEN_QR)
        row_id = self._store.insert(
            mint=target_mint,
            amount=amount_out,
            label=label,
            token=new_token,
            is_mock=False,
        )
        return new_token, amount_out, row_id

    async def _redeem_token_proofs(self, wallet: Wallet, token_obj: Any) -> list[Any]:
        await wallet.load_proofs(reload=True)
        before_secrets = {proof.secret for proof in wallet.proofs}
        await wallet.load_mint()
        proofs = list(getattr(token_obj, "proofs", []))
        if hasattr(wallet, "_expand_short_keyset_ids"):
            await wallet._expand_short_keyset_ids(proofs)
        received_proofs, _ = await wallet.redeem(proofs)
        await wallet.load_proofs(reload=True)
        new_proofs = [proof for proof in wallet.proofs if proof.secret not in before_secrets]
        if not new_proofs:
            new_proofs = received_proofs
        if not new_proofs:
            raise RuntimeError("Mint accepted no new proofs.")
        return list(new_proofs)

    async def _cross_mint_quotes(
        self,
        target_wallet: Wallet,
        source_wallet: Wallet,
        max_amount: int,
    ) -> tuple[Any, Any, int, int]:
        target_amount = max_amount
        for _ in range(10):
            self._log(f"Requesting target mint invoice for {target_amount} sats...")
            mint_quote = await self._request_mint_compat(target_wallet, target_amount)
            invoice = str(get_any_attr(mint_quote, ["request", "invoice", "pr", "payment_request"]) or "")
            if not invoice:
                raise RuntimeError("Target mint did not return a Lightning invoice.")
            melt_quote = await source_wallet.melt_quote(invoice)
            melt_amount = int(get_any_attr(melt_quote, ["amount"], target_amount) or target_amount)
            fee_reserve = int(get_any_attr(melt_quote, ["fee_reserve"], 0) or 0)
            total_amount = melt_amount + fee_reserve
            self._log(
                f"Source mint quote: amount={melt_amount}, fee_reserve={fee_reserve}, total={total_amount}"
            )
            if total_amount <= max_amount:
                return mint_quote, melt_quote, target_amount, total_amount
            next_amount = max_amount - fee_reserve
            if next_amount >= target_amount:
                next_amount = target_amount - 1
            if next_amount <= 0:
                raise RuntimeError(
                    "Token amount is too small to cover the target invoice and Lightning fee reserve."
                )
            target_amount = next_amount
        raise RuntimeError("Could not find a cross-mint amount that fits the token balance.")

    def _same_mint(self, left: str, right: str) -> bool:
        return left.rstrip("/") == right.rstrip("/")

    def _set_token_filter(self, value: str) -> None:
        self._show_used_tokens = value == "all"
        self._out(
            "Token list filter: "
            + ("all saved tokens" if self._show_used_tokens else "unspent tokens only")
        )
        self._emit_state()

    async def _request_mint_compat(self, wallet: Wallet, amount: int) -> Any:
        attempts = [
            ("request_mint(amount)", lambda: wallet.request_mint(amount)),
            ("request_mint(amount=amount)", lambda: wallet.request_mint(amount=amount)),
        ]
        return await self._try_compat("request_mint", attempts)

    async def _get_mint_quote_compat(self, wallet: Wallet, quote_id: str) -> Any:
        attempts = [
            ("get_mint_quote(quote_id)", lambda: wallet.get_mint_quote(quote_id)),
            ("get_mint_quote(quote=quote_id)", lambda: wallet.get_mint_quote(quote=quote_id)),
        ]
        return await self._try_compat("get_mint_quote", attempts)

    def _quote_is_paid(self, quote: Any) -> bool:
        state = get_any_attr(quote, ["state"], "")
        state_value = str(get_any_attr(state, ["value"], state) or "").lower()
        return state_value in {"paid", "mintquotestate.paid"}

    async def _mint_compat(
        self,
        wallet: Wallet,
        amount: int,
        quote_id: str,
        *,
        split: list[int] | None = None,
    ) -> Any:
        if split:
            attempts = [
                (
                    "mint(amount=amount, quote_id=quote_id, split=split)",
                    lambda: wallet.mint(amount=amount, quote_id=quote_id, split=split),
                ),
                ("mint(amount, quote_id, split)", lambda: wallet.mint(amount, quote_id, split)),
            ]
            return await self._try_compat("mint with split", attempts)

        attempts = [
            ("mint(amount=amount, quote_id=quote_id)", lambda: wallet.mint(amount=amount, quote_id=quote_id)),
            ("mint(amount, quote_id=quote_id)", lambda: wallet.mint(amount, quote_id=quote_id)),
            ("mint(amount, quote_id)", lambda: wallet.mint(amount, quote_id)),
            ("mint(quote_id)", lambda: wallet.mint(quote_id)),
        ]
        return await self._try_compat("mint", attempts)

    async def _serialize_token_compat(self, wallet: Wallet, proofs: Any) -> Any:
        attempts = [
            ("wallet.serialize_proofs(proofs)", lambda: wallet.serialize_proofs(proofs)),
            ("wallet.serialize(proofs)", lambda: wallet.serialize(proofs)),
            ("wallet._serialize_proofs(proofs)", lambda: wallet._serialize_proofs(proofs)),
        ]
        return await self._try_compat("token export", attempts, expected_errors=(AttributeError, TypeError))

    async def _try_compat(
        self,
        label: str,
        attempts: list[tuple[str, Any]],
        expected_errors: tuple[type[Exception], ...] = (TypeError,),
    ) -> Any:
        last: Exception | None = None
        for attempt_label, fn in attempts:
            try:
                self._log(f"Trying {label}: {attempt_label}")
                return await maybe_call(fn())
            except expected_errors as exc:
                last = exc
                self._log(f"{type(exc).__name__}: {exc}")
        raise RuntimeError(f"{label} failed: {last}")

    def _sqlite_seed_record(self) -> dict[str, str] | None:
        for db in self._find_cashu_db_files():
            try:
                with sqlite3.connect(db) as conn:
                    tables = [
                        row[0]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                        ).fetchall()
                    ]
                    if "seed" not in tables:
                        continue
                    row = conn.execute("SELECT seed, mnemonic FROM seed LIMIT 1").fetchone()
                    if row:
                        return {"db": str(db), "seed": row[0], "mnemonic": row[1]}
            except Exception as exc:
                self._log(f"Error while reading SQLite seed from {db}: {exc}")
        return None

    def _find_cashu_db_files(self) -> list[Path]:
        mint = self._mint()
        roots = [DATA_DIR / mint.db, DATA_DIR]
        files: list[Path] = []
        for root in roots:
            if root.is_file():
                files.append(root)
            elif root.is_dir():
                files.extend(root.rglob("*.sqlite"))
                files.extend(root.rglob("*.db"))
                files.extend(root.rglob("*.sqlite3"))
        out: list[Path] = []
        seen: set[Path] = set()
        for file in files:
            try:
                resolved = file.resolve()
            except Exception:
                resolved = file
            if resolved not in seen and file.exists() and file.is_file():
                seen.add(resolved)
                out.append(file)
        return out

    def _sqlite_dump(self, *, include_seed: bool) -> str:
        buffer = StringIO()
        with redirect_stdout(buffer):
            print("SQLite dump")
            print("=" * 39)
            files = self._find_cashu_db_files()
            if not files:
                print("No SQLite database found.")
                return buffer.getvalue()
            for db in files:
                print()
                print(f"DB: {db}")
                print("-" * 39)
                try:
                    with sqlite3.connect(db) as conn:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                        )
                        tables = [row[0] for row in cur.fetchall()]
                        if not include_seed:
                            tables = [table for table in tables if table.lower() != "seed"]
                        print("Tables:", tables)
                        for table in tables:
                            print()
                            print(f"TABLE {table}")
                            cur.execute(f'PRAGMA table_info("{table}")')
                            for col in cur.fetchall():
                                print(" ", col)
                            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                            print("Row count:", cur.fetchone()[0])
                            cur.execute(f'SELECT * FROM "{table}" LIMIT 20')
                            for row in cur.fetchall():
                                print(" ", row)
                except Exception as exc:
                    print("SQLite error:", exc)
        return buffer.getvalue()

    def _emit_state(
        self,
        qr_path: Path | None = None,
        selected_token_text: str | None = None,
        selected_token_state: dict[str, Any] | None = None,
    ) -> None:
        mint = self._mint()
        state = {
            "mint": {"label": mint.label, "url": mint.url, "db": str(DATA_DIR / mint.db)},
            "tokens": self._store.last(21, include_used=self._show_used_tokens),
            "pending_invoice": bool(self._pending_quote_id),
            "mint_ready": self._pending_mint_ready,
        }
        if qr_path:
            state["qr_path"] = str(qr_path)
        if selected_token_text is not None:
            state["selected_token_text"] = selected_token_text
            state["selected_token_state"] = selected_token_state or {}
        self.data_signal.emit(state)

    def _log_json(self, label: str, value: object) -> None:
        self._log(f"{label}:\n{json.dumps(obj_to_dict(value), indent=2, ensure_ascii=False, default=str)}")

    def _log_section(self, title: str) -> None:
        self._log("\n" + "=" * 39 + f"\n{title}\n" + "=" * 39)

    def _log(self, message: str) -> None:
        if not self._debug:
            return
        self.log_signal.emit(f"[{now()}] {message}")

    def _out(self, message: str) -> None:
        self.log_signal.emit(f"[{now()}] {message}")
