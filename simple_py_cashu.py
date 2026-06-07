from __future__ import annotations

import asyncio
from typing import Any

from agama_cashu.cashu_wrapper import (
    DATA_DIR,
    ENV_FILE,
    ENV_MNEMONIC_KEY,
    INVOICE_QR,
    INVOICE_TXT,
    MINTS,
    SEED_BACKUP,
    TOKEN_QR,
    TOKEN_TXT,
    CashuWrapper,
    json_text,
    read_env_mnemonic,
)


DEBUG = True
TW = 39


def line(title: str) -> None:
    print()
    print("=" * TW)
    print(title)
    print("=" * TW)


def sub(title: str) -> None:
    print()
    print("-" * TW)
    print(title)
    print("-" * TW)


def wrapper() -> CashuWrapper:
    return CashuWrapper(debug=DEBUG, log=print)


def debug_obj(title: str, obj: Any) -> None:
    if not DEBUG:
        return
    sub(title)
    print("TYPE:", type(obj))
    print("REPR:", repr(obj))
    print("DICT/JSON:")
    print(json_text(obj))


async def menu_info() -> None:
    line("1) Mint info")
    cashu = wrapper()
    wallet = await cashu.wallet()
    print(cashu.mint_info_summary(wallet))

    debug_obj("wallet.keysets", wallet.keysets)
    for attr in ["mint_info", "info", "keysets", "url", "unit", "balance"]:
        if hasattr(wallet, attr):
            try:
                debug_obj(f"wallet.{attr}", getattr(wallet, attr))
            except Exception as exc:
                print(f"Could not print wallet.{attr}: {exc}")

    print(cashu.sqlite_dump(include_seed=False))


def print_seed_sources(cashu: CashuWrapper) -> None:
    line("2) Show/setup my seed / mnemonic")
    record = cashu.sqlite_seed_record()

    sub("SQLite seed / mnemonic")
    if record:
        print("DB:")
        print(record["db"])
        print()
        print("SEED:")
        print(record["seed"])
        print()
        print("MNEMONIC:")
        print(record["mnemonic"])
    else:
        print("<not found>")

    sub(".env mnemonic")
    env_mnemonic = read_env_mnemonic()
    print("ENV file:")
    print(ENV_FILE.resolve())
    print()
    print(f"{ENV_MNEMONIC_KEY}:")
    print(env_mnemonic if env_mnemonic else "<not found>")


async def menu_mnemonic() -> None:
    cashu = wrapper()
    while True:
        print_seed_sources(cashu)
        print()
        print("Seed / mnemonic submenu")
        print("1. Load from .env")
        print("2. Save to .env")
        print("3. Exit")

        choice = input("\nChoice: ").strip()

        if choice == "1":
            env_mnemonic = read_env_mnemonic()
            if not env_mnemonic:
                print()
                print("No mnemonic found in .env.")
                input("\nENTER to continue... ")
                continue

            line("WARNING")
            print("This will overwrite the SQLite wallet seed/mnemonic.")
            print(f"A backup will be saved to {SEED_BACKUP}.")
            print()
            print(".env mnemonic:")
            print(env_mnemonic)
            print()
            print("Type exactly:")
            print("YES UPDATE SEED")
            print()
            confirm = input("Confirmation: ").strip()
            if confirm != "YES UPDATE SEED":
                print("Cancelled.")
                input("\nENTER to continue... ")
                continue

            record, new_seed = cashu.load_seed_from_env()
            print()
            print("SQLite seed/mnemonic updated.")
            print("DB:", record["db"])
            print("Backup:", SEED_BACKUP.resolve())
            print()
            print("NEW SEED:")
            print(new_seed)
            print()
            print("Done. Restarting the app after seed change is recommended.")
            input("\nENTER to continue... ")

        elif choice == "2":
            record = cashu.save_seed_to_env()
            print()
            print(f"Mnemonic saved to {ENV_FILE}.")
            print()
            print(f"{ENV_MNEMONIC_KEY}:")
            print(record["mnemonic"])
            input("\nENTER to continue... ")

        elif choice == "3":
            break

        else:
            print("Unknown choice.")
            input("\nENTER to continue... ")


async def menu_create_token() -> None:
    line("3) Request invoice and create token TXT/PNG after payment")
    cashu = wrapper()

    amount_str = input("Enter amount in sats, for example 21: ").strip()
    if not amount_str.isdigit():
        print("Invalid amount.")
        return

    amount = int(amount_str)
    if amount <= 0:
        print("Amount must be greater than zero.")
        return

    label = input("Token label (empty = token-RRMMDD|hh:mm): ").strip() or None

    line("3.1) Requesting Lightning invoice from mint")
    quote, quote_id, invoice = await cashu.request_invoice(amount)
    debug_obj("Quote object", quote)

    print()
    print("QUOTE ID:")
    print(quote_id)
    print()
    print("LIGHTNING INVOICE:")
    print(invoice)

    line("3.2) Invoice files")
    print("Invoice saved to:")
    print(INVOICE_TXT.resolve())
    print()
    print("Invoice QR saved to:")
    print(INVOICE_QR.resolve())

    line("3.3) Pay the invoice")
    print("Pay the invoice with your Lightning wallet.")
    print(f"You can use {INVOICE_TXT} or scan {INVOICE_QR}.")
    print("After payment, press ENTER to continue.")
    print()
    input("ENTER after invoice payment... ")

    line("3.4) Minting and exporting Cashu token")
    token, row_id = await cashu.mint_paid_invoice(
        amount=amount,
        quote_id=quote_id,
        label=label,
    )

    line("CASHU TOKEN")
    print()
    print(token)
    print()

    line("3.5) Token files and local token table")
    print("Token saved to:")
    print(TOKEN_TXT.resolve())
    print()
    print("Token QR saved to:")
    print(TOKEN_QR.resolve())
    print()
    print("Token table row:")
    print(row_id)

    line("3.6) SQLite state after token creation")
    print(cashu.sqlite_dump(include_seed=False))

    line("Done")
    print("Data dir:")
    print(DATA_DIR.resolve())


async def main() -> None:
    while True:
        cashu = wrapper()
        line("Cashu demo console app")
        print("Mint:", cashu.mint.url)
        print("DB:  ", (DATA_DIR / cashu.mint.db).resolve())
        print("ENV: ", ENV_FILE.resolve())
        print()
        print("Available mints:")
        for index, mint in enumerate(MINTS, start=1):
            print(f"{index}. {mint.label} - {mint.url}")
        print()
        print("1. Mint info")
        print("2. Show/setup my seed / mnemonic")
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
        except Exception as exc:
            line("ERROR")
            print(type(exc).__name__ + ":", exc)

        input("\nENTER to return to menu... ")


if __name__ == "__main__":
    asyncio.run(main())
