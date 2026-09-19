// Fires a real ask() against a deployed Ballpark contract and prints the
// consensus-agreed result, proving the tolerance-based equivalence check
// works end to end against a real validator committee, not just Direct
// Mode's mocked LLM.
//
// Usage: npx tsx scripts/ask_demo.ts <contract_address>
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import "dotenv/config";

const CONTEXT =
  "In Q1 2026, Acme Robotics reported revenue of $4.2 million and closed " +
  "the quarter with a headcount of 120 full-time employees.";

async function main() {
  const address = process.argv[2];
  if (!address) throw new Error("Usage: tsx scripts/ask_demo.ts <contract_address>");

  const rawKey = process.env.DEPLOYER_PRIVATE_KEY;
  if (!rawKey) throw new Error("DEPLOYER_PRIVATE_KEY not set in .env");
  const account = createAccount((rawKey.startsWith("0x") ? rawKey : `0x${rawKey}`) as `0x${string}`);

  const client = createClient({ chain: testnetBradbury, account });
  console.log(`Asking as ${account.address}...`);

  const before: any = await client.readContract({
    address: address as `0x${string}`,
    functionName: "get_state",
    args: [],
  });

  const txHash = await client.writeContract({
    address: address as `0x${string}`,
    functionName: "ask",
    args: [CONTEXT, ["revenue_millions", "headcount"], 500],
    value: 0n,
  });
  console.log(`Submitted ${txHash} - waiting for finality (this can take a while on Bradbury)...`);

  const receipt: any = await client.waitForTransactionReceipt({
    hash: txHash as `0x${string}` & { length: 66 },
    status: "FINALIZED" as any,
    interval: 15000,
    retries: 240,
  });
  console.log("txExecutionResultName:", receipt.txExecutionResultName);

  const after: any = await client.readContract({
    address: address as `0x${string}`,
    functionName: "get_state",
    args: [],
  });
  console.log(`query_count: ${before.query_count} -> ${after.query_count}`);

  const queryId = Number(after.query_count) - 1;
  const q = await client.readContract({
    address: address as `0x${string}`,
    functionName: "get_query",
    args: [queryId],
  });
  console.log(`get_query(${queryId}):`, q);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
