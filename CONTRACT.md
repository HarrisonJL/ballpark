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

## CovenantCheck (composability demo)

- **Address:** [`0xC846a4e0fcE8e8223CB06eee138161B09f2bea8A`](https://explorer-bradbury.genlayer.com/address/0xC846a4e0fcE8e8223CB06eee138161B09f2bea8A)
- **Deploy tx:** [`0xe337c779ec5097506f5dc1aea016e28a37110dd73daec9573802cdcb8ebb6e75`](https://explorer-bradbury.genlayer.com/tx/0xe337c779ec5097506f5dc1aea016e28a37110dd73daec9573802cdcb8ebb6e75)
- **Points at Ballpark:** `0x2d061E63d10EcC6aeeB9f82d232fAEA9F932e6DA` (the current deployment above)

### Live proof the cross-contract call actually works

Three covenants added, two deliberately passable and one deliberately set to fail - so a clean pass wouldn't just mean "the checker rubber-stamps everything":

- `min_dscr`: `dscr >= 1.25` (tx [`0xa13e0f25...`](https://explorer-bradbury.genlayer.com/tx/0xa13e0f25a405fbb1cf64e428d8e958926533a8dd80113b435d38f982df5be415))
- `min_headcount`: `headcount >= 100` (tx [`0x98b1da15...`](https://explorer-bradbury.genlayer.com/tx/0x98b1da15fb26c3b4cfc8501be2e5a59cb548b97cf020b494b78b5c581e41ed2a))
- `min_dscr_strict`: `dscr >= 2.0` (tx [`0x58372061...`](https://explorer-bradbury.genlayer.com/tx/0x583720610a75bd2d758ada6c28f4f5a586ba8653b2055ab757de193f3efd0c21)) - deliberately fails, since query 0's dscr is 1.4

Then `check_against_ballpark_query(0)` - tx [`0x7edbc62b...`](https://explorer-bradbury.genlayer.com/tx/0x7edbc62b4a1a00ebb2c957db346c34fac5bdf49e796229aef8f688bee8e3a95a), `FINISHED_WITH_RETURN`:

```json
{
  "all_passed": false,
  "ballpark_query_id": 0,
  "details_json": "{\"min_dscr\": \"pass\", \"min_dscr_strict\": \"fail\", \"min_headcount\": \"pass\"}",
  "requester": "0x5cdb5699bc1038e115A973bb91A646f7E98C075b"
}
```

This is a real transaction where `CovenantCheck` made a real synchronous cross-contract view call into `Ballpark`'s already-committed state, parsed the result, and correctly evaluated all three covenants - two passing, one deliberately failing, exactly as designed. Not simulated, and not something Direct Mode could even test locally (see the main README's "Testing" section).

## Superseded

[`0xDaBa7fd00049a5C95C0Fd1647B85e888A20d8214`](https://explorer-bradbury.genlayer.com/address/0xDaBa7fd00049a5C95C0Fd1647B85e888A20d8214) - the version that stored the leader's raw extraction directly, correctly rejected by steward review. Left live and linked here rather than hidden, as the actual before/after for the fix described in the README.
