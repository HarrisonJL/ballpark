// Proves the cross-contract call actually works: adds covenants (one
// deliberately set to fail, so this isn't just a rubber-stamp), then
// calls check_against_ballpark_query against a real, already-recorded
// Ballpark query - a genuine cross-contract read, not a mock.
//
// Usage: npx tsx scripts/covenant_check_demo.ts <covenant_check_address> <ballpark_query_id>
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import "dotenv/config";

function safeJson(value: unknown): string {
  return JSON.stringify(value, (_key, v) => (typeof v === "bigint" ? v.toString() : v), 2);
}

async function writeAndWait(client: any, functionName: string, args: unknown[]) {
  const txHash = await client.writeContract({
    address: process.argv[2] as `0x${string}`,
    functionName,
    args,
    value: 0n,
  });
  console.log(`${functionName} submitted ${txHash} - waiting for finality...`);
  const receipt: any = await client.waitForTransactionReceipt({
    hash: txHash as `0x${string}` & { length: 66 },
    status: "FINALIZED" as any,
    interval: 15000,
    retries: 240,
  });
  console.log(`${functionName} txExecutionResultName:`, receipt.txExecutionResultName);
  return receipt;
}

async function main() {
  const address = process.argv[2];
  const queryId = Number(process.argv[3]);
  if (!address || Number.isNaN(queryId)) {
    throw new Error("Usage: tsx scripts/covenant_check_demo.ts <covenant_check_address> <ballpark_query_id>");
  }

  const rawKey = process.env.DEPLOYER_PRIVATE_KEY;
  if (!rawKey) throw new Error("DEPLOYER_PRIVATE_KEY not set in .env");
  const account = createAccount((rawKey.startsWith("0x") ? rawKey : `0x${rawKey}`) as `0x${string}`);
  const client = createClient({ chain: testnetBradbury, account });
  console.log(`Acting as ${account.address}`);

  await writeAndWait(client, "add_covenant", ["min_dscr", "dscr", "gte", 12500]); // dscr >= 1.25
  await writeAndWait(client, "add_covenant", ["min_headcount", "headcount", "gte", 1000000]); // headcount >= 100
  await writeAndWait(client, "add_covenant", ["min_dscr_strict", "dscr", "gte", 20000]); // dscr >= 2.0 - deliberately set to fail

  console.log(`\nChecking Ballpark query ${queryId}...`);
  await writeAndWait(client, "check_against_ballpark_query", [queryId]);

  const state: any = await client.readContract({
    address: address as `0x${string}`,
    functionName: "get_state",
    args: [],
  });
  console.log("\nget_state():", state);

  const resultId = Number(state.result_count) - 1;
  const result = await client.readContract({
    address: address as `0x${string}`,
    functionName: "get_result",
    args: [resultId],
  });
  console.log(`get_result(${resultId}):`, safeJson(result));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
