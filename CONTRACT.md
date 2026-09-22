# Deployment

## Current

- **Address:** [`0xCbE5B73E8905062673EeD89e1C1EC9FBD2C63469`](https://explorer-bradbury.genlayer.com/address/0xCbE5B73E8905062673EeD89e1C1EC9FBD2C63469)
- **Network:** GenLayer Bradbury Testnet (chain id `4221`)
- **Deploy tx:** [`0xd33979e9c6dd4af749475bb344edd9d9a1c473e9528410558ac3d64b72eace22`](https://explorer-bradbury.genlayer.com/tx/0xd33979e9c6dd4af749475bb344edd9d9a1c473e9528410558ac3d64b72eace22)
- **Deployer:** `0x5cdb5699bc1038e115A973bb91A646f7E98C075b`

This is the version with the corrected tolerance enforcement (see README's "Design note" in "How it works") - agreement is a precise, uniform relative-tolerance check on raw values, not an approximate significant-figure rounding. The stored result is the leader's raw extraction; `tolerance_bps` stored alongside it is the actual, exact bound.

Confirmed genuinely readable post-deploy via a real `get_state()` call (not just a "finalized" receipt status).

### Live proof the fix actually enforces the selected tolerance

Fired a real `ask()` call ([`scripts/ask_demo.ts`](scripts/ask_demo.ts)) against the live committee - no mocked LLM, no Direct Mode - with the same deliberately non-round source values used before, so the before/after is directly comparable:

- **Context:** "...reported a debt service coverage ratio of 1.437x and closed the quarter with a headcount of 118 full-time employees."
- **Requested:** `["dscr", "headcount"]`, `tolerance_bps: 500` (5%)
- **Tx:** [`0x5f551b0a37eea24a20cd291b89c79344f9b895ab88fca50233a63c10f9825c51`](https://explorer-bradbury.genlayer.com/tx/0x5f551b0a37eea24a20cd291b89c79344f9b895ab88fca50233a63c10f9825c51) - `FINISHED_WITH_RETURN`
- **Stored result:** `{"dscr": 14370, "headcount": 1180000}` - i.e. **1.437x and 118**, the exact raw extraction, not a rounded 1.4x/120 as the previous (rejected) deployment stored. The independent validator committee's own extractions were each within 5% of this raw figure - that bound is real and exact now, not an approximation that could drift as far as 50% at the loosest setting like the previous version's did.

`query_count` moved 0 -> 1 in the same call.

## CovenantCheck (composability demo)

- **Address:** [`0x599fFD68BAF46De02C381Ed0F14D181f4495c1A7`](https://explorer-bradbury.genlayer.com/address/0x599fFD68BAF46De02C381Ed0F14D181f4495c1A7)
- **Deploy tx:** [`0x9f5b036c0bb2deae5f8ad2155fc315ba181ff6cda05e53f250319522077e57f3`](https://explorer-bradbury.genlayer.com/tx/0x9f5b036c0bb2deae5f8ad2155fc315ba181ff6cda05e53f250319522077e57f3)
- **Points at Ballpark:** `0xCbE5B73E8905062673EeD89e1C1EC9FBD2C63469` (the current deployment above)

### Live proof the cross-contract call actually works

Three covenants added, two deliberately passable and one deliberately set to fail - so a clean pass wouldn't just mean "the checker rubber-stamps everything":

- `min_dscr`: `dscr >= 1.25` (tx [`0x1583c696...`](https://explorer-bradbury.genlayer.com/tx/0x1583c696a25860d0455987455c9a71a76c0a13f53f052e47341a96ff5a08ba19))
- `min_headcount`: `headcount >= 100` (tx [`0xadb658ef...`](https://explorer-bradbury.genlayer.com/tx/0xadb658efa741783fd60fae10c3bc7f9d6254d422c81e458e4776436be1a3e309))
- `min_dscr_strict`: `dscr >= 2.0` (tx [`0xea95bf85...`](https://explorer-bradbury.genlayer.com/tx/0xea95bf851eee7fc83a859dbb19bfb99dc3ccd273b1b557b512df79071c5e9777)) - deliberately fails, since query 0's dscr is 1.437

Then `check_against_ballpark_query(0)` - tx [`0x30ffdabf...`](https://explorer-bradbury.genlayer.com/tx/0x30ffdabf99b037747b8acc1ceae976641cd9d532e4f3f87535dbf421890ec7c4), `FINISHED_WITH_RETURN`:

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

- [`0x2d061E63d10EcC6aeeB9f82d232fAEA9F932e6DA`](https://explorer-bradbury.genlayer.com/address/0x2d061E63d10EcC6aeeB9f82d232fAEA9F932e6DA) - Ballpark, the version that rounded to significant figures instead of enforcing a uniform tolerance, correctly rejected by a second steward review.
- [`0xC846a4e0fcE8e8223CB06eee138161B09f2bea8A`](https://explorer-bradbury.genlayer.com/address/0xC846a4e0fcE8e8223CB06eee138161B09f2bea8A) - CovenantCheck, pointed at the address above.
- [`0xDaBa7fd00049a5C95C0Fd1647B85e888A20d8214`](https://explorer-bradbury.genlayer.com/address/0xDaBa7fd00049a5C95C0Fd1647B85e888A20d8214) - Ballpark, the version that stored the leader's raw extraction with a 100%-tolerance ceiling, correctly rejected by the first steward review.

All left live and linked here rather than hidden, as the actual before/after evidence for both fixes described in the README.
