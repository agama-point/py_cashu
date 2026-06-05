# Cashu Tokens, Proof Splits, Multi-Token Batches, and Expiration

This note summarizes a practical discussion about how Cashu tokens are composed,
how to issue several transferable tokens from one paid mint quote, how proof
denominations affect token and QR size, and what "expiration" means in Cashu.

It is written as an implementation-oriented reference for future work in this
repository.

## Vocabulary

Cashu terminology can be confusing because people often say "token" for several
different layers.

- A `Proof` is the spendable unit held by a wallet. It contains an `amount`, a
  `secret`, a mint signature `C`, and a keyset id.
- A list of proofs is usually called `Proofs`.
- A serialized Cashu token, such as a `cashuB...` string, is a transport
  envelope that contains one or more proofs.
- A wallet can send one serialized token containing many proofs, or several
  serialized tokens, each containing its own proof subset.

So when we say "issue 3 tokens of 21 sats", the precise meaning is:

1. Pay/mint a total amount of 63 sats.
2. Ask the mint to sign blinded outputs whose amounts can be grouped into three
   subsets of 21 sats.
3. Serialize each subset as a separate transferable `cashuB...` token.

This is better described as a multi-token batch or batched token export, not as
a single special Cashu object.

## Proof Amounts and Binary Denominations

Cashu mints publish keysets. A keyset contains public keys for supported proof
amounts. In practice these amounts are powers of two:

```text
1, 2, 4, 8, 16, 32, 64, ...
```

An arbitrary user-facing amount is represented as a sum of these denominations.
The local Cashu library implements this as a binary split:

```python
def amount_split(amount: int) -> list[int]:
    if amount <= 0:
        return []
    rv = []
    for i in range(amount.bit_length()):
        if amount & (1 << i):
            rv.append(1 << i)
    return rv
```

Examples:

```text
21     = 16 + 4 + 1
21000  = 16384 + 4096 + 512 + 8
63000  = 32768 + 16384 + 8192 + 4096 + 1024 + 512 + 16 + 8
```

The important consequence is that token size grows mostly with the number of
proofs, not with the numeric amount. A 21 sat token needs 3 proofs. A 21000 sat
token needs only 4 proofs.

## Example: 3 Tokens of 21 Sats

To create three independent transferable tokens of 21 sats each, the desired
mint split is:

```text
[16, 4, 1, 16, 4, 1, 16, 4, 1]
```

Total:

```text
3 * 21 = 63
sum(split) = 63
proof count = 9
```

After minting, the wallet can group the returned proofs as:

```text
token 1: [16, 4, 1]
token 2: [16, 4, 1]
token 3: [16, 4, 1]
```

Each group is then serialized into a separate Cashu token string.

## Example: 3 Tokens of 21000 Sats

For 21000 sats:

```text
21000 = 16384 + 4096 + 512 + 8
```

Three separate tokens of 21000 sats therefore require:

```text
[16384, 4096, 512, 8,
 16384, 4096, 512, 8,
 16384, 4096, 512, 8]
```

Total:

```text
3 * 21000 = 63000
sum(split) = 63000
proof count = 12
```

This is not excessive. It is only 12 proofs, compared to 9 proofs for three
tokens of 21 sats.

However, one shared token of 63000 sats would be smaller:

```text
63000 = 32768 + 16384 + 8192 + 4096 + 1024 + 512 + 16 + 8
proof count = 8
```

This illustrates the trade-off:

- Three independent 21000 sat tokens: 12 proofs, easier to distribute
  separately.
- One 63000 sat token: 8 proofs, smaller QR, but not already separated into
  three bearer instruments.

## Optimal Split Strategy

If the goal is the smallest serialized token or QR code, minimize the number of
proofs.

With power-of-two denominations, the binary split is optimal for a single target
amount because each set bit corresponds to exactly one proof.

For a batch of separate tokens, the minimum proof count is:

```text
sum(popcount(amount_i) for each token amount)
```

Where `popcount` is the number of set bits in the binary representation.

Examples:

```text
21:
  binary proof count = 3
  split = [16, 4, 1]

21000:
  binary proof count = 4
  split = [16384, 4096, 512, 8]

3 * 21000 as separate tokens:
  proof count = 3 * 4 = 12

63000 as one token:
  proof count = 8
```

For an implementation, a simple planner can do:

```python
def plan_token_batch(amount_per_token: int, count: int) -> list[list[int]]:
    per_token_split = amount_split(amount_per_token)
    return [per_token_split[:] for _ in range(count)]

def flatten_batch(batch: list[list[int]]) -> list[int]:
    return [amount for token_split in batch for amount in token_split]
```

Before minting, validate:

```text
sum(flat_split) == amount_per_token * count
every amount in flat_split is supported by the active mint keyset
estimated proof count is acceptable for UI/QR transport
```

## QR Size Considerations

Serialized Cashu token size is driven primarily by proof count. Each proof
carries at least:

- amount
- keyset reference
- secret
- mint signature
- optional witness or DLEQ data

Large numeric amounts are not necessarily large tokens. Unfriendly amounts with
many set bits create more proofs.

Useful UI estimates:

```text
proofs <= 15: usually comfortable
proofs <= 30: probably still workable, but preview the QR
proofs > 30: warn the user and suggest fewer separate tokens or a different split
```

These are not protocol limits. They are product heuristics. Real QR readability
depends on token version, included optional fields, error correction level,
display size, camera quality, and whether the token is animated or static.

For this app, a good UI could expose:

```text
Amount per token: 21000
Count: 3
Strategy:
  minimal QR / largest denominations
  wallet-balanced split
  custom split

Preview:
  proofs per token: 4
  total proofs: 12
  estimated QR size: OK
```

## Minting Several Tokens from One Quote

The Cashu flow is:

1. Request a mint quote for the total amount.
2. Pay the Lightning invoice.
3. Construct blinded outputs for the desired proof denominations.
4. Ask the mint to sign those outputs.
5. Unblind the signatures into proofs.
6. Group proofs into logical token subsets.
7. Serialize each subset as a separate token string.

In the local Python library, `Wallet.mint` supports an explicit split:

```python
proofs = await wallet.mint(
    amount=63000,
    quote_id=quote_id,
    split=[
        16384, 4096, 512, 8,
        16384, 4096, 512, 8,
        16384, 4096, 512, 8,
    ],
)
```

After that, group and serialize:

```python
groups = [
    proofs[0:4],
    proofs[4:8],
    proofs[8:12],
]

tokens = [
    await wallet.serialize_proofs(group)
    for group in groups
]
```

The actual implementation should not rely only on list positions unless the
library preserves output order. A safer implementation groups proofs by the
planned amount sequence and verifies that each serialized group sums to the
intended amount.

## Receiving and Redeeming Tokens

When a receiver imports a token, they do not merely "store the string" forever.
A normal receive flow is:

1. Deserialize the token into proofs.
2. Send those proofs to the mint in a swap.
3. The mint verifies the proofs and marks the old secrets as spent.
4. The mint returns new blind signatures for fresh wallet-generated secrets.
5. The receiver now owns fresh proofs that the sender no longer knows.

This matters because Cashu tokens are bearer instruments. Whoever has an
unspent proof can try to spend it. Redeeming into fresh proofs is how a receiver
protects themselves from sender double-spend attempts.

## Expiration: What It Is and What It Is Not

Cashu does not have a simple ordinary-token field like:

```text
expires_at = timestamp
```

For already issued ecash, expiration is modeled through spending conditions in
the proof secret, especially P2PK or HTLC conditions.

There are two separate concepts that are easy to mix up:

- Mint quote expiry: the Lightning invoice or quote must be paid and minted
  before a deadline. This affects the deposit/minting flow, not already issued
  proofs.
- Proof locktime: a spending condition embedded in each proof's secret. This
  changes who can spend the proof after a given Unix timestamp.

## P2PK Locktime Semantics

P2PK is a Cashu spending condition that locks a proof to a public key. Spending
the proof requires a valid Schnorr signature from the corresponding private key.

With a `locktime` tag, the proof has two phases:

1. Before `locktime`: the normal lock applies. The intended key or keys must
   sign.
2. After `locktime`: the refund path becomes available.

If refund public keys are present, those keys can spend after the locktime. If
no refund keys are present, the proof may become spendable by anyone after the
locktime, depending on the exact condition.

Therefore, "expiration" does not mean that the sats disappear. It means that the
authorization rules change.

A conceptual P2PK secret contains:

```text
kind: P2PK
data: receiver public key
tags:
  sigflag: SIG_INPUTS or SIG_ALL
  locktime: unix timestamp
  refund: optional refund public key or keys
  n_sigs: optional threshold for the active lock
  n_sigs_refund: optional threshold for the refund path
```

## How to Work with Expiring Tokens

For an expiring payment, the sender and receiver must agree on the intended
semantics:

- Receiver-before-time: until the deadline, only the receiver can redeem.
- Sender-refund-after-time: after the deadline, the sender can reclaim by using
  the refund key.
- Anyone-after-time: after the deadline, no refund key is specified, so the
  proof can become generally spendable. This is usually not what a payment app
  wants unless it is deliberate.

A practical payment flow:

1. Sender creates locked proofs for the receiver public key.
2. Sender includes a locktime and a refund public key controlled by the sender.
3. Receiver redeems before the locktime by providing their signature.
4. If the receiver does not redeem in time, the sender can redeem/refund after
   locktime using the refund key.

Important caveat: spending conditions are enforced by the mint. A wallet should
check the mint info endpoint and verify that the mint supports the relevant
NUTs before relying on P2PK or HTLC behavior.

## Implementation Notes for This Repository

Current behavior:

- The app requests a mint quote for one amount.
- After payment, it calls `wallet.mint(amount, quote_id)`.
- The wallet chooses its own split based on wallet state.
- The returned proofs are serialized as one token.

Future multi-token behavior:

1. Add UI fields for count and amount per token.
2. Compute per-token binary split with `amount_split`.
3. Flatten the splits and pass them as explicit `split` to `wallet.mint`.
4. Group returned proofs back into per-token groups.
5. Serialize and store each group as its own token row.
6. Generate one QR per token, or add a batch navigation/export screen.

Future expiration behavior:

1. Add optional "locked token" mode.
2. Require or generate the receiver public key.
3. Add locktime input.
4. Add refund public key input for sender reclaim.
5. Mint or swap outputs whose secrets are P2PK spending conditions.
6. Include clear UI warnings if the active mint does not advertise support for
   the required spending-condition NUTs.

## References

- Cashu NUT-00: Cryptography and token/proof models
  <https://cashubtc.github.io/nuts/00/>
- Cashu NUT-03: Swapping tokens
  <https://cashubtc.github.io/nuts/03/>
- Cashu NUT-04: Minting tokens
  <https://cashubtc.github.io/nuts/04/>
- Cashu NUT-10: Spending conditions
  <https://cashubtc.github.io/nuts/10/>
- Cashu NUT-11: Pay-to-Public-Key and locktime
  <https://cashubtc.github.io/nuts/11/>
- Cashu NUT-14: HTLCs
  <https://cashubtc.github.io/nuts/14/>
