// One-off: run just check_against_ballpark_query when covenants are
// already added (e.g. after a prior run's later step hit a transient
// network error). Not part of the normal demo flow.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import "dotenv/config";

function safeJson(value: unknown): string {
  return JSON.stringify(value, (_key, v) => (typeof v === "bigint" ? v.toString() : v), 2);
}

async function main() {
  const address = process.argv[2];
  const queryId = Number(process.argv[3]);
  const rawKey = process.env.DEPLOYER_PRIVATE_KEY!;
  const account = createAccount((rawKey.startsWith("0x") ? rawKey : `0x${rawKey}`) as `0x${string}`);
  const client = createClient({ chain: testnetBradbury, account });

  const txHash = await client.writeContract({
    address: address as `0x${string}`,
    functionName: "check_against_ballpark_query",
    args: [queryId],
    value: 0n,
  });
  console.log(`Submitted ${txHash} - waiting for finality...`);
  const receipt: any = await client.waitForTransactionReceipt({
    hash: txHash as `0x${string}` & { length: 66 },
    status: "FINALIZED" as any,
    interval: 15000,
    retries: 240,
  });
  console.log("txExecutionResultName:", receipt.txExecutionResultName);

  const state: any = await client.readContract({ address: address as `0x${string}`, functionName: "get_state", args: [] });
  console.log("get_state():", state);
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
