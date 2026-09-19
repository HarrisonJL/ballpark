// Quick read-only check against a deployed Ballpark contract.
// Usage: npx tsx scripts/check_state.ts <contract_address> [query_id]
import { createClient } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";

async function main() {
  const address = process.argv[2] ?? process.env.CONTRACT_ADDRESS;
  if (!address) throw new Error("Usage: tsx scripts/check_state.ts <contract_address> [query_id]");
  const queryId = process.argv[3] ? Number(process.argv[3]) : undefined;

  const client = createClient({ chain: testnetBradbury });
  const state = await client.readContract({
    address: address as `0x${string}`,
    functionName: "get_state",
    args: [],
  });
  console.log("get_state():", state);

  if (queryId !== undefined) {
    const q = await client.readContract({
      address: address as `0x${string}`,
      functionName: "get_query",
      args: [queryId],
    });
    console.log(`get_query(${queryId}):`, q);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
