import asyncio
import inspect
import json
import sqlite3
from pathlib import Path
from typing import Any

import qrcode

from cashu.wallet.wallet import Wallet


MINT_URL = "https://cashu.cz"
DB_FILE = "cashu_cz_demo.sqlite"

DEBUG = True

INVOICE_TXT = "temp_invoice.txt"
INVOICE_QR = "temp_invoice.png"

TOKEN_TXT = "temp_token.txt"
TOKEN_QR = "temp_token.png"


def line(title: str):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def sub(title: str):
    print()
    print("-" * 78)
    print(title)
    print("-" * 78)


def safe_json(obj: Any):
    try:
        print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
    except Exception:
        print(repr(obj))


def obj_to_dict(obj: Any):
    if obj is None:
        return None

    if isinstance(obj, dict):
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
        return {
            k: v
            for k, v in vars(obj).items()
            if not k.startswith("_")
        }

    return str(obj)


def debug_obj(title: str, obj: Any):
    if not DEBUG:
        return

    sub(title)
    print("TYPE:", type(obj))
    print("REPR:", repr(obj))
    print("DICT/JSON:")
    safe_json(obj_to_dict(obj))


def debug_signature(name: str, fn: Any):
    if not DEBUG:
        return

    sub(f"Method signature: {name}")
    try:
        print(inspect.signature(fn))
    except Exception as e:
        print("Could not inspect signature:", e)


async def maybe_call(result):
    if inspect.isawaitable(result):
        return await result
    return result


def get_any_attr(obj: Any, names: list[str], default=None):
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]

        if hasattr(obj, name):
            return getattr(obj, name)

    return default


def find_db_files() -> list[Path]:
    p = Path(DB_FILE)
    files = []

    if p.is_file():
        files.append(p)

    if p.is_dir():
        files.extend(p.rglob("*.sqlite"))
        files.extend(p.rglob("*.db"))
        files.extend(p.rglob("*.sqlite3"))

    files.extend(Path(".").glob("*.sqlite"))
    files.extend(Path(".").glob("*.db"))
    files.extend(Path(".").glob("*.sqlite3"))

    out = []
    seen = set()

    for f in files:
        try:
            r = f.resolve()
        except Exception:
            r = f

        if r not in seen and f.exists() and f.is_file():
            seen.add(r)
            out.append(f)

    return out


def sqlite_dump(include_seed: bool = False):
    line("SQLite dump")

    files = find_db_files()

    if not files:
        print("No SQLite database found.")
        return

    for db in files:
        sub(f"DB: {db}")

        try:
            conn = sqlite3.connect(db)
            cur = conn.cursor()

            cur.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' "
                "ORDER BY name"
            )

            tables = [r[0] for r in cur.fetchall()]

            if not include_seed:
                tables = [t for t in tables if t.lower() != "seed"]

            print("Tables:", tables)

            for table in tables:
                print()
                print(f"TABLE {table}")

                cur.execute(f'PRAGMA table_info("{table}")')
                cols = cur.fetchall()

                for c in cols:
                    print(" ", c)

                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                count = cur.fetchone()[0]
                print("Row count:", count)

                cur.execute(f'SELECT * FROM "{table}" LIMIT 20')
                rows = cur.fetchall()

                for row in rows:
                    print(" ", row)

            conn.close()

        except Exception as e:
            print("SQLite error:", e)


def print_seed_from_sqlite():
    line("2) Show my seed / mnemonic")

    files = find_db_files()

    if not files:
        print("No SQLite database found.")
        return

    found = False

    for db in files:
        try:
            conn = sqlite3.connect(db)
            cur = conn.cursor()

            cur.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' "
                "ORDER BY name"
            )
            tables = [r[0] for r in cur.fetchall()]

            if "seed" not in tables:
                conn.close()
                continue

            sub(f"DB: {db}")

            cur.execute("SELECT seed, mnemonic FROM seed LIMIT 10")
            rows = cur.fetchall()

            for i, row in enumerate(rows, start=1):
                seed, mnemonic = row

                print(f"Record #{i}")
                print()
                print("SEED:")
                print(seed)
                print()
                print("MNEMONIC:")
                print(mnemonic)
                print()

            found = True
            conn.close()

        except Exception as e:
            print("Error while reading seed:", e)

    if not found:
        print("Seed table was not found.")


async def request_mint_compat(wallet: Wallet, amount: int):
    debug_signature("wallet.request_mint", wallet.request_mint)

    attempts = [
        ("request_mint(amount)", lambda: wallet.request_mint(amount)),
        ("request_mint(amount=amount)", lambda: wallet.request_mint(amount=amount)),
    ]

    last = None

    for label, fn in attempts:
        try:
            print("Trying:", label)
            return await maybe_call(fn())

        except TypeError as e:
            last = e
            print(" TypeError:", e)

    raise RuntimeError(f"request_mint failed: {last}")


async def mint_compat(wallet: Wallet, amount: int, quote_id: str):
    debug_signature("wallet.mint", wallet.mint)

    attempts = [
        (
            "mint(amount=amount, quote_id=quote_id)",
            lambda: wallet.mint(amount=amount, quote_id=quote_id),
        ),
        (
            "mint(amount, quote_id=quote_id)",
            lambda: wallet.mint(amount, quote_id=quote_id),
        ),
        (
            "mint(amount, quote_id)",
            lambda: wallet.mint(amount, quote_id),
        ),
        (
            "mint(quote_id)",
            lambda: wallet.mint(quote_id),
        ),
    ]

    last = None

    for label, fn in attempts:
        try:
            print("Trying:", label)
            return await maybe_call(fn())

        except TypeError as e:
            last = e
            print(" TypeError:", e)

    raise RuntimeError(f"mint failed: {last}")


async def serialize_token_compat(wallet: Wallet, proofs: Any):
    attempts = [
        (
            "wallet.serialize_proofs(proofs)",
            lambda: wallet.serialize_proofs(proofs),
        ),
        (
            "wallet.serialize(proofs)",
            lambda: wallet.serialize(proofs),
        ),
        (
            "wallet._serialize_proofs(proofs)",
            lambda: wallet._serialize_proofs(proofs),
        ),
    ]

    last = None

    for label, fn in attempts:
        try:
            print("Trying export:", label)

            result = fn()
            result = await maybe_call(result)

            return result

        except AttributeError as e:
            last = e
            print(" AttributeError:", e)

        except TypeError as e:
            last = e
            print(" TypeError:", e)

    raise RuntimeError(f"Token export failed: {last}")


def save_text_and_qr(text: str, txt_file: str, png_file: str, label: str):
    txt_path = Path(txt_file)
    png_path = Path(png_file)

    txt_path.write_text(text, encoding="utf-8")

    img = qrcode.make(text)
    img.save(png_path)

    print()
    print(f"{label} saved to:")
    print(txt_path.resolve())

    print()
    print(f"{label} QR saved to:")
    print(png_path.resolve())


def save_invoice_files(invoice: str):
    save_text_and_qr(
        text=invoice,
        txt_file=INVOICE_TXT,
        png_file=INVOICE_QR,
        label="Invoice",
    )


def save_token_files(token: str):
    save_text_and_qr(
        text=token,
        txt_file=TOKEN_TXT,
        png_file=TOKEN_QR,
        label="Token",
    )


async def open_wallet() -> Wallet:
    wallet = await Wallet.with_db(
        url=MINT_URL,
        db=DB_FILE,
        name="cashu-cz-demo",
    )

    await wallet.load_mint()

    return wallet


async def menu_info():
    line("1) Mint info")

    wallet = await open_wallet()

    print("Mint URL:")
    print(wallet.url)

    print()
    print("Number of keysets:")
    print(len(wallet.keysets))

    debug_obj("wallet.keysets", wallet.keysets)

    possible_attrs = [
        "mint_info",
        "info",
        "keysets",
        "url",
        "unit",
        "balance",
    ]

    for attr in possible_attrs:
        if hasattr(wallet, attr):
            try:
                value = getattr(wallet, attr)
                debug_obj(f"wallet.{attr}", value)
            except Exception as e:
                print(f"Could not print wallet.{attr}: {e}")

    # Do not include seed here.
    sqlite_dump(include_seed=False)


async def menu_mnemonic():
    print_seed_from_sqlite()


async def menu_create_token():
    line("3) Request invoice and create token TXT/PNG after payment")

    wallet = await open_wallet()

    amount_str = input("Enter amount in sats, for example 21: ").strip()

    if not amount_str.isdigit():
        print("Invalid amount.")
        return

    amount = int(amount_str)

    if amount <= 0:
        print("Amount must be greater than zero.")
        return

    line("3.1) Requesting Lightning invoice from mint")

    quote = await request_mint_compat(wallet, amount)
    debug_obj("Quote object", quote)

    quote_id = get_any_attr(quote, ["quote", "quote_id", "id"])
    invoice = get_any_attr(
        quote,
        ["request", "invoice", "pr", "payment_request"],
    )

    if not quote_id:
        raise RuntimeError("Could not obtain quote_id.")

    if not invoice:
        raise RuntimeError("Could not obtain Lightning invoice.")

    invoice = str(invoice)

    print()
    print("QUOTE ID:")
    print(quote_id)

    print()
    print("LIGHTNING INVOICE:")
    print(invoice)

    line("3.2) Saving invoice files")

    save_invoice_files(invoice)

    line("3.3) Pay the invoice")

    print("Pay the invoice with your Lightning wallet.")
    print(f"You can use {INVOICE_TXT} or scan {INVOICE_QR}.")
    print("After payment, press ENTER to continue.")
    print()
    input("ENTER after invoice payment... ")

    line("3.4) Minting Cashu token")

    proofs = await mint_compat(wallet, amount, quote_id)
    debug_obj("Proofs", proofs)

    line("3.5) Exporting Cashu token")

    token = await serialize_token_compat(wallet, proofs)

    if not token:
        raise RuntimeError("Token is empty / None.")

    token = str(token)

    line("CASHU TOKEN")
    print()
    print(token)
    print()

    line("3.6) Saving token files")

    save_token_files(token)

    line("3.7) SQLite state after token creation")
    sqlite_dump(include_seed=False)

    line("Done")
    print("Invoice:")
    print(Path(INVOICE_TXT).resolve())
    print(Path(INVOICE_QR).resolve())
    print()
    print("Token:")
    print(Path(TOKEN_TXT).resolve())
    print(Path(TOKEN_QR).resolve())


async def main():
    while True:
        line("Cashu demo console app")

        print("Mint:", MINT_URL)
        print("DB:  ", Path(DB_FILE).absolute())
        print()
        print("1. Mint info")
        print("2. Show my seed / mnemonic")
        print("3. Request invoice and create token TXT/PNG after payment")
        print("0. Exit")

        choice = input("\nChoice: ").strip()

        try:
            if choice == "1":
                await menu_info()

            elif choice == "2":
                await menu_mnemonic()

            elif choice == "3":
                await menu_create_token()

            elif choice == "0":
                line("Exit")
                break

            else:
                print("Unknown choice.")

        except Exception as e:
            line("ERROR")
            print(type(e).__name__ + ":", e)

        input("\nENTER to return to menu... ")


if __name__ == "__main__":
    asyncio.run(main())