// Deploys contracts/ballpark.py to GenLayer testnet (Bradbury by default)
// via genlayer-js and prints the address.
//
// Usage:
//   npx tsx scripts/deploy.ts
//
// Requires DEPLOYER_PRIVATE_KEY in .env (gitignored). Never commit a key.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createClient, createAccount } from "genlayer-js";
import { localnet, testnetBradbury } from "genlayer-js/chains";
import "dotenv/config";

function safeJson(value: unknown): string {
  return JSON.stringify(value, (_key, v) => (typeof v === "bigint" ? v.toString() : v), 2);
}

const FINALIZED = "FINALIZED";

const __dirname = dirname(fileURLToPath(import.meta.url));
const CONTRACTS_DIR = join(__dirname, "..", "contracts");

const CHAIN_NAME = process.env.DEPLOY_CHAIN ?? "bradbury";
const chain = CHAIN_NAME === "localnet" ? localnet : testnetBradbury;
const IS_LOCAL = CHAIN_NAME === "localnet";

// Real consensus plus the finality/appeal window takes far longer than
// genlayer-js's defaults assume - confirmed repeatedly against Bradbury in
// the sibling genlayer-vault and covenant-sentinel projects (one deploy
// took ~37 minutes end to end).
const WAIT_OPTS = IS_LOCAL ? {} : { status: FINALIZED as any, interval: 15000, retries: 240 };

async function main() {
  const rawKey = process.env.DEPLOYER_PRIVATE_KEY;
  if (!rawKey) throw new Error("DEPLOYER_PRIVATE_KEY not set in .env");

  const privateKey = (rawKey.startsWith("0x") ? rawKey : `0x${rawKey}`) as `0x${string}`;
  const account = createAccount(privateKey);
  console.log(`Deploying as ${account.address} on ${chain.name} (chain id ${chain.id})`);

  const code = readFileSync(join(CONTRACTS_DIR, "ballpark.py"), "utf-8");
  const client = createClient({ chain, account });

  console.log("Deploying contract...");
  const deployTxHash = await client.deployContract({
    account,
    code,
    args: [],
  });
  console.log(`Submitted ${deployTxHash} - waiting for finality...`);
  const deployReceipt: any = await client.waitForTransactionReceipt({
    hash: deployTxHash as `0x${string}` & { length: 66 },
    ...WAIT_OPTS,
  });

  if (deployReceipt.txExecutionResultName === "FINISHED_WITH_ERROR") {
    throw new Error(`Deploy finalized but execution failed. Receipt: ${safeJson(deployReceipt)}`);
  }

  const address = deployReceipt.to_address ?? deployReceipt.recipient;
  if (!address) {
    throw new Error(`Deploy did not return a contract address. Receipt: ${safeJson(deployReceipt)}`);
  }
  console.log(`\nDeployed at: ${address}`);
  console.log(`Deploy tx: ${deployTxHash}`);
  console.log(`Network: ${chain.name} (chain id ${chain.id})`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
