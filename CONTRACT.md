# Deployment

## Current

- **Address:** [`0x2d061E63d10EcC6aeeB9f82d232fAEA9F932e6DA`](https://explorer-bradbury.genlayer.com/address/0x2d061E63d10EcC6aeeB9f82d232fAEA9F932e6DA)
- **Network:** GenLayer Bradbury Testnet (chain id `4221`)
- **Deploy tx:** [`0xbefea4995e72ae4f67bd2997cf1356c70abe1b46fb4ee2987b238e033822fa41`](https://explorer-bradbury.genlayer.com/tx/0xbefea4995e72ae4f67bd2997cf1356c70abe1b46fb4ee2987b238e033822fa41)
- **Deployer:** `0x5cdb5699bc1038e115A973bb91A646f7E98C075b`

This is the version with the bucketing fix (see README's "Design note" in "How it works") - the leader's raw extraction is never what gets stored; a rounded, canonical value both parties independently reproduce is.

Confirmed genuinely readable post-deploy via a real `get_state()` call (not just a "finalized" receipt status).

### Live proof the fix actually changes what's stored

Fired a real `ask()` call ([`scripts/ask_demo.ts`](scripts/ask_demo.ts)) against the live committee - no mocked LLM, no Direct Mode - with deliberately non-round source values so the fix would be visible in the result, not just asserted:

- **Context:** "...reported a debt service coverage ratio of 1.437x and closed the quarter with a headcount of 118 full-time employees."
- **Requested:** `["dscr", "headcount"]`, `tolerance_bps: 500` (5%, 2 significant figures)
- **Tx:** [`0x68eb4c33e5bfcb128873e9f8085ce4cf5a3582601d75dd4932c336e5ccefc467`](https://explorer-bradbury.genlayer.com/tx/0x68eb4c33e5bfcb128873e9f8085ce4cf5a3582601d75dd4932c336e5ccefc467) - `FINISHED_WITH_RETURN`
- **Stored result:** `{"dscr": 14000, "headcount": 1200000}` - i.e. **1.4x and 120**, not the raw 1.437x and 118 the text actually states. The independent validator committee's own extractions rounded onto the same canonical bucket as the leader's and agreed on *that*, and that rounded figure - not either party's raw pick - is what landed on-chain.

`query_count` moved 0 -> 1 in the same call.

## Superseded

[`0xDaBa7fd00049a5C95C0Fd1647B85e888A20d8214`](https://explorer-bradbury.genlayer.com/address/0xDaBa7fd00049a5C95C0Fd1647B85e888A20d8214) - the version that stored the leader's raw extraction directly, correctly rejected by steward review. Left live and linked here rather than hidden, as the actual before/after for the fix described in the README.
