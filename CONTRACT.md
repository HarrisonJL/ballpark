# Deployment

- **Address:** [`0xDaBa7fd00049a5C95C0Fd1647B85e888A20d8214`](https://explorer-bradbury.genlayer.com/address/0xDaBa7fd00049a5C95C0Fd1647B85e888A20d8214)
- **Network:** GenLayer Bradbury Testnet (chain id `4221`)
- **Deploy tx:** [`0x24ea1b6e67fa937b6c55fa79c4d234e370f33492879272db89d0e3ded7a45afd`](https://explorer-bradbury.genlayer.com/tx/0x24ea1b6e67fa937b6c55fa79c4d234e370f33492879272db89d0e3ded7a45afd)
- **Deployer:** `0x5cdb5699bc1038e115A973bb91A646f7E98C075b`

Confirmed genuinely readable post-deploy via a real `get_state()` call (not just a "finalized" receipt status).

## Live proof: real consensus, not mocked

Fired a real `ask()` call ([`scripts/ask_demo.ts`](scripts/ask_demo.ts)) against the live committee - no mocked LLM, no Direct Mode:

- **Context:** "In Q1 2026, Acme Robotics reported revenue of $4.2 million and closed the quarter with a headcount of 120 full-time employees."
- **Requested:** `["revenue_millions", "headcount"]`, `tolerance_bps: 500` (5%)
- **Tx:** [`0x60303d298aaa840e1f9ad3d8432677edbedc8e3c808449e2993af45f50009c81`](https://explorer-bradbury.genlayer.com/tx/0x60303d298aaa840e1f9ad3d8432677edbedc8e3c808449e2993af45f50009c81) - `FINISHED_WITH_RETURN`
- **Result:** `{"headcount": 1200000, "revenue_millions": 42000}` - i.e. 120 and 4.2, both exact - a real committee of independent validators each ran their own extraction and landed within 5% of each other (in this case, exactly), reaching consensus through the custom `gl.vm.run_nondet` tolerance check described in the README, not `strict_eq`.

`query_count` moved 0 -> 1 in the same call, confirming the write and the consensus-agreed record landed together.
