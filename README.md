\# py\_cashu



A small educational project exploring the Cashu protocol using Python.



The goal is not to build a production-ready wallet, but to better understand how Cashu mints, Lightning invoices, blind signatures, proofs, and token transfers work under the hood.



\---



\# What is Cashu?



Cashu is an open protocol for bearer digital cash built on top of Bitcoin and the Lightning Network.



Unlike Bitcoin itself, Cashu uses a trusted mint (custodian) that issues cryptographic tokens representing value. These tokens can be transferred privately between users without the mint learning who paid whom.



Cashu combines:



\* Bitcoin as the underlying asset

\* Lightning Network for deposits and withdrawals

\* Blind signatures for privacy

\* Bearer tokens for transferability

\* Open standards known as NUTs (Cashu protocol specifications)



\## Simplified workflow



\### Deposit



1\. User requests a Lightning invoice from a mint.

2\. User pays the invoice.

3\. Wallet creates blinded messages.

4\. Mint signs the blinded messages.

5\. Wallet unblinds the signatures and receives proofs (Cashu tokens).



\### Transfer



1\. User sends a Cashu token to another user.

2\. Receiver imports the token into their wallet.

3\. Receiver swaps the proofs with the mint.

4\. New proofs are issued to the receiver.



\### Withdraw



1\. User presents proofs to the mint.

2\. Mint pays a Lightning invoice.

3\. Proofs become invalid.



\---



\# simple\_py\_cashu.py



`simple\_py\_cashu.py` is a verbose educational example built around the official Python Cashu library.



Its purpose is to demonstrate the complete flow:



```text

Lightning invoice

&#x20;       ↓

Invoice payment

&#x20;       ↓

Cashu minting

&#x20;       ↓

Token export

&#x20;       ↓

Token transfer

```



\## Features



\* Connect to a Cashu mint

\* Display mint information

\* Create Lightning invoices

\* Mint Cashu tokens

\* Export tokens

\* Generate QR codes

\* Inspect wallet data

\* Explore SQLite wallet storage



\## Generated files



Invoice:



```text

temp\_invoice.txt

temp\_invoice.png

```



Token:



```text

temp\_token.txt

temp\_token.png

```



These files make it easy to test transfers between devices and wallets.



\## Educational focus



The code intentionally contains a large amount of logging and debug output.



Rather than hiding protocol details, it exposes:



\* quote IDs

\* invoices

\* keysets

\* wallet metadata

\* SQLite contents

\* exported tokens



This makes it easier to understand how a Cashu wallet operates internally.



\---



\# py\_cashu\_app.py



Work in progress.



The next step of this project is a more user-friendly desktop wallet built with:



\* Python

\* Cashu

\* Qt6 / PyQt6



The goal is to create a lightweight educational Cashu wallet with a graphical user interface.



Planned features:



\* Mint management

\* Balance overview

\* Receive tokens

\* Send tokens

\* QR scanning

\* QR generation

\* Lightning deposits

\* Lightning withdrawals

\* Multiple mints

\* Improved token management



The application is intended primarily as a learning project and protocol exploration tool.



\---



\# Requirements



```bash

pip install cashu

pip install "qrcode\[pil]"

```



\---



\# References



Cashu protocol:



https://cashu.space



Cashu specifications (NUTs):



https://github.com/cashubtc/nuts



Nutshell implementation:



https://github.com/cashubtc/nutshell



Lightning Network:



https://lightning.network



