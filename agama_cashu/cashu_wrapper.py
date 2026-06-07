from __future__ import annotations

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
from typing import Any, Callable

import qrcode
from cashu.wallet.wallet import Wallet
from dotenv import load_dotenv, set_key

from .tokenstore import TokenStore


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


def json_text(value: Any) -> str:
    return json.dumps(obj_to_dict(value), indent=2, ensure_ascii=False, default=str)


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


class CashuWrapper:
    def __init__(
        self,
        mint: MintProfile | None = None,
        *,
        debug: bool = False,
        log: Callable[[str], None] | None = None,
    ) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.mint = mint or MINTS[0]
        self.debug = debug
        self._log = log or (lambda message: None)
        self.store = TokenStore(APP_DB, TOKEN_TXT, TOKEN_QR, now_fn=now)

    async def wallet(self) -> Wallet:
        return await self.wallet_for_mint(self.mint)

    async def wallet_for_mint(self, mint: MintProfile) -> Wallet:
        wallet = await Wallet.with_db(
            url=mint.url,
            db=str(DATA_DIR / mint.db),
            name=mint.wallet_name,
        )
        await wallet.load_mint()
        if not getattr(wallet, "keysets", None):
            raise RuntimeError(f"Mint keysets are not available: {mint.url}")
        return wallet

    async def request_invoice(self, amount: int) -> tuple[Any, str, str]:
        wallet = await self.wallet()
        quote = await self.request_mint_compat(wallet, amount)
        quote_id = get_any_attr(quote, ["quote", "quote_id", "id"])
        invoice = get_any_attr(quote, ["request", "invoice", "pr", "payment_request"])
        if not quote_id:
            raise RuntimeError("Could not obtain quote_id.")
        if not invoice:
            raise RuntimeError("Could not obtain Lightning invoice.")
        save_text_and_qr(str(invoice), INVOICE_TXT, INVOICE_QR)
        return quote, str(quote_id), str(invoice)

    async def mint_paid_invoice(
        self,
        *,
        amount: int,
        quote_id: str,
        label: str | None = None,
    ) -> tuple[str, int]:
        wallet = await self.wallet()
        proofs = await self.mint_compat(wallet, amount, quote_id)
        token = await self.serialize_token_compat(wallet, proofs)
        if not token:
            raise RuntimeError("Token is empty.")
        token_text = str(token)
        save_text_and_qr(token_text, TOKEN_TXT, TOKEN_QR)
        row_id = self.store.insert(
            mint=self.mint,
            amount=amount,
            label=label or f"token-{short_stamp()}",
            token=token_text,
            is_mock=False,
        )
        return token_text, row_id

    async def request_mint_compat(self, wallet: Wallet, amount: int) -> Any:
        attempts = [
            ("request_mint(amount)", lambda: wallet.request_mint(amount)),
            ("request_mint(amount=amount)", lambda: wallet.request_mint(amount=amount)),
        ]
        return await self._try_compat("request_mint", attempts)

    async def mint_compat(self, wallet: Wallet, amount: int, quote_id: str) -> Any:
        attempts = [
            ("mint(amount=amount, quote_id=quote_id)", lambda: wallet.mint(amount=amount, quote_id=quote_id)),
            ("mint(amount, quote_id=quote_id)", lambda: wallet.mint(amount, quote_id=quote_id)),
            ("mint(amount, quote_id)", lambda: wallet.mint(amount, quote_id)),
            ("mint(quote_id)", lambda: wallet.mint(quote_id)),
        ]
        return await self._try_compat("mint", attempts)

    async def serialize_token_compat(self, wallet: Wallet, proofs: Any) -> Any:
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
                self._debug(f"Trying {label}: {attempt_label}")
                return await maybe_call(fn())
            except expected_errors as exc:
                last = exc
                self._debug(f"{type(exc).__name__}: {exc}")
        raise RuntimeError(f"{label} failed: {last}")

    def sqlite_seed_record(self) -> dict[str, str] | None:
        for db in self.find_cashu_db_files():
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

    def load_seed_from_env(self) -> tuple[dict[str, str], str]:
        env_mnemonic = read_env_mnemonic()
        if not env_mnemonic:
            raise RuntimeError(f"No {ENV_MNEMONIC_KEY} found in .env.")
        record = self.sqlite_seed_record()
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
        SEED_BACKUP.parent.mkdir(parents=True, exist_ok=True)
        SEED_BACKUP.write_text(backup_text, encoding="utf-8")
        new_seed = bip39_seed_hex_from_mnemonic(env_mnemonic)
        with sqlite3.connect(record["db"]) as conn:
            conn.execute("DELETE FROM seed")
            conn.execute(
                "INSERT INTO seed(seed, mnemonic) VALUES (?, ?)",
                (new_seed, env_mnemonic),
            )
        return record, new_seed

    def save_seed_to_env(self) -> dict[str, str]:
        record = self.sqlite_seed_record()
        if not record:
            raise RuntimeError("No SQLite mnemonic found.")
        save_env_mnemonic(record["mnemonic"])
        return record

    def find_cashu_db_files(self) -> list[Path]:
        roots = [DATA_DIR / self.mint.db, DATA_DIR]
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

    def sqlite_dump(self, *, include_seed: bool = False) -> str:
        buffer = StringIO()
        with redirect_stdout(buffer):
            print("SQLite dump")
            print("=" * 39)
            files = self.find_cashu_db_files()
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

    def mint_info_summary(self, wallet: Wallet) -> str:
        unit = get_any_attr(wallet, ["unit"], None)
        balance = get_any_attr(wallet, ["balance"], None)
        info = get_any_attr(wallet, ["mint_info", "info"], None)
        name = get_any_attr(info, ["name"], None) if info else None
        return "\n".join(
            [
                "Mint info: available",
                f"Mint: {self.mint.label}",
                f"URL: {wallet.url}",
                f"Name: {name or '-'}",
                f"Keysets: {len(getattr(wallet, 'keysets', []) or [])}",
                f"Unit: {unit or '-'}",
                f"Wallet balance: {balance if balance is not None else '-'}",
                f"Wallet DB: {DATA_DIR / self.mint.db}",
            ]
        )

    def _debug(self, message: str) -> None:
        if self.debug:
            self._log(message)
