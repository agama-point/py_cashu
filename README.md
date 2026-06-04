# py_cashu

A small educational project exploring the Cashu protocol from Python.

The goal is not to build a production-ready wallet. The project is a hands-on
console experiment for understanding how Cashu mints, Lightning invoices, blind
signatures, proofs, bearer tokens, wallet seed material, and token transfers fit
together.

## What Is Cashu?

Cashu is an open protocol for bearer digital cash built on top of Bitcoin and
the Lightning Network.

Unlike Bitcoin itself, Cashu uses a trusted mint that issues cryptographic
tokens representing value. These tokens can be transferred privately between
users without the mint learning who paid whom.

Cashu combines:

- Bitcoin as the underlying asset
- Lightning Network for deposits and withdrawals
- Blind signatures for privacy
- Bearer tokens for transferability
- Open standards known as NUTs, the Cashu protocol specifications

## Simplified Workflow

### Deposit

1. The user requests a Lightning invoice from a mint.
2. The user pays the invoice.
3. The wallet creates blinded messages.
4. The mint signs the blinded messages.
5. The wallet unblinds the signatures and receives proofs, which are Cashu
   tokens.

### Transfer

1. The sender exports a Cashu token.
2. The receiver imports the token into their own wallet.
3. The receiver swaps the proofs with the mint.
4. New proofs are issued to the receiver.

### Withdraw

1. The user presents proofs to the mint.
2. The mint pays a Lightning invoice.
3. The spent proofs become invalid.

## Current Console Demo

`simple_py_cashu.py` is the working terminal test for this repository.

It is intentionally verbose and educational. It connects to `https://cashu.cz`,
uses the local wallet database at `cashu_cz_demo.sqlite`, and exposes protocol
details that a production wallet would usually hide.

Run it from PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
python simple_py_cashu.py
```

The menu currently supports:

1. Showing mint and wallet information.
2. Showing or setting up the wallet seed / mnemonic.
3. Requesting a Lightning invoice and creating a Cashu token after payment.

## Qt App

`cashu_app.py` is the new Qt6 desktop experiment built from the working console
flow. UI layout and styling live in the external `cashu_ui.py` module.

Run it from PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
python cashu_app.py
```

The app keeps the same educational shape:

- left side menu for mint, keys, invoices, tokens, and mock data
- upper right verbose logs
- lower right QR preview for invoices and tokens
- mint selection between `cashu.cz`, `kashu.me`, and `cashu.21m.lol`
- `.env` mnemonic display/import/export
- invoice TXT/PNG generation
- token TXT/PNG generation
- local token history in `cashu_app.sqlite3`
- redeeming pasted tokens into the selected mint, including cross-mint moves
  through Lightning when needed
- offline mock tokens for testing token database behavior

The token table stores `created_at`, mint, amount, label, token text, output
paths, used/unspent state, and whether the row is a mock token. The UI shows the
last five rows and provides actions to toggle used state or delete a row.

## Seed And `.env`

The console demo can keep the wallet mnemonic in a local `.env` file:

```dotenv
CASHU_MNEMO="your mnemonic words stay here"
```

Do not commit `.env` or any real mnemonic material. A Cashu mnemonic controls
wallet secrets and must be treated as sensitive data.

The seed menu in `simple_py_cashu.py` has two directions:

- `Load from .env` reads `CASHU_MNEMO` and overwrites the mnemonic stored in the
  local SQLite wallet database. Before changing the database, the script writes
  `temp_seed_backup.txt`.
- `Save to .env` reads the current SQLite wallet mnemonic and stores it as
  `CASHU_MNEMO` in `.env`.

After changing the SQLite seed or mnemonic, restart the console app before
continuing with wallet operations.

## Generated Files

The demo writes generated test artifacts into the project directory.

Lightning invoice:

```text
temp_invoice.txt
temp_invoice.png
```

Cashu token:

```text
temp_token.txt
temp_token.png
```

Seed backup, created only when loading a new mnemonic from `.env` into SQLite:

```text
temp_seed_backup.txt
```

Local wallet database:

```text
cashu_cz_demo.sqlite/
kashu_me_demo.sqlite/
cashu_21m_lol_demo.sqlite/
cashu_app.sqlite3
```

These files are useful for testing transfers between devices and wallets, but
they can contain sensitive or spendable material. Treat exported tokens and seed
backups carefully.

## Educational Focus

The code intentionally contains a large amount of logging and debug output.

Rather than hiding protocol details, it exposes:

- quote IDs
- Lightning invoices
- mint keysets
- wallet metadata
- SQLite wallet contents
- exported Cashu tokens
- wallet seed / mnemonic sources

This makes it easier to understand how a Cashu wallet operates internally.

## Requirements

Install dependencies into the local virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The minimal dependency set is:

```text
cashu>=0.20.1
qrcode[pil]>=8.0
python-dotenv>=1.0.1
```

## Status

Working:

- `simple_py_cashu.py` terminal demo
- `cashu_app.py` Qt6 desktop demo
- mint info inspection
- Lightning invoice generation
- QR code generation
- Cashu token export
- SQLite wallet inspection
- `.env` mnemonic import/export
- local token table with mock-token testing

Not production ready:

- real wallet UX
- robust error handling
- secure secret storage
- multi-mint wallet management
- token import / receive flow
- Lightning withdrawal flow

## Notes

This is an experiment, not a production Evolu Python client. Any real Evolu
logic still belongs to the official TypeScript packages.

## References

- [Cashu protocol](https://cashu.space)
- [Cashu specifications, NUTs](https://github.com/cashubtc/nuts)
- [Nutshell implementation](https://github.com/cashubtc/nutshell)
- [Lightning Network](https://lightning.network)
